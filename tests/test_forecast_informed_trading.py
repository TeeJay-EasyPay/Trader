"""Phase 4 of the CIO-level forecasting build (2026-08-20, Founder-directed):
the forecast becomes a genuine INPUT to trade selection, not just a display.

Two halves, both tested here:
- Upstream: the forecast reaches the proposal LLM's prompt context, so it shapes
  confidence and the written thesis at the point they are formed.
- Downstream: a rare hard-block circuit breaker in the Risk Sentinel for the severe
  case -- a fresh trade straight into a confidently-called opposite move whose reasoning
  never acknowledges it.

The bar for that block is deliberately high (see sprint6.py's constants). A gate that
fires often would silently starve trade volume, which is far harder to notice than an
outright failure and which this system has already suffered from other causes.
"""

import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.forecasting import record_forecast
from ai_trader.models import AccountContext, TradeProposal
from ai_trader.proposal_context import build_proposal_context
from ai_trader.sprint6 import _market_forecast_conflict, production_risk_sentinel_decision


def _proposal(**overrides) -> TradeProposal:
    data = {
        "symbol": "BTC",
        "side": "buy",
        "entry_price": 50000.0,
        "stop_loss": 49000.0,
        "take_profit": 52000.0,
        "position_size": 0.001,
        "risk_percentage": 0.01,
        "confidence_score": 0.9,
        "news_summary": "news",
        "market_sentiment_summary": "sentiment",
        "technical_summary": "technical",
        "plain_english_reasoning": "Momentum is positive and the setup is clean.",
        "ai_guardrails_passed": True,
        "asset_type": "crypto",
        "exchange": "KRAKEN",
    }
    data.update(overrides)
    return TradeProposal(**data).normalized()


def _seed_forecast(db_path: Path, *, direction: str, confidence: float, symbol: str = "BTC") -> None:
    record_forecast(
        db_path,
        scope="symbol",
        symbol=symbol,
        asset_type="crypto",
        forecast={
            "direction": direction,
            "horizon_days": 14,
            "confidence": confidence,
            "reasoning": "Real multi-timeframe technical read.",
            "supporting_evidence": ["daily momentum weak"],
            "contradictory_evidence": ["weekly trend still intact"],
            "key_risks": ["a sharp reversal"],
            "invalidation": "A daily close back above the 20-period moving average.",
        },
        evidence={"daily": {"candles_available": 40}},
        generated_by="test-model",
    )


class ForecastConflictGateTests(unittest.TestCase):
    def test_a_confident_opposing_forecast_blocks_an_unaware_trade(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            _seed_forecast(db_path, direction="bearish", confidence=0.85)

            conflict = _market_forecast_conflict(db_path, proposal=_proposal(side="buy"))

            self.assertIsNotNone(conflict)
            self.assertIn("market_forecast_conflict", conflict["issue"])
            self.assertEqual(conflict["evidence"]["direction"], "bearish")

    def test_a_trade_whose_reasoning_addresses_the_opposing_view_is_left_alone(self):
        # A considered disagreement is exactly what a good analyst does -- this gate
        # exists to catch trades that appear unaware of the conflict, not to override
        # real judgment.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            _seed_forecast(db_path, direction="bearish", confidence=0.85)

            aware = _proposal(
                side="buy",
                plain_english_reasoning="Despite the bearish backdrop, this specific support level has held three times.",
            )
            self.assertIsNone(_market_forecast_conflict(db_path, proposal=aware))

    def test_a_low_confidence_forecast_never_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            _seed_forecast(db_path, direction="bearish", confidence=0.55)
            self.assertIsNone(_market_forecast_conflict(db_path, proposal=_proposal(side="buy")))

    def test_an_agreeing_forecast_never_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            _seed_forecast(db_path, direction="bullish", confidence=0.95)
            self.assertIsNone(_market_forecast_conflict(db_path, proposal=_proposal(side="buy")))

    def test_no_forecast_at_all_never_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            self.assertIsNone(_market_forecast_conflict(db_path, proposal=_proposal(side="buy")))

    def test_a_stale_forecast_stops_blocking(self):
        # A view formed days ago must not keep blocking trades indefinitely.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            _seed_forecast(db_path, direction="bearish", confidence=0.85)
            import sqlite3
            from contextlib import closing

            stale = (datetime.now(timezone.utc) - timedelta(hours=72)).isoformat()
            with closing(sqlite3.connect(db_path)) as conn:
                with conn:
                    conn.execute("UPDATE FORECAST_RECORDS SET created_at = ?", (stale,))

            self.assertIsNone(_market_forecast_conflict(db_path, proposal=_proposal(side="buy")))

    def test_the_risk_sentinel_actually_blocks_on_a_real_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            _seed_forecast(db_path, direction="bearish", confidence=0.9)
            account = AccountContext(equity=10_000, daily_realized_pnl=0, open_positions=[])

            decision = production_risk_sentinel_decision(
                db_path, proposal=_proposal(side="buy"), broker="kraken", account=account,
            )

            self.assertEqual(decision["decision"], "blocked")
            self.assertIn("market_forecast_conflict", decision["reason"])

    def test_the_risk_sentinel_still_approves_a_clean_trade_with_an_agreeing_forecast(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            _seed_forecast(db_path, direction="bullish", confidence=0.9)
            account = AccountContext(equity=10_000, daily_realized_pnl=0, open_positions=[])

            decision = production_risk_sentinel_decision(
                db_path, proposal=_proposal(side="buy"), broker="kraken", account=account,
            )

            self.assertEqual(decision["decision"], "approved")


class ForecastReachesTheProposalPromptTests(unittest.TestCase):
    def test_the_forecast_is_included_in_proposal_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            _seed_forecast(db_path, direction="bearish", confidence=0.8)

            context = build_proposal_context(db_path, symbol="BTC", asset_type="crypto")

            self.assertIn("market_forecast", context)
            self.assertIn("bearish", context["market_forecast"])
            self.assertIn("Real multi-timeframe technical read", context["market_forecast"])
            self.assertIn("invalidate", context["market_forecast"].lower())
            # Contradictory evidence must be shown too -- a one-sided forecast would push
            # the model toward simply agreeing with it.
            self.assertIn("weekly trend still intact", context["market_forecast"])

    def test_no_forecast_yet_is_stated_honestly_rather_than_omitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            context = build_proposal_context(db_path, symbol="BTC", asset_type="crypto")
            self.assertIn("market_forecast", context)
            self.assertIn("no market forecast", context["market_forecast"].lower())


if __name__ == "__main__":
    unittest.main()
