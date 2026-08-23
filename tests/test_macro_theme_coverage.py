"""2026-08-23: every equity recommendation was scoring macro_score 0, dragging
overall_confidence to ~0.655 against an 0.85 auto-trade gate.

macro_score is decided by _macro_context_available (foundation.py), which matches a
company's sector/industry keywords against MARKET_THEMES. Where no theme covers a sector,
those companies score a permanent zero no matter how good the trade is -- not a judgement
about the trade, just missing reference data.

Measured against the live COMPANY_MASTER before the fix: 13 of 50 companies (26%) had no
matching theme -- Sports 6, Mining 4, Technology 2, Steel 1.
"""

import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.database import connect
from ai_trader.foundation import _macro_context_available, initialize_foundation_schema
from ai_trader.intelligence import InvestmentIntelligenceDatabase
from ai_trader.intelligence_data import COMPANIES, THEMES
from ai_trader.models import TradeProposal


def equity(symbol):
    return TradeProposal(
        symbol=symbol, side="buy", entry_price=100.0, stop_loss=98.0, take_profit=110.0,
        position_size=1.0, risk_percentage=0.01, confidence_score=0.9, news_summary="x",
        market_sentiment_summary="x", technical_summary="x", plain_english_reasoning="x",
        asset_type="stock", exchange="NASDAQ",
    ).normalized()


class MacroThemeCoverageTests(unittest.TestCase):
    def _seeded_db(self, tmp):
        db_path = Path(tmp) / "audit.sqlite3"
        initialize_foundation_schema(db_path)
        InvestmentIntelligenceDatabase(db_path).seed_initial_data()
        return db_path

    def test_every_seeded_company_has_macro_context(self):
        """The property that matters: no company in the tradeable universe should be denied
        macro context purely because its sector has no theme."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._seeded_db(tmp)
            uncovered = []
            with closing(connect(db_path)) as conn:
                for company in COMPANIES:
                    ticker = company.get("ticker")
                    if not ticker:
                        continue
                    if not _macro_context_available(conn, equity(ticker)):
                        uncovered.append(f"{ticker} ({company.get('sector')})")
            self.assertEqual(
                uncovered, [],
                "These companies score a permanent macro_score 0 because no MARKET_THEMES "
                f"row matches their sector/industry: {uncovered}",
            )

    def test_the_previously_uncovered_sectors_are_now_matched(self):
        """Named explicitly so a future theme edit that drops one of these fails loudly."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._seeded_db(tmp)
            with closing(connect(db_path)) as conn:
                for ticker in ("MSFT", "LULU"):  # Technology and Sports, both previously 0
                    self.assertTrue(
                        _macro_context_available(conn, equity(ticker)),
                        f"{ticker} was one of the 13 companies with no matching theme.",
                    )

    def test_an_unknown_company_still_honestly_reports_no_macro_context(self):
        """The fix must not turn this into 'always true' -- a symbol with no company record
        genuinely has no macro context, and saying otherwise would fabricate evidence."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self._seeded_db(tmp)
            with closing(connect(db_path)) as conn:
                self.assertFalse(_macro_context_available(conn, equity("ZZZZ")))

    def test_themes_carry_the_fields_the_matcher_reads(self):
        for theme in THEMES:
            for field in ("theme", "summary", "key_drivers"):
                self.assertTrue(
                    str(theme.get(field) or "").strip(),
                    f"{theme.get('theme')} is missing {field}, which the keyword match reads.",
                )


if __name__ == "__main__":
    unittest.main()
