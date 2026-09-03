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
    assert round(btc * 100, 2) == 2.17


def test_the_old_formula_could_never_have_told_them_apart():
    """The old range was 1.5%-3.0% for everything. GRT swings 10.3% a day and got 1.6%."""
    old_low, old_high = 0.015, 0.030
    assert volatility_stop_pct(REAL_ATR["GRT"]) > old_high
    assert old_low <= volatility_stop_pct(REAL_ATR["BTC"]) <= old_high


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

    0.6 exists because the typical adverse move is about half the daily range. If someone later
    raises it to make the fee-to-risk ratio look better, they have reintroduced the mistake the
    Founder corrected: a wider stop keeps the same prize and enlarges the loss, so break-even
    gets harder, not easier.
    """
    assert 0.5 <= ATR_STOP_MULTIPLIER <= 0.8, (
        "0.6x ATR clears the typical dip. Widening it for fee reasons makes trading worse."
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
