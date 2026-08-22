"""Founder-directed 2026-08-22: leverage on the Alpaca equities learning track.

Alpaca already reports ~4x buying power ($407,457 against $101,864 equity), so this decides
how much of that the AI may use -- it grants nothing the broker was not already offering.

The Founder's own framing was leverage "capping losses with active trailing stops", so a
working trailing stop is treated as a PRECONDITION, not a companion feature.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.foundation import MAX_PERMITTED_LEVERAGE, effective_leverage


class FakePolicy:
    def __init__(self, multiplier=1.0, trailing=True):
        self.equities_leverage_multiplier = multiplier
        self.trailing_stop_enabled = trailing


class EffectiveLeverageTests(unittest.TestCase):
    def test_crypto_is_never_leveraged(self):
        """Kraken here is a spot account holding the Founder's real money. The leverage
        decision was made for the paper equities track only."""
        self.assertEqual(effective_leverage(FakePolicy(4.0, True), "crypto"), 1.0)

    def test_leverage_is_refused_when_trailing_stops_are_off(self):
        """The stop is what bounds the loss leverage creates, so no stop means no leverage.
        Reverting to cash-only is the safe failure."""
        self.assertEqual(effective_leverage(FakePolicy(4.0, False), "stock"), 1.0)

    def test_a_real_multiplier_applies_to_equities_when_stops_are_on(self):
        self.assertEqual(effective_leverage(FakePolicy(3.0, True), "stock"), 3.0)

    def test_it_is_clamped_to_the_hard_ceiling(self):
        """A fat-fingered policy value must not quietly authorise unlimited exposure."""
        self.assertEqual(effective_leverage(FakePolicy(50.0, True), "stock"), MAX_PERMITTED_LEVERAGE)

    def test_values_at_or_below_one_are_cash_only(self):
        for value in (1.0, 0.5, 0.0, -2.0):
            self.assertEqual(effective_leverage(FakePolicy(value, True), "stock"), 1.0, f"multiplier={value}")

    def test_a_junk_multiplier_falls_back_to_cash_only(self):
        for junk in ("abc", None, object()):
            self.assertEqual(effective_leverage(FakePolicy(junk, True), "stock"), 1.0)

    def test_it_defaults_to_off(self):
        """Leverage must never arrive via a deploy -- only a deliberate policy change."""
        from ai_trader.foundation import DEFAULT_RISK_POLICIES

        self.assertEqual(DEFAULT_RISK_POLICIES["equities_leverage_multiplier"][0], 1.0)


class LeveragedAllocationTests(unittest.TestCase):
    def _approved(self, multiplier, trailing, asset_type):
        import tempfile

        from ai_trader.foundation import calculate_capital_allocation, load_trading_policy, set_risk_policy_value
        from ai_trader.models import AutoTradeConfig, GuardrailConfig, TradeProposal

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            policy = load_trading_policy(db_path, auto_trade=AutoTradeConfig(), guardrails=GuardrailConfig())
            set_risk_policy_value(db_path, "equities_leverage_multiplier", multiplier)
            set_risk_policy_value(db_path, "trailing_stop_enabled", trailing)
            policy = load_trading_policy(db_path, auto_trade=AutoTradeConfig(), guardrails=GuardrailConfig())
            item = TradeProposal(
                symbol="AAPL", side="buy", entry_price=200.0, stop_loss=194.0, take_profit=230.0,
                position_size=10_000.0, risk_percentage=0.01, confidence_score=1.0,
                news_summary="x", market_sentiment_summary="x", technical_summary="x",
                plain_english_reasoning="x", asset_type=asset_type, exchange="NASDAQ",
            )
            equity = 100_000.0
            result = calculate_capital_allocation(
                db_path, item, policy, account_equity=equity, available_cash=equity,
            )
            return float(result["approved_notional"])

    def test_leverage_actually_increases_the_approved_equity_notional(self):
        cash_only = self._approved(1.0, True, "stock")
        levered = self._approved(3.0, True, "stock")
        self.assertAlmostEqual(cash_only, 5_000.0, places=2, msg="5% of 100k, unlevered.")
        self.assertAlmostEqual(levered, 15_000.0, places=2, msg="Leverage must reach the position ceiling, not be re-capped by the cash limit.")

    def test_turning_trailing_stops_off_removes_the_leverage(self):
        self.assertAlmostEqual(self._approved(3.0, False, "stock"), 5_000.0, places=2)


if __name__ == "__main__":
    unittest.main()
