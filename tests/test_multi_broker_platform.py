import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from unittest.mock import call, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.api import LocalApiService, _kraken_balance_summary, _kraken_trading_allocation_gbp
from ai_trader.audit import AuditDatabase
from ai_trader.config import Settings
from ai_trader.broker_adapters import KrakenAdapter
from ai_trader.foundation import load_trading_policy
from ai_trader.models import AutoTradeConfig, GuardrailConfig, OrderRequest, TradeProposal, ValidationResult
from ai_trader.multi_broker import (
    broker_auto_trading_enabled,
    close_managed_exit_and_record,
    initialize_multi_broker_schema,
    latest_recommendation_set,
    list_performance_attribution,
    record_broker_trade_history,
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

    def test_api_persists_broker_auto_trading_to_render_when_configured(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = replace(settings_for(tmp), render_api_key="render-key", render_service_id="srv-test")
            service = LocalApiService(settings)

            with patch.object(LocalApiService, "_render_api_json", return_value={"status": "ok", "http_status": 200}) as render_api:
                result = service.set_broker_auto_trading({"broker": "alpaca", "enabled": True})

            self.assertEqual(result["render_sync"]["status"], "synced")
            self.assertEqual(result["render_sync"]["env_var"], "ALPACA_AUTO_TRADING")
            render_api.assert_has_calls([
                call("PUT", "/services/srv-test/env-vars/ALPACA_AUTO_TRADING", {"value": "true"}),
                call("POST", "/services/srv-test/deploys", {"deployMode": "deploy_only"}),
            ])

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

    def test_broker_history_poll_is_idempotent_without_integrity_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            event = {
                "id": "alpaca-order-1",
                "symbol": "AAPL",
                "side": "buy",
                "status": "filled",
                "qty": "2",
                "filled_avg_price": "210.50",
                "updated_at": "2026-07-23T14:00:00+00:00",
            }

            first = record_broker_trade_history(db_path, "alpaca", [event])
            second = record_broker_trade_history(db_path, "alpaca", [event])

            self.assertEqual(len(first), 1)
            self.assertEqual(second, [])
            with closing(sqlite3.connect(db_path)) as conn:
                count = conn.execute("SELECT COUNT(*) FROM BROKER_TRADE_HISTORY").fetchone()[0]
            self.assertEqual(count, 1)

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

    def test_kraken_analysis_bootstraps_empty_crypto_universe_from_allowed_pairs(self):
        previous = {key: os.environ.get(key) for key in [
            "KRAKEN_API_KEY",
            "KRAKEN_PRIVATE_KEY",
            "KRAKEN_ALLOWED_PAIRS",
            "KRAKEN_SUBMIT_REAL_ORDERS",
        ]}
        try:
            os.environ["KRAKEN_API_KEY"] = "key"
            os.environ["KRAKEN_PRIVATE_KEY"] = "c2VjcmV0"
            os.environ["KRAKEN_ALLOWED_PAIRS"] = "XBTGBP,ETHGBP"
            os.environ["KRAKEN_SUBMIT_REAL_ORDERS"] = "true"
            with tempfile.TemporaryDirectory() as tmp:
                service = LocalApiService(settings_for(tmp))
                adapter = FakeKrakenAdapter()
                adapter.prices = {
                    "XBTGBP": {"c": ["50000.0"]},
                    "ETHGBP": {"c": ["3000.0"]},
                }
                service.orchestrator.adapters["kraken"] = adapter

                result = service.run_crypto_analysis(limit=10)

                self.assertEqual(result["status"], "completed")
                self.assertEqual(result["symbols"], ["BTC", "ETH"])
                self.assertGreaterEqual(len(result["proposals"]), 1)
                with closing(sqlite3.connect(service.settings.db_path)) as conn:
                    master_count = conn.execute("SELECT COUNT(*) FROM CRYPTO_MASTER").fetchone()[0]
                    score_count = conn.execute("SELECT COUNT(*) FROM CRYPTO_RESEARCH_SCORES").fetchone()[0]
                self.assertEqual(master_count, 2)
                self.assertEqual(score_count, 2)
        finally:
            restore_env(previous)

    def test_kraken_live_switches_enable_crypto_policy(self):
        previous = {key: os.environ.get(key) for key in [
            "KRAKEN_TRADING_ENABLED",
            "KRAKEN_LIVE_TRADING_APPROVED",
            "KRAKEN_SUBMIT_REAL_ORDERS",
        ]}
        try:
            os.environ["KRAKEN_TRADING_ENABLED"] = "true"
            os.environ["KRAKEN_LIVE_TRADING_APPROVED"] = "true"
            os.environ["KRAKEN_SUBMIT_REAL_ORDERS"] = "true"
            with tempfile.TemporaryDirectory() as tmp:
                settings = settings_for(tmp)

                policy = load_trading_policy(settings.db_path, auto_trade=settings.auto_trade, guardrails=settings.guardrails)

                self.assertTrue(policy.crypto_enabled)
        finally:
            restore_env(previous)

    def test_kraken_allocation_basis_does_not_trip_full_account_drawdown(self):
        previous = {key: os.environ.get(key) for key in [
            "KRAKEN_API_KEY",
            "KRAKEN_PRIVATE_KEY",
            "KRAKEN_TRADING_ENABLED",
            "KRAKEN_LIVE_TRADING_APPROVED",
            "KRAKEN_SUBMIT_REAL_ORDERS",
            "KRAKEN_ALLOWED_PAIRS",
            "KRAKEN_TRADING_ALLOCATION_GBP",
            "KRAKEN_MAX_ORDER_GBP",
            "KRAKEN_MIN_ORDER_GBP",
        ]}
        try:
            os.environ["KRAKEN_API_KEY"] = "key"
            os.environ["KRAKEN_PRIVATE_KEY"] = "c2VjcmV0"
            os.environ["KRAKEN_TRADING_ENABLED"] = "true"
            os.environ["KRAKEN_LIVE_TRADING_APPROVED"] = "true"
            os.environ["KRAKEN_SUBMIT_REAL_ORDERS"] = "true"
            os.environ["KRAKEN_ALLOWED_PAIRS"] = "XBTGBP"
            os.environ["KRAKEN_TRADING_ALLOCATION_GBP"] = "100"
            os.environ["KRAKEN_MAX_ORDER_GBP"] = "5"
            os.environ["KRAKEN_MIN_ORDER_GBP"] = "1"
            with tempfile.TemporaryDirectory() as tmp:
                settings = settings_for(tmp)
                service = LocalApiService(settings)
                adapter = FakeKrakenAdapter()
                service.orchestrator.adapters["kraken"] = adapter
                record_crypto_research_score(
                    settings.db_path,
                    symbol="BTC",
                    category="Founder approved Kraken pairs",
                    source="test",
                    metrics={
                        "technical_trend_score": 0.9,
                        "momentum_score": 0.9,
                        "risk_score": 0.9,
                        "sentiment": 0.9,
                        "liquidity": 0.9,
                    },
                )
                with closing(sqlite3.connect(settings.db_path)) as conn:
                    with conn:
                        conn.execute(
                            """
                            INSERT INTO PORTFOLIO_SNAPSHOTS (
                                created_at, broker, exchange, account_currency, cash,
                                portfolio_value, buying_power, open_positions_count,
                                day_pnl, week_pnl, month_pnl, notes
                            ) VALUES (?, 'kraken', 'Kraken', 'GBP', 100, 4000, 100, 9, NULL, NULL, NULL, 'test')
                            """,
                            ("2026-07-10T10:00:00+00:00",),
                        )
                        conn.execute(
                            """
                            INSERT INTO CRYPTO_MASTER (symbol, name, category, source, active, created_at, updated_at)
                            VALUES ('BTC', 'Bitcoin', 'Founder approved Kraken pairs', 'test', 1, ?, ?)
                            """,
                            ("2026-07-10T10:00:00+00:00", "2026-07-10T10:00:00+00:00"),
                        )
                proposal = TradeProposal(
                    symbol="BTC",
                    side="buy",
                    entry_price=50000,
                    stop_loss=49000,
                    take_profit=52000,
                    position_size=0.0001,
                    risk_percentage=0.001,
                    confidence_score=0.9,
                    news_summary="Crypto research reviewed.",
                    market_sentiment_summary="Positive.",
                    technical_summary="Positive trend.",
                    plain_english_reasoning="Test Kraken trade.",
                    ai_guardrails_passed=True,
                    asset_type="crypto",
                    exchange="KRAKEN",
                    philosophy_fit=0.9,
                )
                AuditDatabase(settings.db_path, settings.trading_log_path).record_trade_event(
                    "agent_proposal",
                    proposal,
                    validation=ValidationResult(passed=True),
                )

                result = service.approve_and_execute({"proposal_id": proposal.proposal_id, "amount": "5"})

                reason = result.get("result", {}).get("rejection_reason") or ""
                self.assertNotIn("maximum_drawdown_exceeded", reason)
                self.assertNotIn("crypto_disabled_by_policy", reason)
        finally:
            restore_env(previous)

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

    def test_kraken_live_order_rejects_notional_above_trading_allocation(self):
        previous = {key: os.environ.get(key) for key in [
            "KRAKEN_API_KEY",
            "KRAKEN_PRIVATE_KEY",
            "KRAKEN_AUTO_TRADING",
            "KRAKEN_LIVE_TRADING_APPROVED",
            "KRAKEN_MAX_ORDER_GBP",
            "KRAKEN_TRADING_ALLOCATION_GBP",
        ]}
        try:
            os.environ["KRAKEN_API_KEY"] = "key"
            os.environ["KRAKEN_PRIVATE_KEY"] = "c2VjcmV0"
            os.environ["KRAKEN_AUTO_TRADING"] = "true"
            os.environ["KRAKEN_LIVE_TRADING_APPROVED"] = "true"
            os.environ["KRAKEN_MAX_ORDER_GBP"] = "500"
            os.environ["KRAKEN_TRADING_ALLOCATION_GBP"] = "100"
            adapter = FakeKrakenAdapter()

            result = adapter.place_order(OrderRequest("BTC", "buy", 0.01, "crypto", "KRAKEN", 90, 120, notional_amount=101, client_order_id="over-allocation"))

            self.assertEqual(result["status"], "rejected")
            self.assertIn("kraken_trading_allocation_exceeded", result["seatbelt_failures"])
            self.assertFalse(adapter.submitted_orders)
        finally:
            restore_env(previous)

    def test_kraken_entry_sell_orders_are_blocked_to_protect_existing_coins(self):
        previous = {key: os.environ.get(key) for key in [
            "KRAKEN_API_KEY",
            "KRAKEN_PRIVATE_KEY",
            "KRAKEN_AUTO_TRADING",
            "KRAKEN_LIVE_TRADING_APPROVED",
            "KRAKEN_MAX_ORDER_GBP",
            "KRAKEN_MIN_ORDER_GBP",
            "KRAKEN_ALLOWED_PAIRS",
            "KRAKEN_BUY_ONLY_ENTRIES",
        ]}
        try:
            os.environ["KRAKEN_API_KEY"] = "key"
            os.environ["KRAKEN_PRIVATE_KEY"] = "c2VjcmV0"
            os.environ["KRAKEN_AUTO_TRADING"] = "true"
            os.environ["KRAKEN_LIVE_TRADING_APPROVED"] = "true"
            os.environ["KRAKEN_MAX_ORDER_GBP"] = "5"
            os.environ["KRAKEN_MIN_ORDER_GBP"] = "1"
            os.environ["KRAKEN_ALLOWED_PAIRS"] = "XBTGBP"
            os.environ.pop("KRAKEN_BUY_ONLY_ENTRIES", None)
            adapter = FakeKrakenAdapter()

            result = adapter.place_order(OrderRequest("BTC", "sell", 0.00005, "crypto", "KRAKEN", 90, 120, notional_amount=2, client_order_id="sell-existing"))

            self.assertEqual(result["status"], "rejected")
            self.assertIn("kraken_entry_sells_disabled", result["seatbelt_failures"])
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

    def test_kraken_existing_broker_orders_do_not_count_as_ai_managed_slots(self):
        previous = {key: os.environ.get(key) for key in [
            "KRAKEN_API_KEY",
            "KRAKEN_PRIVATE_KEY",
            "KRAKEN_AUTO_TRADING",
            "KRAKEN_LIVE_TRADING_APPROVED",
            "KRAKEN_MAX_ORDER_GBP",
            "KRAKEN_MIN_ORDER_GBP",
            "KRAKEN_ALLOWED_PAIRS",
            "KRAKEN_SUBMIT_REAL_ORDERS",
            "KRAKEN_MAX_OPEN_TRADES",
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
            os.environ["KRAKEN_MAX_OPEN_TRADES"] = "2"
            adapter = FakeKrakenAdapter()
            adapter.orders = [{"symbol": f"OLD{i}", "status": "open"} for i in range(9)]

            result = adapter.place_order(OrderRequest("BTC", "buy", 0.00005, "crypto", "KRAKEN", 90, 120, notional_amount=2, client_order_id="micro"))

            self.assertEqual(result["status"], "accepted")
            self.assertNotIn("max_open_kraken_trades_exceeded", result.get("seatbelt_failures", []))
        finally:
            restore_env(previous)

    def test_kraken_managed_trade_capacity_counts_only_ai_managed_exits(self):
        previous = {"KRAKEN_MAX_OPEN_TRADES": os.environ.get("KRAKEN_MAX_OPEN_TRADES")}
        try:
            os.environ["KRAKEN_MAX_OPEN_TRADES"] = "2"
            with tempfile.TemporaryDirectory() as tmp:
                service = LocalApiService(settings_for(tmp))
                record_managed_trade_exit(
                    service.settings.db_path,
                    broker="kraken",
                    symbol="BTC",
                    side="buy",
                    quantity=0.001,
                    entry_order_id="ai-1",
                    entry_price=100,
                    stop_loss=95,
                    take_profit=110,
                    payload={},
                )

                capacity = service._broker_managed_trade_capacity("kraken")

                self.assertTrue(capacity["can_open"])
                self.assertEqual(capacity["ai_managed_open_trades"], 1)
                self.assertEqual(capacity["remaining_ai_trade_slots"], 1)

                record_managed_trade_exit(
                    service.settings.db_path,
                    broker="kraken",
                    symbol="ETH",
                    side="buy",
                    quantity=0.01,
                    entry_order_id="ai-2",
                    entry_price=100,
                    stop_loss=95,
                    take_profit=110,
                    payload={},
                )
                capacity = service._broker_managed_trade_capacity("kraken")

                self.assertFalse(capacity["can_open"])
                self.assertEqual(capacity["ai_managed_open_trades"], 2)
                self.assertEqual(capacity["remaining_ai_trade_slots"], 0)
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

    def test_kraken_balance_summary_separates_total_balance_from_trading_allocation(self):
        previous = {"KRAKEN_TRADING_ALLOCATION_GBP": os.environ.get("KRAKEN_TRADING_ALLOCATION_GBP")}
        try:
            os.environ["KRAKEN_TRADING_ALLOCATION_GBP"] = "100"
            adapter = FakeKrakenAdapter()
            adapter.prices = {"XBTGBP": {"c": ["40000"]}}

            summary = _kraken_balance_summary({"ZGBP": "5000", "XXBT": "0.1", "USDT": "250"}, adapter)

            self.assertEqual(summary["gbp_cash"], 5000.0)
            self.assertEqual(summary["trading_allocation_gbp"], 100.0)
            self.assertEqual(summary["total_estimated_gbp"], 9000.0)
            self.assertEqual(len(summary["raw_balance_rows"]), 3)
            self.assertEqual(summary["unpriced_assets"][0]["normalized_asset"], "USDT")
            self.assertIn("excluded from the estimated total", summary["valuation_note"])
            self.assertEqual(_kraken_trading_allocation_gbp({"ZGBP": "50"}), 50.0)
        finally:
            restore_env(previous)

    def test_kraken_balance_summary_bridges_usd_pairs_to_gbp(self):
        previous = {"KRAKEN_TRADING_ALLOCATION_GBP": os.environ.get("KRAKEN_TRADING_ALLOCATION_GBP")}
        try:
            os.environ["KRAKEN_TRADING_ALLOCATION_GBP"] = "100"
            adapter = FakeKrakenAdapter()
            adapter.prices = {
                "QNTUSD": {"c": ["40"]},
                "USDGBP": {"c": ["0.8"]},
            }

            summary = _kraken_balance_summary({"QNT": "2"}, adapter)

            self.assertEqual(summary["total_estimated_gbp"], 64.0)
            self.assertEqual(summary["converted_assets"][0]["pricing_route"], "usd_bridge_to_gbp")
            self.assertEqual(summary["converted_assets"][0]["pair"], "QNTUSD")
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
        self.prices = {}
        self.orders = []

    def get_orders(self):
        return self.orders

    def get_account(self):
        return {"status": "connected", "balances": {"ZGBP": "100"}}

    def _private_request(self, path, payload=None):
        if path == "/0/private/AddOrder":
            self.submitted_orders.append(payload)
            return {"result": {"txid": ["TST-ORDER"]}}
        return {"result": {}}

    def current_prices(self, symbols):
        return {symbol: self.prices[symbol] for symbol in symbols if symbol in self.prices}


def restore_env(previous):
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
