import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.api import LocalApiService
from ai_trader.api import ApiHandler
from ai_trader.agent import AITradingAgent
from ai_trader.alpaca import AlpacaCredentials, AlpacaError, AlpacaPaperClient
from ai_trader.ai import _proposal_from_response_text
from ai_trader.audit import AuditDatabase
from ai_trader.benchmark import BenchmarkIntelligenceDatabase
from ai_trader.config import Settings
from ai_trader.db_browser import ReadOnlyDatabaseBrowser
from ai_trader.intelligence import InvestmentIntelligenceDatabase
from ai_trader.models import AccountContext, GuardrailConfig, TradeProposal, ValidationResult
from ai_trader.models import AutoTradeConfig
from ai_trader.scheduler import IntervalWorker, ResearchScheduler


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

    def test_daily_learning_update_includes_trade_and_benchmark_lessons(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(tmp)
            service = LocalApiService(settings)
            BenchmarkIntelligenceDatabase(settings.db_path).seed_initial_data()
            yesterday = "2026-07-06"
            with closing(sqlite3.connect(settings.db_path)) as conn:
                with conn:
                    conn.execute(
                        """
                        INSERT INTO PERFORMANCE_ATTRIBUTION (
                            created_at, proposal_id, broker, symbol, asset_type, side,
                            entry_price, exit_price, quantity, profit_loss, opened_at,
                            closed_at, holding_period_seconds, entry_reason, exit_reason,
                            primary_factors_json
                        ) VALUES (?, 'p1', 'kraken', 'BTC', 'crypto', 'sell', 100, 110, 1, 10, ?, ?, 60, 'trend', 'take_profit_triggered', '{}')
                        """,
                        (f"{yesterday}T12:00:00+00:00", f"{yesterday}T11:59:00+00:00", f"{yesterday}T12:00:00+00:00"),
                    )

            status, payload = service.get("/daily-learning-update", {"date": [yesterday]})

            self.assertEqual(status, 200)
            self.assertEqual(payload["trade_outcomes"]["closed_trades"], 1)
            self.assertEqual(payload["trade_outcomes"]["total_profit_loss"], 10.0)
            self.assertTrue(payload["benchmark_learning"])
            self.assertIn("Founder approval", " ".join(payload["recommendations_for_founder"]))

    def test_generate_trading_report_explains_negative_pnl_and_saves_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(tmp)
            service = LocalApiService(settings)
            report_date = "2026-07-07"
            with closing(sqlite3.connect(settings.db_path)) as conn:
                with conn:
                    conn.execute(
                        """
                        INSERT INTO PORTFOLIO_SNAPSHOTS (
                            created_at, broker, exchange, portfolio_value, cash,
                            buying_power, day_pnl, week_pnl, month_pnl,
                            open_positions_count, notes
                        ) VALUES (?, 'alpaca', 'Alpaca', 100000, 10000, 40000, 0, 0, 0, 1, 'start')
                        """,
                        (f"{report_date}T09:00:00+00:00",),
                    )
                    conn.execute(
                        """
                        INSERT INTO PORTFOLIO_SNAPSHOTS (
                            created_at, broker, exchange, portfolio_value, cash,
                            buying_power, day_pnl, week_pnl, month_pnl,
                            open_positions_count, notes
                        ) VALUES (?, 'alpaca', 'Alpaca', 99000, 10000, 40000, -1000, -2000, -2000, 1, 'end')
                        """,
                        (f"{report_date}T15:00:00+00:00",),
                    )
                    conn.execute(
                        """
                        INSERT INTO PERFORMANCE_ATTRIBUTION (
                            created_at, proposal_id, broker, symbol, asset_type, side,
                            entry_price, exit_price, quantity, profit_loss, opened_at,
                            closed_at, holding_period_seconds, entry_reason, exit_reason,
                            primary_factors_json
                        ) VALUES (?, 'p2', 'alpaca', 'NVDA', 'equity', 'buy', 100, 90, 10, -100, ?, ?, 3600, 'momentum', 'stop_loss_triggered', '{}')
                        """,
                        (f"{report_date}T16:00:00+00:00", f"{report_date}T15:00:00+00:00", f"{report_date}T16:00:00+00:00"),
                    )
                    conn.execute(
                        """
                        INSERT INTO BROKER_TRADE_HISTORY (
                            broker, external_id, symbol, asset_type, side, quantity,
                            price, notional, status, opened_at, closed_at, updated_at,
                            payload_json
                        ) VALUES (
                            'alpaca', 'fill-buy-1', 'ABC', 'equity', 'buy', 10,
                            100, 1000, 'fill', ?, NULL, ?,
                            '{"type":"fill","symbol":"ABC","side":"buy","qty":"10","price":"100","transaction_time":"2026-07-07T10:00:00+00:00"}'
                        )
                        """,
                        (f"{report_date}T10:00:00+00:00", f"{report_date}T10:00:00+00:00"),
                    )
                    conn.execute(
                        """
                        INSERT INTO BROKER_TRADE_HISTORY (
                            broker, external_id, symbol, asset_type, side, quantity,
                            price, notional, status, opened_at, closed_at, updated_at,
                            payload_json
                        ) VALUES (
                            'alpaca', 'fill-sell-1', 'ABC', 'equity', 'sell', 10,
                            110, 1100, 'fill', ?, NULL, ?,
                            '{"type":"fill","symbol":"ABC","side":"sell","qty":"10","price":"110","transaction_time":"2026-07-07T11:00:00+00:00"}'
                        )
                        """,
                        (f"{report_date}T11:00:00+00:00", f"{report_date}T11:00:00+00:00"),
                    )
                    conn.execute(
                        """
                        INSERT INTO BROKER_TRADE_HISTORY (
                            broker, external_id, symbol, asset_type, side, quantity,
                            price, notional, status, opened_at, closed_at, updated_at,
                            payload_json
                        ) VALUES (
                            'alpaca', 'fill-sell-rog', 'ROG', 'equity', 'sell', 4,
                            141.2, 564.8, 'fill', ?, NULL, ?,
                            '{"type":"fill","symbol":"ROG","side":"sell","qty":"4","price":"141.2","transaction_time":"2026-07-07T12:00:00+00:00"}'
                        )
                        """,
                        (f"{report_date}T12:00:00+00:00", f"{report_date}T12:00:00+00:00"),
                    )

            status, payload = service.post("/generate-report", {"date": report_date, "broker": "alpaca", "type": "daily"})

            self.assertEqual(status, 200)
            self.assertEqual(payload["status"], "generated")
            self.assertIn("Start And End Balances", payload["report_markdown"])
            self.assertIn("Performance Over The Period", payload["report_markdown"])
            self.assertIn("negative", payload["report_markdown"])
            self.assertIn("NVDA", payload["report_markdown"])
            self.assertIn("Plain English Executive Answer", payload["report_markdown"])
            self.assertIn("appears to be tied up in open positions", payload["report_markdown"])
            self.assertIn("opened 07 Jul 2026, 15:00 UTC", payload["report_markdown"])
            self.assertIn("closed 07 Jul 2026, 16:00 UTC", payload["report_markdown"])
            self.assertIn("P&L -100.00", payload["report_markdown"])
            self.assertIn("Reconstructed Broker Fill P&L", payload["report_markdown"])
            self.assertIn("Matched trade 1", payload["report_markdown"])
            self.assertIn("ABC", payload["report_markdown"])
            self.assertIn("P&L 100.00", payload["report_markdown"])
            self.assertIn("Open/unmatched fills", payload["report_markdown"])
            self.assertIn("ROG", payload["report_markdown"])
            self.assertIn("Lessons Learned", payload["report_markdown"])
            self.assertIn("Recommendations For Founder Approval", payload["report_markdown"])
            self.assertTrue(Path(payload["path"]).exists())
            self.assertIsNotNone(payload["report_id"])
            self.assertEqual(payload["report_url"], f"/reports/{payload['report_id']}")
            with closing(sqlite3.connect(settings.db_path)) as conn:
                stored = conn.execute("SELECT COUNT(*) FROM TRADING_REPORTS").fetchone()[0]
            self.assertEqual(stored, 1)

            page_status, page_payload = service.get(payload["report_url"], {})

            self.assertEqual(page_status, 200)
            self.assertIn("html", page_payload)
            self.assertIn("AI Trader Daily Report", page_payload["html"])

            weekly_status, weekly_payload = service.get("/trading-report", {"date": [report_date], "broker": ["alpaca"], "type": ["weekly"]})

            self.assertEqual(weekly_status, 200)
            self.assertIn("Weekly report window", weekly_payload["report_markdown"])
            self.assertIn("Start And End Balances", weekly_payload["report_markdown"])

    def test_ask_ai_trader_is_read_only_and_uses_local_evidence_without_openai(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(tmp)
            service = LocalApiService(settings)
            with closing(sqlite3.connect(settings.db_path)) as conn:
                with conn:
                    conn.execute(
                        """
                        INSERT INTO PORTFOLIO_SNAPSHOTS (
                            created_at, broker, exchange, portfolio_value, cash,
                            buying_power, day_pnl, week_pnl, month_pnl,
                            open_positions_count, notes
                        ) VALUES ('2026-07-07T12:00:00+00:00', 'alpaca', 'Alpaca', 100000, 89000, 89000, -1000, -1000, -1000, 1, 'test')
                        """
                    )

            status, payload = service.post("/ask-ai-trader", {"question": "Why am I down today and can you trade out of it?"})

            self.assertEqual(status, 200)
            self.assertTrue(payload["read_only"])
            self.assertEqual(payload["status"], "openai_not_configured")
            self.assertIn("cannot place or approve trades", payload["answer"])
            self.assertIn("Latest alpaca snapshot", payload["answer"])
            self.assertIn("estimated in positions", payload["answer"])

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

    def test_healthz_is_available_for_cloud_health_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalApiService(settings_for(tmp))

            status, payload = service.get("/healthz", {})

            self.assertEqual(status, 200)
            self.assertEqual(payload["status"], "ok")

    def test_api_token_authorization_accepts_bearer_or_api_key(self):
        class Headers:
            def __init__(self, values):
                self.values = values

            def get(self, key, default=""):
                return self.values.get(key, default)

        handler = object.__new__(ApiHandler)
        handler.api_token = "secret"
        handler.headers = Headers({"Authorization": "Bearer secret"})
        self.assertTrue(handler._authorized("/status"))

        handler.headers = Headers({"X-API-Key": "secret"})
        self.assertTrue(handler._authorized("/status"))

        handler.headers = Headers({})
        self.assertFalse(handler._authorized("/status"))
        self.assertTrue(handler._authorized("/healthz"))

    def test_repeated_auth_failures_lock_out_the_source_ip(self):
        class Headers:
            def __init__(self, values):
                self.values = values

            def get(self, key, default=""):
                return self.values.get(key, default)

        handler = object.__new__(ApiHandler)
        handler.api_token = "secret"
        handler.client_address = ("203.0.113.9", 4321)
        handler.headers = Headers({})
        for _ in range(handler._MAX_AUTH_FAILURES):
            handler._authorized("/status")

        handler.headers = Headers({"Authorization": "Bearer secret"})
        self.assertFalse(
            handler._authorized("/status"),
            "The correct token must still be rejected once the source IP is locked out.",
        )

        other = object.__new__(ApiHandler)
        other.api_token = "secret"
        other.client_address = ("203.0.113.10", 4321)
        other.headers = Headers({"Authorization": "Bearer secret"})
        self.assertTrue(other._authorized("/status"), "Lockout must be scoped per source IP.")

    def test_hosted_read_only_mode_rejects_post_commands(self):
        captured = {}

        class Handler:
            path = "/start-trading"
            hosted_read_only = True

            def _authorized(self, path):
                return True

            def _json(self, status, payload):
                captured["status"] = status
                captured["payload"] = payload

        ApiHandler.do_POST(Handler())

        self.assertEqual(captured["status"], 403)
        self.assertEqual(captured["payload"]["error"], "hosted_read_only")

    def test_research_scheduler_background_loop_survives_a_failed_cycle(self):
        import threading
        import time

        calls = []
        errors = []

        class FailingService:
            def run_analysis(self, body):
                calls.append(body)
                raise RuntimeError("simulated broker timeout")

        scheduler = ResearchScheduler(FailingService(), interval_minutes=0, on_error=errors.append)
        stop = scheduler.start_background(limit=1)
        try:
            time.sleep(0.2)
            thread = next((t for t in threading.enumerate() if t.name == "ai-trader-research-scheduler"), None)
            self.assertIsNotNone(thread, "The scheduler thread should have started.")
            self.assertTrue(thread.is_alive(), "A raised exception must not kill the scheduler thread.")
            self.assertEqual(len(calls), 1)
            self.assertEqual(len(errors), 1)
        finally:
            stop.set()

    def test_interval_worker_keeps_running_after_an_exception(self):
        import threading
        import time

        calls = []
        errors = []

        def flaky():
            calls.append(1)
            raise RuntimeError("simulated failure")

        worker = IntervalWorker(flaky, interval_seconds=0.01, name="test-worker", on_error=errors.append)
        stop = worker.start_background()
        try:
            time.sleep(0.2)
            thread = next((t for t in threading.enumerate() if t.name == "test-worker"), None)
            self.assertIsNotNone(thread, "The worker thread should have started.")
            self.assertTrue(thread.is_alive(), "A raised exception must not kill the worker thread.")
            self.assertEqual(len(calls), 1)
            self.assertEqual(len(errors), 1)
        finally:
            stop.set()

    def test_recommendations_include_freshness_and_expiry(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(tmp)
            audit = AuditDatabase(settings.db_path, settings.trading_log_path)
            proposal = TradeProposal(
                symbol="AAPL",
                side="buy",
                entry_price=100,
                stop_loss=99,
                take_profit=103,
                position_size=1,
                risk_percentage=0.01,
                confidence_score=0.9,
                news_summary="Public news context.",
                market_sentiment_summary="Neutral.",
                technical_summary="Setup available.",
                plain_english_reasoning="Test recommendation.",
                ai_guardrails_passed=True,
            )
            audit.record_trade_event("agent_proposal", proposal, validation=ValidationResult(passed=True))
            with closing(sqlite3.connect(settings.db_path)) as conn:
                with conn:
                    conn.execute(
                        "UPDATE trade_audit SET created_at = ? WHERE proposal_id = ?",
                        ("2026-01-01T00:00:00+00:00", proposal.proposal_id),
                    )

            recommendations = LocalApiService(settings).recommendations()

            self.assertEqual(recommendations[0]["freshness_status"], "Expired")
            self.assertIsNotNone(recommendations[0]["expires_at"])
            self.assertFalse(recommendations[0]["auto_trade_eligible"])

    def test_recommendations_keep_history_ordered_by_confidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(tmp)
            audit = AuditDatabase(settings.db_path, settings.trading_log_path)
            low = TradeProposal(
                symbol="LOW",
                side="buy",
                entry_price=100,
                stop_loss=99,
                take_profit=103,
                position_size=1,
                risk_percentage=0.01,
                confidence_score=0.86,
                news_summary="Public news context.",
                market_sentiment_summary="Neutral.",
                technical_summary="Setup available.",
                plain_english_reasoning="Lower confidence.",
                ai_guardrails_passed=True,
            )
            high = TradeProposal(
                symbol="HIGH",
                side="buy",
                entry_price=100,
                stop_loss=99,
                take_profit=103,
                position_size=1,
                risk_percentage=0.01,
                confidence_score=0.91,
                news_summary="Public news context.",
                market_sentiment_summary="Neutral.",
                technical_summary="Setup available.",
                plain_english_reasoning="Higher confidence.",
                ai_guardrails_passed=True,
            )
            audit.record_trade_event("agent_proposal", low, validation=ValidationResult(passed=True))
            audit.record_trade_event("agent_proposal", high, validation=ValidationResult(passed=True))
            with closing(sqlite3.connect(settings.db_path)) as conn:
                with conn:
                    conn.execute(
                        "UPDATE trade_audit SET created_at = ? WHERE proposal_id = ?",
                        ("2026-01-01T00:00:00+00:00", low.proposal_id),
                    )

            recommendations = LocalApiService(settings).recommendations()

            self.assertGreaterEqual(len(recommendations), 2)
            self.assertEqual(recommendations[0]["ticker"], "HIGH")
            self.assertEqual(recommendations[1]["ticker"], "LOW")
            self.assertEqual(recommendations[1]["freshness_status"], "Expired")

    def test_recommendations_include_guardrail_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(tmp)
            audit = AuditDatabase(settings.db_path, settings.trading_log_path)
            proposal = TradeProposal(
                symbol="EDV",
                side="sell",
                entry_price=100,
                stop_loss=101,
                take_profit=98,
                position_size=1,
                risk_percentage=0.01,
                confidence_score=0.9,
                news_summary="Public news context.",
                market_sentiment_summary="Cautious.",
                technical_summary="Setup available.",
                plain_english_reasoning="Test recommendation.",
                ai_guardrails_passed=False,
            )
            audit.record_trade_event(
                "agent_proposal",
                proposal,
                validation=ValidationResult(passed=False, failures=["short_selling_disabled"]),
            )

            recommendation = LocalApiService(settings).recommendations()[0]

            self.assertFalse(recommendation["guardrails_passed"])
            self.assertEqual(recommendation["guardrail_failures"], ["short_selling_disabled"])
            self.assertIn("short selling disabled", recommendation["guardrail_summary"])
            self.assertIn("Stop loss is present", recommendation["guardrail_passes"])
            failed_checks = [
                check for check in recommendation["guardrail_checks"]
                if check["status"] == "failed"
            ]
            passed_checks = [
                check for check in recommendation["guardrail_checks"]
                if check["status"] == "passed"
            ]
            self.assertEqual(failed_checks, [
                {
                    "key": "short_selling_disabled",
                    "label": "Short selling rule is satisfied",
                    "status": "failed",
                }
            ])
            self.assertTrue(passed_checks)

    def test_expired_recommendation_is_blocked_before_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(tmp)
            settings = Settings(
                alpaca_api_key="paper-key",
                alpaca_secret_key="paper-secret",
                alpaca_paper_base_url=settings.alpaca_paper_base_url,
                alpaca_data_base_url=settings.alpaca_data_base_url,
                openai_api_key=None,
                openai_model=settings.openai_model,
                db_path=settings.db_path,
                output_dir=settings.output_dir,
                trading_log_path=settings.trading_log_path,
                guardrails=settings.guardrails,
            )
            audit = AuditDatabase(settings.db_path, settings.trading_log_path)
            proposal = TradeProposal(
                symbol="AAPL",
                side="buy",
                entry_price=100,
                stop_loss=99,
                take_profit=103,
                position_size=1,
                risk_percentage=0.01,
                confidence_score=0.9,
                news_summary="Public news context.",
                market_sentiment_summary="Neutral.",
                technical_summary="Setup available.",
                plain_english_reasoning="Test recommendation.",
                ai_guardrails_passed=True,
            )
            audit.record_trade_event("agent_proposal", proposal, validation=ValidationResult(passed=True))
            with closing(sqlite3.connect(settings.db_path)) as conn:
                with conn:
                    conn.execute(
                        "UPDATE trade_audit SET created_at = ? WHERE proposal_id = ?",
                        ("2026-01-01T00:00:00+00:00", proposal.proposal_id),
                    )

            result = LocalApiService(settings).approve_and_execute({"proposal_id": proposal.proposal_id})

            self.assertEqual(result["status"], "blocked")
            self.assertIn("expired", result["message"].lower())

    def test_auto_execute_explains_guardrail_skips(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = settings_for(tmp)
            settings = Settings(
                alpaca_api_key="paper-key",
                alpaca_secret_key="paper-secret",
                alpaca_paper_base_url=base.alpaca_paper_base_url,
                alpaca_data_base_url=base.alpaca_data_base_url,
                openai_api_key=None,
                openai_model=base.openai_model,
                db_path=base.db_path,
                output_dir=base.output_dir,
                trading_log_path=base.trading_log_path,
                guardrails=base.guardrails,
                auto_trade=AutoTradeConfig(enabled=True),
            )
            audit = AuditDatabase(settings.db_path, settings.trading_log_path)
            proposal = TradeProposal(
                symbol="EDV",
                side="sell",
                entry_price=100,
                stop_loss=101,
                take_profit=98,
                position_size=1,
                risk_percentage=0.01,
                confidence_score=0.87,
                news_summary="Public news context.",
                market_sentiment_summary="Cautious.",
                technical_summary="Setup available.",
                plain_english_reasoning="Test recommendation.",
                ai_guardrails_passed=False,
            )
            audit.record_trade_event(
                "agent_proposal",
                proposal,
                validation=ValidationResult(passed=False, failures=["short_selling_disabled"]),
            )

            result = LocalApiService(settings).auto_execute_recommendations()

            self.assertEqual(result["status"], "skipped")
            self.assertEqual(result["eligible_count"], 0)
            self.assertEqual(result["skipped"][0]["symbol"], "EDV")
            self.assertIn("Guardrails failed", result["skipped"][0]["message"])

    def test_agent_records_no_trade_when_market_bar_missing(self):
        class EmptyMarketData:
            def get_latest_bars(self, symbols):
                return {"bars": {}, "unavailable_symbols": symbols}

            def get_news(self, symbols, limit=5):
                return {"news": []}

        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(tmp)
            audit = AuditDatabase(settings.db_path, settings.trading_log_path)
            agent = AITradingAgent(
                market_data=EmptyMarketData(),
                audit=audit,
                guardrails=settings.guardrails,
            )

            proposals = agent.propose_trades(
                ["KGH"],
                account=AccountContext(equity=100_000, daily_realized_pnl=0, open_positions=[]),
            )

            self.assertEqual(proposals, [])
            with closing(sqlite3.connect(settings.db_path)) as conn:
                row = conn.execute(
                    "SELECT event_type, payload_json FROM execution_events ORDER BY id DESC LIMIT 1"
                ).fetchone()
            self.assertEqual(row[0], "agent_no_trade")
            self.assertIn("No latest market bar", row[1])

    def test_alpaca_missing_asset_returns_empty_market_data(self):
        class MissingAssetClient(AlpacaPaperClient):
            def _request(self, method, path, *, payload=None, data_api=False):
                raise AlpacaError('Alpaca API error 422: {"message":"asset \\"KGHN\\" not found"}')

        client = MissingAssetClient(AlpacaCredentials(api_key="key", secret_key="secret"))

        bars = client.get_latest_bars(["KGH"])
        news = client.get_news(["KGH"])

        self.assertEqual(bars["bars"], {})
        self.assertEqual(news["news"], [])
        self.assertEqual(bars["unavailable_symbols"], ["KGH"])

    def test_openai_empty_json_means_no_trade(self):
        self.assertIsNone(_proposal_from_response_text("{}"))
        self.assertIsNone(_proposal_from_response_text("null"))

    def test_run_analysis_uses_watchlist_limit_before_credentials_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(tmp)
            InvestmentIntelligenceDatabase(settings.db_path).seed_initial_data()

            result = LocalApiService(settings).run_analysis({"limit": 30})

            self.assertEqual(result["status"], "not_available")
            self.assertEqual(len(result["symbols"]), 30)


if __name__ == "__main__":
    unittest.main()
