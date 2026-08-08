import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.database import connect
from ai_trader.experience_engine import record_experience
from ai_trader.external_intelligence import initialize_external_intelligence_schema, record_crypto_news, record_market_regime_evidence
from ai_trader.market_intelligence_platform import multi_timeframe_conclusion
from ai_trader.proposal_context import build_proposal_context
from ai_trader.trading_intelligence import initialize_trading_intelligence_schema


class BuildProposalContextTests(unittest.TestCase):
    def test_returns_honest_no_data_strings_for_a_brand_new_symbol(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            context = build_proposal_context(db_path, symbol="ZZZZ", asset_type="stock")
        self.assertIn("No historical analogues", context["historical_analogues"])
        self.assertIn("No prior backtest", context["backtest_evidence"])
        self.assertIn("No external intelligence", context["external_intelligence"])
        # position_sizing_discipline.md etc. apply broadly to "stock" -- a
        # brand-new symbol should still get real reference material, since
        # reference_material is keyed on asset_type/sector, not symbol history.
        self.assertNotIn("No matching curated reference material", context["reference_material"])

    def test_includes_real_historical_analogue_once_one_is_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            record_experience(
                db_path,
                symbol="AAPL",
                strategy_id="trend-following",
                decision_context={"note": "test"},
                result_context={"outcome": "win", "pnl": 120.5},
            )
            context = build_proposal_context(db_path, symbol="AAPL", asset_type="stock", strategy_id="trend-following")
        self.assertIn("1 historical analogue(s)", context["historical_analogues"])
        self.assertIn("outcome=win", context["historical_analogues"])

    def test_includes_real_external_intelligence_once_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_external_intelligence_schema(db_path)
            record_crypto_news(db_path, posts=[{"title": "ETH upgrade ships", "url": "https://x/1", "currencies": [{"code": "eth"}]}])
            record_market_regime_evidence(db_path, scope="global", multi_timeframe=multi_timeframe_conclusion({}), macro="supportive")
            context = build_proposal_context(db_path, symbol="ETH", asset_type="crypto")
        self.assertIn("ETH upgrade ships", context["external_intelligence"])
        self.assertIn("Market regime", context["external_intelligence"])

    def test_reference_material_respects_asset_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            context = build_proposal_context(db_path, symbol="BTC", asset_type="crypto")
        # position_sizing_discipline.md and others apply to crypto too.
        self.assertNotIn("No matching curated reference material", context["reference_material"])

    def test_logs_a_knowledge_gap_when_asset_type_has_no_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            build_proposal_context(db_path, symbol="EURUSD", asset_type="forex")
            with closing(connect(db_path)) as conn:
                row = conn.execute(
                    "SELECT component, event_type FROM OPERATIONAL_EVENTS ORDER BY event_id DESC LIMIT 1"
                ).fetchone()
        self.assertEqual(row[0], "knowledge_base")
        self.assertEqual(row[1], "knowledge_gap")

    def test_missing_tables_do_not_raise(self):
        # A fresh database that has never run trading_intelligence's schema
        # init must not crash context assembly -- external_intelligence is
        # entirely absent, this must degrade to the honest "no data" string,
        # not an unhandled sqlite3.OperationalError.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_trading_intelligence_schema(db_path)
            context = build_proposal_context(db_path, symbol="NEWSYM", asset_type="stock")
        self.assertIn("No external intelligence", context["external_intelligence"])


if __name__ == "__main__":
    unittest.main()
