"""Take a strategy's real-money permission away when its own record says it should lose it.

Founder-directed 2026-09-05, Phase 2 of the learning work.

WHY THIS EXISTS. On 4 September eleven strategies were promoted to Micro Live on Founder
authorisation, because the `Paper` stage they sat at was a bootstrap default rather than an
earned position -- no strategy carried any performance data at all. That promotion was
deliberately one-way, and this is the missing half.

The maturity ladder's real value was never blocking untested strategies; it is removing one
that starts losing real money. Without this, promotion is a ratchet and the app can only ever
become more permissive.

THE TEST IT APPLIES. A strategy is demoted when its own closed trades say, on a sample big
enough to mean something, that it loses money per unit of risk taken. Not on a bad week, and
not on three trades: `strategy_performance` only returns a verdict of "confident" at 30
closed trades or more, and only expectancy measured in R -- profit or loss per pound
risked -- is used, because that is the only figure comparable across a GBP 25 crypto trade
and a USD 2,500 equity one.

WHAT IT DELIBERATELY DOES NOT DO.

  * It never promotes. Promotion stays a Founder decision; this can only remove permission.
  * It never demotes on missing data. `strategy_performance` returns nothing at all when
    `learning_readiness` says the outcome record is untrustworthy, and no record means no
    demotion -- the opposite of the doom loop, where an absent input was read as a negative
    finding and a coin could never recover because it was never traded again.
  * It never demotes below Paper, so a demoted strategy keeps running in paper and can earn
    its way back if the Founder re-promotes it on better evidence.

FIRST RUN, MEASURED. `crypto_trend_following_2r` has 53 closed trades at -1.37R expectancy
and a 45% win rate, net -GBP 7.64. It is the only strategy with a real record and it will be
demoted the first time this runs. That is the correct answer -- it is also the strategy that
was winning selection only while the trend score was a hardcoded 0.62 -- but it is a real
change to what may trade, so it is recorded loudly rather than applied quietly.
"""

from __future__ import annotations

import json
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .database import connect
from .strategy_performance import CONFIDENT_SAMPLE, strategy_records

# Expectancy at or below this, on a confident sample, costs a strategy its real-money
# permission. Zero would demote on the first penny of loss and thrash on noise; -0.25R is a
# quarter of the risk budget lost per trade on average, which is a genuine verdict rather
# than a wobble.
DEMOTION_EXPECTANCY_R = -0.25

# 2026-09-05, Founder challenge, and it caught a real defect in the first version of this
# module: "does it ever get promoted again? otherwise we end up having just one or two
# strategies, which then makes the app weaker at trading anyway."
#
# He was right twice over. Demotion sends a strategy to Paper, but crypto only ever trades
# LIVE on Kraken -- there is no paper Kraken -- so a demoted crypto strategy stopped trading
# altogether, generated no new outcomes, and could never accumulate the evidence needed to
# earn its permission back. That is the August per-coin doom loop rebuilt in a new place: an
# input that can only fall, where the only route to recovery is the thing now forbidden.
#
# Two guards below. The route BACK is shadow evidence -- SHADOW_TRADES already records every
# candidate the app would have taken, with its strategy and regime, so a demoted strategy can
# keep proving itself on paper at no risk. Those 2,312 rows are all outcome_status='pending'
# because nothing resolves them; resolving them is Phase 3, and re-promotion is gated on it
# rather than being faked from nothing here.

# Never leave the app with fewer than this many strategies holding real-money permission.
# A demotion that would breach it is recorded as a concern and not applied: an app down to one
# or two strategies cannot adapt when the regime turns, which is a larger risk than one
# underperforming strategy continuing at GBP 25 a trade.
MINIMUM_LIVE_STRATEGIES = 3

# Judge a strategy on the market it is actually in, not on its whole history. 45 days matches
# symbol_track_record's lookback, chosen there for the same reason: a strategy that behaved
# badly in a different regime should stop being condemned for it once the evidence ages out.
# Without this, -1.37R earned in a flat market would bar a trend strategy for good, however
# well it would do when the trend returns.
EVALUATION_WINDOW_DAYS = 45

