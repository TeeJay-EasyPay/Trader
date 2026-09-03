"""Size the stop to the coin, not to a number chosen for a different market.

2026-09-03, Founder-directed. He worked this out before I did: "it also will vary from coin to
coin. The smaller cap coins will fluctuate much harder and broader than the large cap coins."

WHY THIS EXISTS. Crypto had not traded for a week. The last gate standing was a proposal whose
stop sat 0.4% below the entry -- refused, correctly, as inside the noise. Looking at why such a
stop was ever produced turned up two faults:

  * THE RANGE WAS FAR TOO NARROW. The old formula was crypto_default_stop_loss_pct (1.5%) times
    a multiplier of 1.0 to 2.0, so it could only ever produce 1.5% to 3.0% no matter what the
    coin did. GRT swings 10.3% in a normal day and was handed a 1.6% stop. It was scaling, but
    inside a range set for a much calmer market.

  * IT SCALED ON THE WRONG THING. The "volatility" score it used gave BTC a WIDER stop than
    ADA, when ADA is nearly twice as volatile. Measured against real candles:

        coin   ATR%    actual daily swing    old stop
        BTC    3.61%          3.54%          ~1.8%
        ADA    8.55%          6.61%          ~1.6%
        GRT    8.74%         10.33%          ~1.6%

ATR -- average true range -- is the standard measure for this and the app was already computing
it (analyze_price_series) and not using it for the stop.

WHY 0.6x ATR. Buy at a random point in a day and the price typically dips about half its daily
range against you before doing anything. ATR is roughly that daily range, so 0.6x sits just
outside the ordinary dip: the stop fires when something is actually wrong, not when the price
breathes. It gives BTC ~2.2% and GRT ~5%, which is the whole point -- one number cannot be
right for both.

NOT A FEE ARGUMENT. Fees are no reason to widen a stop: widening keeps the same prize and
enlarges the loss, so it makes the break-even win rate WORSE. The Founder corrected me on that
and he was right. The only justification for a wider stop is noise, and it is the only one used
here.
"""

from __future__ import annotations

# Buy at a random moment and the typical adverse move is roughly half the day's range. 0.6
# clears that with a little room, without drifting into "wide stop" territory where every loss
# costs more for no better win rate.
ATR_STOP_MULTIPLIER = 0.6

# Never tighter than this, whatever the maths says. Below it the stop is inside the spread and
# ordinary liquidity gaps for even the calmest coin -- this is the floor that a 0.4% proposal
# would have violated.
MINIMUM_STOP_PCT = 0.015

# Never wider than this. Matches crypto_max_stop_loss_pct: past here a loss costs more than the
# strategy can carry, and the trade should simply not be taken instead.
MAXIMUM_STOP_PCT = 0.05


def volatility_stop_pct(
    atr_pct: float | None,
    *,
    multiplier: float = ATR_STOP_MULTIPLIER,
    floor: float = MINIMUM_STOP_PCT,
    cap: float = MAXIMUM_STOP_PCT,
    fallback: float | None = None,
) -> float:
    """How far below the entry this coin's stop belongs, as a share of price.

    `fallback` is used when ATR cannot be measured -- a coin with too little history. Falling
    back to the old flat default is right there: a stop sized from no data is a guess, and a
    guess should be the conservative middle rather than an extreme.
    """
    try:
        atr = float(atr_pct) if atr_pct is not None else None
    except (TypeError, ValueError):
        atr = None
    if atr is None or atr <= 0:
        base = fallback if fallback is not None else floor
    else:
        base = atr * float(multiplier)
    return round(max(float(floor), min(float(cap), float(base))), 6)


def describe_stop(symbol: str, atr_pct: float | None, stop_pct: float) -> str:
    """One line the Founder can read, because a number without a reason is not an answer."""
    if atr_pct:
        return (
            f"{symbol} moves about {atr_pct * 100:.1f}% on a normal day, so its stop sits "
            f"{stop_pct * 100:.1f}% below the entry -- outside the ordinary wobble, not inside it."
        )
    return (
        f"{symbol} has too little price history to measure its normal movement, so it gets the "
        f"cautious default of {stop_pct * 100:.1f}%."
    )
