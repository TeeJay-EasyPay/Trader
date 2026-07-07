import sqlite3
import sys
import tempfile
import time
import unittest
from contextlib import closing
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.benchmark import BenchmarkIntelligenceDatabase
from ai_trader.broker_adapters import AlpacaBrokerAdapter, InteractiveBrokersAdapter, KrakenAdapter, SaxoAdapter
from ai_trader.briefing import generate_session_brief
from ai_trader.intelligence import InvestmentIntelligenceDatabase
from ai_trader.models import AccountContext, AutoTradeConfig, GuardrailConfig, OrderRequest, Position, TradeProposal, utc_now_iso
from ai_trader.operational import initialize_operational_schema
from ai_trader.orchestrator import InvestmentOrchestrator, OrchestratorContext
from ai_trader.scheduler import ResearchScheduler


def seed_due_diligence_context(db_path: Path) -> None:
    """Gives the default AAPL test proposal real macro (market theme) and behavioural
    (benchmark trader) context so due diligence completes instead of insufficient_data -
    matching a genuinely well-researched trade rather than papering over the check."""
    InvestmentIntelligenceDatabase(db_path)
    BenchmarkIntelligenceDatabase(db_path)
    now = utc_now_iso()
    today = date.today().isoformat()
    with closing(sqlite3.connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO COMPANY_MASTER (company_name, ticker, exchange, sector, industry, last_updated, created_at, updated_at)
                VALUES ('Apple Inc', 'AAPL', 'NASDAQ', 'Technology', 'Consumer Electronics', ?, ?, ?)
                """,
                (now, now, now),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO MARKET_THEMES (theme, summary, key_drivers, last_updated, created_at, updated_at)
                VALUES ('Technology Sector Growth', 'Technology adoption continues.', 'Technology demand', ?, ?, ?)
                """,
                (now, now, now),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO BENCHMARK_TRADERS (trader_name, platform, created_date, last_updated)
                VALUES ('Test Trader', 'Test Platform', ?, ?)
                """,
                (now, now),
            )
            trader_id = conn.execute(
                "SELECT trader_id FROM BENCHMARK_TRADERS WHERE trader_name = 'Test Trader'"
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO BENCHMARK_DAILY_RESEARCH (research_date, trader_id, source, created_date) VALUES (?, ?, 'test', ?)",
                (today, trader_id, now),
            )


MARKET_TIME = datetime(2026, 7, 2, 10, 0, tzinfo=ZoneInfo("America/New_York"))


class FakeAdapter:
    name = "fake"

    def __init__(self, *, market_open=True, asset_available=True):
        self.market_open = market_open
        self.asset_available = asset_available
        self.orders = []

    def get_account(self):
        return {"status": "ACTIVE"}

    def get_positions(self):
        return []

    def get_orders(self):
        return self.orders

    def get_supported_markets(self):
        return ["NYSE"]

    def get_supported_assets(self):
        return ["stock"]

    def is_asset_available(self, symbol, exchange, asset_type):
        return self.asset_available

    def is_market_open(self, exchange):
        return self.market_open

    def place_order(self, order_request):
        return self.place_bracket_order(order_request)

    def place_bracket_order(self, order_request):
        order = {"id": f"fake-{len(self.orders) + 1}", "status": "accepted", "symbol": order_request.symbol}
        self.orders.append(order)
        return order

    def cancel_order(self, order_id):
        return {"id": order_id, "status": "cancel_requested"}

    def close_position(self, symbol):
        return {"symbol": symbol, "status": "close_requested"}


class FakeAlpacaClient:
    def place_bracket_order(self, *, symbol, side, qty, stop_loss, take_profit):
        return {"id": "alpaca-test", "status": "accepted", "symbol": symbol, "side": side, "qty": qty}


def proposal(**overrides):
    data = {
        "symbol": "AAPL",
        "side": "buy",
        "entry_price": 100.0,
        "stop_loss": 97.0,
        "take_profit": 106.0,
        "position_size": 0.2,
        "risk_percentage": 0.000006,
        "confidence_score": 0.9,
        "philosophy_fit": 0.9,
        "asset_type": "stock",
        "exchange": "NYSE",
        "news_summary": "news",
        "market_sentiment_summary": "sentiment",
        "technical_summary": "technical",
        "plain_english_reasoning": "reason",
        "ai_guardrails_passed": True,
    }
    data.update(overrides)
    return TradeProposal(**data).normalized()


def context(auto_enabled=True):
    return OrchestratorContext(
        account=AccountContext(equity=100_000, daily_realized_pnl=0, open_positions=[]),
        auto_trade=AutoTradeConfig(enabled=auto_enabled),
        guardrails=GuardrailConfig(min_confidence_score=0.65),
        now=MARKET_TIME,
    )


class OrchestratorTests(unittest.TestCase):
    def run_decision(self, item, adapter=None, auto_enabled=True):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            seed_due_diligence_context(db_path)
            orchestrator = InvestmentOrchestrator(db_path=db_path, adapters=[adapter or FakeAdapter()])
            return orchestrator.evaluate_recommendation(item, context(auto_enabled=auto_enabled), auto_execute=True)

    def test_routes_executable_auto_trade_to_adapter(self):
        adapter = FakeAdapter()
        decision = self.run_decision(proposal(), adapter=adapter)

        self.assertEqual(decision.decision, "approved")
        self.assertEqual(decision.selected_broker, "fake")
        self.assertEqual(adapter.orders[0]["symbol"], "AAPL")

    def test_market_closed_rejection(self):
        decision = self.run_decision(proposal(), adapter=FakeAdapter(market_open=False))

        self.assertEqual(decision.decision, "rejected")
        self.assertIn("market_closed", decision.rejection_reason)

    def test_asset_unavailable_rejection(self):
        decision = self.run_decision(proposal(), adapter=FakeAdapter(asset_available=False))

        self.assertEqual(decision.decision, "rejected")
        self.assertIn("asset_unavailable", decision.rejection_reason)

    def test_confidence_below_85_rejection(self):
        decision = self.run_decision(proposal(confidence_score=0.84))

        self.assertEqual(decision.decision, "rejected")
        self.assertIn("confidence_below_auto_trade_minimum", decision.rejection_reason)

    def test_missing_stop_loss_rejection(self):
        decision = self.run_decision(proposal(stop_loss=0))

        self.assertEqual(decision.decision, "rejected")
        self.assertIn("stop_loss_mandatory", decision.rejection_reason)

    def test_max_stop_loss_breach_rejection(self):
        decision = self.run_decision(proposal(stop_loss=94.0))

        self.assertEqual(decision.decision, "rejected")
        self.assertIn("max_stop_loss_pct_exceeded", decision.rejection_reason)

    def test_auto_paper_trading_disabled_requires_manual_approval(self):
        decision = self.run_decision(proposal(), auto_enabled=False)

        self.assertEqual(decision.decision, "manual_approval_required")
        self.assertIsNone(decision.rejection_reason)

    def test_weekly_loss_limit_blocks_new_trades(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            seed_due_diligence_context(db_path)
            orchestrator = InvestmentOrchestrator(db_path=db_path, adapters=[FakeAdapter()])
            initialize_operational_schema(db_path)
            with closing(sqlite3.connect(db_path)) as conn:
                with conn:
                    conn.execute(
                        """
                        INSERT INTO PORTFOLIO_SNAPSHOTS (
                            created_at, broker, exchange, cash, portfolio_value,
                            open_positions_count, day_pnl, week_pnl, month_pnl, notes
                        ) VALUES (?, 'fake', 'Fake', 100000, 100000, 0, -100, -8000, -100, 'test')
                        """,
                        (utc_now_iso(),),
                    )
            decision = orchestrator.evaluate_recommendation(proposal(), context(), auto_execute=True)

            self.assertEqual(decision.decision, "rejected")
            self.assertIn("maximum_weekly_loss_exceeded", decision.rejection_reason)

    def test_portfolio_exposure_limit_blocks_new_trades(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            seed_due_diligence_context(db_path)
            orchestrator = InvestmentOrchestrator(db_path=db_path, adapters=[FakeAdapter()])
            heavy_context = OrchestratorContext(
                account=AccountContext(
                    equity=100_000,
                    daily_realized_pnl=0,
                    open_positions=[Position(symbol="MSFT", qty=1, market_value=90_000)],
                ),
                auto_trade=AutoTradeConfig(enabled=True),
                guardrails=GuardrailConfig(min_confidence_score=0.65),
                now=MARKET_TIME,
            )
            decision = orchestrator.evaluate_recommendation(proposal(), heavy_context, auto_execute=True)

            self.assertEqual(decision.decision, "rejected")
            self.assertIn("maximum_concurrent_exposure_exceeded", decision.rejection_reason)

    def test_approve_and_execute_style_call_blocks_duplicate_order_intent(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            seed_due_diligence_context(db_path)
            adapter = FakeAdapter()
            orchestrator = InvestmentOrchestrator(db_path=db_path, adapters=[adapter])
            p = proposal()

            first = orchestrator.evaluate_recommendation(p, context(), auto_execute=True)
            second = orchestrator.evaluate_recommendation(p, context(), auto_execute=True)

            self.assertEqual(first.decision, "approved")
            self.assertEqual(second.decision, "rejected")
            self.assertIn("duplicate_order_intent", second.rejection_reason)
            self.assertEqual(len(adapter.orders), 1)

    def test_placeholder_adapters_are_not_configured(self):
        for adapter in [InteractiveBrokersAdapter(), SaxoAdapter(), KrakenAdapter()]:
            self.assertEqual(adapter.place_order(OrderRequest("AAPL", "buy", 1, "stock", "NYSE", 97, 106))["status"], "not_configured")

    def test_alpaca_adapter_uses_standard_bracket_interface(self):
        adapter = AlpacaBrokerAdapter(FakeAlpacaClient())
        result = adapter.place_bracket_order(OrderRequest("AAPL", "buy", 1, "stock", "NYSE", 97, 106))

        self.assertEqual(result["status"], "accepted")
        self.assertEqual(result["symbol"], "AAPL")

    def test_morning_and_evening_briefs_are_stored(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            orchestrator = InvestmentOrchestrator(db_path=db_path, adapters=[FakeAdapter()])
            orchestrator.evaluate_recommendation(proposal(), context(), auto_execute=True)

            morning = generate_session_brief(db_path=db_path, output_dir=Path(tmp), brief_type="morning", briefing_date=MARKET_TIME.date())
            evening = generate_session_brief(db_path=db_path, output_dir=Path(tmp), brief_type="evening", briefing_date=MARKET_TIME.date())

            self.assertIn("Morning Brief", morning)
            self.assertIn("Evening Brief", evening)
            with closing(sqlite3.connect(db_path)) as conn:
                count = conn.execute("SELECT COUNT(*) FROM DAILY_BRIEFS").fetchone()[0]
            self.assertEqual(count, 2)

    def test_research_scheduler_runs_one_cycle(self):
        class Service:
            def __init__(self):
                self.calls = 0

            def run_analysis(self, body):
                self.calls += 1
                return {"status": "completed", "limit": body["limit"]}

        service = Service()
        result = ResearchScheduler(service).run_once(limit=7).to_dict()

        self.assertEqual(result["result"]["status"], "completed")
        self.assertEqual(result["result"]["limit"], 7)
        self.assertIsNotNone(result["next_run_at"])
        self.assertEqual(service.calls, 1)

    def test_research_scheduler_background_runs_without_blocking(self):
        class Service:
            def __init__(self):
                self.calls = 0

            def run_analysis(self, body):
                self.calls += 1
                return {"status": "completed"}

        service = Service()
        stop = ResearchScheduler(service, interval_minutes=1).start_background(limit=1)
        time.sleep(0.1)
        stop.set()

        self.assertGreaterEqual(service.calls, 1)


if __name__ == "__main__":
    unittest.main()
