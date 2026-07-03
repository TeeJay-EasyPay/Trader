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
