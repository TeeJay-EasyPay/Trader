"""What each strategy has actually done with real money.

Founder-directed 2026-09-05, Phase 1 of the learning work.

WHY THIS EXISTS. `trading_intelligence._strategy_profile` already has a slot for this:

    base.setdefault("historical_statistics",
                    {"sample_size": 0, "win_rate": None, "average_r": None, "expectancy_r": None})

It is filled from a static dict in code and nothing ever populates it from outcomes, so it
reports sample_size 0 and win_rate None for every strategy, permanently. Two places consume
it, and both are therefore inert:

  * one refuses to trust a strategy until `sample_size >= minimum_sample_size` (30). With
    sample_size hard-wired to 0 that check can never pass, for any strategy, ever.
  * the other scores `(win_rate or 0.5) * 0.10`, so every strategy contributes the same
    neutral 0.5 whether it has made money or lost it.

That is the whole reason the app does not get better: the machinery to let past results
influence which strategy is chosen exists and is wired to a constant.

WHAT THIS COMPUTES, AND FROM WHAT. PERFORMANCE_ATTRIBUTION holds the outcomes but carries no
strategy_id, so each row is linked back through its proposal_id to the TRADE_AUDIT payload,
which carries both the strategy_id and the stop-loss the trade was sized against. That stop
is what makes an R-multiple possible: R is the profit or loss expressed in units of the money
originally put at risk, which is the only way to compare a GBP 25 crypto trade with a USD
2,500 equity one.

WHAT IT REFUSES TO DO. If `learning_readiness` says the outcome record is not trustworthy,
this returns nothing at all rather than a plausible-looking number -- and a strategy below
MINIMUM_SAMPLE is reported as `insufficient_evidence`, never as a neutral 0.5. Measured on
2026-09-05, 53 of 66 closed trades belong to one strategy and the other fifteen have none, so
the honest answer for almost every strategy today is "not enough evidence". Saying so is the
point.
"""

from __future__ import annotations

import json
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .database import connect
from .learning_readiness import assess_learning_readiness

# Below this a per-strategy figure is an anecdote. Reported as evidence, never as a verdict.
MINIMUM_SAMPLE = 5

# The sample at which the figure is strong enough to influence strategy selection. Matches
# the `minimum_sample_size` the strategy profiles already declare.
CONFIDENT_SAMPLE = 30

# Trades risking less than this contribute a win or a loss but no R, borrowed from
# expectancy.DEFAULT_MINIMUM_RISK and for the reason that module already documents: dividing
# a real gain by a few pence produces a spectacular-looking multiple out of small change.
#
# Measured here on 2026-09-05 before the floor was applied: 53 trades gave a mean of +1.78R
# against a NET LOSS of GBP 7.64 -- because nine trades from the GBP 2-5 sizing era, where the
# money at risk was around four pence, scored up to +19.8R each and carried the average. The
# median over the same 53 was -0.45R. An unfloored mean would have told the strategy scorer
# that a losing strategy was excellent.
MINIMUM_RISK_FOR_R = 0.25


@dataclass(frozen=True)
class StrategyRecord:
    strategy_id: str
    sample_size: int
    wins: int
    win_rate: float | None
    average_r: float | None
    expectancy_r: float | None
    net_profit_loss: float
    verdict: str          # "insufficient_evidence" | "provisional" | "confident"

    def to_statistics(self) -> dict[str, Any]:
        """The shape `_strategy_profile` expects, so this can drop straight in."""
        return {
            "sample_size": self.sample_size,
            "win_rate": self.win_rate,
            "average_r": self.average_r,
            "expectancy_r": self.expectancy_r,
            "verdict": self.verdict,
            "net_profit_loss": round(self.net_profit_loss, 2),
        }


def _float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result