# Stated on every run so the one-way-ratchet risk stays visible rather than being rediscovered
# later. Nothing in this module can restore a permission it removes.
_RE_PROMOTION_NOTE = (
    "Demotion is currently one-way. The route back is shadow evidence -- SHADOW_TRADES records "
    "every candidate this app would have taken -- but those rows are still "
    "outcome_status='pending' because nothing resolves them. Until that exists, a demoted "
    "strategy can only be restored by the Founder."
)

PAPER_STAGE = "Paper"
MICRO_LIVE_MODE = "micro_live"


@dataclass(frozen=True)
class Demotion:
    strategy_id: str
    from_stage: str
    expectancy_r: float
    sample_size: int
    win_rate: float | None
    net_profit_loss: float

    @property
    def reason(self) -> str:
        return (
            f"{self.strategy_id} is {self.sample_size} closed trades in with an expectancy of "
            f"{self.expectancy_r:+.2f}R and {self.net_profit_loss:+.2f} net. It loses money per "
            f"pound risked on a sample large enough to mean it, so its real-money permission is "
            f"withdrawn. It continues to run in paper and can be re-promoted on better evidence."
        )


def review_strategies_for_demotion(db_path: Path, *, apply: bool = True) -> dict[str, Any]:
    """Withdraw micro_live from strategies their own results condemn.

    `apply=False` reports what would happen without touching anything, so the decision can be
    inspected before it changes what trades.
    """
    records = strategy_records(db_path, window_days=EVALUATION_WINDOW_DAYS)
    if not records:
        return {"status": "stood_down",
                "reason": "no trustworthy outcome record, so nothing is demoted",
                "demoted": [], "considered": 0,
                "minimum_live_strategies": MINIMUM_LIVE_STRATEGIES,
                "re_promotion": _RE_PROMOTION_NOTE}

    # Both tables belong to other modules -- the registry to sprint6, the decision log to
    # production_spine -- so ensure them rather than assume a boot order, exactly as
    # strategy_promotions.py does. Imported inside the function to avoid a circular import.
    try:
        from .production_spine import initialize_production_spine_schema
        from .sprint6 import initialize_sprint6_schema

        initialize_sprint6_schema(db_path)
        initialize_production_spine_schema(db_path)
    except Exception:  # noqa: BLE001 - a schema check must not stop the review reporting
        pass

    candidates: list[Demotion] = []
    now = datetime.now(timezone.utc).isoformat()
    try:
        with closing(connect(db_path)) as conn:
            for strategy_id, record in records.items():
                if record.verdict != "confident" or record.sample_size < CONFIDENT_SAMPLE:
                    continue
                if record.expectancy_r is None or record.expectancy_r > DEMOTION_EXPECTANCY_R:
                    continue
                row = conn.execute(
                    "SELECT current_stage, permitted_modes_json FROM STRATEGY_MATURITY_REGISTRY "
                    "WHERE strategy_id = ?",
                    (strategy_id,),
                ).fetchone()
                if row is None:
                    continue
                try:
                    modes = [str(m) for m in (json.loads(row[1] or "[]") or [])]
                except (TypeError, ValueError):
                    modes = []
                if MICRO_LIVE_MODE not in modes and str(row[0]) == PAPER_STAGE:
                    continue  # already has no real-money permission to remove
                candidates.append(Demotion(
                    strategy_id=strategy_id, from_stage=str(row[0]),
                    expectancy_r=record.expectancy_r, sample_size=record.sample_size,
                    win_rate=record.win_rate, net_profit_loss=record.net_profit_loss,
                ))

            # The erosion guard. Count what currently holds real-money permission and refuse
            # to drop below the floor, worst performer demoted first so the one that leaves is
            # the one that most deserves to.
            live_now = conn.execute(
                "SELECT COUNT(*) FROM STRATEGY_MATURITY_REGISTRY "
                "WHERE suspended = 0 AND current_stage <> ?",
                (PAPER_STAGE,),
            ).fetchone()
            live_count = int(live_now[0]) if live_now else 0
            candidates.sort(key=lambda d: d.expectancy_r)
            allowed = max(0, live_count - MINIMUM_LIVE_STRATEGIES)
            if len(candidates) > allowed:
                withheld = candidates[allowed:]
                candidates = candidates[:allowed]
                for held in withheld:
                    with conn:
                        conn.execute(
                            """
                            INSERT INTO STRATEGY_PROMOTION_DECISIONS (
                                created_at, strategy_id, current_stage, proposed_stage, decision,
                                evidence_gate_status, reason, payload_json
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (now, held.strategy_id, held.from_stage, held.from_stage, "hold",
                             "failed_on_live_evidence_but_withheld",
                             f"{held.strategy_id} qualifies for demotion at "
                             f"{held.expectancy_r:+.2f}R, but demoting it would leave fewer than "
                             f"{MINIMUM_LIVE_STRATEGIES} strategies able to trade real money. An "
                             f"app down to one or two strategies cannot adapt when the regime "
                             f"turns, which is the larger risk. Left live and flagged.",
                             json.dumps({"expectancy_r": held.expectancy_r,
                                         "sample_size": held.sample_size,
                                         "live_strategies_before": live_count,
                                         "minimum_live_strategies": MINIMUM_LIVE_STRATEGIES},
                                        sort_keys=True)),
                        )
            if apply:
                for demotion in candidates:
                    row = conn.execute(
                        "SELECT permitted_modes_json FROM STRATEGY_MATURITY_REGISTRY WHERE strategy_id = ?",
                        (demotion.strategy_id,),
                    ).fetchone()
                    try:
                        modes = [str(m) for m in (json.loads(row[0] or "[]") or [])] if row else []
                    except (TypeError, ValueError):
                        modes = []
                    with conn:
                        conn.execute(
                            """
                            UPDATE STRATEGY_MATURITY_REGISTRY
                            SET current_stage = ?, permitted_modes_json = ?, demotion_reason = ?,
                                approval_authority = ?, updated_at = ?
                            WHERE strategy_id = ?
                            """,
                            (PAPER_STAGE,
                             json.dumps(sorted(m for m in modes if m != MICRO_LIVE_MODE)),
                             demotion.reason, "automatic_demotion_on_live_evidence", now,
                             demotion.strategy_id),
                        )
                        conn.execute(
                            """
                            INSERT INTO STRATEGY_PROMOTION_DECISIONS (
                                created_at, strategy_id, current_stage, proposed_stage, decision,
                                evidence_gate_status, reason, payload_json
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (now, demotion.strategy_id, demotion.from_stage, PAPER_STAGE, "demote",
                             "failed_on_live_evidence", demotion.reason,
                             json.dumps({"expectancy_r": demotion.expectancy_r,
                                         "sample_size": demotion.sample_size,
                                         "win_rate": demotion.win_rate,
                                         "net_profit_loss": round(demotion.net_profit_loss, 2),
                                         "threshold_expectancy_r": DEMOTION_EXPECTANCY_R},
                                        sort_keys=True)),
                        )
    except Exception as exc:  # noqa: BLE001 - a failed review must never stop the worker
        return {"status": "failed", "reason": f"{type(exc).__name__}: {exc}",
                "demoted": [], "considered": len(records)}

    return {
        "status": "applied" if (apply and candidates) else ("would_demote" if candidates else "no_change"),
        "considered": len(records),
        "minimum_live_strategies": MINIMUM_LIVE_STRATEGIES,
        # Stated on every run so the one-way-ratchet risk stays visible rather than being
        # rediscovered later: nothing here can restore a permission it removes.
        "re_promotion": _RE_PROMOTION_NOTE,
        "demoted": [
            {"strategy_id": d.strategy_id, "from_stage": d.from_stage, "expectancy_r": d.expectancy_r,
             "sample_size": d.sample_size, "reason": d.reason}
            for d in candidates
        ],
    }
