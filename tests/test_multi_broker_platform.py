import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import call, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.api import (
    LocalApiService,
    _kraken_balance_summary,
    _kraken_trading_allocation_gbp,
)
# Phase 6a (architecture/AI_TRADER_MODULARISATION_ARCHITECTURE_2026-08-02.md) moved
# _recent_unique_broker_events into BrokerService (it is now module-level in that file,
# not a method); _kraken_balance_summary/_kraken_trading_allocation_gbp deliberately
# stayed in ai_trader.api as the single implementation of the Kraken capital-isolation
# pricing pipeline (see broker_service.py's kraken_balance_summary_lookup injection).
from ai_trader.application.administration_service import AdministrationService
from ai_trader.application.broker_service import BrokerService, _recent_unique_broker_events
from ai_trader.audit import AuditDatabase
from ai_trader.config import Settings
from ai_trader.broker_adapters import KrakenAdapter
from ai_trader.foundation import load_trading_policy
from ai_trader.models import AccountContext, AutoTradeConfig, GuardrailConfig, OrderRequest, TradeProposal, ValidationResult
from ai_trader.multi_broker import (
    acquire_order_intent_lock,
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

            # Phase 7 (architecture/AI_TRADER_MODULARISATION_ARCHITECTURE_2026-08-02.md)
            # moved _render_api_json/_sync_broker_auto_trading_to_render/
            # set_broker_auto_trading into AdministrationService (corrected from a Phase 6a
            # scoping mistake that had put these mutating methods in the presentation-only
            # BrokerService), so the class to patch is AdministrationService.
            with patch.object(AdministrationService, "_render_api_json", return_value={"status": "ok", "http_status": 200}) as render_api:
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

    def test_broker_history_without_timestamp_remains_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            event = {
                "id": "alpaca-order-without-time",
                "symbol": "MSFT",
                "side": "buy",
                "status": "filled",
                "qty": "1",
                "filled_avg_price": "500.00",
            }

            first = record_broker_trade_history(db_path, "alpaca", [event])
            second = record_broker_trade_history(db_path, "alpaca", [event])

            self.assertEqual(len(first), 1)
            self.assertEqual(second, [])

    def test_recent_broker_events_are_deduplicated_bounded_and_orders_first(self):
        order = {"id": "order-1", "status": "filled", "qty": "1"}
        history = [
            dict(order),
            {"id": "trade-1", "status": "filled", "qty": "2"},
            {"id": "trade-2", "status": "filled", "qty": "3"},
        ]

        selected = _recent_unique_broker_events([order], history, limit=2)

        self.assertEqual([row["id"] for row in selected], ["order-1", "trade-1"])

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

    def test_run_crypto_analysis_no_longer_calls_auto_execute_recommendations_inline(self):
        # Regression guard for the crypto-research timeout remediation: the dedicated,
        # independently-scheduled auto-execution job must remain the sole autonomous execution
        # path. run_crypto_analysis previously called self.auto_execute_recommendations()
        # synchronously inside itself - redundant (the standalone job picks up the same
        # proposals within its own ~60-90s cadence) and a major contributor to crypto-research's
        # chronic timeouts.
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

                with patch.object(LocalApiService, "auto_execute_recommendations") as mock_auto_execute:
                    result = service.run_crypto_analysis(limit=10)

                mock_auto_execute.assert_not_called()
                self.assertEqual(
                    result["auto_execution"],
                    {"status": "delegated", "message": "Handled by the independent per-broker auto-execution jobs."},
                )
                # No order was ever submitted directly from research - confirms there is no
                # duplicate execution path hiding elsewhere in this call.
                self.assertEqual(adapter.submitted_orders, [])
        finally:
            restore_env(previous)

    def test_run_analysis_scopes_its_inline_auto_execution_to_alpaca_only(self):
        # 2026-08-10 hosted incident: unlike run_crypto_analysis (see test above), Alpaca's
        # run_analysis DOES call auto-execution inline, once real proposals exist -- and it
        # called the unfiltered auto_execute_recommendations(), which evaluated the entire
        # shared candidate backlog (both brokers, dominated by Kraken) synchronously inside
        # this one job. At ~30-40s per candidate that reliably burned through the job's 450s
        # timeout, silently discarding the cycle's own fresh Alpaca proposals along with
        # everything else. Confirmed live: most market-open-equity runs timed out. Now that
        # trade_audit has a real broker column to filter on, this call must be scoped to
        # "alpaca" specifically -- broker_name is always "alpaca" here (run_analysis's
        # "kraken" branch returns earlier via run_crypto_analysis).
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = Settings(
                alpaca_api_key="paper-key",
                alpaca_secret_key="paper-secret",
                alpaca_paper_base_url="https://paper-api.alpaca.markets",
                alpaca_data_base_url="https://data.alpaca.markets",
                openai_api_key=None,
                openai_model="gpt-4.1-mini",
                db_path=root / "audit.sqlite3",
                output_dir=root,
                trading_log_path=root / "TRADING_LOG.md",
                guardrails=GuardrailConfig(),
                auto_trade=AutoTradeConfig(),
            )
            service = LocalApiService(settings)
            found_proposal = TradeProposal(
                symbol="AAPL", side="buy", entry_price=100, stop_loss=98, take_profit=106,
                position_size=1, risk_percentage=0.01, confidence_score=0.9,
                news_summary="No material news.", market_sentiment_summary="Neutral.",
                technical_summary="Setup available.",
                plain_english_reasoning=(
                    "Strongest argument for: the trend is constructive. "
                    "Strongest argument against: volatility could invalidate the setup."
                ),
                ai_guardrails_passed=True, asset_type="stock", exchange="NASDAQ",
            ).normalized()

            class FakeAgent:
                def __init__(self, *args, **kwargs):
                    pass

                def propose_trades(self, symbols, account, skipped_symbols=None):
                    return [found_proposal]

            class FakeBroker:
                def account_context(self, daily_realized_pnl=0):
                    return AccountContext(equity=100000, daily_realized_pnl=daily_realized_pnl, open_positions=[])

            with (
                patch("ai_trader.application.research_service.AITradingAgent", FakeAgent),
                patch.object(LocalApiService, "_broker", return_value=FakeBroker()),
                patch.object(LocalApiService, "auto_execute_recommendations", return_value={"status": "ok"}) as mock_auto_execute,
            ):
                result = service.run_analysis({"symbols": "AAPL"})

            mock_auto_execute.assert_called_once_with(broker_filter="alpaca")
            self.assertEqual(len(result["proposals"]), 1)

    def test_auto_execute_recommendations_broker_filter_isolates_candidates(self):
        # AT-ED-003 Section 1 item 4: auto-execution-alpaca/auto-execution-kraken must
        # each only consider candidates whose resolved broker matches, without touching
        # the governance chain for the other broker's candidates at all.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = Settings(
                alpaca_api_key="paper-key",
                alpaca_secret_key="paper-secret",
                alpaca_paper_base_url="https://paper-api.alpaca.markets",
                alpaca_data_base_url="https://data.alpaca.markets",
                openai_api_key=None,
                openai_model="gpt-4.1-mini",
                db_path=root / "audit.sqlite3",
                output_dir=root,
                trading_log_path=root / "TRADING_LOG.md",
                guardrails=GuardrailConfig(),
                auto_trade=AutoTradeConfig(enabled=True),
            )
            service = LocalApiService(settings)
            set_broker_auto_trading(settings.db_path, "alpaca", True)
            set_broker_auto_trading(settings.db_path, "kraken", True)
            audit = AuditDatabase(settings.db_path, settings.trading_log_path)

            stock_proposal = TradeProposal(
                symbol="AAPL", side="buy", entry_price=100, stop_loss=98, take_profit=106,
                position_size=1, risk_percentage=0.01, confidence_score=0.95,
                news_summary="No material news.", market_sentiment_summary="Neutral.",
                technical_summary="Setup available.",
                plain_english_reasoning=(
                    "Strongest argument for: the trend is constructive. "
                    "Strongest argument against: volatility could invalidate the setup."
                ),
                ai_guardrails_passed=True, asset_type="stock", exchange="NASDAQ",
            ).normalized()
            crypto_proposal = TradeProposal(
                symbol="BTC", side="buy", entry_price=50000, stop_loss=48000, take_profit=53000,
                position_size=0.01, risk_percentage=0.01, confidence_score=0.95,
                news_summary="No material news.", market_sentiment_summary="Neutral.",
                technical_summary="Setup available.",
                plain_english_reasoning=(
                    "Strongest argument for: the trend is constructive. "
                    "Strongest argument against: volatility could invalidate the setup."
                ),
                ai_guardrails_passed=True, asset_type="crypto", exchange="KRAKEN",
            ).normalized()
            audit.record_trade_event("agent_proposal", stock_proposal, validation=ValidationResult(passed=True))
            audit.record_trade_event("agent_proposal", crypto_proposal, validation=ValidationResult(passed=True))

            def fake_select_adapter(proposal):
                name = "alpaca" if proposal.asset_type == "stock" else "kraken"
                return SimpleNamespace(name=name)

            evaluated_symbols: list[str] = []

            def fake_evaluate(proposal, context, auto_execute=True):
                evaluated_symbols.append(proposal.symbol)
                return SimpleNamespace(
                    decision="rejected",
                    rejection_reason="test_short_circuit",
                    notes=None,
                    symbol=proposal.symbol,
                    to_dict=lambda: {},
                )

            with (
                patch.object(service.orchestrator, "_select_adapter", side_effect=fake_select_adapter),
                patch.object(service.orchestrator, "evaluate_recommendation", side_effect=fake_evaluate),
                patch.object(LocalApiService, "_account_context_for_broker", return_value=SimpleNamespace()),
            ):
                alpaca_result = service.auto_execute_recommendations(broker_filter="alpaca")
                self.assertEqual(evaluated_symbols, ["AAPL"])
                evaluated_symbols.clear()
                kraken_result = service.auto_execute_recommendations(broker_filter="kraken")
                self.assertEqual(evaluated_symbols, ["BTC"])

            alpaca_skipped_symbols = {row["symbol"] for row in alpaca_result.get("skipped", [])}
            kraken_skipped_symbols = {row["symbol"] for row in kraken_result.get("skipped", [])}
            self.assertIn("AAPL", alpaca_skipped_symbols)
            self.assertNotIn("BTC", alpaca_skipped_symbols)
            self.assertIn("BTC", kraken_skipped_symbols)
            self.assertNotIn("AAPL", kraken_skipped_symbols)

    def test_auto_execute_recommendations_excludes_candidates_older_than_24h(self):
        # The candidate query used to be ORDER BY ai_confidence DESC with no time
        # bound, so an old high-confidence proposal could occupy a LIMIT 50 slot
        # forever and starve fresh, lower-confidence proposals from ever being
        # considered -- confirmed in hosted logs 2026-07-31: the same handful of
        # expired proposal_ids recurred unchanged for 40+ minutes across several
        # research cycles. A proposal older than the longest freshness lifetime
        # (24h, see _recommendation_freshness) can never be anything but Expired,
        # so it must now be excluded from the candidate pool entirely, not merely
        # skipped after being selected.
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(tmp)
            set_broker_auto_trading(settings.db_path, "alpaca", True)
            audit = AuditDatabase(settings.db_path, settings.trading_log_path)

            def make_proposal(symbol: str, confidence: float) -> TradeProposal:
                return TradeProposal(
                    symbol=symbol, side="buy", entry_price=100, stop_loss=98, take_profit=106,
                    position_size=1, risk_percentage=0.01, confidence_score=confidence,
                    news_summary="No material news.", market_sentiment_summary="Neutral.",
                    technical_summary="Setup available.",
                    plain_english_reasoning=(
                        "Strongest argument for: the trend is constructive. "
                        "Strongest argument against: volatility could invalidate the setup."
                    ),
                    ai_guardrails_passed=True, asset_type="stock", exchange="NASDAQ",
                ).normalized()

            old_proposal = make_proposal("OLDCO", 0.99)
            fresh_proposal = make_proposal("NEWCO", 0.5)
            audit.record_trade_event("agent_proposal", old_proposal, validation=ValidationResult(passed=True))
            audit.record_trade_event("agent_proposal", fresh_proposal, validation=ValidationResult(passed=True))
            stale_cutoff = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
            with closing(sqlite3.connect(settings.db_path)) as conn:
                with conn:
                    conn.execute(
                        "UPDATE trade_audit SET created_at = ? WHERE proposal_id = ?",
                        (stale_cutoff, old_proposal.proposal_id),
                    )

            with patch.object(LocalApiService, "_account_context_for_broker", return_value=SimpleNamespace()):
                result = LocalApiService(settings).auto_execute_recommendations()

            seen_symbols = {row["symbol"] for row in result.get("skipped", [])}
            self.assertNotIn("OLDCO", seen_symbols)
            self.assertIn("NEWCO", seen_symbols)

    def test_auto_execute_never_fetches_payload_json_for_a_candidate_that_fails_a_cheap_filter(self):
        # 2026-08-10 Supabase egress finding: this query used to select payload_json (the
        # full proposal dossier, confirmed ~11KB average per row via /database-diagnostics)
        # for all up-to-50 candidates up front, even though confidence/freshness/guardrails/
        # already-executed are all checked from lightweight columns already in the first
        # SELECT -- running every ~60s per broker, this was a likely-dominant real
        # contributor to reported ~800MB/day egress. Now a low-confidence candidate must
        # never appear in the second, targeted payload_json fetch at all.
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(tmp)
            settings = replace(settings, auto_trade=AutoTradeConfig(enabled=True, min_confidence=0.85))
            set_broker_auto_trading(settings.db_path, "alpaca", True)
            audit = AuditDatabase(settings.db_path, settings.trading_log_path)

            def make_proposal(symbol: str, confidence: float) -> TradeProposal:
                return TradeProposal(
                    symbol=symbol, side="buy", entry_price=100, stop_loss=98, take_profit=106,
                    position_size=1, risk_percentage=0.01, confidence_score=confidence,
                    news_summary="No material news.", market_sentiment_summary="Neutral.",
                    technical_summary="Setup available.",
                    plain_english_reasoning=(
                        "Strongest argument for: the trend is constructive. "
                        "Strongest argument against: volatility could invalidate the setup."
                    ),
                    ai_guardrails_passed=True, asset_type="stock", exchange="NASDAQ",
                ).normalized()

            low_confidence = make_proposal("LOWCO", 0.50)
            high_confidence = make_proposal("HIGHCO", 0.95)
            audit.record_trade_event("agent_proposal", low_confidence, validation=ValidationResult(passed=True))
            audit.record_trade_event("agent_proposal", high_confidence, validation=ValidationResult(passed=True))

            service = LocalApiService(settings)
            real_rows = service._query_executor.rows
            payload_queries: list[tuple[str, tuple]] = []

            def spy_rows(sql, params=()):
                if "payload_json" in sql:
                    payload_queries.append((sql, tuple(params)))
                return real_rows(sql, params)

            with (
                patch.object(service._query_executor, "rows", side_effect=spy_rows),
                patch.object(LocalApiService, "_account_context_for_broker", return_value=SimpleNamespace()),
                patch.object(service.orchestrator, "_select_adapter", return_value=SimpleNamespace(name="alpaca")),
                patch.object(
                    service.orchestrator,
                    "evaluate_recommendation",
                    side_effect=lambda proposal, context, auto_execute=True: SimpleNamespace(
                        decision="rejected", rejection_reason="test_short_circuit", notes=None,
                        symbol=proposal.symbol, to_dict=lambda: {},
                    ),
                ),
            ):
                result = service.auto_execute_recommendations(broker_filter="alpaca")

            self.assertEqual(len(payload_queries), 1, "expected exactly one targeted payload fetch")
            fetched_ids = payload_queries[0][1]
            self.assertIn(high_confidence.proposal_id, fetched_ids)
            self.assertNotIn(low_confidence.proposal_id, fetched_ids)
            skipped_symbols = {row["symbol"] for row in result.get("skipped", [])}
            self.assertIn("LOWCO", skipped_symbols)

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

    def test_kraken_rejects_a_pair_outside_the_founder_approved_allowlist(self):
        # Stage 0.4 (architecture/AI_TRADER_MODULARISATION_ARCHITECTURE_2026-08-02.md):
        # "Kraken order size, allocation, allowed-pair and buy-only checks remain enforced
        # at the adapter boundary" -- buy-only and order-size/allocation already had
        # coverage; the allowed-pair half of that invariant did not.
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
            # DOGEGBP is deliberately absent from the allowlist.
            os.environ["KRAKEN_ALLOWED_PAIRS"] = "XBTGBP,ETHGBP,SOLGBP"
            os.environ["KRAKEN_SUBMIT_REAL_ORDERS"] = "false"
            adapter = FakeKrakenAdapter()

            result = adapter.place_order(OrderRequest("DOGE", "buy", 5.0, "crypto", "KRAKEN", 0.05, 0.08, notional_amount=2, client_order_id="unlisted-pair"))

            self.assertEqual(result["status"], "rejected")
            self.assertIn("pair_not_allowed", result["seatbelt_failures"])
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

    def test_account_context_for_kraken_never_lets_personal_holdings_inflate_ai_equity(self):
        # Stage 0.4 (architecture/AI_TRADER_MODULARISATION_ARCHITECTURE_2026-08-02.md
        # section 3): "Kraken personal holdings never enter the AI trading capital
        # sleeve." _kraken_trading_allocation_gbp is already unit-tested as a pure
        # function; this exercises the real integration point governance actually reads
        # from (_account_context_for_broker -> AccountContext.equity), with an account
        # holding thousands of pounds of pre-existing personal crypto (from before the
        # AI was ever given trading authority) and only a small GBP cash remainder.
        previous = {"KRAKEN_TRADING_ALLOCATION_GBP": os.environ.get("KRAKEN_TRADING_ALLOCATION_GBP")}
        try:
            os.environ["KRAKEN_TRADING_ALLOCATION_GBP"] = "100"
            with tempfile.TemporaryDirectory() as tmp:
                service = LocalApiService(settings_for(tmp))
                adapter = FakeKrakenAdapter()
                # A large pre-existing personal Bitcoin holding (worth thousands of GBP
                # at any realistic price) plus a small GBP cash remainder below the
                # £100 allocation cap.
                adapter.get_account = lambda: {
                    "status": "connected",
                    "balances": {"ZGBP": "38.23", "XXBT": "0.5"},
                }
                service.orchestrator.adapters["kraken"] = adapter

                account = service._account_context_for_broker("kraken")

                # Equity must reflect only the isolated GBP cash sleeve (capped at the
                # allocation), never the personal BTC holding's value.
                self.assertEqual(account.equity, 38.23)
        finally:
            restore_env(previous)

    def test_account_context_for_kraken_never_lets_mismatched_whole_account_daily_pnl_trip_the_daily_loss_guardrail(self):
        # Hosted evidence (2026-08-05/06): every Kraken auto-execution candidate was rejected
        # with "maximum_daily_loss_exceeded", every cycle, 100% of the time. Root cause:
        # PORTFOLIO_SNAPSHOTS.day_pnl reflects the broker's WHOLE account (thousands of GBP
        # of the Founder's pre-existing personal crypto holdings), while AccountContext.equity
        # is deliberately scoped to only the AI's small isolated allocation
        # (_kraken_trading_allocation_gbp). guardrails.py's maximum_daily_loss_exceeded check
        # compared the two directly, so ordinary price movement on personal holdings the AI
        # never touched could - and did - permanently block every live Kraken trade.
        # orchestrator.py's weekly/monthly/drawdown checks already had a basis-matching guard
        # (_snapshot_equity_basis_matches_context) for this exact mismatch; this test proves
        # the same guard is now applied at the source, in _account_context_for_broker, before
        # daily_realized_pnl ever reaches any guardrail.
        previous = {"KRAKEN_TRADING_ALLOCATION_GBP": os.environ.get("KRAKEN_TRADING_ALLOCATION_GBP")}
        try:
            os.environ["KRAKEN_TRADING_ALLOCATION_GBP"] = "100"
            with tempfile.TemporaryDirectory() as tmp:
                settings = settings_for(tmp)
                service = LocalApiService(settings)
                adapter = FakeKrakenAdapter()
                adapter.get_account = lambda: {
                    "status": "connected",
                    "balances": {"ZGBP": "38.23", "XXBT": "0.5"},
                }
                service.orchestrator.adapters["kraken"] = adapter
                # A real snapshot representing the WHOLE Kraken account (~£3,692, mostly
                # pre-existing personal crypto) with a real day_pnl swing that would trip the
                # £1.15 (3% of £38.23) daily-loss threshold if ever compared against the AI's
                # scoped equity directly.
                with closing(sqlite3.connect(settings.db_path)) as conn:
                    with conn:
                        conn.execute(
                            """
                            INSERT INTO PORTFOLIO_SNAPSHOTS (
                                created_at, broker, exchange, account_currency, cash,
                                portfolio_value, buying_power, open_positions_count,
                                day_pnl, week_pnl, month_pnl, month_start_value, notes
                            ) VALUES (?, 'kraken', 'Kraken', 'GBP', 38.23, 3692.27, 38.23, 12,
                                      -50.0, -130.69, 4.05, 3688.22, 'test')
                            """,
                            (datetime.now(timezone.utc).isoformat(),),
                        )

                account = service._account_context_for_broker("kraken")

                # The mismatched whole-account day_pnl (-£50, dwarfing the £38.23 AI
                # allocation) must never reach the guardrail - honestly zeroed instead of
                # fabricating a same-basis figure that doesn't exist.
                self.assertEqual(account.daily_realized_pnl, 0.0)
        finally:
            restore_env(previous)

    def test_account_context_for_kraken_keeps_daily_pnl_when_snapshot_basis_genuinely_matches_equity(self):
        # Companion to the mismatch test above: when the snapshot's portfolio_value is
        # genuinely in the same ballpark as the AI's scoped equity (no large pre-existing
        # personal holdings inflating it), the real daily_pnl must still reach the guardrail -
        # the fix must not silently suppress a real, same-basis loss signal.
        previous = {"KRAKEN_TRADING_ALLOCATION_GBP": os.environ.get("KRAKEN_TRADING_ALLOCATION_GBP")}
        try:
            os.environ["KRAKEN_TRADING_ALLOCATION_GBP"] = "100"
            with tempfile.TemporaryDirectory() as tmp:
                settings = settings_for(tmp)
                service = LocalApiService(settings)
                adapter = FakeKrakenAdapter()
                adapter.get_account = lambda: {
                    "status": "connected",
                    "balances": {"ZGBP": "38.23"},
                }
                service.orchestrator.adapters["kraken"] = adapter
                with closing(sqlite3.connect(settings.db_path)) as conn:
                    with conn:
                        conn.execute(
                            """
                            INSERT INTO PORTFOLIO_SNAPSHOTS (
                                created_at, broker, exchange, account_currency, cash,
                                portfolio_value, buying_power, open_positions_count,
                                day_pnl, week_pnl, month_pnl, month_start_value, notes
                            ) VALUES (?, 'kraken', 'Kraken', 'GBP', 38.23, 45.0, 38.23, 0,
                                      -10.0, -12.0, -5.0, 55.0, 'test')
                            """,
                            (datetime.now(timezone.utc).isoformat(),),
                        )

                account = service._account_context_for_broker("kraken")

                self.assertEqual(account.daily_realized_pnl, -10.0)
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

    def _public_request(self, path):
        # Never make a real network call from a unit test -- pair_minimum_notional (real
        # KrakenAdapter method, inherited here) falls back to this if a test exercises it
        # without a more specific override.
        return {"result": {}}


