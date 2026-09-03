"""The price moves between deciding to buy and actually buying.

2026-09-03, Founder-directed: "if we feel that when the order gets filled, it's moved, then we
can always adjust the stop loss accordingly... if the price moves substantially, then that
changes the whole nature of the trade. And so, yes, it's better to abandon that trade than to
risk the money."

He asked the question that found this: how long do the candles stay in memory, and could the
price have moved by the time a decision is made? The candles turned out to be fine -- they
produce a PERCENTAGE, and "GRT swings 10% a day" does not go stale in five minutes. But the
question exposed a real gap one step further on.

Kraken entries rest as post-only limit orders for up to 300 seconds to earn the 0.40% maker fee
rather than 0.80% taker. On coins swinging a median 5.6% a day, five minutes is not nothing,
and two things went wrong in that window:

  1. The stop is an ABSOLUTE price derived from the INTENDED entry. Buy at 100 with a stop at
     95, fill at 97, and the stop is 2% below the real entry instead of the 5% that was sized
     against that coin's volatility. It tightens exactly when the price has been falling --
     when a trade most needs room -- and it undoes all the care taken sizing it.

  2. If the patient order does not fill, the app cancels and buys AT MARKET. Correct when the
     price drifted a little; wrong when it ran away, because the trade being entered is no
     longer the trade that was analysed.
"""

from __future__ import annotations

from ai_trader.entry_drift import (
    MAX_ADVERSE_ENTRY_DRIFT_PCT,
    entry_drift_pct,
    rebased_exits,
    should_abandon_entry,
)


# --------------------------------------------------------------------------
# Which way is "against us"
# --------------------------------------------------------------------------
def test_a_higher_price_is_adverse_when_buying():
    assert entry_drift_pct(intended_entry=100.0, current_price=102.0, side="buy") == 0.02


def test_a_lower_price_is_favourable_when_buying():
    assert entry_drift_pct(intended_entry=100.0, current_price=98.0, side="buy") == -0.02


def test_the_direction_flips_when_selling():
    assert entry_drift_pct(intended_entry=100.0, current_price=98.0, side="sell") == 0.02


def test_an_unusable_price_says_so_rather_than_guessing():
    for bad in (None, 0, -5, "abc"):
        assert entry_drift_pct(intended_entry=100.0, current_price=bad) is None
        assert entry_drift_pct(intended_entry=bad, current_price=100.0) is None


# --------------------------------------------------------------------------
# Abandoning
# --------------------------------------------------------------------------
def test_a_big_adverse_move_abandons_the_trade():
    abandon, why = should_abandon_entry(intended_entry=100.0, current_price=103.0)
    assert abandon is True
    assert "abandoned" in why.lower()


def test_a_small_adverse_move_still_trades():
    abandon, _ = should_abandon_entry(intended_entry=100.0, current_price=100.5)
    assert abandon is False


def test_a_favourable_move_never_abandons():
    """A cheaper entry is a better trade. Abandoning it would be the wrong lesson drawn from
    the right principle -- and it is the easiest sign error to make here."""
    abandon, why = should_abandon_entry(intended_entry=100.0, current_price=90.0)
    assert abandon is False
    assert "favour" in why.lower()


def test_the_threshold_is_about_the_cost_of_trading():
    """1.5% sits just under the 1.54% round trip. If the entry has already moved against us by
    more than a whole round trip, the edge is gone before the trade starts."""
    assert 0.010 <= MAX_ADVERSE_ENTRY_DRIFT_PCT <= 0.020


def test_an_unreadable_price_does_not_abandon():
    """The failure mode that kept this app from trading for a week was refusing to act on
    missing data. A price hiccup must not become a silent halt."""
    abandon, why = should_abandon_entry(intended_entry=100.0, current_price=None)
    assert abandon is False
    assert "could not read" in why.lower()


# --------------------------------------------------------------------------
# Rebasing the exits
# --------------------------------------------------------------------------
def test_the_stop_keeps_its_distance_when_the_fill_is_worse():
    """The core case. 5% risk and 10% reward must stay 5% and 10% against what was paid."""
    out = rebased_exits(intended_entry=100.0, actual_fill=97.0, stop_loss=95.0, take_profit=110.0)
    assert out["rebased"] is True
    assert round(out["stop_loss"], 4) == 92.15      # 97 * 0.95
    assert round(out["take_profit"], 4) == 106.7    # 97 * 1.10


def test_without_rebasing_the_stop_would_have_been_far_tighter():
    """Shows the size of the bug rather than just the fix: on this fill the original stop is
    2.06% away where the analysis chose 5%."""
    original_distance = (97.0 - 95.0) / 97.0
    assert round(original_distance * 100, 2) == 2.06
    out = rebased_exits(intended_entry=100.0, actual_fill=97.0, stop_loss=95.0, take_profit=110.0)
    rebased_distance = (97.0 - out["stop_loss"]) / 97.0
    assert round(rebased_distance * 100, 2) == 5.00


def test_a_better_fill_moves_the_exits_too():
    """Not only a protection against bad fills -- a cheaper entry should take its target down
    with it, or the trade quietly becomes more ambitious than approved."""
    out = rebased_exits(intended_entry=100.0, actual_fill=95.0, stop_loss=95.0, take_profit=110.0)
    assert round(out["stop_loss"], 4) == 90.25
    assert round(out["take_profit"], 4) == 104.5


def test_filling_at_the_intended_price_changes_nothing():
    out = rebased_exits(intended_entry=100.0, actual_fill=100.0, stop_loss=95.0, take_profit=110.0)
    assert out["rebased"] is False
    assert out["stop_loss"] == 95.0 and out["take_profit"] == 110.0


def test_unusable_prices_return_the_originals_untouched():
    """A wrong stop is far worse than an unadjusted one, so every bad input falls back."""
    for bad in (None, 0, -1, "x"):
        out = rebased_exits(intended_entry=100.0, actual_fill=bad, stop_loss=95.0, take_profit=110.0)
        assert out["rebased"] is False
        assert out["stop_loss"] == 95.0 and out["take_profit"] == 110.0


def test_the_reward_to_risk_ratio_survives_rebasing():
    """The whole point. Whatever the fill, the trade keeps the shape that was approved."""
    before = (110.0 - 100.0) / (100.0 - 95.0)
    out = rebased_exits(intended_entry=100.0, actual_fill=103.0, stop_loss=95.0, take_profit=110.0)
    after = (out["take_profit"] - 103.0) / (103.0 - out["stop_loss"])
    assert round(before, 6) == round(after, 6)


def test_it_explains_itself_in_plain_english():
    out = rebased_exits(intended_entry=100.0, actual_fill=97.0, stop_loss=95.0, take_profit=110.0)
    assert "5.00% risk" in out["reason"] and "10.00% reward" in out["reason"]