def strategy_records(db_path: Path) -> dict[str, StrategyRecord]:
    """Per-strategy live results, or {} when the outcome record cannot be trusted."""
    readiness = assess_learning_readiness(db_path)
    if not readiness.ready:
        return {}

    try:
        with closing(connect(db_path)) as conn:
            outcomes = conn.execute(
                """
                SELECT proposal_id, profit_loss, entry_price, exit_price, quantity
                FROM PERFORMANCE_ATTRIBUTION
                """
            ).fetchall()
            proposal_ids = [row[0] for row in outcomes if row[0]]
            if not proposal_ids:
                return {}
            # Narrowed to the proposals that actually have an outcome, deliberately.
            # `payload_json` averages ~11KB, so selecting it for every agent_proposal row
            # pulls tens of megabytes out of Supabase on each call -- the precise pattern
            # behind this project's egress blowout, and it timed this function out the first
            # time it was run. The IN-list is at most the number of closed trades.
            placeholders = ",".join("?" for _ in proposal_ids)
            audits = conn.execute(
                f"""
                SELECT proposal_id, payload_json FROM TRADE_AUDIT
                WHERE event_type = 'agent_proposal' AND proposal_id IN ({placeholders})
                """,
                tuple(proposal_ids),
            ).fetchall()
    except Exception:  # noqa: BLE001 - an unreadable record yields no lesson, not a crash
        return {}

    # strategy_id and the stop the trade was sized against, keyed by proposal.
    context: dict[str, tuple[str, float | None]] = {}
    wanted = set(proposal_ids)
    for row in audits:
        if row[0] not in wanted or row[0] in context:
            continue
        try:
            proposal = (json.loads(row[1] or "{}") or {}).get("proposal") or {}
        except (TypeError, ValueError):
            continue
        strategy_id = str(proposal.get("strategy_id") or "").strip()
        if strategy_id:
            context[row[0]] = (strategy_id, _float(proposal.get("stop_loss")))

    grouped: dict[str, list[tuple[float, float | None]]] = {}
    for row in outcomes:
        linked = context.get(row[0])
        if not linked:
            continue
        strategy_id, stop_loss = linked
        profit_loss = _float(row[1])
        if profit_loss is None:
            continue
        # R = result / money originally at risk. Without a usable stop the trade still counts
        # towards win rate but contributes no R, rather than being given an invented one.
        entry, quantity = _float(row[2]), _float(row[4])
        risk = None
        if stop_loss is not None and entry is not None and quantity:
            distance = abs(entry - stop_loss) * quantity
            # The floor, not merely > 0: see MINIMUM_RISK_FOR_R.
            risk = distance if distance >= MINIMUM_RISK_FOR_R else None
        grouped.setdefault(strategy_id, []).append(
            (profit_loss, (profit_loss / risk) if risk else None)
        )

    records: dict[str, StrategyRecord] = {}
    for strategy_id, entries in grouped.items():
        sample = len(entries)
        wins = sum(1 for profit_loss, _r in entries if profit_loss > 0)
        net = sum(profit_loss for profit_loss, _r in entries)
        r_values = [r for _p, r in entries if r is not None]
        if sample < MINIMUM_SAMPLE:
            verdict = "insufficient_evidence"
        elif sample < CONFIDENT_SAMPLE:
            verdict = "provisional"
        else:
            verdict = "confident"
        records[strategy_id] = StrategyRecord(
            strategy_id=strategy_id,
            sample_size=sample,
            wins=wins,
            # Deliberately None below the minimum: a win rate from three trades is not a win
            # rate, and returning 0.5 there is exactly the neutral default this replaces.
            win_rate=round(wins / sample, 4) if sample >= MINIMUM_SAMPLE else None,
            average_r=round(sum(r_values) / len(r_values), 4) if r_values and sample >= MINIMUM_SAMPLE else None,
            expectancy_r=round(sum(r_values) / len(r_values), 4) if r_values and sample >= MINIMUM_SAMPLE else None,
            net_profit_loss=net,
            verdict=verdict,
        )
    return records


def historical_statistics_for(db_path: Path, strategy_id: str) -> dict[str, Any] | None:
    """Real statistics for one strategy, or None when there is nothing honest to report.

    None means the caller keeps its existing behaviour. That is deliberate: a strategy with no
    record should be treated as unproven, not as average.
    """
    record = strategy_records(db_path).get(strategy_id)
    return record.to_statistics() if record else None