def restore_env(previous):
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


class KrakenCapitalLedgerPricingTests(unittest.TestCase):
    """AT-ED-003 corrective session, Part 1: evidence-snapshot regressed to a chronic
    180s timeout after capture_production_broker_snapshots() started calling
    _broker_trading_permissions() per broker, because the Kraken branch made a fresh
    live Kraken pricing API call every cycle. These tests prove the fix: the capital
    ledger reuses prices already fetched this cycle and never makes a live call when
    told not to, while still degrading gracefully (not crashing, not hiding governance
    fields) when no pricing is available at all."""

    def test_capital_ledger_reuses_price_hints_without_live_lookup(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalApiService(settings_for(tmp))
            adapter = FakeKrakenAdapter()

            def fail_if_called(symbols):
                raise AssertionError("current_prices must not be called when hints cover every unpriced symbol")

            adapter.current_prices = fail_if_called
            service.orchestrator.adapters["kraken"] = adapter

            unpriced_summary = {"unpriced_open_symbols": ["BTC"], "allocation_gbp": 100.0}
            priced_summary = {"unpriced_open_symbols": [], "unrealized_pnl_gbp": 50.0}

            with patch("ai_trader.application.broker_service.kraken_capital_ledger_summary", side_effect=[unpriced_summary, priced_summary]) as mocked:
                ledger = service._kraken_ai_capital_ledger(price_hints={"BTC": 50000.0}, allow_live_pricing=False)

            self.assertEqual(ledger, priced_summary)
            self.assertEqual(mocked.call_count, 2)
            _, kwargs = mocked.call_args_list[1]
            self.assertEqual(kwargs.get("current_prices"), {"BTC": 50000.0})

    def test_capital_ledger_degrades_gracefully_without_hints_or_live_pricing(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalApiService(settings_for(tmp))
            adapter = FakeKrakenAdapter()

            def fail_if_called(symbols):
                raise AssertionError("current_prices must not be called when allow_live_pricing is False")

            adapter.current_prices = fail_if_called
            service.orchestrator.adapters["kraken"] = adapter

            unpriced_summary = {
                "unpriced_open_symbols": ["BTC"],
                "unrealized_pnl_gbp": None,
                "unrealized_pnl_status": "Unavailable because current Kraken prices were not captured for: BTC",
            }

            with patch("ai_trader.application.broker_service.kraken_capital_ledger_summary", return_value=unpriced_summary) as mocked:
                ledger = service._kraken_ai_capital_ledger(price_hints=None, allow_live_pricing=False)

            # The ledger is still returned, clearly labelled as unpriced -- not a crash,
            # not a hidden/missing field, and no fabricated valuation.
            self.assertEqual(ledger, unpriced_summary)
            mocked.assert_called_once()

    def test_capital_ledger_falls_back_to_live_pricing_when_explicitly_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalApiService(settings_for(tmp))
            adapter = FakeKrakenAdapter()
            adapter.prices = {"XBTGBP": {"c": ["50000.0"]}}
            service.orchestrator.adapters["kraken"] = adapter

            unpriced_summary = {"unpriced_open_symbols": ["BTC"]}
            priced_summary = {"unpriced_open_symbols": [], "unrealized_pnl_gbp": 10.0}

            with patch("ai_trader.application.broker_service.kraken_capital_ledger_summary", side_effect=[unpriced_summary, priced_summary]) as mocked:
                ledger = service._kraken_ai_capital_ledger(price_hints=None, allow_live_pricing=True)

            self.assertEqual(ledger, priced_summary)
            self.assertEqual(mocked.call_count, 2)

    def test_evidence_snapshot_never_calls_live_kraken_pricing(self):
        """End-to-end: capture_production_broker_snapshots() must not trigger a live
        Kraken price lookup even when the ledger has unpriced open positions and no
        wallet-balance price hints are available for them."""
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalApiService(settings_for(tmp))
            adapter = FakeKrakenAdapter()

            def fail_if_called(symbols):
                raise AssertionError("evidence-snapshot must never make a live Kraken pricing call")

            adapter.current_prices = fail_if_called
            service.orchestrator.adapters["kraken"] = adapter
            # Phase 6a (architecture/AI_TRADER_MODULARISATION_ARCHITECTURE_2026-08-02.md)
            # moved capture_production_broker_snapshots/_live_alpaca_portfolio/
            # _exchange_portfolio into BrokerService; capture_production_broker_snapshots
            # now calls self._live_alpaca_portfolio()/self._exchange_portfolio() on the
            # BrokerService instance, not the LocalApiService delegate, so these
            # monkeypatches must target service._broker_service directly.
            service._broker_service._live_alpaca_portfolio = lambda: {"connection_status": "Connected", "portfolio_value": 100_000}
            service._broker_service._exchange_portfolio = lambda broker: {
                "connection_status": "Connected",
                "portfolio_value": 4_000,
                "balance_summary": {"converted_assets": []},
            }

            with (
                patch("ai_trader.application.broker_service.kraken_capital_ledger_summary", return_value={"unpriced_open_symbols": ["BTC"]}),
                patch("ai_trader.application.broker_service.record_broker_snapshot") as snapshot,
            ):
                result = service.capture_production_broker_snapshots()

            self.assertEqual(result["alpaca"]["status"], "captured")
            self.assertEqual(result["kraken"]["status"], "captured")
            panels = {call.args[1]["broker"]: call.args[1] for call in snapshot.call_args_list}
            # Governance fields must still be present even though the ledger valuation
            # could not be fully priced.
            self.assertIn("auto_trading_enabled", panels["kraken"])
            self.assertIn("block_reason", panels["kraken"])
            self.assertIsNotNone(panels["kraken"]["trading_permissions"])


class AtEd010BrokerPanelsPerformanceTests(unittest.TestCase):
    """AT-ED-010: /brokers was confirmed to hang ~60s in production. Root cause traced
    to broker_panels() making an unbatched, uncapped number of sequential live Kraken
    API calls: one full portfolio fetch per broker done sequentially, plus a second
    live pricing round trip inside the capital ledger that didn't reuse prices the
    portfolio fetch already obtained, plus one live pricing call PER ROW in both the
    trade-history and managed-exits lists (up to ~17 sequential Kraken round trips for
    a single Kraken panel). These tests prove the fix: batched pricing calls and
    price-hint reuse, without changing what a successful panel returns."""

    def test_broker_trade_rows_batches_pricing_into_one_call_not_one_per_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalApiService(settings_for(tmp))
            for symbol, order_id in [("BTC", "kr-1"), ("ETH", "kr-2"), ("SOL", "kr-3")]:
                record_broker_trade_history(
                    service.settings.db_path,
                    "kraken",
                    [{
                        "id": order_id,
                        "symbol": symbol,
                        "side": "buy",
                        "status": "filled",
                        "vol": "1",
                        "price": "100",
                        "closetm": "2026-08-01T10:00:00+00:00",
                    }],
                )
            adapter = FakeKrakenAdapter()
            # _broker_trade_symbol extracts the raw stored symbol ("BTC"), not a
            # Kraken-pair-formatted string ("XBTGBP") -- the existing (pre-AT-ED-010)
            # code already queried current_prices with that raw symbol too; this test
            # preserves that exact lookup key, not "fixing" it as an unrelated change.
            adapter.prices = {"BTC": {"c": ["50000.0"]}, "ETH": {"c": ["3000.0"]}, "SOL": {"c": ["150.0"]}}
            call_count = {"n": 0}
            real_current_prices = adapter.current_prices

            def counting_current_prices(symbols):
                call_count["n"] += 1
                return real_current_prices(symbols)

            adapter.current_prices = counting_current_prices
            service.orchestrator.adapters["kraken"] = adapter

            rows = service._broker_service._broker_trade_rows("kraken")

            self.assertEqual(call_count["n"], 1, "current_prices must be called once for the whole row set, not once per row")
            self.assertEqual(len(rows), 3)
            priced = {row["symbol"]: row.get("current_price") for row in rows}
            self.assertEqual(priced["BTC"], 50000.0)
            self.assertEqual(priced["ETH"], 3000.0)
            self.assertEqual(priced["SOL"], 150.0)

    def test_managed_exit_rows_batches_pricing_into_one_call_not_one_per_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalApiService(settings_for(tmp))
            for symbol, order_id in [("BTC", "ai-1"), ("ETH", "ai-2")]:
                record_managed_trade_exit(
                    service.settings.db_path,
                    broker="kraken",
                    symbol=symbol,
                    side="buy",
                    quantity=1,
                    entry_order_id=order_id,
                    entry_price=100,
                    stop_loss=95,
                    take_profit=110,
                    payload={},
                )
            adapter = FakeKrakenAdapter()
            adapter.prices = {"XBTGBP": {"c": ["50000.0"]}, "ETHGBP": {"c": ["3000.0"]}}
            call_count = {"n": 0}
            real_current_prices = adapter.current_prices

            def counting_current_prices(symbols):
                call_count["n"] += 1
                return real_current_prices(symbols)

            adapter.current_prices = counting_current_prices
            service.orchestrator.adapters["kraken"] = adapter

            rows = service._broker_service._managed_exit_rows("kraken")

            self.assertEqual(call_count["n"], 1, "current_prices must be called once for the whole open-exits set, not once per row")
            self.assertEqual(len(rows), 2)
            priced = {row["symbol"]: row.get("current_price") for row in rows}
            self.assertEqual(priced["BTC"], 50000.0)
            self.assertEqual(priced["ETH"], 3000.0)

    def test_broker_trade_rows_degrades_gracefully_when_pricing_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalApiService(settings_for(tmp))
            record_broker_trade_history(
                service.settings.db_path,
                "kraken",
                [{"id": "kr-1", "symbol": "BTC", "side": "buy", "status": "filled", "vol": "1", "price": "100", "closetm": "2026-08-01T10:00:00+00:00"}],
            )
            adapter = FakeKrakenAdapter()

            def raise_slow_or_failed(symbols):
                raise TimeoutError("Kraken pricing API did not respond in time")

            adapter.current_prices = raise_slow_or_failed
            service.orchestrator.adapters["kraken"] = adapter

            rows = service._broker_service._broker_trade_rows("kraken")

            self.assertEqual(len(rows), 1, "a pricing failure must not drop the row, only leave it unpriced")
            self.assertNotIn("current_price", rows[0])
            self.assertIn("current_price_error", rows[0])

    def test_broker_panels_reuses_portfolio_price_hints_for_capital_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalApiService(settings_for(tmp))
            adapter = FakeKrakenAdapter()
            service.orchestrator.adapters["kraken"] = adapter

            kraken_portfolio = {
                "connection_status": "Connected",
                "portfolio_value": 100.0,
                "cash_available": 50.0,
                "source": "Kraken",
                "balance_summary": {"converted_assets": [{"normalized_asset": "BTC", "price_gbp": 50000.0}]},
            }

            def fake_fetch_portfolio(broker):
                return kraken_portfolio if broker == "kraken" else {"connection_status": "Not configured", "source": "Not configured"}

            with (
                patch.object(service._broker_service, "_exchange_portfolio", side_effect=lambda broker: fake_fetch_portfolio(broker)),
                patch.object(service._broker_service, "_alpaca_panel_portfolio", side_effect=lambda: fake_fetch_portfolio("alpaca")),
                patch(
                    "ai_trader.application.broker_service.kraken_capital_ledger_summary",
                    return_value={"unpriced_open_symbols": ["BTC"]},
                ) as ledger_summary,
            ):
                panels = service.broker_panels()

            kraken_panel = next(p for p in panels if p["broker"] == "kraken")
            self.assertIsNotNone(kraken_panel["trading_permissions"])
            # The second kraken_capital_ledger_summary call (the re-valuation once prices
            # are known) must have been given the price extracted from the portfolio's own
            # balance_summary, not left to make its own separate live Kraken call.
            second_call_kwargs = ledger_summary.call_args_list[-1].kwargs
            self.assertEqual(second_call_kwargs.get("current_prices"), {"BTC": 50000.0})


class ManagedExitDuplicateOrderProtectionTests(unittest.TestCase):
    """CRITICAL_REMEDIATION_PLAN.md P0-2: exit orders must have the same
    duplicate-submission protection entry orders already had. These tests
    exercise LocalApiService.monitor_managed_exits / force_managed_exit
    directly (previously untested anywhere in this suite)."""

    def _env(self):
        return {
            key: os.environ.get(key)
            for key in ["KRAKEN_API_KEY", "KRAKEN_PRIVATE_KEY", "KRAKEN_LIVE_TRADING_APPROVED", "KRAKEN_SUBMIT_REAL_ORDERS"]
        }

    def _activate_kraken(self):
        os.environ["KRAKEN_API_KEY"] = "key"
        os.environ["KRAKEN_PRIVATE_KEY"] = "c2VjcmV0"
        os.environ["KRAKEN_LIVE_TRADING_APPROVED"] = "true"
        os.environ["KRAKEN_SUBMIT_REAL_ORDERS"] = "true"

    def _open_position(self, service, *, entry_price=50_000.0, stop_loss=49_000.0, take_profit=52_000.0):
        entry = record_managed_trade_exit(
            service.settings.db_path,
            broker="kraken",
            symbol="BTC",
            side="buy",
            quantity=0.1,
            entry_order_id="entry-dup-test",
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            payload={"proposal_id": "prop-dup-test"},
        )
        return int(entry["managed_exit_id"])

    def test_monitor_managed_exits_submits_and_closes_the_lock_on_success(self):
        previous = self._env()
        try:
            self._activate_kraken()
            with tempfile.TemporaryDirectory() as tmp:
                service = LocalApiService(settings_for(tmp))
                adapter = FakeKrakenAdapter()
                adapter.prices = {"XBTGBP": {"c": ["48000.0"]}}  # below stop_loss -> triggers exit
                service.orchestrator.adapters["kraken"] = adapter
                self._open_position(service)

                result = service.monitor_managed_exits()

                self.assertEqual(len(adapter.submitted_orders), 1, "Exactly one exit order must reach the broker.")
                self.assertEqual(result["managed_exits"][0]["status"], "exit_submitted")

                # A second cycle must see the position no longer 'open' (it was marked
                # exit_submitted) and therefore must not re-evaluate or resubmit it.
                second = service.monitor_managed_exits()
                self.assertEqual(len(adapter.submitted_orders), 1, "A second cycle must not submit a second exit order.")
                self.assertEqual(second["managed_exits"], [])
        finally:
            restore_env(previous)

    def test_monitor_managed_exits_refuses_to_resubmit_while_a_prior_attempt_is_still_locked(self):
        """Simulates the exact P0-2 failure mode: the worker's own timeout-kill
        mechanism can terminate a job after the broker already accepted an exit
        order but before the local DB write confirming it completes, leaving
        the intent lock 'locked' with no result recorded. The next cycle must
        refuse to submit a second order for the same position rather than
        blindly retrying."""
        previous = self._env()
        try:
            self._activate_kraken()
            with tempfile.TemporaryDirectory() as tmp:
                service = LocalApiService(settings_for(tmp))
                adapter = FakeKrakenAdapter()
                adapter.prices = {"XBTGBP": {"c": ["48000.0"]}}
                service.orchestrator.adapters["kraken"] = adapter
                managed_exit_id = self._open_position(service)

                # Pre-acquire the lock the way orchestrator.py's entry path already
                # does, and the way the exit path now does before calling the broker --
                # simulating that a prior process died after acquiring it.
                locked = acquire_order_intent_lock(
                    service.settings.db_path,
                    broker="kraken",
                    client_order_id=f"exit-{managed_exit_id}",
                    symbol="BTC",
                    side="sell",
                    notional=4800.0,
                )
                self.assertTrue(locked, "Precondition: the lock must be acquirable exactly once.")

                result = service.monitor_managed_exits()

                self.assertEqual(adapter.submitted_orders, [], "No broker call may happen while the prior intent lock is unresolved.")
                self.assertEqual(result["managed_exits"][0]["status"], "duplicate_exit_intent")
        finally:
            restore_env(previous)

    def test_force_managed_exit_and_monitor_managed_exits_share_one_lock_for_the_same_position(self):
        """A founder-forced exit and the automatic stop-loss/take-profit monitor
        must not be able to both submit an order for the same managed position."""
        previous = self._env()
        try:
            self._activate_kraken()
            with tempfile.TemporaryDirectory() as tmp:
                service = LocalApiService(settings_for(tmp))
                adapter = FakeKrakenAdapter()
                adapter.prices = {"XBTGBP": {"c": ["48000.0"]}}
                service.orchestrator.adapters["kraken"] = adapter
                managed_exit_id = self._open_position(service)

                first = service.force_managed_exit({"managed_exit_id": managed_exit_id})
                self.assertEqual(first["status"], "submitted")
                self.assertEqual(len(adapter.submitted_orders), 1)

                # The position is no longer 'open' (mark_managed_exit_submitted already
                # ran), so monitor_managed_exits should not even see it -- but exercise
                # the lock directly to prove it would refuse a same-key resubmission too.
                relocked = acquire_order_intent_lock(
                    service.settings.db_path,
                    broker="kraken",
                    client_order_id=f"exit-{managed_exit_id}",
                    symbol="BTC",
                    side="sell",
                    notional=4800.0,
                )
                self.assertFalse(relocked, "The lock acquired by force_managed_exit must still be held.")
        finally:
            restore_env(previous)

    def test_definite_broker_rejection_releases_the_lock_for_a_legitimate_retry(self):
        """A synchronous, unambiguous broker rejection (e.g. Kraken trading not
        yet approved) must not permanently strand a position with no way to
        ever exit it -- the lock must be released so the next cycle can retry."""
        previous = self._env()
        try:
            os.environ["KRAKEN_API_KEY"] = "key"
            os.environ["KRAKEN_PRIVATE_KEY"] = "c2VjcmV0"
            os.environ["KRAKEN_LIVE_TRADING_APPROVED"] = "false"  # definite, synchronous rejection
            with tempfile.TemporaryDirectory() as tmp:
                service = LocalApiService(settings_for(tmp))
                adapter = FakeKrakenAdapter()
                adapter.prices = {"XBTGBP": {"c": ["48000.0"]}}
                service.orchestrator.adapters["kraken"] = adapter
                self._open_position(service)

                first = service.monitor_managed_exits()
                self.assertEqual(first["managed_exits"][0]["status"], "exit_failed")
                self.assertEqual(adapter.submitted_orders, [])

                # Now approve trading and retry -- the earlier rejection must not have
                # left the position permanently locked out of ever exiting.
                os.environ["KRAKEN_LIVE_TRADING_APPROVED"] = "true"
                os.environ["KRAKEN_SUBMIT_REAL_ORDERS"] = "true"
                second = service.monitor_managed_exits()
                self.assertEqual(second["managed_exits"][0]["status"], "exit_submitted")
                self.assertEqual(len(adapter.submitted_orders), 1)
        finally:
            restore_env(previous)

    def test_ambiguous_broker_outcome_does_not_release_the_lock(self):
        # Stage 0.4 (architecture/AI_TRADER_MODULARISATION_ARCHITECTURE_2026-08-02.md
        # section 3): "An uncertain broker outcome must not cause an order-intent lock
        # to be automatically released." release_order_intent_lock's own docstring
        # already states this must only be called after a definite, synchronous
        # rejection -- this proves the actual call site (monitor_managed_exits,
        # api.py) honours that: when place_exit_order raises (simulating a network
        # timeout or any other outcome where we genuinely don't know whether Kraken
        # received the order), no release call is reached and the lock survives.
        previous = self._env()
        try:
            self._activate_kraken()
            with tempfile.TemporaryDirectory() as tmp:
                service = LocalApiService(settings_for(tmp))
                adapter = FakeKrakenAdapter()
                adapter.prices = {"XBTGBP": {"c": ["48000.0"]}}

                def raise_ambiguous_outcome(order_request):
                    raise TimeoutError("Kraken did not respond before the request timed out")

                adapter.place_exit_order = raise_ambiguous_outcome
                service.orchestrator.adapters["kraken"] = adapter
                managed_exit_id = self._open_position(service)

                with self.assertRaises(TimeoutError):
                    service.monitor_managed_exits()

                # The lock acquired before the ambiguous call must still be held --
                # a same-key re-acquire attempt must fail.
                relocked = acquire_order_intent_lock(
                    service.settings.db_path,
                    broker="kraken",
                    client_order_id=f"exit-{managed_exit_id}",
                    symbol="BTC",
                    side="sell",
                    notional=4800.0,
                )
                self.assertFalse(relocked, "An ambiguous broker outcome must never release the order-intent lock.")
        finally:
            restore_env(previous)


if __name__ == "__main__":
    unittest.main()
