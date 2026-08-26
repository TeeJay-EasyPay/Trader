import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.api import LocalApiService
from ai_trader.api import ApiHandler
from ai_trader.agent import AITradingAgent
from ai_trader.alpaca import AlpacaCredentials, AlpacaError, AlpacaPaperClient
from ai_trader.ai import OpenAIReadOnlyExplainer, _proposal_from_response_text
from ai_trader.audit import AuditDatabase
from ai_trader.intelligence_data import THEMES
from ai_trader.benchmark import BenchmarkIntelligenceDatabase
from ai_trader.config import Settings
from ai_trader.db_browser import ReadOnlyDatabaseBrowser
from ai_trader.foundation import initialize_foundation_schema
from ai_trader.intelligence import InvestmentIntelligenceDatabase
from ai_trader.market_intelligence_platform import initialize_market_intelligence_schema
from ai_trader.models import AccountContext, GuardrailConfig, TradeProposal, ValidationResult
from ai_trader.models import AutoTradeConfig
from ai_trader.multi_broker import set_broker_auto_trading
from ai_trader.operational import safe_score
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
            # 2026-08-14: 31 non-US watchlist companies + 19 real US-listed (Alpaca-eligible,
            # Shariah business-activity screened) companies added so Alpaca has genuinely
            # tradable candidates -- see intelligence_data.py's COMPANIES list.
            self.assertEqual(status["counts"]["watchlist"], 50)
            # 2026-08-23: 10 -> 14. Technology, Sports, Mining and Steel were added because
            # 13 of the 50 watchlist companies had no MARKET_THEMES row matching their
            # sector, and _macro_context_available scores those a permanent macro_score 0.
            # Asserted against the seed list rather than a hardcoded number so adding a
            # theme to close a coverage gap does not require editing this expectation again.
            self.assertEqual(status["counts"]["market_themes"], len(THEMES))
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

    def test_ask_ai_trader_falls_back_when_openai_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(tmp)
            settings = Settings(
                alpaca_api_key=settings.alpaca_api_key,
                alpaca_secret_key=settings.alpaca_secret_key,
                alpaca_paper_base_url=settings.alpaca_paper_base_url,
                alpaca_data_base_url=settings.alpaca_data_base_url,
                openai_api_key="test-key",
                openai_model=settings.openai_model,
                db_path=settings.db_path,
                output_dir=settings.output_dir,
                trading_log_path=settings.trading_log_path,
                guardrails=settings.guardrails,
                auto_trade=settings.auto_trade,
                research_scheduler_enabled=settings.research_scheduler_enabled,
                research_scheduler_interval_minutes=settings.research_scheduler_interval_minutes,
                research_scheduler_limit=settings.research_scheduler_limit,
            )
            service = LocalApiService(settings)
            with patch("ai_trader.api.OpenAIReadOnlyExplainer.answer", side_effect=RuntimeError("simulated timeout")):
                status, payload = service.post("/ask-ai-trader", {"question": "Are you ready to trade?"})

            self.assertEqual(status, 200)
            self.assertEqual(payload["status"], "openai_failed")
            self.assertTrue(payload["read_only"])
            self.assertIn("cannot place or approve trades", payload["answer"])
            self.assertIn("OpenAI is configured", payload["answer"])
            self.assertNotIn("configure OPENAI_API_KEY", payload["answer"])
            self.assertIn("simulated timeout", payload["note"])

    def test_ask_ai_trader_context_excludes_the_payloads_that_blew_the_proxy_timeout(self):
        """2026-08-24 regression: every Ask request died at Render's hard 60s proxy
        timeout. The context embedded world_class_evidence (>60s on its own in
        production) plus two recommendations(limit=20) calls at ~118KB per row. The
        Founder never saw an answer -- only "the request timed out"."""
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(tmp)
            service = LocalApiService(settings)

            with patch.object(
                LocalApiService, "world_class_evidence", side_effect=AssertionError("world_class_evidence must not be built for Ask")
            ), patch.object(
                LocalApiService, "recommendations", wraps=service.recommendations
            ) as recommendations:
                context = service._ask_ai_context(deadline=time.monotonic() + 50.0)

            self.assertNotIn("world_class_evidence", context)
            self.assertEqual(recommendations.call_count, 1, "recommendations should be gathered once, not twice")

    def test_ask_ai_trader_never_triggers_a_live_broker_fetch(self):
        """2026-08-24: Ask built the broker panels itself, which measured ~29s of its
        50s budget in production -- a real question took 57.2s, the app hung up at 55s,
        and the Founder saw an error for an answer the backend had produced. Ask
        explains stored evidence; the portfolio snapshots in its context already carry
        the same balances, so it may reuse panels someone else built but must never
        pay to build them."""
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalApiService(settings_for(tmp))

            with patch.object(
                LocalApiService, "broker_panels", side_effect=AssertionError("Ask must not build broker panels")
            ), patch.object(
                type(service._broker_service), "_build_broker_panels",
                side_effect=AssertionError("Ask must not build broker panels"),
            ):
                context = service._ask_ai_context(deadline=time.monotonic() + 50.0)

            # Absent panels are still said out loud, not left silent -- but in their own
            # field, because putting the sentence in broker_panels made a list-shaped field
            # hold a string and 500'd the endpoint (see AskWithoutCachedPanelsTests).
            self.assertEqual(context["broker_panels"], [])
            self.assertIn("snapshots below", str(context["broker_panels_note"]))

    def test_ask_ai_trader_context_includes_the_systems_own_research(self):
        """2026-08-24, Founder: "it works but only using its own traded data". Asked how
        XRP might do, Ask answered that it had no view -- while a 14-day XRP forecast
        with full reasoning sat unread in the database. It could see what it had bought
        and sold but none of the research it runs every hour."""
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(tmp)
            service = LocalApiService(settings)
            initialize_market_intelligence_schema(settings.db_path)
            with closing(sqlite3.connect(settings.db_path)) as conn:
                with conn:
                    conn.execute(
                        """
                        INSERT INTO FORECAST_RECORDS (
                            created_at, scope, symbol, asset_type, direction, horizon_days,
                            confidence, reasoning, invalidation, evidence_json, generated_by, expires_at
                        ) VALUES ('2026-08-24T06:33:16+00:00', 'symbol', 'XRP', 'crypto', 'uncertain', 14,
                                  0.35, ?, 'A weekly close below the long moving average.', '{}', 'test',
                                  '2099-01-01T00:00:00+00:00')
                        """,
                        ("Strong daily momentum against a weak weekly trend. " + "x" * 2000,),
                    )
                    conn.execute(
                        """
                        INSERT INTO CRYPTO_RESEARCH_SCORES (created_at, symbol, technical_trend_score, momentum_score, rsi, reasoning_json)
                        VALUES ('2026-08-24T10:00:00+00:00', 'XRP', 1.0, 1.0, 62.5, '{}')
                        """
                    )

            context = service._ask_ai_context(deadline=time.monotonic() + 50.0)

            forecast = next(row for row in context["market_forecasts"] if row["symbol"] == "XRP")
            self.assertEqual(forecast["direction"], "uncertain")
            self.assertEqual(forecast["horizon_days"], 14)
            self.assertEqual(forecast["confidence"], 0.35)
            self.assertIn("weak weekly trend", forecast["reasoning"])
            self.assertIn("moving average", forecast["invalidation"])
            # Reasoning is kept but capped: ~25 of these, several hundred words each.
            self.assertTrue(forecast["reasoning"].endswith("..."))
            self.assertLessEqual(len(forecast["reasoning"]), 720)

            score = next(row for row in context["crypto_research_scores"] if row["symbol"] == "XRP")
            self.assertEqual(score["momentum_score"], 1.0)
            self.assertIn("recent_crypto_news", context)

    def test_ask_ai_trader_forecasts_are_one_per_symbol_and_exclude_expired(self):
        """Stale forecasts must not be read back as current, and the newest view of a
        symbol is the one that counts -- otherwise a superseded call argues with itself."""
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(tmp)
            service = LocalApiService(settings)
            initialize_market_intelligence_schema(settings.db_path)
            rows = [
                ("BTC", "up", "2099-01-01T00:00:00+00:00", "current view"),
                ("BTC", "down", "2099-01-01T00:00:00+00:00", "superseded view"),
                ("SOL", "up", "2020-01-01T00:00:00+00:00", "long expired"),
            ]
            with closing(sqlite3.connect(settings.db_path)) as conn:
                with conn:
                    for symbol, direction, expires_at, reasoning in reversed(rows):
                        conn.execute(
                            """
                            INSERT INTO FORECAST_RECORDS (
                                created_at, scope, symbol, asset_type, direction, horizon_days,
                                confidence, reasoning, evidence_json, generated_by, expires_at
                            ) VALUES ('2026-08-24T06:00:00+00:00', 'symbol', ?, 'crypto', ?, 7, 0.6, ?, '{}', 'test', ?)
                            """,
                            (symbol, direction, reasoning, expires_at),
                        )

            forecasts = service._ask_ai_context(deadline=time.monotonic() + 50.0)["market_forecasts"]

            symbols = [row["symbol"] for row in forecasts]
            self.assertEqual(symbols.count("BTC"), 1)
            self.assertNotIn("SOL", symbols, "an expired forecast must not be presented as current")
            self.assertEqual(next(row for row in forecasts if row["symbol"] == "BTC")["reasoning"], "current view")

    def test_ask_ai_trader_recommendations_are_slimmed_for_the_prompt(self):
        from ai_trader.api import _slim_recommendation

        fat = {
            "symbol": "XRP",
            "reason_for_recommendation": "x" * 5000,
            "trade_lifecycle": {"stages": ["huge"] * 5000},
            "signals": {"noise": "y" * 20000},
            "committee": {"votes": ["z"] * 5000},
        }

        slim = _slim_recommendation(fat)

        self.assertEqual(slim["symbol"], "XRP")
        self.assertNotIn("trade_lifecycle", slim)
        self.assertNotIn("signals", slim)
        self.assertNotIn("committee", slim)
        self.assertTrue(slim["reason_for_recommendation"].endswith("..."))
        self.assertLess(len(json.dumps(slim)), 1000)

    def test_ask_ai_trader_answers_from_evidence_when_the_budget_is_already_spent(self):
        """A slow context must not then start an OpenAI call that outlives the proxy.
        Late answers don't arrive -- the connection is already dead."""
        with tempfile.TemporaryDirectory() as tmp:
            settings = replace(settings_for(tmp), openai_api_key="test-key")
            service = LocalApiService(settings)

            def slow_context(*args, **kwargs):
                return {"openai_configured": True, "latest_portfolio_snapshots": []}

            with patch.object(LocalApiService, "_ask_ai_context", side_effect=slow_context), patch(
                "ai_trader.api.time.monotonic", side_effect=[0.0, 49.0]
            ), patch("ai_trader.api.OpenAIReadOnlyExplainer.answer", side_effect=AssertionError("must not call OpenAI without runway")):
                status, payload = service.post("/ask-ai-trader", {"question": "How are we doing?"})

            self.assertEqual(status, 200)
            self.assertEqual(payload["status"], "evidence_only")
            self.assertTrue(payload["read_only"])
            self.assertIn("time available", payload["note"])

    def test_openai_explainer_timeout_is_bounded_by_the_callers_budget(self):
        explainer = OpenAIReadOnlyExplainer("test-key", "gpt-test", timeout_seconds=18.5)
        self.assertEqual(explainer.timeout_seconds, 18.5)
        self.assertEqual(OpenAIReadOnlyExplainer("k", "m").timeout_seconds, OpenAIReadOnlyExplainer.DEFAULT_TIMEOUT_SECONDS)

    def test_crypto_rejections_explained_uses_local_digest_without_openai(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(tmp)
            service = LocalApiService(settings)
            proposal = TradeProposal(
                symbol="BTC",
                side="buy",
                entry_price=50000.0,
                stop_loss=49000.0,
                take_profit=52000.0,
                position_size=1,
                risk_percentage=0.01,
                confidence_score=0.9,
                asset_type="crypto",
                exchange="KRAKEN",
                news_summary="",
                market_sentiment_summary="",
                technical_summary="",
                plain_english_reasoning="Test.",
                ai_guardrails_passed=False,
            )
            AuditDatabase(settings.db_path, None).record_trade_event(
                "agent_proposal", proposal, validation=ValidationResult(passed=False, failures=["duplicate_open_position"])
            )

            status, payload = service.get("/crypto-rejections-explained", {})

            self.assertEqual(status, 200)
            self.assertTrue(payload["read_only"])
            self.assertEqual(payload["status"], "openai_not_configured")
            self.assertEqual(payload["digest"]["rejections"][0]["symbol"], "BTC")
            self.assertEqual(payload["digest"]["rejections"][0]["dominant_reason"], "duplicate_open_position")
            self.assertIn("enough evidence yet", payload["learned_synthesis"])

    def test_crypto_rejections_explained_falls_back_when_openai_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(tmp)
            settings = Settings(
                alpaca_api_key=settings.alpaca_api_key,
                alpaca_secret_key=settings.alpaca_secret_key,
                alpaca_paper_base_url=settings.alpaca_paper_base_url,
                alpaca_data_base_url=settings.alpaca_data_base_url,
                openai_api_key="test-key",
                openai_model=settings.openai_model,
                db_path=settings.db_path,
                output_dir=settings.output_dir,
                trading_log_path=settings.trading_log_path,
                guardrails=settings.guardrails,
                auto_trade=settings.auto_trade,
                research_scheduler_enabled=settings.research_scheduler_enabled,
                research_scheduler_interval_minutes=settings.research_scheduler_interval_minutes,
                research_scheduler_limit=settings.research_scheduler_limit,
            )
            service = LocalApiService(settings)

            with patch("ai_trader.api.OpenAIReadOnlyExplainer.answer", side_effect=RuntimeError("simulated timeout")):
                status, payload = service.get("/crypto-rejections-explained", {})

            self.assertEqual(status, 200)
            self.assertEqual(payload["status"], "openai_failed")
            self.assertTrue(payload["read_only"])
            self.assertIn("simulated timeout", payload["note"])
            self.assertIn("summary", payload["digest"])

    def test_admin_set_risk_policy_updates_an_existing_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(tmp)
            service = LocalApiService(settings)
            initialize_foundation_schema(settings.db_path)

            status, payload = service.post("/admin/set-risk-policy", {"key": "maximum_concurrent_positions", "value": 5})

            self.assertEqual(status, 200)
            self.assertEqual(payload["status"], "updated")
            self.assertEqual(payload["new_value"], "5")

    def test_admin_set_risk_policy_rejects_a_missing_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(tmp)
            service = LocalApiService(settings)

            status, payload = service.post("/admin/set-risk-policy", {"value": 5})

            self.assertEqual(status, 400)
            self.assertEqual(payload["error"], "missing_key")

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

    def test_connection_readiness_shows_hosted_control_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalApiService(settings_for(tmp))
            service.hosted_read_only = True
            service.api_token_configured = False

            readiness = service.connection_readiness([])
            control = next(item for item in readiness["checks"] if item["component"] == "Control Actions")

            self.assertFalse(readiness["trade_ready"])
            self.assertEqual(control["status"], "locked")
            self.assertFalse(control["ready"])
            self.assertIn("AI_TRADER_API_TOKEN", control["detail"])

    def test_broker_panels_expose_kraken_trading_permissions(self):
        previous = {
            key: os.environ.get(key)
            for key in [
                "KRAKEN_TRADING_ENABLED",
                "KRAKEN_LIVE_TRADING_APPROVED",
                "KRAKEN_SUBMIT_REAL_ORDERS",
                "KRAKEN_TRADING_ALLOCATION_GBP",
                "KRAKEN_MAX_ORDER_GBP",
                "KRAKEN_MIN_ORDER_GBP",
                "KRAKEN_MAX_OPEN_TRADES",
                "KRAKEN_BUY_ONLY_ENTRIES",
                "KRAKEN_ALLOWED_PAIRS",
            ]
        }
        try:
            os.environ["KRAKEN_TRADING_ENABLED"] = "true"
            os.environ["KRAKEN_LIVE_TRADING_APPROVED"] = "true"
            os.environ["KRAKEN_SUBMIT_REAL_ORDERS"] = "false"
            os.environ["KRAKEN_TRADING_ALLOCATION_GBP"] = "100"
            os.environ["KRAKEN_MAX_ORDER_GBP"] = "5"
            os.environ["KRAKEN_MIN_ORDER_GBP"] = "1"
            os.environ["KRAKEN_MAX_OPEN_TRADES"] = "1"
            os.environ["KRAKEN_BUY_ONLY_ENTRIES"] = "true"
            os.environ["KRAKEN_ALLOWED_PAIRS"] = "XBTGBP,ETHGBP,SOLGBP"
            with tempfile.TemporaryDirectory() as tmp:
                service = LocalApiService(settings_for(tmp))

                kraken = next(item for item in service.broker_panels() if item["broker"] == "kraken")
                permissions = kraken["trading_permissions"]

                self.assertEqual(permissions["trading_allocation_gbp"], 100.0)
                # 2026-08-22: this asserted 5.0, which was the REPORTED figure back when
                # broker_service kept its own 0.05 literal while _validate_live_order had
                # moved to 0.10 -- i.e. the test was pinning the understatement in place.
                # Assert the property that actually matters instead: the ceiling shown to
                # the Founder is the one the broker layer will really enforce.
                from ai_trader.broker_adapters import kraken_max_order_pct_of_cash

                self.assertEqual(permissions["max_order_pct_of_cash"], kraken_max_order_pct_of_cash())
                self.assertEqual(
                    permissions["max_order_gbp"],
                    round(100.0 * kraken_max_order_pct_of_cash(), 2),
                    "Reported max order size must equal the enforced percentage of available cash.",
                )
                self.assertIn("limit_entries_enabled", permissions)
                self.assertEqual(permissions["max_open_trades"], 1)
                self.assertTrue(permissions["buy_only_entries"])
                self.assertEqual(permissions["allowed_pairs"], ["XBTGBP", "ETHGBP", "SOLGBP"])
                self.assertFalse(permissions["can_submit_real_orders"])
                self.assertIn("dry-run", permissions["status"])
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_broker_panels_use_live_alpaca_portfolio_when_connected(self):
        class FakeAlpaca:
            def get_account(self):
                return {
                    "currency": "USD",
                    "cash": "90000",
                    "portfolio_value": "100000",
                    "equity": "100000",
                    "buying_power": "180000",
                }

            def get_positions(self):
                return [{"symbol": "AAPL", "qty": "2", "market_value": "10000", "unrealized_pl": "50"}]

            def get_orders(self, status="all", limit=10):
                return []

            def get_activities(self, activity_type):
                return []

        with tempfile.TemporaryDirectory() as tmp:
            settings = replace(settings_for(tmp), alpaca_api_key="key", alpaca_secret_key="secret")
            service = LocalApiService(settings)
            service._broker = lambda: FakeAlpaca()

            alpaca = next(item for item in service.broker_panels() if item["broker"] == "alpaca")

            self.assertEqual(alpaca["connection_status"], "Connected")
            self.assertEqual(alpaca["portfolio_value"], 100000.0)
            self.assertEqual(alpaca["cash_available"], 90000.0)
            self.assertEqual(alpaca["buying_power"], 180000.0)
            self.assertEqual(alpaca["estimated_in_positions"], 10000.0)
            self.assertEqual(alpaca["open_positions"], "1")

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

    def test_kraken_recommendations_use_broker_auto_trading_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = replace(
                settings_for(tmp),
                auto_trade=AutoTradeConfig(enabled=False, broker_enabled={"kraken": True}),
            )
            set_broker_auto_trading(settings.db_path, "kraken", True)
            audit = AuditDatabase(settings.db_path, settings.trading_log_path)
            proposal = TradeProposal(
                symbol="SOL",
                side="buy",
                entry_price=100,
                stop_loss=98,
                take_profit=104,
                position_size=0.05,
                risk_percentage=0.01,
                confidence_score=0.9,
                news_summary="Crypto news context.",
                market_sentiment_summary="Neutral.",
                technical_summary="Setup available.",
                plain_english_reasoning="Kraken recommendation.",
                ai_guardrails_passed=True,
                asset_type="crypto",
                exchange="KRAKEN",
                philosophy_fit=0.9,
            )
            audit.record_trade_event("agent_proposal", proposal, validation=ValidationResult(passed=True))

            recommendation = next(item for item in LocalApiService(settings).recommendations() if item["symbol"] == "SOL")

            self.assertEqual(recommendation["symbol"], "SOL")
            self.assertEqual(recommendation["suggested_broker"], "kraken")
            self.assertTrue(recommendation["auto_trade_eligible"])
            self.assertNotIn("AUTO_PAPER_TRADING is false", recommendation["auto_trade_reason"])
            self.assertEqual(recommendation["auto_trade_reason"], "Eligible for broker auto-trade.")

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

    def test_manual_approval_recovers_latest_symbol_when_cached_proposal_id_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(tmp)
            audit = AuditDatabase(settings.db_path, settings.trading_log_path)
            proposal = TradeProposal(
                symbol="RIO",
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

            result = LocalApiService(settings).approve_and_execute({"proposal_id": "cached-missing-id", "symbol": "RIO"})

            self.assertNotIn("Proposal not found", result["message"])
            self.assertIn(result["status"], {"not_available", "rejected"})

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

    def test_propose_trades_fetches_market_data_once_for_the_whole_batch(self):
        # run_analysis used to call propose_trades once per symbol, meaning one full
        # get_latest_bars/get_news HTTP round trip *per symbol* (60 calls for a 30-symbol
        # watchlist) -- confirmed as the reason equity research was consistently timing out
        # before generating a single proposal. propose_trades must now fetch market/news
        # exactly once regardless of how many symbols are in the batch.
        class CountingMarketData:
            def __init__(self):
                self.bars_calls: list[list[str]] = []
                self.news_calls: list[list[str]] = []

            def get_latest_bars(self, symbols):
                self.bars_calls.append(list(symbols))
                return {"bars": {}, "unavailable_symbols": symbols}

            def get_news(self, symbols, limit=5):
                self.news_calls.append(list(symbols))
                return {"news": []}

        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(tmp)
            audit = AuditDatabase(settings.db_path, settings.trading_log_path)
            market_data = CountingMarketData()
            agent = AITradingAgent(market_data=market_data, audit=audit, guardrails=settings.guardrails)

            agent.propose_trades(
                ["AAA", "BBB", "CCC"],
                account=AccountContext(equity=100_000, daily_realized_pnl=0, open_positions=[]),
            )

            self.assertEqual(len(market_data.bars_calls), 1)
            self.assertEqual(len(market_data.news_calls), 1)
            self.assertEqual(market_data.bars_calls[0], ["AAA", "BBB", "CCC"])

    def test_propose_trades_isolates_one_symbols_failure_from_the_rest_of_the_batch(self):
        class FlakyAnalyzer:
            def propose(self, symbol, market, news, account, *, context=None):
                if symbol == "BAD":
                    raise RuntimeError("simulated analyzer failure")
                return None

        class EmptyMarketData:
            def get_latest_bars(self, symbols):
                return {"bars": {symbol: {"c": 100.0} for symbol in symbols}}

            def get_news(self, symbols, limit=5):
                return {"news": []}

        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(tmp)
            audit = AuditDatabase(settings.db_path, settings.trading_log_path)
            agent = AITradingAgent(
                market_data=EmptyMarketData(),
                audit=audit,
                guardrails=settings.guardrails,
                analyzer=FlakyAnalyzer(),
            )
            skipped: list[dict[str, str]] = []

            proposals = agent.propose_trades(
                ["GOOD", "BAD"],
                account=AccountContext(equity=100_000, daily_realized_pnl=0, open_positions=[]),
                skipped_symbols=skipped,
            )

            self.assertEqual(proposals, [])
            self.assertEqual(len(skipped), 1)
            self.assertEqual(skipped[0]["symbol"], "BAD")
            self.assertIn("simulated analyzer failure", skipped[0]["reason"])

    def test_known_exchange_for_symbol_uses_company_master_not_the_llm_default(self):
        # 2026-08-13 hosted incident: OpenAIProposalAnalyzer.propose's prompt never asks the
        # model for `exchange` (see ai.py's field list), and TradeProposal.exchange defaults to
        # "NYSE" when unset -- so every equity proposal silently inherited that default
        # regardless of where the symbol is actually listed. Confirmed live: FRES (Fresnillo
        # plc, correctly tagged "LSE" in this system's own COMPANY_MASTER seed data) kept being
        # proposed with exchange="NYSE", routed to Alpaca (a US-only broker), and failed
        # asset_unavailable on every single evaluation for 4+ hours straight -- a permanent dead
        # end for any non-US symbol in the research watchlist, not a FRES-specific glitch.
        # Pulled out as its own pure, directly-testable method (mirrors this codebase's existing
        # pattern for gating logic, e.g. orchestrator._kraken_min_order_floor_notional) rather
        # than asserting through the full propose_trades -> intelligence -> validation chain,
        # which needs real market-signal richness unrelated to this specific fix.
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(tmp)
            InvestmentIntelligenceDatabase(settings.db_path).seed_initial_data()
            audit = AuditDatabase(settings.db_path, settings.trading_log_path)
            agent = AITradingAgent(
                market_data=None,
                audit=audit,
                guardrails=settings.guardrails,
                db_path=settings.db_path,
            )

            self.assertEqual(agent._known_exchange_for_symbol("FRES"), "LSE")
            self.assertEqual(agent._known_exchange_for_symbol("fres"), "LSE")
            # No COMPANY_MASTER row at all -- caller keeps TradeProposal's existing default,
            # unchanged behaviour for symbols this system has no exchange metadata for.
            self.assertIsNone(agent._known_exchange_for_symbol("ZZZNOTREAL"))

    def test_watchlist_philosophy_fit_is_read_from_the_watchlist_not_left_at_zero(self):
        # 2026-08-24 hosted finding, same class of bug as the exchange default above:
        # ai.py's prompt never asks the model for philosophy_fit, from_dict only keeps
        # fields the model returned, and the field defaults to 0.0 -- so every equity
        # proposal carried 0.0 while the crypto path sets it explicitly. Zero fails three
        # gates at once (philosophy_fit_below_auto_trade_minimum,
        # investment_policy_score_below_minimum, and investment_policy_status ->
        # due_diligence_incomplete), so Alpaca could never trade regardless of the idea.
        # Confirmed live: 14 fresh guardrail-passing equity recommendations at confidence
        # 0.85-0.87, all rejected for exactly those reasons, account 100% in cash -- while
        # the values sat in INVESTMENT_WATCHLIST and the app's own display layer already
        # joined them.
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(tmp)
            InvestmentIntelligenceDatabase(settings.db_path).seed_initial_data()
            audit = AuditDatabase(settings.db_path, settings.trading_log_path)
            agent = AITradingAgent(
                market_data=None,
                audit=audit,
                guardrails=settings.guardrails,
                db_path=settings.db_path,
            )
            with closing(sqlite3.connect(settings.db_path)) as conn:
                row = conn.execute(
                    """
                    SELECT cm.ticker, iw.current_investment_philosophy_fit
                    FROM INVESTMENT_WATCHLIST iw
                    JOIN COMPANY_MASTER cm ON cm.id = iw.company_id
                    WHERE iw.current_investment_philosophy_fit IS NOT NULL
                    LIMIT 1
                    """
                ).fetchone()
            self.assertIsNotNone(row, "seed data should carry at least one assessed company")
            ticker, expected = row

            # Stored qualitatively ("Strong") as often as numerically, which is why every
            # reader of this column goes through safe_score -- float() raises on real seed data.
            expected_score = safe_score(expected)
            self.assertIsNotNone(expected_score)
            self.assertAlmostEqual(agent._watchlist_philosophy_fit(ticker), expected_score)
            self.assertAlmostEqual(agent._watchlist_philosophy_fit(str(ticker).lower()), expected_score)
            # A company this system has never assessed must not auto-trade on an invented
            # score: None leaves TradeProposal's existing default in place.
            self.assertIsNone(agent._watchlist_philosophy_fit("ZZZNOTREAL"))

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
        # 2026-08-14: run_analysis now restricts equity candidates to exchanges Alpaca can
        # actually fill (NYSE/NASDAQ/AMEX/ARCA/OTC) -- the seed watchlist has 19 such
        # companies (COMPANY_MASTER also carries 31 non-US ones for a later broker), so a
        # limit of 30 is capped down to the 19 that actually match, not the full 30.
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(tmp)
            InvestmentIntelligenceDatabase(settings.db_path).seed_initial_data()

            result = LocalApiService(settings).run_analysis({"limit": 30})

            self.assertEqual(result["status"], "not_available")
            self.assertEqual(len(result["symbols"]), 19)

    def test_run_analysis_limit_zero_uses_the_real_default_not_one_symbol(self):
        """2026-08-14 incident: the scheduled equity research jobs (cli.py's
        _run_named_job) call run_analysis with limit=0 as their "no override" sentinel.
        _int_or_default(0, 30) legitimately returns 0 (0 parses fine, it's not a
        default-triggering failure), and the old `max(1, min(0, 30))` clamp collapsed
        that to exactly 1 -- every scheduled equity cycle silently researched only
        COMPANY_MASTER's single first row forever, never the intended full watchlist.
        limit=0 must behave like "use the real default of 30", not "use 1" -- capped here
        to the 19 seeded companies Alpaca can actually trade (see the sibling test above)."""
        with tempfile.TemporaryDirectory() as tmp:
            settings = settings_for(tmp)
            InvestmentIntelligenceDatabase(settings.db_path).seed_initial_data()

            result = LocalApiService(settings).run_analysis({"limit": 0})

            self.assertEqual(result["status"], "not_available")
            self.assertEqual(len(result["symbols"]), 19)

    def test_portfolio_never_leaks_a_raw_exception_to_the_founder(self):
        # AT-ED-011.7: portfolio() previously interpolated the raw exception straight into
        # Founder-facing fields (f"Not available - {exc}"). A failure at the database layer
        # could include a psycopg/sqlite3-compatibility exception's low-level wording (table
        # names, driver internals) - simulated here with a realistic example of exactly that.
        with tempfile.TemporaryDirectory() as tmp:
            settings = replace(settings_for(tmp), alpaca_api_key="key", alpaca_secret_key="secret")
            service = LocalApiService(settings)

            def _boom():
                raise RuntimeError('relation "performance_attribution" does not exist')

            service._broker_service._live_alpaca_portfolio = _boom

            result = service.portfolio("alpaca")

            for field in ("portfolio_value", "cash_available", "todays_pnl", "source"):
                self.assertNotIn("relation", result[field])
                self.assertNotIn("does not exist", result[field])
                self.assertTrue(result[field].startswith("Not available"))
            self.assertEqual(result["open_positions"], [])


if __name__ == "__main__":
    unittest.main()


class MacroContextBackendShapeTests(unittest.TestCase):
    """2026-08-24 hosted incident: _macro_context_available iterated a database row
    directly. Under SQLite a row is a tuple and iterating yields the three VALUES, so
    matching worked and every test passed. Under Postgres a row is HybridRow, a dict
    subclass, so iterating yields the three KEYS -- the haystack became the literal
    string "theme summary key_drivers", no company keyword could ever match, and every
    equity scored macro_status insufficient_data with macro_score 0.

    That single zero failed due diligence outright and dragged the seven-part investment
    score to 0.7622, under its 0.85 minimum -- so Alpaca could not place a trade at all,
    confirmed live on NVDA at 18:52 that day with correct sector data and a matching
    Technology theme sitting right there in the database.
    """

    class _DictRowConnection:
        """Rows shaped the way the Postgres adapter really returns them."""

        def __init__(self, company, themes):
            self._company = company
            self._themes = themes

        def execute(self, sql, params=()):
            from ai_trader.database import HybridRow

            if "COMPANY_MASTER" in sql:
                rows = [HybridRow(self._company)] if self._company else []
            else:
                rows = [HybridRow(theme) for theme in self._themes]

            class _Cursor:
                def __init__(self, rows):
                    self._rows = rows

                def fetchone(self):
                    return self._rows[0] if self._rows else None

                def fetchall(self):
                    return self._rows

                def __iter__(self):
                    return iter(self._rows)

            return _Cursor(rows)

    def test_macro_context_reads_theme_values_not_column_names(self):
        from ai_trader.foundation import _macro_context_available

        proposal = TradeProposal(
            symbol="NVDA", side="buy", entry_price=100.0, stop_loss=95.0, take_profit=110.0,
            position_size=10, risk_percentage=1.0, confidence_score=0.9,
            news_summary="n", market_sentiment_summary="m", technical_summary="t",
            plain_english_reasoning="r", asset_type="stock", exchange="NASDAQ",
        ).normalized()
        themes = [{
            "theme": "Technology",
            "summary": "Software, cloud and semiconductor demand is underpinned by AI infrastructure build-out.",
            "key_drivers": "AI infrastructure spending; semiconductor cycle.",
        }]
        conn = self._DictRowConnection({"sector": "Technology", "industry": "Semiconductors"}, themes)

        self.assertTrue(
            _macro_context_available(conn, proposal),
            "a Technology/Semiconductors company must match the Technology theme on either backend",
        )

    def test_macro_context_still_says_no_when_nothing_matches(self):
        from ai_trader.foundation import _macro_context_available

        proposal = TradeProposal(
            symbol="ZZZZ", side="buy", entry_price=100.0, stop_loss=95.0, take_profit=110.0,
            position_size=10, risk_percentage=1.0, confidence_score=0.9,
            news_summary="n", market_sentiment_summary="m", technical_summary="t",
            plain_english_reasoning="r", asset_type="stock", exchange="NASDAQ",
        ).normalized()
        themes = [{"theme": "Airlines", "summary": "Carrier demand.", "key_drivers": "Fuel prices."}]
        conn = self._DictRowConnection({"sector": "Aquaculture", "industry": "Salmon farming"}, themes)

        self.assertFalse(_macro_context_available(conn, proposal))


class AlpacaFractionalShareTests(unittest.TestCase):
    """2026-08-24: the first equity order this system ever got as far as submitting was
    rejected by Alpaca with 422 "fractional orders must be DAY orders", and the raised
    exception took the whole auto-execution job down with it -- FSLR had been approved
    cleanly 12 seconds earlier.

    Risk-based sizing produces fractional share counts naturally (5% of a $101k account
    in a ~$200 stock is 24.7 shares). Alpaca allows fractional quantities only on plain
    DAY orders: never with a bracket, never good-til-cancelled. Rounding down keeps the
    bracket, which is what the 2026-08-12 CSL incident bought -- exits that survive the
    close rather than expiring the same day and leaving a real position unprotected for
    a month.
    """

    class _RecordingClient(AlpacaPaperClient):
        def __init__(self):
            super().__init__(AlpacaCredentials(api_key="k", secret_key="s"))
            self.payloads = []

        def _request(self, method, path, *, payload=None, data_api=False):
            self.payloads.append(payload)
            return {"id": "order-1", "status": "accepted"}

    def test_a_fractional_size_is_rounded_down_to_whole_shares(self):
        client = self._RecordingClient()

        result = client.place_bracket_order(symbol="FSLR", side="buy", qty=24.73, stop_loss=180.0, take_profit=230.0)

        self.assertEqual(result["status"], "accepted")
        payload = client.payloads[0]
        self.assertEqual(payload["qty"], "24", "a fractional quantity cannot carry a bracket on Alpaca")
        self.assertEqual(payload["order_class"], "bracket")
        # The protective legs must still outlive the session.
        self.assertEqual(payload["time_in_force"], "gtc")

    def test_a_whole_size_is_unchanged(self):
        client = self._RecordingClient()

        client.place_bracket_order(symbol="NEE", side="buy", qty=40, stop_loss=60.0, take_profit=80.0)

        self.assertEqual(client.payloads[0]["qty"], "40")

    def test_under_one_share_is_refused_rather_than_submitted(self):
        """Rounding 0.6 shares up would exceed the risk budget; sending 0 would be
        rejected by Alpaca. Saying so plainly is the honest third option."""
        client = self._RecordingClient()

        result = client.place_bracket_order(symbol="BRK.A", side="buy", qty=0.6, stop_loss=1.0, take_profit=2.0)

        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["reason"], "below_one_whole_share")
        self.assertEqual(client.payloads, [], "nothing should reach Alpaca")


class AskEvidencePayloadTests(unittest.TestCase):
    """2026-08-26: every answer shipped the whole evidence context to the phone. Measured
    live, 73,100 bytes of evidence attached to a 1,594-byte answer -- 98% of the response,
    on every question, over mobile data, and Ask.js has never read a byte of it (it uses
    answer, note and model only).

    Kept available on request because it is genuinely useful when diagnosing an answer from
    a terminal; the fault was sending it to a phone that ignores it.
    """

    def test_the_evidence_blob_is_not_sent_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalApiService(settings_for(tmp))

            _, payload = service.post("/ask-ai-trader", {"question": "How are we doing?"})

            self.assertNotIn("evidence", payload)
            self.assertIn("answer", payload, "the answer itself must always be present")

    def test_the_evidence_blob_is_returned_when_explicitly_requested(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalApiService(settings_for(tmp))

            _, payload = service.post(
                "/ask-ai-trader", {"question": "How are we doing?", "include_evidence": True}
            )

            self.assertIn("evidence", payload)
            self.assertIn("latest_portfolio_snapshots", payload["evidence"])


class AskWithoutCachedPanelsTests(unittest.TestCase):
    """2026-08-26 Founder-reported: Ask replied "something went wrong reaching AI Trader"
    twice in a row while the backend answered the same question fine from a terminal.

    Cause: when no cached broker panels existed, the context put an explanatory STRING in
    broker_panels. Every consumer iterates that field expecting broker dicts, so the string
    was iterated character by character and "L".get(...) raised AttributeError -- a 500 from
    the endpoint, surfaced to the Founder as a vague network-sounding failure.

    The honesty was right and the type was wrong. Panels stay a list; the explanation lives
    in its own field where nothing will iterate it.
    """

    def test_asking_without_cached_panels_still_answers(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalApiService(settings_for(tmp))

            status, payload = service.post("/ask-ai-trader", {"question": "Why no Kraken trades today?"})

            self.assertEqual(status, 200)
            self.assertTrue(payload.get("answer"))

    def test_broker_panels_is_always_a_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalApiService(settings_for(tmp))

            context = service._ask_ai_context(deadline=time.monotonic() + 40.0)

            self.assertIsInstance(context["broker_panels"], list)
            # Absent panels are still said out loud -- just somewhere type-safe.
            self.assertIn("were not refreshed", str(context["broker_panels_note"]))
