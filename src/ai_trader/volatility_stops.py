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

2026-09-08. The Founder, having had this conversation more times than he should have:

    "we just have to go for higher trades and... have a wider stop in case the market goes down
     once a trade is placed. Isn't that what we'd agreed anyway?"

That is the NOISE argument, not the fee one -- surviving the move against you after entry -- so
it is the one this file accepts, and it says 0.6x was too tight.

WHY 1.0x NOW. 0.6x was sized for the typical adverse move, which is about half a day's range.
But "typical" is the wrong target: a stop only has to be wrong once to end the trade, and the
half of entries that dip further than typical were being stopped out of positions that were not
actually wrong. A full ATR is the ordinary daily swing, so the stop now sits outside a normal
day rather than inside it. On real numbers that is BTC ~3.6%, ADA ~8.0%, GRT ~8.0% -- against
the 1.5-2.0% every closed trade in the record was given.

The prize moves with it. take_profit is set at a minimum of 2x the stop distance, so a wider
stop asks for a bigger move rather than settling for the same one -- which is the other half of
what he asked for, and the half that makes the arithmetic work.
"""

from __future__ import annotations

# A full ordinary day's range below the entry. 0.6 covered the TYPICAL dip, which meant every
# worse-than-typical dip -- about half of them -- stopped out a trade that was not wrong.
# Founder-directed 2026-09-08: "a wider stop in case the market goes down once a trade is
# placed."
ATR_STOP_MULTIPLIER = 1.0

# Never tighter than this, whatever the maths says. Below it the stop is inside the spread and
# ordinary liquidity gaps for even the calmest coin -- this is the floor that a 0.4% proposal
# would have violated.
MINIMUM_STOP_PCT = 0.015

# Never wider than this. Must match crypto_max_stop_loss_pct, or whichever is smaller silently
# wins and the widening never reaches a real trade -- the disagreeing-values trap that locked
# every Kraken candidate out on 2026-08-16.
#
# Raised from 0.05 on 2026-09-08. At 1.0x ATR the old ceiling clipped every genuinely volatile
# coin back to 5%: ADA at 8.55% ATR and GRT at 8.74% both want ~8%, and handing them 5% is the
# same "one number for every coin" mistake this file was written to end, just at a higher
# number. Past 8% the position is small enough to be noise, and not taking the trade is the
# better answer.
MAXIMUM_STOP_PCT = 0.08


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
