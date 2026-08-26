import os
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

    def test_kraken_sleeve_with_room_to_diversify_does_not_trip_the_concentration_warning(self):
        # 2026-08-13 hosted incident: confirmed live that this deployment's real
        # KRAKEN_MAX_OPEN_TRADES is 5 (render.yaml states 1, but Render's dashboard overrides
        # it -- the same class of drift already found for KRAKEN_MIN_ORDER_GBP). With only 2 of
        # 5 designed slots genuinely filled, >25% concentration in the current largest position
        # is not a diversification failure -- there's real room (3 more slots) to dilute it, and
        # the fix is for the sleeve to keep filling, not to block every candidate that could do
        # that filling. Confirmed live: with a legacy position at 50% of a 2-position book, this
        # warning demoted every single new candidate to portfolio_manager_manual_review
        # regardless of symbol -- a closed loop, since the 3 remaining slots that would have
        # diluted the concentration were exactly what every candidate was blocked from filling.
        # An earlier fix attempt used a flat "cap <= 1" skip (based on render.yaml's stated
        # default, not the real deployed value) -- confirmed live that it does not fire for a
        # real cap of 5, so the check instead compares position count to the sleeve's own actual
        # capacity, whatever that capacity really is.
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(tmp)
            positions = [
                {"symbol": "BCH", "market_value": 100},
                {"symbol": "XRP", "market_value": 20},
            ]
            old_value = os.environ.pop("KRAKEN_MAX_OPEN_TRADES", None)
            try:
                os.environ["KRAKEN_MAX_OPEN_TRADES"] = "5"
                kraken_exposure = calculate_portfolio_exposure(settings.db_path, positions, broker="kraken")
                self.assertFalse(any("is a large position" in warning for warning in kraken_exposure["warnings"]))

                # 2026-08-26: Alpaca was one of these "unaffected brokers", and that was the
                # bug rather than the design. It hit the identical closed loop live -- two
                # positions (FSLR 48.7%, NEE 51.3%) on a sleeve nowhere near capacity, with
                # $96k of cash unused, and every diversifying candidate demoted to
                # portfolio_manager_manual_review. It now reads its own capacity
                # (MAX_OPEN_POSITIONS, the same variable the guardrails use) and behaves like
                # Kraken here.
                os.environ["MAX_OPEN_POSITIONS"] = "3"
                alpaca_exposure = calculate_portfolio_exposure(settings.db_path, positions, broker="alpaca")
                self.assertFalse(any("is a large position" in warning for warning in alpaca_exposure["warnings"]))

                # A broker whose capacity genuinely is unknown keeps the conservative
                # always-on check rather than silently losing a safety signal.
                other_broker_exposure = calculate_portfolio_exposure(settings.db_path, positions, broker="coinbase")
                self.assertTrue(any("is a large position" in warning for warning in other_broker_exposure["warnings"]))
                no_broker_exposure = calculate_portfolio_exposure(settings.db_path, positions, broker=None)
                self.assertTrue(any("is a large position" in warning for warning in no_broker_exposure["warnings"]))

                # Once the sleeve has actually filled its own designed capacity (2 positions
                # held, cap of 2), concentration among those positions is a meaningful signal
                # again -- diversification was genuinely possible within the sleeve's own limit
                # and didn't happen.
                os.environ["KRAKEN_MAX_OPEN_TRADES"] = "2"
                full_sleeve_exposure = calculate_portfolio_exposure(settings.db_path, positions, broker="kraken")
                self.assertTrue(any("is a large position" in warning for warning in full_sleeve_exposure["warnings"]))
            finally:
                if old_value is None:
                    os.environ.pop("KRAKEN_MAX_OPEN_TRADES", None)
                else:
                    os.environ["KRAKEN_MAX_OPEN_TRADES"] = old_value


if __name__ == "__main__":
    unittest.main()
