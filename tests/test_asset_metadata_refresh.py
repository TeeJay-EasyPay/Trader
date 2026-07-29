import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.api import LocalApiService
from ai_trader.config import Settings
from ai_trader.models import AutoTradeConfig, GuardrailConfig
from ai_trader.portfolio_intelligence import calculate_portfolio_exposure


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
        database_backend="sqlite",
    )


def _seed_company(db_path: Path, ticker: str, sector: str, country: str) -> None:
    with closing(sqlite3.connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO COMPANY_MASTER (company_name, ticker, exchange, sector, industry, country, last_updated, created_at, updated_at)
                VALUES (?, ?, 'NASDAQ', ?, 'Software', ?, datetime('now'), datetime('now'), datetime('now'))
                """,
                (ticker, ticker, sector, country),
            )


class AssetMetadataRefreshTests(unittest.TestCase):
    def test_refresh_copies_company_master_sector_and_country_into_asset_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(tmp)
            service = LocalApiService(settings)
            _seed_company(settings.db_path, "AAPL", "Technology", "US")
            _seed_company(settings.db_path, "MSFT", "Technology", "US")

            updated = service._refresh_asset_metadata_from_company_master(["AAPL", "MSFT", "NOPE"])

            self.assertEqual(updated, 2)
            with closing(sqlite3.connect(settings.db_path)) as conn:
                conn.row_factory = sqlite3.Row
                rows = {row["symbol"]: row for row in conn.execute("SELECT symbol, sector, country FROM ASSET_METADATA")}
            self.assertEqual(rows["AAPL"]["sector"], "Technology")
            self.assertEqual(rows["AAPL"]["country"], "US")

    def test_portfolio_exposure_stops_defaulting_to_unknown_once_metadata_is_refreshed(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(tmp)
            service = LocalApiService(settings)
            _seed_company(settings.db_path, "AAPL", "Technology", "US")
            positions = [{"symbol": "AAPL", "market_value": 1000}]

            before = calculate_portfolio_exposure(settings.db_path, positions)
            self.assertIn("Unknown - sector metadata missing", before["exposure"]["sector"])

            service._refresh_asset_metadata_from_company_master(["AAPL"])
            after = calculate_portfolio_exposure(settings.db_path, positions)

            self.assertIn("Technology", after["exposure"]["sector"])
            self.assertNotIn("Unknown - sector metadata missing", after["exposure"]["sector"])


if __name__ == "__main__":
    unittest.main()
