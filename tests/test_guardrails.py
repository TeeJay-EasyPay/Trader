import unittest
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.guardrails import validate_trade_proposal
from ai_trader.models import AccountContext, GuardrailConfig, Position, TradeProposal


MARKET_TIME = datetime(2026, 7, 2, 10, 0, tzinfo=ZoneInfo("America/New_York"))


def proposal(**overrides):
    data = {
        "symbol": "AAPL",
        "side": "buy",
        "entry_price": 100.0,
        "stop_loss": 99.0,
        "take_profit": 102.0,
        "position_size": 10.0,
        "risk_percentage": 0.0001,
        "confidence_score": 0.8,
        "news_summary": "news",
        "market_sentiment_summary": "sentiment",
        "technical_summary": "technical",
        "plain_english_reasoning": "reason",
    }
    data.update(overrides)
    return TradeProposal(**data).normalized()


class GuardrailTests(unittest.TestCase):
    def test_valid_proposal_passes(self):
        result = validate_trade_proposal(
            proposal(),
            AccountContext(equity=100_000, daily_realized_pnl=0, open_positions=[]),
            GuardrailConfig(),
            now=MARKET_TIME,
        )
        self.assertTrue(result.passed)

    def test_rejects_duplicate_position(self):
        result = validate_trade_proposal(
            proposal(),
            AccountContext(equity=100_000, daily_realized_pnl=0, open_positions=[Position("AAPL", 1)]),
            GuardrailConfig(),
            now=MARKET_TIME,
        )
        self.assertFalse(result.passed)
        self.assertIn("duplicate_open_position", result.failures)

    def test_rejects_outside_trading_hours(self):
        result = validate_trade_proposal(
            proposal(),
            AccountContext(equity=100_000, daily_realized_pnl=0, open_positions=[]),
            GuardrailConfig(),
            now=datetime(2026, 7, 4, 10, 0, tzinfo=ZoneInfo("America/New_York")),
        )
        self.assertFalse(result.passed)
        self.assertIn("outside_regular_trading_hours", result.failures)

    def test_rejects_a_live_non_paper_stock_account(self):
        # Stage 0.4 (architecture/AI_TRADER_MODULARISATION_ARCHITECTURE_2026-08-02.md
        # section 3): "Alpaca remains paper-only unless an explicitly approved future
        # change alters that policy." No existing test exercised the actual failure
        # path -- only the default (paper, passing) case was covered.
        result = validate_trade_proposal(
            proposal(asset_type="stock"),
            AccountContext(equity=100_000, daily_realized_pnl=0, open_positions=[], is_paper=False),
            GuardrailConfig(paper_trading_only=True),
            now=MARKET_TIME,
        )
        self.assertFalse(result.passed)
        self.assertIn("paper_trading_only_failed", result.failures)

    def test_crypto_is_exempt_from_the_paper_only_check(self):
        # Kraken crypto trading is deliberately real-money (the founder's isolated £100
        # sleeve), so the paper-only guard must not block it the way it blocks stocks.
        result = validate_trade_proposal(
            proposal(asset_type="crypto", symbol="BTC"),
            AccountContext(equity=100_000, daily_realized_pnl=0, open_positions=[], is_paper=False),
            GuardrailConfig(paper_trading_only=True),
            now=MARKET_TIME,
        )
        self.assertNotIn("paper_trading_only_failed", result.failures)


if __name__ == "__main__":
    unittest.main()
