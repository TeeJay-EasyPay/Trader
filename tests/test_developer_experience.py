import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.api import LocalApiService
from ai_trader.benchmark import BenchmarkIntelligenceDatabase
from ai_trader.config import Settings
from ai_trader.db_browser import ReadOnlyDatabaseBrowser
from ai_trader.intelligence import InvestmentIntelligenceDatabase
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


class DeveloperExperienceTests(unittest.TestCase):
    def test_developer_status_reports_local_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(tmp)
            InvestmentIntelligenceDatabase(settings.db_path).seed_initial_data()
            BenchmarkIntelligenceDatabase(settings.db_path).seed_initial_data()

            status = LocalApiService(settings).developer_status()

            self.assertEqual(status["components"]["python"]["state"], "Healthy")
            self.assertEqual(status["counts"]["watchlist"], 31)
            self.assertEqual(status["counts"]["market_themes"], 10)
            self.assertEqual(status["counts"]["benchmark_traders"], 4)

    def test_database_browser_lists_and_searches_tables_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            with closing(sqlite3.connect(db_path)) as conn:
                with conn:
                    conn.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, name TEXT)")
                    conn.execute("INSERT INTO sample (name) VALUES ('alpha'), ('beta')")

            browser = ReadOnlyDatabaseBrowser(db_path)
            columns, rows = browser.rows("sample", search="alp", sort="name")

            self.assertIn("sample", browser.tables())
            self.assertEqual(columns, ["id", "name"])
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["name"], "alpha")


if __name__ == "__main__":
    unittest.main()
