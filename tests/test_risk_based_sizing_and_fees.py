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

from ai_trader.models import AutoTradeConfig
from ai_trader.technical_discretion import (
    cash_capped_notional,
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


class CryptoSizingDefaultsTests(unittest.TestCase):
    """2026-08-22 Founder-directed: "trade larger, e.g. GBP 50 instead of GBP 25". Live trade
    history showed real recent entries landing at ~GBP 2 (Kraken's own order minimum), well
    below even the old ~GBP 25 ceiling -- reconstructing the old formula against the real
    entry/stop from one such trade does NOT reproduce GBP 2 (it comes out close to the old
    GBP 25 ceiling instead), so the exact mechanism behind those specific historical GBP 2
    fills is not confirmed by this change and is called out as still open, separate from the
    sizing increase itself. What IS confirmed and tested here: the new defaults raise both
    the typical and ceiling trade size to the Founder-requested ~GBP 50, and the two
    ceilings that must move together (the requested-size percentage and the broker's hard
    rejection percentage) stay in agreement.
    """

    def _typical_notional(self, config: AutoTradeConfig, *, equity: float, entry: float, stop_pct: float) -> float:
        risk_budget = max(0.0, equity * config.crypto_risk_per_trade_pct)
        ceiling = equity * config.crypto_max_trade_pct
        stop_loss = entry * (1.0 - stop_pct)
        return risk_based_notional(risk_budget=risk_budget, entry_price=entry, stop_loss=stop_loss, max_notional=ceiling)

    def test_the_old_defaults_did_not_actually_reproduce_the_observed_two_pound_fills(self):
        # Documented so this isn't re-litigated as "obviously explained" later: reconstructing
        # the OLD formula (0.0015 / 0.05) against the real entry/stop from a live ETH trade
        # produces a notional near the old GBP 25 ceiling, not GBP 2. Whatever produced the
        # historical GBP 2 fills, it was not simply "the risk budget was too small" under
        # realistic stop distances.
        old_risk_pct, old_max_pct = 0.0015, 0.05
        equity = 500.0
        entry = 1666.50  # the real ETH entry price from the observed live trade.
        stop_loss = 1640.08  # that same trade's real original_stop.
        risk_budget = equity * old_risk_pct
        ceiling = equity * old_max_pct
        notional = risk_based_notional(risk_budget=risk_budget, entry_price=entry, stop_loss=stop_loss, max_notional=ceiling)
        self.assertGreater(notional, 20.0, "The old formula, reconstructed against the real trade, does not land near GBP 2.")

    def test_the_new_defaults_produce_a_meaningfully_larger_trade_at_every_realistic_stop_distance(self):
        config = AutoTradeConfig()
        equity = 500.0
        entry = 1666.50
        for stop_pct in (0.015, 0.03, 0.05):
            notional = self._typical_notional(config, equity=equity, entry=entry, stop_pct=stop_pct)
            self.assertGreaterEqual(
                notional, 20.0,
                f"stop_pct={stop_pct}: new defaults still only produced GBP {notional:.2f} -- "
                "the fix must move real trade size well clear of the GBP 2 exchange minimum.",
            )

    def test_the_new_percentage_of_cash_ceiling_is_the_founder_requested_fifty_pounds_on_a_typical_account(self):
        config = AutoTradeConfig()
        equity = 500.0
        ceiling = equity * config.crypto_max_trade_pct
        self.assertAlmostEqual(ceiling, 50.0, places=2)

    def test_the_hard_reject_ceiling_and_the_requested_size_ceiling_agree(self):
        # Regression guard for the "three limits must move together" trap already found
        # twice in this codebase's history (KRAKEN_MAX_ORDER_PCT_OF_CASH vs.
        # crypto_max_trade_pct): if these two ever drift apart again, the sizing change
        # would be silently rejected at the broker layer instead of taking effect.
        from ai_trader.broker_adapters import _float_env

        config = AutoTradeConfig()
        broker_reject_pct = _float_env("KRAKEN_MAX_ORDER_PCT_OF_CASH", 0.10)
        self.assertAlmostEqual(config.crypto_max_trade_pct, broker_reject_pct, places=6)

    def test_load_settings_actually_uses_the_dataclass_defaults_rather_than_stale_literals(self):
        """The trap that made the GBP 50 sizing increase inert in production for a day.

        models.py's AutoTradeConfig defaults were raised, but config.py's load_settings()
        passed its own hardcoded literals (0.05 / 0.0015) for the same fields, so the
        dataclass defaults were never consulted and live sizing never changed. This asserts
        the two agree for EVERY field, not just the two that drifted -- any future default
        changed in one place but not the other fails here instead of silently doing nothing.
        """
        import os
        from dataclasses import fields
        from unittest import mock

        from ai_trader.config import load_settings

        env_names = {
            "min_confidence": "AUTO_TRADE_MIN_CONFIDENCE",
            "min_philosophy_fit": "AUTO_TRADE_MIN_PHILOSOPHY_FIT",
            "max_trade_amount": "MAX_AUTO_TRADE_AMOUNT",
            "default_stop_loss_pct": "DEFAULT_STOP_LOSS_PCT",
            "max_stop_loss_pct": "MAX_STOP_LOSS_PCT",
            "crypto_max_trade_amount": "CRYPTO_MAX_AUTO_TRADE_AMOUNT",
            "crypto_max_trade_pct": "CRYPTO_MAX_AUTO_TRADE_PCT",
            "crypto_risk_per_trade_pct": "CRYPTO_RISK_PER_TRADE_PCT",
            "crypto_min_net_reward_risk": "CRYPTO_MIN_NET_REWARD_RISK",
            "crypto_default_stop_loss_pct": "CRYPTO_DEFAULT_STOP_LOSS_PCT",
            "crypto_max_stop_loss_pct": "CRYPTO_MAX_STOP_LOSS_PCT",
        }
        # Clear every override so load_settings() must fall back to its own defaults, and
        # neutralise .env so a developer's local file cannot mask a real drift.
        cleared = {name: "" for name in env_names.values()}
        with mock.patch.dict(os.environ, cleared, clear=False):
            for name in env_names.values():
                os.environ.pop(name, None)
            with mock.patch("ai_trader.config.load_dotenv", lambda *a, **k: None):
                live = load_settings().auto_trade

        expected = AutoTradeConfig()
        for field_def in fields(AutoTradeConfig):
            if field_def.name not in env_names:
                continue
            self.assertEqual(
                getattr(live, field_def.name),
                getattr(expected, field_def.name),
                f"{field_def.name}: load_settings() default disagrees with AutoTradeConfig's. "
                "Change it in models.py only -- config.py must read the dataclass default.",
            )

    def test_cash_capped_notional_never_undoes_the_larger_ceiling(self):
        # Sanity check that the risk-reducing cash cap (max_trade_pct_of_available_cash,
        # a SEPARATE RISK_POLICIES-driven guard) does not itself reintroduce a tiny ceiling
        # when available cash matches the AI's allocation.
        capped = cash_capped_notional(approved_notional=50.0, available_cash=500.0, max_pct_of_available_cash=0.20)
        self.assertAlmostEqual(capped, 50.0, places=2)


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
