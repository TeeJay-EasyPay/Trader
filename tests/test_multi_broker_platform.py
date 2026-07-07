import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.api import LocalApiService
from ai_trader.config import Settings
from ai_trader.broker_adapters import KrakenAdapter
from ai_trader.models import AutoTradeConfig, GuardrailConfig, OrderRequest
from ai_trader.multi_broker import (
    broker_auto_trading_enabled,
    close_managed_exit_and_record,
    initialize_multi_broker_schema,
    latest_recommendation_set,
    list_performance_attribution,
    record_crypto_research_score,
    record_managed_trade_exit,
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

    def test_kraken_live_order_rejects_oversized_notional_before_submission(self):
        previous = {key: os.environ.get(key) for key in [
            "KRAKEN_API_KEY",
            "KRAKEN_PRIVATE_KEY",
            "KRAKEN_AUTO_TRADING",
            "KRAKEN_LIVE_TRADING_APPROVED",
            "KRAKEN_MAX_ORDER_GBP",
        ]}
        try:
            os.environ["KRAKEN_API_KEY"] = "key"
            os.environ["KRAKEN_PRIVATE_KEY"] = "c2VjcmV0"
            os.environ["KRAKEN_AUTO_TRADING"] = "true"
            os.environ["KRAKEN_LIVE_TRADING_APPROVED"] = "true"
            os.environ["KRAKEN_MAX_ORDER_GBP"] = "5"
            adapter = FakeKrakenAdapter()

            result = adapter.place_order(OrderRequest("BTC", "buy", 0.001, "crypto", "KRAKEN", 90, 120, notional_amount=10, client_order_id="too-large"))

            self.assertEqual(result["status"], "rejected")
            self.assertIn("max_order_amount_exceeded", result["seatbelt_failures"])
            self.assertFalse(adapter.submitted_orders)
        finally:
            restore_env(previous)

    def test_kraken_live_micro_order_submits_when_all_seatbelts_pass(self):
        previous = {key: os.environ.get(key) for key in [
            "KRAKEN_API_KEY",
            "KRAKEN_PRIVATE_KEY",
            "KRAKEN_AUTO_TRADING",
            "KRAKEN_LIVE_TRADING_APPROVED",
            "KRAKEN_MAX_ORDER_GBP",
            "KRAKEN_MIN_ORDER_GBP",
            "KRAKEN_ALLOWED_PAIRS",
            "KRAKEN_SUBMIT_REAL_ORDERS",
        ]}
        try:
            os.environ["KRAKEN_API_KEY"] = "key"
            os.environ["KRAKEN_PRIVATE_KEY"] = "c2VjcmV0"
            os.environ["KRAKEN_AUTO_TRADING"] = "true"
            os.environ["KRAKEN_LIVE_TRADING_APPROVED"] = "true"
            os.environ["KRAKEN_MAX_ORDER_GBP"] = "5"
            os.environ["KRAKEN_MIN_ORDER_GBP"] = "1"
            os.environ["KRAKEN_ALLOWED_PAIRS"] = "XBTGBP"
            os.environ["KRAKEN_SUBMIT_REAL_ORDERS"] = "false"
            adapter = FakeKrakenAdapter()

            result = adapter.place_order(OrderRequest("BTC", "buy", 0.00005, "crypto", "KRAKEN", 90, 120, notional_amount=2, client_order_id="micro"))

            self.assertEqual(result["status"], "accepted")
            self.assertEqual(result["pair"], "XBTGBP")
            self.assertEqual(adapter.submitted_orders[0]["validate"], "true")
        finally:
            restore_env(previous)

    def test_kraken_defaults_to_validate_mode_when_submit_real_orders_unset(self):
        previous = {key: os.environ.get(key) for key in [
            "KRAKEN_API_KEY",
            "KRAKEN_PRIVATE_KEY",
            "KRAKEN_AUTO_TRADING",
            "KRAKEN_LIVE_TRADING_APPROVED",
            "KRAKEN_MAX_ORDER_GBP",
            "KRAKEN_MIN_ORDER_GBP",
            "KRAKEN_ALLOWED_PAIRS",
            "KRAKEN_SUBMIT_REAL_ORDERS",
        ]}
        try:
            os.environ["KRAKEN_API_KEY"] = "key"
            os.environ["KRAKEN_PRIVATE_KEY"] = "c2VjcmV0"
            os.environ["KRAKEN_AUTO_TRADING"] = "true"
            os.environ["KRAKEN_LIVE_TRADING_APPROVED"] = "true"
            os.environ["KRAKEN_MAX_ORDER_GBP"] = "5"
            os.environ["KRAKEN_MIN_ORDER_GBP"] = "1"
            os.environ["KRAKEN_ALLOWED_PAIRS"] = "XBTGBP"
            os.environ.pop("KRAKEN_SUBMIT_REAL_ORDERS", None)
            adapter = FakeKrakenAdapter()

            result = adapter.place_order(OrderRequest("BTC", "buy", 0.00005, "crypto", "KRAKEN", 90, 120, notional_amount=2, client_order_id="unset-env"))

            self.assertEqual(result["status"], "accepted")
            self.assertEqual(
                adapter.submitted_orders[0]["validate"],
                "true",
                "An unset KRAKEN_SUBMIT_REAL_ORDERS must default to validate/dry-run mode, not real order submission.",
            )
        finally:
            restore_env(previous)

    def test_closing_a_buy_position_at_a_lower_price_records_a_loss(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            entry = record_managed_trade_exit(
                db_path,
                broker="kraken",
                symbol="BTC",
                side="buy",
                quantity=0.1,
                entry_order_id="entry-1",
                entry_price=50_000.0,
                stop_loss=49_000.0,
                take_profit=52_000.0,
                payload={},
            )
            close_managed_exit_and_record(
                db_path,
                entry["managed_exit_id"],
                broker="kraken",
                symbol="BTC",
                asset_type="crypto",
                side="sell",
                quantity=0.1,
                price=40_000.0,
                exit_order_id="exit-1",
                exit_reason="stop_loss_triggered",
                entry_price=50_000.0,
                entry_side="buy",
                opened_at=entry["created_at"],
            )
            rows = list_performance_attribution(db_path)

            self.assertEqual(len(rows), 1)
            self.assertLess(rows[0]["profit_loss"], 0, "A stop-loss exit below entry price must record a loss, not a gain.")

    def test_closing_a_sell_position_at_a_lower_price_records_a_gain(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            entry = record_managed_trade_exit(
                db_path,
                broker="kraken",
                symbol="BTC",
                side="sell",
                quantity=0.1,
                entry_order_id="entry-2",
                entry_price=50_000.0,
                stop_loss=51_000.0,
                take_profit=48_000.0,
                payload={},
            )
            close_managed_exit_and_record(
                db_path,
                entry["managed_exit_id"],
                broker="kraken",
                symbol="BTC",
                asset_type="crypto",
                side="buy",
                quantity=0.1,
                price=48_000.0,
                exit_order_id="exit-2",
                exit_reason="take_profit_triggered",
                entry_price=50_000.0,
                entry_side="sell",
                opened_at=entry["created_at"],
            )
            rows = list_performance_attribution(db_path)

            self.assertEqual(len(rows), 1)
            self.assertGreater(rows[0]["profit_loss"], 0, "A short position closed below entry at take-profit must record a gain.")


class FakeKrakenAdapter(KrakenAdapter):
    def __init__(self):
        super().__init__()
        self.submitted_orders = []

    def get_orders(self):
        return []

    def get_account(self):
        return {"status": "connected", "balances": {"ZGBP": "100"}}

    def _private_request(self, path, payload=None):
        if path == "/0/private/AddOrder":
            self.submitted_orders.append(payload)
            return {"result": {"txid": ["TST-ORDER"]}}
        return {"result": {}}


def restore_env(previous):
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
