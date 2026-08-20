"""Founder-directed 2026-08-20: size from the money at risk, and refuse trades that cannot
pay their own trading costs.

The trap these two changes close, in order:

1. Crypto used a FLAT notional, so the stop distance mapped one-for-one into cash at risk --
   a wider stop simply risked more money. Handing a model the stop distance under that
   scheme would have handed it a risk dial, and wider stops flatter a win rate right up
   until the losses land. Sizing from risk inverts it: a wider stop buys a smaller position.

2. Measured live across the first 8 settled trades, fees ran ~1.6% of notional per round
   trip -- about 6x Kraken's published 0.26%. A target only 3% away therefore keeps barely
   half the move. XRP was a CORRECT call that still returned +0.004 net on +0.036 gross.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.technical_discretion import (
    clears_fee_hurdle,
    net_reward_risk_after_fees,
    risk_based_notional,
)
from ai_trader.trade_scorecard import estimate_round_trip_fee_pct


class RiskBasedNotionalTests(unittest.TestCase):
    def test_a_wider_stop_buys_a_smaller_position(self):
        """THE property. Under the old flat sizing both of these were the same size."""
        tight = risk_based_notional(risk_budget=0.75, entry_price=100.0, stop_loss=97.0, max_notional=1000.0)
        wide = risk_based_notional(risk_budget=0.75, entry_price=100.0, stop_loss=94.0, max_notional=1000.0)
        self.assertAlmostEqual(tight, 25.0, places=6)
        self.assertAlmostEqual(wide, 12.5, places=6)
        self.assertLess(wide, tight, "Widening the stop must cost position size, never be free.")

    def test_cash_at_risk_stays_constant_as_the_stop_widens(self):
        for stop in (97.0, 96.0, 95.0, 94.0):
            notional = risk_based_notional(risk_budget=0.75, entry_price=100.0, stop_loss=stop, max_notional=1000.0)
            risk = notional * (100.0 - stop) / 100.0
            self.assertAlmostEqual(risk, 0.75, places=6, msg=f"stop={stop}")

    def test_the_concentration_ceiling_still_binds(self):
        notional = risk_based_notional(risk_budget=0.75, entry_price=100.0, stop_loss=99.5, max_notional=25.0)
        self.assertAlmostEqual(notional, 25.0, places=6)

    def test_risk_is_bounded_above_by_the_budget_and_never_exceeds_it(self):
        # When the ceiling binds the realised risk is LOWER than budget, never higher.
        for stop in (99.5, 99.0, 97.0, 95.0):
            notional = risk_based_notional(risk_budget=0.75, entry_price=100.0, stop_loss=stop, max_notional=25.0)
            risk = notional * (100.0 - stop) / 100.0
            self.assertLessEqual(risk, 0.75 + 1e-9, f"stop={stop}")

    def test_degenerate_inputs_return_zero_rather_than_raising(self):
        self.assertEqual(risk_based_notional(risk_budget=0.75, entry_price=0.0, stop_loss=1.0, max_notional=25.0), 0.0)
        self.assertEqual(risk_based_notional(risk_budget=0.0, entry_price=100.0, stop_loss=97.0, max_notional=25.0), 0.0)
        self.assertEqual(risk_based_notional(risk_budget=0.75, entry_price=100.0, stop_loss=100.0, max_notional=25.0), 0.0)


class FeeHurdleTests(unittest.TestCase):
    def test_the_real_xrp_shape_is_rejected(self):
        # A correct call that still netted almost nothing after costs.
        self.assertFalse(
            clears_fee_hurdle(entry_price=100.0, stop_loss=98.5, take_profit=103.0, round_trip_fee_pct=0.016)
        )

    def test_a_target_that_genuinely_clears_costs_passes(self):
        self.assertTrue(
            clears_fee_hurdle(entry_price=100.0, stop_loss=98.5, take_profit=108.0, round_trip_fee_pct=0.016)
        )

    def test_fees_are_taken_off_the_reward_and_added_to_the_risk(self):
        ratio = net_reward_risk_after_fees(
            entry_price=100.0, stop_loss=98.0, take_profit=104.0, round_trip_fee_pct=0.01,
        )
        # reward 4 - 1 = 3; risk 2 + 1 = 3 -> 1.0
        self.assertAlmostEqual(ratio, 1.0, places=6)

    def test_a_target_swallowed_entirely_by_fees_scores_zero(self):
        ratio = net_reward_risk_after_fees(
            entry_price=100.0, stop_loss=98.0, take_profit=100.5, round_trip_fee_pct=0.02,
        )
        self.assertEqual(ratio, 0.0)

    def test_an_unknown_fee_rate_does_not_block_everything(self):
        self.assertTrue(
            clears_fee_hurdle(entry_price=100.0, stop_loss=98.0, take_profit=101.0, round_trip_fee_pct=0.0)
        )

    def test_a_zero_risk_trade_is_not_judged_rather_than_divided_by_zero(self):
        self.assertIsNone(
            net_reward_risk_after_fees(entry_price=100.0, stop_loss=100.0, take_profit=110.0, round_trip_fee_pct=0.01)
        )


class FeeRateEstimateTests(unittest.TestCase):
    def test_measures_the_rate_actually_paid(self):
        # Real shapes from live KRAKEN_RECONCILED_RESULTS rows.
        rows = [
            {"exchange_fee": 0.0316, "quantity": 2.64992, "actual_exit": 0.73874},
            {"exchange_fee": 0.0324, "quantity": 0.0132371, "actual_exit": 155.66},
            {"exchange_fee": 0.0591, "quantity": 0.06, "actual_exit": 63.1},
        ]
        rate = estimate_round_trip_fee_pct(rows)
        self.assertGreater(rate, 0.014, "Published 0.26% is not what this account pays.")
        self.assertLess(rate, 0.018)

    def test_defaults_to_unknown_so_the_gate_stays_inactive_without_evidence(self):
        """Regression: defaulting to the observed 1.6% made a fresh database inherit another
        account's punitive rate and block every trade on an assumption."""
        self.assertEqual(estimate_round_trip_fee_pct([]), 0.0)
        self.assertEqual(estimate_round_trip_fee_pct([{"exchange_fee": 0}]), 0.0)
        self.assertEqual(estimate_round_trip_fee_pct([], default=0.016), 0.016)

    def test_uses_the_median_so_one_odd_fill_cannot_move_it(self):
        rows = [
            {"exchange_fee": 0.016, "quantity": 1, "actual_exit": 1.0},
            {"exchange_fee": 0.016, "quantity": 1, "actual_exit": 1.0},
            {"exchange_fee": 5.0, "quantity": 1, "actual_exit": 1.0},
        ]
        self.assertAlmostEqual(estimate_round_trip_fee_pct(rows), 0.016, places=6)

    def test_tolerates_junk(self):
        estimate_round_trip_fee_pct([None, "x", {"exchange_fee": "a", "quantity": "b"}])


if __name__ == "__main__":
    unittest.main()
