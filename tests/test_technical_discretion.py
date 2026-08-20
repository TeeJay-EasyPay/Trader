"""Phase 5.5 of the CIO-level forecasting build (2026-08-20, Founder-requested):
bounded technical discretion within existing guardrails.

The Founder asked whether the AI should eventually decide which guardrails to follow.
Agreed answer, which this module encodes and these tests protect: discretion WITHIN a
mandate, never authority to rewrite it. Every clamp test below exists to prove the AI
can use better information inside the limits but can never produce a riskier outcome
than today's flat-percentage logic already would.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.technical_discretion import (
    conviction_scaled_notional,
    technical_stop_loss,
    technical_take_profit,
)


class TechnicalStopLossTests(unittest.TestCase):
    def test_places_the_stop_just_below_a_real_support_level(self):
        stop = technical_stop_loss(
            entry_price=100.0, side="buy", support=97.0, resistance=110.0, atr=2.0,
            max_stop_loss_pct=0.10, default_stop_loss_pct=0.03,
        )
        self.assertLess(stop, 97.0, "The stop must sit just BEYOND support, not inside it.")
        self.assertGreater(stop, 96.0, "The buffer should be modest, not a wholesale widening.")

    def test_never_exceeds_the_policy_maximum_stop_distance(self):
        # A support level far below entry must never widen real risk past policy.
        stop = technical_stop_loss(
            entry_price=100.0, side="buy", support=50.0, resistance=110.0, atr=2.0,
            max_stop_loss_pct=0.05, default_stop_loss_pct=0.03,
        )
        self.assertAlmostEqual(stop, 95.0, places=6, msg="Must clamp to the 5% policy ceiling, not follow support to 50.")

    def test_never_tighter_than_the_noise_floor(self):
        stop = technical_stop_loss(
            entry_price=100.0, side="buy", support=99.99, resistance=110.0, atr=0.01,
            max_stop_loss_pct=0.10, default_stop_loss_pct=0.03, min_stop_loss_pct=0.01,
        )
        self.assertLessEqual(stop, 99.0, "A stop a hair from entry would be noise-triggered; it must be floored.")

    def test_falls_back_to_the_flat_default_with_no_technical_level(self):
        stop = technical_stop_loss(
            entry_price=100.0, side="buy", support=None, resistance=None, atr=None,
            max_stop_loss_pct=0.10, default_stop_loss_pct=0.03,
        )
        self.assertAlmostEqual(stop, 97.0, places=6)

    def test_a_nonsensical_support_above_entry_falls_back_rather_than_inverting(self):
        stop = technical_stop_loss(
            entry_price=100.0, side="buy", support=120.0, resistance=130.0, atr=1.0,
            max_stop_loss_pct=0.10, default_stop_loss_pct=0.03,
        )
        self.assertAlmostEqual(stop, 97.0, places=6, msg="A support above entry is not a stop level; use the flat default.")
        self.assertLess(stop, 100.0, "A buy stop must always be below entry.")

    def test_sell_side_places_the_stop_above_resistance_and_clamps(self):
        stop = technical_stop_loss(
            entry_price=100.0, side="sell", support=90.0, resistance=103.0, atr=2.0,
            max_stop_loss_pct=0.10, default_stop_loss_pct=0.03,
        )
        self.assertGreater(stop, 103.0, "A sell stop must sit just beyond resistance.")
        clamped = technical_stop_loss(
            entry_price=100.0, side="sell", support=90.0, resistance=150.0, atr=2.0,
            max_stop_loss_pct=0.05, default_stop_loss_pct=0.03,
        )
        self.assertAlmostEqual(clamped, 105.0, places=6)


class TechnicalTakeProfitTests(unittest.TestCase):
    def test_uses_a_real_resistance_level_when_it_clears_the_required_ratio(self):
        target = technical_take_profit(
            entry_price=100.0, stop_loss=97.0, side="buy", resistance=112.0, support=95.0, min_reward_risk=2.0,
        )
        self.assertAlmostEqual(target, 112.0, places=6)

    def test_rejects_a_technical_level_that_would_break_the_required_reward_risk(self):
        # Resistance at 104 would be only ~1.3:1 against a 3-point risk -- policy wins.
        target = technical_take_profit(
            entry_price=100.0, stop_loss=97.0, side="buy", resistance=104.0, support=95.0, min_reward_risk=2.0,
        )
        self.assertAlmostEqual(target, 106.0, places=6, msg="Risk/reward discipline is policy, not discretion.")

    def test_falls_back_to_the_ratio_target_without_a_level(self):
        target = technical_take_profit(
            entry_price=100.0, stop_loss=97.0, side="buy", resistance=None, support=None, min_reward_risk=2.0,
        )
        self.assertAlmostEqual(target, 106.0, places=6)

    def test_sell_side_mirrors_correctly(self):
        target = technical_take_profit(
            entry_price=100.0, stop_loss=103.0, side="sell", resistance=105.0, support=88.0, min_reward_risk=2.0,
        )
        self.assertAlmostEqual(target, 88.0, places=6)
        self.assertLess(target, 100.0, "A sell target must be below entry.")


class ConvictionScaledNotionalTests(unittest.TestCase):
    def test_maximum_confidence_takes_the_full_approved_allowance(self):
        self.assertAlmostEqual(
            conviction_scaled_notional(approved_notional=100.0, confidence=1.0, min_confidence=0.85),
            100.0, places=6,
        )

    def test_minimum_confidence_takes_the_smallest_fraction(self):
        self.assertAlmostEqual(
            conviction_scaled_notional(approved_notional=100.0, confidence=0.85, min_confidence=0.85),
            50.0, places=6,
        )

    def test_never_exceeds_the_approved_ceiling_even_for_absurd_confidence(self):
        # THE safety property: this can only ever decline to use the full allowance.
        for confidence in (1.0, 1.5, 99.0):
            scaled = conviction_scaled_notional(approved_notional=100.0, confidence=confidence, min_confidence=0.85)
            self.assertLessEqual(scaled, 100.0, f"Must never exceed the policy-approved ceiling (confidence={confidence}).")

    def test_below_minimum_confidence_still_never_goes_below_the_floor_fraction(self):
        scaled = conviction_scaled_notional(approved_notional=100.0, confidence=0.1, min_confidence=0.85)
        self.assertAlmostEqual(scaled, 50.0, places=6)

    def test_a_rejected_zero_allocation_stays_zero(self):
        self.assertEqual(conviction_scaled_notional(approved_notional=0.0, confidence=0.95, min_confidence=0.85), 0.0)

    def test_scales_monotonically_with_conviction(self):
        weak = conviction_scaled_notional(approved_notional=100.0, confidence=0.87, min_confidence=0.85)
        strong = conviction_scaled_notional(approved_notional=100.0, confidence=0.98, min_confidence=0.85)
        self.assertLess(weak, strong, "Higher conviction must size nearer the top of the allowed range.")


if __name__ == "__main__":
    unittest.main()
