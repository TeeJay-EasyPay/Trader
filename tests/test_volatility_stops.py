"""One stop distance cannot be right for both BTC and GRT.

2026-09-03, Founder-directed. He reached this before I did: "it also will vary from coin to
coin. The smaller cap coins will fluctuate much harder and broader than the large cap coins."

This was the last gate keeping crypto from trading for a week. A proposal arrived with a stop
0.4% below the entry, was refused as inside the noise -- correctly -- and the question was why
such a stop was ever produced. Two faults:

  * THE RANGE WAS TOO NARROW. The old formula could only ever produce 1.5%-3.0%, whatever the
    coin did.
  * IT SCALED ON THE WRONG THING. It gave BTC a wider stop than ADA, when ADA is nearly twice
    as volatile.

Real measurements from production candles, which the fixtures below use:

    coin   ATR%    daily swing    old stop    new stop
    BTC    3.61%       3.54%        ~1.8%       2.17%
    ADA    8.55%       6.61%        ~1.6%       5.00%  (capped)
    GRT    8.74%      10.33%        ~1.6%       5.00%  (capped)

NOT A FEE ARGUMENT, and the tests say so explicitly. Widening a stop to make fees look smaller
keeps the same prize and enlarges the loss, so the break-even win rate gets WORSE. The Founder
corrected me on that. Noise is the only justification used here.
"""

from __future__ import annotations

from ai_trader.volatility_stops import (
    ATR_STOP_MULTIPLIER,
    MAXIMUM_STOP_PCT,
    MINIMUM_STOP_PCT,
    describe_stop,
    volatility_stop_pct,
)

# ATR measured from real production candles on 2026-09-03.
REAL_ATR = {"BTC": 0.0361, "ETH": 0.0460, "LTC": 0.0503, "LINK": 0.0593,
            "ALGO": 0.0613, "SOL": 0.0647, "DOT": 0.0665, "FIL": 0.0677,
            "ADA": 0.0855, "XRP": 0.0870, "GRT": 0.0874}


def test_a_calm_coin_gets_a_tighter_stop_than_a_wild_one():
    """The entire point. One number cannot serve both."""
    btc = volatility_stop_pct(REAL_ATR["BTC"])
    grt = volatility_stop_pct(REAL_ATR["GRT"])
    assert btc < grt
    # 3.61% at 1.0x ATR, where it was 2.17% at 0.6x. Updated 2026-09-08 with the multiplier,
    # not around it: the number is asserted exactly so a silent drift still fails here.
    assert round(btc * 100, 2) == 3.61


def test_the_old_formula_could_never_have_told_them_apart():
    """The old range was 1.5%-3.0% for everything. GRT swings 10.3% a day and got 1.6%.

    Asserted as a SPREAD rather than a band, because the band moved on 2026-09-08 and the
    thing worth protecting was never the band -- it was that a coin swinging three times
    harder gets a stop to match.
    """
    btc = volatility_stop_pct(REAL_ATR["BTC"])
    grt = volatility_stop_pct(REAL_ATR["GRT"])
    assert grt - btc > 0.03, "the two must be far apart, not merely ordered"
    assert grt > 0.030, "the old formula's ceiling for everything"


def test_every_real_coin_lands_between_the_floor_and_the_cap():
    for coin, atr in REAL_ATR.items():
        stop = volatility_stop_pct(atr)
        assert MINIMUM_STOP_PCT <= stop <= MAXIMUM_STOP_PCT, f"{coin} -> {stop}"


def test_the_stop_sits_below_the_typical_daily_dip_not_inside_it():
    """Buy at a random point and the price typically dips about half its daily range. The stop
    must clear that, or it fires on ordinary movement -- which is the whole failure being fixed.
    """
    for coin, atr in REAL_ATR.items():
        typical_dip = atr / 2
        stop = volatility_stop_pct(atr)
        if stop < MAXIMUM_STOP_PCT:  # capped coins are a separate, deliberate compromise
            assert stop >= typical_dip, f"{coin}: stop {stop:.4f} inside its typical dip {typical_dip:.4f}"


def test_a_tiny_stop_can_never_be_produced():
    """The 0.4% proposal that blocked everything. Even a motionless coin gets the floor."""
    assert volatility_stop_pct(0.001) == MINIMUM_STOP_PCT
    assert volatility_stop_pct(0.0) == MINIMUM_STOP_PCT


def test_a_wildly_volatile_coin_is_capped_rather_than_given_a_huge_stop():
    """Past the cap the answer is not a wider stop, it is no trade."""
    assert volatility_stop_pct(0.90) == MAXIMUM_STOP_PCT


def test_missing_history_falls_back_rather_than_guessing_an_extreme():
    """A stop sized from no data is a guess, and a guess should be the cautious middle."""
    assert volatility_stop_pct(None, fallback=0.02) == 0.02
    assert volatility_stop_pct("not a number", fallback=0.02) == 0.02


def test_the_multiplier_is_about_noise_not_fees():
    """Guards the reasoning, not just the number.

    The rule this protects has not changed: a wider stop that keeps the SAME prize makes the
    break-even win rate worse, and widening for fee reasons is the mistake the Founder
    corrected. What changed on 2026-09-08 is the noise judgement behind the number.

    0.6x covered the TYPICAL adverse move, about half a day's range. But a stop only has to be
    wrong once, and every worse-than-typical dip -- roughly half of them -- was ending trades
    that were not actually wrong. Founder-directed: "a wider stop in case the market goes down
    once a trade is placed." 1.0x is one ordinary day, so the stop sits outside a normal day
    rather than inside it.

    The bound stays tight in both directions. Below 0.8 is back inside the daily noise; above
    1.2 is no longer a noise argument at all, and would need a different justification than
    this file offers.
    """
    assert 0.8 <= ATR_STOP_MULTIPLIER <= 1.2, (
        "1.0x ATR clears one ordinary day. Widening beyond that needs a reason this file "
        "does not have, and widening for fee reasons makes trading worse."
    )


def test_widening_the_stop_widens_the_prize_with_it():
    """The invariant that separates this from the mistake the Founder corrected.

    His correction was right: a wider stop holding the same target enlarges the loss for the
    same prize, so break-even gets harder. It does not apply here only because the target is
    set as a MULTIPLE of the stop -- widen one and the other widens with it, leaving the
    reward-to-risk ratio untouched. If that ever stops being true, this change becomes the
    mistake it was careful not to be.
    """
    from ai_trader.technical_discretion import technical_take_profit

    for atr in (0.02, 0.05, 0.09):
        entry = 100.0
        stop = entry * (1 - volatility_stop_pct(atr))
        target = technical_take_profit(
            entry_price=entry, stop_loss=stop, side="buy",
            resistance=None, support=None, min_reward_risk=2.0,
        )
        reward_to_risk = (target - entry) / (entry - stop)
        assert reward_to_risk >= 2.0 - 1e-9, (
            f"a {atr:.0%} ATR coin was given a stop without a prize to match it"
        )


def test_the_cap_can_be_overridden_by_policy():
    """The caller passes the policy maximum, so this never silently exceeds the mandate."""
    assert volatility_stop_pct(0.90, cap=0.03) == 0.03


def test_it_explains_itself_in_plain_english():
    text = describe_stop("GRT", REAL_ATR["GRT"], volatility_stop_pct(REAL_ATR["GRT"]))
    assert "8.7%" in text and "normal day" in text
    assert "atr" not in text.lower(), "the Founder is not an engineer"


def test_a_coin_with_no_history_says_so_plainly():
    text = describe_stop("NEWCOIN", None, 0.015)
    assert "too little price history" in text
