import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.intelligence import InvestmentIntelligenceDatabase
from ai_trader.intelligence_data import COMPANIES, THEMES


class InvestmentIntelligenceTests(unittest.TestCase):
    def test_seed_creates_watchlist_and_themes(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            db = InvestmentIntelligenceDatabase(db_path)

            result = db.seed_initial_data()

            self.assertEqual(result["companies"], len(COMPANIES))
            self.assertEqual(result["themes"], len(THEMES))
            with closing(sqlite3.connect(db_path)) as conn:
                company_count = conn.execute("SELECT COUNT(*) FROM COMPANY_MASTER").fetchone()[0]
                watchlist_count = conn.execute("SELECT COUNT(*) FROM INVESTMENT_WATCHLIST").fetchone()[0]
                theme_count = conn.execute("SELECT COUNT(*) FROM MARKET_THEMES").fetchone()[0]
            self.assertEqual(company_count, len(COMPANIES))
            self.assertEqual(watchlist_count, len(COMPANIES))
            self.assertEqual(theme_count, len(THEMES))

    def test_daily_refresh_appends_company_updates(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            db = InvestmentIntelligenceDatabase(db_path)
            db.seed_initial_data()

            result = db.daily_refresh(date(2026, 7, 3))

            self.assertEqual(result["companies_reviewed"], len(COMPANIES))
            self.assertEqual(result["themes_reviewed"], len(THEMES))
            with closing(sqlite3.connect(db_path)) as conn:
                daily_reviews = conn.execute(
                    "SELECT COUNT(*) FROM COMPANY_DAILY_UPDATES WHERE update_type = 'daily_review'"
                ).fetchone()[0]
            self.assertEqual(daily_reviews, len(COMPANIES))


if __name__ == "__main__":
    unittest.main()
