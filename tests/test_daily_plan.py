import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.api import LocalApiService
from ai_trader.config import Settings
from ai_trader.daily_plan import daily_trading_plan_status, record_daily_trading_plan, trading_day_for
from ai_trader.models import AutoTradeConfig, GuardrailConfig, TradeProposal
from ai_trader.production_evidence import record_trade_evidence


def settings_for(tmp: str) -> Settings:
    root = Path(tmp)
    return Settings(
        alpaca_api_key=None,
        alpaca_secret_key=None,
        alpaca_paper_base_url="https://paper-api.alpaca.markets",
        alpaca_data_base_url="https://data.alpaca.markets",
        openai_api_key=None,
        openai_model="gpt-4.1-mini",
        db_path=root / "audit.sqlite3",
        output_dir=root,
        trading_log_path=root / "TRADING_LOG.md",
        guardrails=GuardrailConfig(),
        auto_trade=AutoTradeConfig(),
    )


def _proposal(symbol: str = "AAPL") -> TradeProposal:
    return TradeProposal(
        symbol=symbol,
        side="buy",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        position_size=1.0,
        risk_percentage=1.0,
        confidence_score=0.9,
        news_summary="",
        market_sentiment_summary="",
        technical_summary="",
        plain_english_reasoning="Strong quarter and healthy balance sheet.",
    )


class DailyTradingPlanTests(unittest.TestCase):
    def test_no_plan_yet_reports_not_yet_generated(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(tmp)

            status = daily_trading_plan_status(settings.db_path, broker="alpaca")

            self.assertEqual(status["status"], "not_yet_generated")
            self.assertIn("not been generated yet", status["plain_english"])

    def test_seek_trades_plan_with_no_trades_yet(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(tmp)
            record_daily_trading_plan(
                settings.db_path,
                broker="alpaca",
                decision="seek_trades",
                market_assessment="Morning scan of 19 candidate(s) from the watchlist.",
                reasoning="AAPL: Strong quarter and healthy balance sheet.",
                symbols_scanned=19,
                candidates_found=1,
            )

            status = daily_trading_plan_status(settings.db_path, broker="alpaca")

            self.assertEqual(status["status"], "generated")
            self.assertEqual(status["decision"], "seek_trades")
            self.assertEqual(status["trades_today"], 0)
            self.assertEqual(status["outcome"], "no_trades_yet")

    def test_seek_trades_plan_with_a_real_trade_is_as_planned(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(tmp)
            record_daily_trading_plan(
                settings.db_path,
                broker="alpaca",
                decision="seek_trades",
                market_assessment="Morning scan of 19 candidate(s) from the watchlist.",
                reasoning="AAPL: Strong quarter and healthy balance sheet.",
                symbols_scanned=19,
                candidates_found=1,
            )
            record_trade_evidence(
                settings.db_path,
                broker="alpaca",
                event={"order_id": "order-1", "status": "filled", "symbol": "AAPL", "qty": 1, "price": 101.0},
            )

            status = daily_trading_plan_status(settings.db_path, broker="alpaca")

            self.assertEqual(status["trades_today"], 1)
            self.assertEqual(status["outcome"], "as_planned")

    def test_stand_aside_plan_with_no_trades_is_as_planned(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(tmp)
            record_daily_trading_plan(
                settings.db_path,
                broker="alpaca",
                decision="stand_aside",
                market_assessment="Morning scan of 19 candidate(s) from the watchlist.",
                reasoning="None of the 19 candidate(s) scanned this morning produced a trade idea.",
                symbols_scanned=19,
                candidates_found=0,
            )

            status = daily_trading_plan_status(settings.db_path, broker="alpaca")

            self.assertEqual(status["decision"], "stand_aside")
            self.assertEqual(status["outcome"], "as_planned")
            self.assertIn("Stood aside as planned", status["outcome_plain_english"])

    def test_stand_aside_plan_with_a_trade_is_flagged_as_broken(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(tmp)
            record_daily_trading_plan(
                settings.db_path,
                broker="alpaca",
                decision="stand_aside",
                market_assessment="Morning scan of 19 candidate(s) from the watchlist.",
                reasoning="None of the 19 candidate(s) scanned this morning produced a trade idea.",
                symbols_scanned=19,
                candidates_found=0,
            )
            record_trade_evidence(
                settings.db_path,
                broker="alpaca",
                event={"order_id": "order-2", "status": "filled", "symbol": "NVDA", "qty": 1, "price": 500.0},
            )

            status = daily_trading_plan_status(settings.db_path, broker="alpaca")

            self.assertEqual(status["outcome"], "plan_broken")

    def test_record_is_idempotent_per_broker_and_trading_day(self):
        """A retried premarket-equity job (this deployment's idempotency-key scheduling
        can re-run a job) must never overwrite the morning's real decision with a
        second, possibly different one."""
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(tmp)
            first = record_daily_trading_plan(
                settings.db_path,
                broker="alpaca",
                decision="stand_aside",
                market_assessment="First pass.",
                reasoning="Nothing found.",
                symbols_scanned=19,
                candidates_found=0,
            )
            second = record_daily_trading_plan(
                settings.db_path,
                broker="alpaca",
                decision="seek_trades",
                market_assessment="Second pass -- must not win.",
                reasoning="Should be ignored.",
                symbols_scanned=19,
                candidates_found=1,
            )

            self.assertEqual(first["decision"], "stand_aside")
            self.assertEqual(second["decision"], "stand_aside")
            self.assertEqual(second["market_assessment"], "First pass.")

    def test_invalid_decision_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(tmp)
            with self.assertRaises(ValueError):
                record_daily_trading_plan(
                    settings.db_path,
                    broker="alpaca",
                    decision="maybe_later",
                    market_assessment="x",
                    reasoning="x",
                    symbols_scanned=1,
                    candidates_found=0,
                )

    def test_trading_day_uses_america_new_york_for_alpaca(self):
        # 2026-08-14T02:00:00Z is 2026-08-13T22:00 in America/New_York (UTC-4 in August).
        moment = datetime(2026, 8, 14, 2, 0, tzinfo=timezone.utc)
        self.assertEqual(trading_day_for("alpaca", now=moment), "2026-08-13")

    def test_research_service_records_seek_trades_when_a_proposal_survives(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(tmp)
            service = LocalApiService(settings)

            service._research_service._record_daily_trading_plan(
                ["AAPL", "MSFT"], [_proposal("AAPL")], []
            )

            status = daily_trading_plan_status(settings.db_path, broker="alpaca")
            self.assertEqual(status["decision"], "seek_trades")
            self.assertEqual(status["candidates_found"], 1)
            self.assertIn("AAPL", status["reasoning"])

    def test_research_service_records_stand_aside_when_nothing_survives(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(tmp)
            service = LocalApiService(settings)

            service._research_service._record_daily_trading_plan(["AAPL", "MSFT"], [], [])

            status = daily_trading_plan_status(settings.db_path, broker="alpaca")
            self.assertEqual(status["decision"], "stand_aside")
            self.assertEqual(status["candidates_found"], 0)


if __name__ == "__main__":
    unittest.main()
