"""The price moves between deciding to buy and actually buying. Handle that honestly.

2026-09-03, Founder-directed, after he asked how the app copes when a coin moves between the
decision and the fill: "if we feel that when the order gets filled, it's moved, then we can
always adjust the stop loss accordingly... if the price moves substantially, then that changes
the whole nature of the trade. And so, yes, it's better to abandon that trade."

THE GAP THIS CLOSES. Kraken entries are patient post-only limit orders that rest below the
market for up to 300 seconds, to earn the 0.40% maker fee instead of the 0.80% taker fee. That
patience is worth real money -- but crypto moves. These coins swing a median of 5.6% in a day,
so five minutes of waiting is not nothing.

Two things went wrong in that window, and both are silent:

  1. THE STOP WAS CALCULATED FROM A PRICE WE DID NOT PAY. The stop is an absolute price worked
     out from the INTENDED entry. Decide to buy at 100 with a stop at 95 (5% of risk), fill at
     97, and the stop is still 95 -- now 2% below the real entry, not 5%. The stop silently
     tightens exactly when the price has been falling, which is precisely when a trade needs
     room. All the care taken sizing that stop to the coin's volatility is undone by arithmetic.

  2. THE MARKET FALLBACK BUYS AT ANY PRICE. If the patient order does not fill, the app cancels
     it and buys at market. That is correct when the price drifted a little and wrong when it
     ran away: the trade being entered is no longer the trade that was analysed. The entry is
     worse, the target is further off, and the reward-to-risk that justified it has quietly
     become something else.

Both are handled here as pure arithmetic so they can be tested without a broker.
"""

from __future__ import annotations

from typing import Any

# How far the price may move between deciding and filling before the trade is abandoned.
#
# 1.5% is deliberately close to the round-trip fee (1.54%). The reasoning: if the entry has
# already moved against us by more than the entire cost of trading, the edge that justified the
# trade is gone before it starts. Below that the shape still roughly holds and rebasing the
# exits is enough.
#
# Applied to ADVERSE movement only. A price that has fallen while we waited to buy is a better
# entry, not a worse one, and abandoning it would be the wrong lesson from the right principle.
MAX_ADVERSE_ENTRY_DRIFT_PCT = 0.015


def entry_drift_pct(*, intended_entry: float, current_price: float, side: str = "buy") -> float | None:
    """How far the price has moved AGAINST us since the decision, as a share of the entry.

    Positive means worse than intended. Negative means better. None when it cannot be judged,
    so the caller can decline to act rather than act on a fabricated number.
    """
    try:
        intended = float(intended_entry)
        current = float(current_price)
    except (TypeError, ValueError):
        return None
    if intended <= 0 or current <= 0:
        return None
    move = (current - intended) / intended
    # Buying: a HIGHER price is adverse. Selling: a LOWER price is adverse.
    return move if str(side).lower() == "buy" else -move


def should_abandon_entry(
    *,
    intended_entry: float,
    current_price: float,
    side: str = "buy",
    max_drift_pct: float = MAX_ADVERSE_ENTRY_DRIFT_PCT,
) -> tuple[bool, str]:
    """Should this entry be given up rather than filled at the current price?

    Returns (abandon, plain-English reason). The reason is written for the Founder, because it
    will appear as the explanation for a trade that did not happen.
    """
    drift = entry_drift_pct(intended_entry=intended_entry, current_price=current_price, side=side)
    if drift is None:
        # Cannot tell. Do NOT abandon: refusing to trade on a missing price reading would turn
        # every data hiccup into a silent halt, which is the failure mode that kept this app
        # from trading for a week.
        return False, "Could not read a current price to compare, so the entry was left alone."
    if drift <= max_drift_pct:
        if drift < 0:
            return False, f"Price moved {abs(drift) * 100:.2f}% in our favour while the order rested."
        return False, f"Price moved {drift * 100:.2f}% against us, inside the {max_drift_pct * 100:.2f}% limit."
    return True, (
        f"Abandoned: the price moved {drift * 100:.2f}% against us while the order waited, "
        f"more than the {max_drift_pct * 100:.2f}% limit. That is more than a whole round trip "
        "in fees, so the trade that was analysed is not the trade on offer any more."
    )


def rebased_exits(
    *,
    intended_entry: float,
    actual_fill: float,
    stop_loss: float,
    take_profit: float,
) -> dict[str, Any]:
    """Move the stop and target so the trade keeps the SHAPE it was approved with.

    The percentages are what the analysis decided -- 5% of risk for 10% of reward, sized to
    that coin's own volatility. Those percentages are re-applied to the price actually paid,
    rather than leaving absolute prices that were computed against a price we did not get.

    Returns the originals unchanged when anything is unusable, because a wrong stop is far
    worse than an unadjusted one.
    """
    try:
        intended = float(intended_entry)
        fill = float(actual_fill)
        stop = float(stop_loss)
        target = float(take_profit)
    except (TypeError, ValueError):
        return {"stop_loss": stop_loss, "take_profit": take_profit, "rebased": False,
                "reason": "One of the prices could not be read as a number."}
    if intended <= 0 or fill <= 0 or stop <= 0 or target <= 0:
        return {"stop_loss": stop_loss, "take_profit": take_profit, "rebased": False,
                "reason": "Prices must all be positive to rebase safely."}
    if abs(fill - intended) / intended < 1e-9:
        return {"stop_loss": stop, "take_profit": target, "rebased": False,
                "reason": "Filled at the intended price, so nothing needed moving."}

    stop_pct = (intended - stop) / intended
    target_pct = (target - intended) / intended
    return {
        "stop_loss": round(fill * (1.0 - stop_pct), 10),
        "take_profit": round(fill * (1.0 + target_pct), 10),
        "rebased": True,
        "stop_distance_pct": round(stop_pct, 6),
        "target_distance_pct": round(target_pct, 6),
        "reason": (
            f"Filled at {fill:.8g} instead of {intended:.8g}, so the stop and target moved with it "
            f"to keep the same {stop_pct * 100:.2f}% risk and {target_pct * 100:.2f}% reward."
        ),
    }
