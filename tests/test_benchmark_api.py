import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.api import LocalApiService
from ai_trader.benchmark import BenchmarkIntelligenceDatabase
from ai_trader.benchmark_data import BENCHMARK_RESEARCH, BENCHMARK_TRADERS
from ai_trader.config import Settings
from ai_trader.models import GuardrailConfig


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
    )


class BenchmarkAndApiTests(unittest.TestCase):
    def test_benchmark_seed_creates_public_research_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            db = BenchmarkIntelligenceDatabase(db_path)

            result = db.seed_initial_data()

            self.assertEqual(result["benchmark_traders"], len(BENCHMARK_TRADERS))
            self.assertEqual(result["benchmark_research_rows"], len(BENCHMARK_RESEARCH))
            with closing(sqlite3.connect(db_path)) as conn:
                trader_count = conn.execute("SELECT COUNT(*) FROM BENCHMARK_TRADERS").fetchone()[0]
                research_count = conn.execute("SELECT COUNT(*) FROM BENCHMARK_DAILY_RESEARCH").fetchone()[0]
                private_metrics = conn.execute(
                    """
                    SELECT COUNT(*) FROM BENCHMARK_TRADERS
                    WHERE performance_notes IS NOT NULL OR drawdown_notes IS NOT NULL OR consistency_score IS NOT NULL
                    """
                ).fetchone()[0]
            self.assertEqual(trader_count, len(BENCHMARK_TRADERS))
            self.assertEqual(research_count, len(BENCHMARK_RESEARCH))
            self.assertEqual(private_metrics, 0)

    def test_local_api_returns_missing_values_without_fabricating_portfolio(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalApiService(settings_for(tmp))
            service.intelligence.seed_initial_data()
            service.benchmark.seed_initial_data()

            portfolio = service.portfolio()
            benchmark = service.benchmark_daily_brief("2026-07-02")
            run_analysis = service.run_analysis({})

            self.assertIsNone(portfolio["portfolio_value"])
            self.assertEqual(len(benchmark["items"]), len(BENCHMARK_RESEARCH))
            self.assertEqual(run_analysis["status"], "not_available")


if __name__ == "__main__":
    unittest.main()
