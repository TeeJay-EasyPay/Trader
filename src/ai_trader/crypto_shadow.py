"""Keeping a record of the crypto trades we refused, so refusing can be judged.

2026-09-08. The trading AI raised it in the standup and was right:

    "the shadow-trade record hasn't updated since 4 September. I'd check whether rejected
     candidates are still being tracked in simulation; otherwise we're missing the evidence
     that could tell us whether this caution is protecting you or passing up good trades."

Confirmed against production: the last SHADOW_TRADES row is 2026-09-04 23:40, and every crypto
refusal since then has vanished without a trace of what would have happened. Meanwhile the
system refused 271 candidates on 7 September alone.

WHY IT STOPPED. Shadow recording lives in the research service. The crypto path in agent.py is a
different module and never had any. So the moment crypto became the only thing being researched,
the record went quiet -- not a bug that broke, a half that was never built.

WHY IT MATTERS MORE THAN ANY THRESHOLD. The whole argument in that standup -- is the 0.70 bar
too high, is the track-record penalty a doom loop, should the stop be wider -- is unanswerable
without knowing what the refused trades would have done. Every party to it was reasoning from
opinion because the evidence was not being kept. A week of this recording settles it with facts.

WHAT IS DELIBERATELY NOT RECORDED. A candidate refused before it has an entry, a stop and a
target has no tradeable shape, so there is nothing to settle it against later; those are skipped
rather than written as rows that can only ever stay pending. And one row per symbol, per reason,
per day: research runs about 46 times a day over 10-19 symbols, so recording every pass would
write hundreds of near-identical rows for one setup and put real weight on the Supabase egress
this project has spent a week cutting.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .always_on import record_shadow_trade
from .models import utc_now_iso

# The same status the research service writes, so everything that already reads shadow trades --
# the resolver, the strategy records, the scorecard -- picks these up with no change at all.
DECISION_STATUS = "shadow_candidate"


def _tradeable(entry: Any, stop: Any, target: Any) -> tuple[float, float, float] | None:
    """The three numbers a shadow trade needs, or None if this cannot be settled later.

    shadow_outcomes.resolve_shadow_trades needs an entry, a stop and a target, and needs the
    stop below the entry -- everything here is long-only. Anything else stays pending for ever,
    which is worse than not recording it: it looks like evidence and never becomes any.
    """

    try:
        entry_price, stop_loss, take_profit = float(entry), float(stop), float(target)
    except (TypeError, ValueError):
        return None
    if entry_price <= 0 or stop_loss <= 0 or take_profit <= 0:
        return None
    if stop_loss >= entry_price or take_profit <= entry_price:
        return None
    return entry_price, stop_loss, take_profit


def record_crypto_rejection(
    db_path: Path,
    *,
    symbol: str,
    reason: str,
    entry_price: Any,
    stop_loss: Any,
    take_profit: Any,
    confidence: Any = None,
    quantity: Any = None,
    notional: Any = None,
    argument_for: str | None = None,
    argument_against: str | None = None,
    evidence: dict[str, Any] | None = None,
) -> bool:
    """Write down a crypto candidate we turned away. Returns whether a row was written.

    NEVER RAISES. This is bookkeeping alongside a decision that has already been made; a failure
    to record must not be able to change, delay or break the decision itself.
    """

    shape = _tradeable(entry_price, stop_loss, take_profit)
    if shape is None:
        return False
    entry, stop, target = shape

    try:
        probability = None if confidence is None else float(confidence)
    except (TypeError, ValueError):
        probability = None
    # What the trade was expected to return, in units of what it risked. Stored so a later
    # reader can tell an ambitious refusal from a marginal one without recomputing it.
    expected_r = round((target - entry) / (entry - stop), 4) if entry > stop else None

    try:
        record_shadow_trade(
            db_path,
            symbol=str(symbol).upper(),
            asset_type="crypto",
            intended_broker="kraken",
            decision_status=DECISION_STATUS,
            strategy="crypto_research_refused",
            intended_entry=entry,
            stop_loss=stop,
            take_profit=target,
            quantity=_number(quantity),
            notional=_number(notional),
            probability=probability,
            expected_r=expected_r,
            strongest_argument_for=argument_for,
            strongest_argument_against=argument_against,
            # The reason IS the finding. Six months from now the useful question is not "did
            # refusals work" but "did refusing for THIS reason work", and that can only be
            # answered if the reason travels with the row.
            wait_or_rejection_reason=reason,
            market_evidence={"refused_at_stage": reason, **(evidence or {})},
            data_quality={"status": "recorded_from_crypto_rejection",
                          "note": "Prices are the ones the refusal was made on."},
            # One per symbol, per reason, per day. See the module note on why not per cycle.
            idempotency_key=f"{str(symbol).upper()}:kraken:{reason}:{utc_now_iso()[:10]}",
        )
        return True
    except Exception:  # noqa: BLE001 - bookkeeping must never break the decision it describes
        return False


def _number(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def rejection_evidence(**fields: Any) -> dict[str, Any]:
    """Small helper so callers can hand over whatever context they hold without worrying about
    whether it will serialise -- anything awkward becomes its string form rather than an error
    raised in the middle of a trading cycle."""

    safe: dict[str, Any] = {}
    for key, value in fields.items():
        if value is None:
            continue
        try:
            # No default= here on purpose: the point is to find out whether this value is
            # genuinely JSON-native, and turn it into text now if it is not. Leaning on a
            # downstream default= would push the surprise into the row instead of fixing it.
            json.dumps(value)
            safe[key] = value
        except (TypeError, ValueError):
            safe[key] = str(value)
    return safe
