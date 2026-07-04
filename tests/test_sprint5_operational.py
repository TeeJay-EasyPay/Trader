import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.api import LocalApiService
from ai_trader.audit import AuditDatabase
from ai_trader.benchmark import BenchmarkIntelligenceDatabase
from ai_trader.broker_adapters import CoinbaseAdapter, KrakenAdapter
from ai_trader.config import Settings
from ai_trader.models import AutoTradeConfig, GuardrailConfig, OrderRequest, TradeProposal, ValidationResult
from ai_trader.operational import initialize_operational_schema, record_portfolio_snapshot, safe_score, seed_crypto_universe


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


class Sprint5OperationalTests(unittest.TestCase):
    def test_qualitative_scores_parse_safely(self):
        self.assertEqual(safe_score("Good"), 0.75)
        self.assertEqual(safe_score("Medium"), 0.5)
        self.assertEqual(safe_score("High"), 0.85)
        self.assertEqual(safe_score("Cautious"), 0.35)
        self.assertIsNone(safe_score("not-a-score"))

    def test_recommendations_do_not_crash_on_good_confidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(tmp)
            audit = AuditDatabase(settings.db_path, settings.trading_log_path)
            proposal = TradeProposal(
                symbol="AAPL",
                side="buy",
                entry_price=100,
                stop_loss=97,
                take_profit=106,
                position_size=1,
                risk_percentage=0.001,
                confidence_score=0.9,
                philosophy_fit=0.9,
                news_summary="News",
                market_sentiment_summary="Positive",
                technical_summary="Good",
                plain_english_reasoning="Reason",
                ai_guardrails_passed=True,
            )
            audit.record_trade_event("agent_proposal", proposal, validation=ValidationResult(passed=True))
            with closing(sqlite3.connect(settings.db_path)) as conn:
                with conn:
                    conn.execute("UPDATE trade_audit SET ai_confidence = 'Good' WHERE proposal_id = ?", (proposal.proposal_id,))

            recommendations = LocalApiService(settings).recommendations()

            self.assertEqual(recommendations[0]["confidence"], 0.75)

    def test_portfolio_snapshot_creation_and_unavailable_pnl_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            snapshot = record_portfolio_snapshot(
                db_path,
                broker="alpaca",
                exchange="Alpaca",
                account={"currency": "USD", "cash": "1000", "portfolio_value": "1000", "buying_power": "4000"},
                positions=[],
                notes="test",
            )

            self.assertIsNone(snapshot["day_pnl"])
            with closing(sqlite3.connect(db_path)) as conn:
                count = conn.execute("SELECT COUNT(*) FROM PORTFOLIO_SNAPSHOTS").fetchone()[0]
            self.assertEqual(count, 1)

    def test_research_run_tracking(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(tmp)
            service = LocalApiService(settings)
            result = service.run_analysis({"symbols": "AAPL", "trigger_type": "scheduled"})

            self.assertEqual(result["status"], "not_available")
            with closing(sqlite3.connect(settings.db_path)) as conn:
                row = conn.execute("SELECT status, trigger_type FROM RESEARCH_RUNS ORDER BY research_run_id DESC LIMIT 1").fetchone()
            self.assertEqual(row[1], "scheduled")

    def test_benchmark_falls_back_to_latest_seeded_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(tmp)
            BenchmarkIntelligenceDatabase(settings.db_path).seed_initial_data()

            brief = LocalApiService(settings).benchmark_daily_brief("2099-01-01")

            self.assertTrue(brief["items"])
            self.assertIn("showing latest", brief["unavailable_reason"])

    def test_exchange_selector_unconfigured_states(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalApiService(settings_for(tmp))

            kraken = service.portfolio("kraken")
            coinbase = service.portfolio("coinbase")

            self.assertIn("Kraken not configured", kraken["source"])
            self.assertIn("Coinbase not configured", coinbase["source"])

    def test_kraken_and_coinbase_not_configured(self):
        request = OrderRequest("BTC", "buy", 1, "crypto", "KRAKEN", 100, 120)

        self.assertEqual(KrakenAdapter().place_order(request)["status"], "not_configured")
        self.assertEqual(CoinbaseAdapter().place_order(request)["status"], "not_configured")

    def test_crypto_universe_table_creation_without_dummy_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            result = seed_crypto_universe(db_path, fetch_live=False)

            self.assertEqual(result["inserted"], 0)
            self.assertIn("not requested", result["notes"])
            with closing(sqlite3.connect(db_path)) as conn:
                count = conn.execute("SELECT COUNT(*) FROM CRYPTO_ASSET_MASTER").fetchone()[0]
            self.assertEqual(count, 0)

    def test_safe_crypto_auto_trade_rejected_when_disabled(self):
        request = OrderRequest("BTC", "buy", 1, "crypto", "KRAKEN", 100, 120)
        adapter = KrakenAdapter()

        self.assertEqual(adapter.place_order(request)["status"], "not_configured")


if __name__ == "__main__":
    unittest.main()
