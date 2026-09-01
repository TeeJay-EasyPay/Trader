"""A trade must be given room to be right, and must be worth taking at all.

2026-09-01, Founder-directed: "I agree with you on both points. please make the changes."

The first day Alpaca could hold more than 5 positions, it opened nine and lost 215 dollars.
The picks were not the problem. Two gates were missing:

  * Only a MAXIMUM stop distance was ever checked (orchestrator.py's
    max_stop_loss_pct_exceeded), so a stop could be arbitrarily TIGHT and nothing objected.
    All nine entries that day sat inside the configured 3% default -- 0.19% to 2.39% -- and
    the two tightest were the two that lost. JNJ was stopped out 91 seconds after entry on a
    0.19% stop, which is inside the ordinary bid/ask jiggle of a large-cap. That is not a
    losing idea, it is an untested one.

  * No reward:risk floor for equities. NVDA was bought risking 3.71 dollars a share to make
    2.78 -- a ratio of 0.75, needing to be right 57% of the time just to break even. Crypto
    has refused this shape since it had fees to clear (crypto_min_net_reward_risk); equities
    never got the equivalent.

The real numbers from that day are used as fixtures below, so these tests fail against the
exact trades that prompted them.
"""

from __future__ import annotations

from ai_trader.foundation import (
    DEFAULT_BROKER_POLICIES,
    DEFAULT_RISK_POLICIES,
    min_stop_loss_pct_for,
    reward_risk_ratio,
)


class _Policy:
    def __init__(self, shared=0.005, per_broker=None):
        self.min_stop_loss_pct = shared
        self.broker_min_stop_loss_pct = per_broker or {}


class _Proposal:
    def __init__(self, entry, stop, target):
        self.entry_price = entry
        self.stop_loss = stop
        self.take_profit = target


# The nine real Alpaca entries of 2026-09-01: (symbol, entry, stop, take-profit).
SEPTEMBER_FIRST = [
    ("AAPL", 316.78, 313.60, 328.78),
    ("DAL", 78.25, 77.64, 80.41),
    ("FSLR", 201.50, 196.69, 214.00),
    ("ISRG", 368.74, 360.00, 380.00),
    ("JNJ", 268.22, 267.72, 275.00),
    ("LLY", 1173.99, 1165.00, 1185.00),
    ("MSFT", 511.46, 504.60, 525.00),
    ("NKE", 39.31, 38.75, 40.00),
    ("NVDA", 217.21, 213.50, 219.99),
]


def _stop_pct(entry, stop):
    return abs(entry - stop) / entry


def test_the_equities_floor_is_higher_than_the_global_one():
    """The global figure is a floor against the absurd, set well below Kraken's own 1.5%
    default so real-money crypto behaviour does not change. Equities carry the real floor."""
    shared = DEFAULT_RISK_POLICIES["minimum_stop_loss_pct"][0]
    alpaca = DEFAULT_BROKER_POLICIES["alpaca"]["minimum_stop_loss_pct"][0]
    assert shared < alpaca, "the per-broker floor must be the demanding one"
    assert shared < 0.015, "the global floor must stay below crypto_default_stop_loss_pct"


def test_kraken_keeps_the_permissive_global_floor():
    """Kraken is real money and was not part of this change. It has no per-broker floor, so
    it gets the global one, which sits below its own 1.5% default stop."""
    policy = _Policy(shared=0.005, per_broker={"alpaca": 0.015})
    assert min_stop_loss_pct_for(policy, "kraken") == 0.005
    assert min_stop_loss_pct_for(policy, None) == 0.005


def test_a_broker_can_demand_more_room_but_never_less():
    """max(), not override. A broker may ask for a wider stop than the global floor; it must
    not be able to quietly ask for a tighter one."""
    policy = _Policy(shared=0.02, per_broker={"alpaca": 0.015})
    assert min_stop_loss_pct_for(policy, "alpaca") == 0.02


def test_broker_names_are_matched_case_insensitively():
    policy = _Policy(shared=0.005, per_broker={"alpaca": 0.015})
    assert min_stop_loss_pct_for(policy, "Alpaca") == 0.015


def test_the_two_trades_that_lost_money_would_now_be_refused():
    """JNJ (0.19%, stopped out in 91 seconds) and LLY (0.77%, in 6m41s)."""
    floor = DEFAULT_BROKER_POLICIES["alpaca"]["minimum_stop_loss_pct"][0]
    refused = {
        symbol for symbol, entry, stop, _ in SEPTEMBER_FIRST if _stop_pct(entry, stop) < floor
    }
    assert "JNJ" in refused
    assert "LLY" in refused


def test_the_widest_stops_that_day_still_pass():
    """The floor must not simply refuse everything -- FSLR and ISRG were shaped sensibly."""
    floor = DEFAULT_BROKER_POLICIES["alpaca"]["minimum_stop_loss_pct"][0]
    for symbol in ("FSLR", "ISRG"):
        entry, stop = next((e, s) for sym, e, s, _ in SEPTEMBER_FIRST if sym == symbol)
        assert _stop_pct(entry, stop) >= floor, symbol


def test_nvda_is_refused_for_aiming_to_win_less_than_it_risked():
    """Risking 3.71 a share to make 2.78. The stop distance was fine; the shape was not,
    which is why this needs its own gate rather than being folded into the stop check."""
    entry, stop, target = 217.21, 213.50, 219.99
    ratio = reward_risk_ratio(_Proposal(entry, stop, target))
    assert ratio is not None and ratio < 1.0
    assert _stop_pct(entry, stop) >= DEFAULT_BROKER_POLICIES["alpaca"]["minimum_stop_loss_pct"][0]


def test_a_healthy_shape_passes():
    """AAPL the same morning: risking 3.18 to make 12.00."""
    ratio = reward_risk_ratio(_Proposal(316.78, 313.60, 328.78))
    assert ratio is not None and ratio >= DEFAULT_RISK_POLICIES["minimum_reward_risk"][0]


def test_the_reward_risk_floor_cannot_reject_a_crypto_trade_that_passed_its_own_gate():
    """Kraken already refuses net reward:risk below 1.0, measured AFTER fees. Net >= 1 means
    reward >= risk + fees, so the gross ratio checked here is strictly greater than 1 and
    this gate is provably a no-op for crypto. That is the argument for applying it globally
    rather than per broker, so it is asserted rather than left in a comment."""
    floor = DEFAULT_RISK_POLICIES["minimum_reward_risk"][0]
    risk, fees = 100.0, 1.6
    for net_ratio in (1.0, 1.5, 3.0):
        reward = net_ratio * risk + fees
        assert reward / risk > floor


def test_an_unmeasurable_shape_is_not_failed_for_the_wrong_reason():
    """A missing take-profit is take_profit_required's job. Returning 0.0 here would refuse
    the trade citing reward:risk, which would send us looking in the wrong place."""
    assert reward_risk_ratio(_Proposal(100.0, 98.0, 0.0)) is None
    assert reward_risk_ratio(_Proposal(100.0, 100.0, 110.0)) is None
    assert reward_risk_ratio(_Proposal(0.0, 0.0, 0.0)) is None


def test_older_databases_without_these_rows_behave_exactly_as_before():
    """Both policies default to 0 in TradingPolicy, and the orchestrator skips a gate whose
    value is 0. A deployment that has not yet seeded the new rows must not start refusing
    every trade because a policy read came back empty."""
    from ai_trader.foundation import TradingPolicy

    fields = TradingPolicy.__dataclass_fields__
    assert fields["min_stop_loss_pct"].default == 0.0
    assert fields["min_reward_risk"].default == 0.0
