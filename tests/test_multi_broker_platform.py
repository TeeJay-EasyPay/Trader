import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.api import LocalApiService
from ai_trader.config import Settings
from ai_trader.models import AutoTradeConfig, GuardrailConfig
from ai_trader.multi_broker import (
    broker_auto_trading_enabled,
    initialize_multi_broker_schema,
    latest_recommendation_set,
    record_crypto_research_score,
    record_recommendation_set,
    set_broker_auto_trading,
)


def settings_for(tmp: str, auto_trade: AutoTradeConfig | None = None) -> Settings:
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
        auto_trade=auto_trade or AutoTradeConfig(),
    )


class MultiBrokerPlatformTests(unittest.TestCase):
    def test_broker_auto_trading_is_independent(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_multi_broker_schema(db_path)

            set_broker_auto_trading(db_path, "kraken", True)

            self.assertTrue(broker_auto_trading_enabled(db_path, "kraken"))
            self.assertFalse(broker_auto_trading_enabled(db_path, "alpaca"))

    def test_api_updates_one_broker_auto_trading_setting(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalApiService(settings_for(tmp))

            result = service.set_broker_auto_trading({"broker": "kraken", "enabled": True})
            status = service.status()

            self.assertEqual(result["status"], "updated")
            self.assertTrue(status["broker_auto_trading"]["kraken"])
            self.assertFalse(status["broker_auto_trading"]["alpaca"])

    def test_latest_recommendation_set_is_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            record_recommendation_set(
                db_path,
                trigger_type="manual",
                broker="kraken",
                symbols=["BTC", "SOL"],
                proposal_ids=["p1", "p2"],
                status="completed",
                summary="Two recommendations.",
            )

            latest = latest_recommendation_set(db_path)

            self.assertEqual(latest["broker"], "kraken")
            self.assertEqual(latest["proposal_ids"], ["p1", "p2"])

    def test_crypto_research_score_stores_numeric_due_diligence(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            score = record_crypto_research_score(
                db_path,
                symbol="BTC",
                category="Top 20 by market cap",
                metrics={
                    "technical_trend_score": 0.8,
                    "momentum_score": 0.7,
                    "risk_score": 0.6,
                    "sentiment": 0.65,
                    "liquidity": 0.9,
                    "rsi": 55,
                },
                source="test",
            )

            self.assertIsInstance(score["overall_due_diligence_score"], float)
            with closing(sqlite3.connect(db_path)) as conn:
                count = conn.execute("SELECT COUNT(*) FROM CRYPTO_RESEARCH_SCORES").fetchone()[0]
            self.assertEqual(count, 1)

    def test_legacy_auto_paper_trading_enables_only_alpaca_for_compatibility(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalApiService(settings_for(tmp, AutoTradeConfig(enabled=True)))
            status = service.status()

            self.assertTrue(status["broker_auto_trading"]["alpaca"])
            self.assertFalse(status["broker_auto_trading"]["kraken"])


if __name__ == "__main__":
    unittest.main()
