import io
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from contextlib import closing, redirect_stdout
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.benchmark import BenchmarkIntelligenceDatabase
from ai_trader.broker_adapters import AlpacaBrokerAdapter, InteractiveBrokersAdapter, KrakenAdapter, SaxoAdapter
from ai_trader.briefing import generate_session_brief
from ai_trader.intelligence import InvestmentIntelligenceDatabase
from ai_trader.models import AccountContext, AutoTradeConfig, GuardrailConfig, OrderRequest, Position, TradeProposal, utc_now_iso
from ai_trader.foundation import initialize_foundation_schema
from ai_trader.operational import initialize_operational_schema
from ai_trader.kraken_reconciliation import set_reconciliation_hold
from ai_trader.orchestrator import InvestmentOrchestrator, OrchestratorContext, _snapshot_equity_basis_matches_context, _kraken_min_order_floor_notional
from ai_trader.scheduler import ResearchScheduler
from ai_trader.sprint6 import apply_founder_strategy_authorization, seed_default_strategy_registry, set_kill_switch


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
    # A synthetic test double for exercising the orchestrator's own allocation/guardrail logic in
    # isolation - it is not a registered broker in STRATEGY_MATURITY_REGISTRY's permitted_brokers,
    # so routing it through the real sprint6 production governance chain would only ever be
    # rejected as "not permitted for broker fake", not exercise anything these tests are about.
    requires_production_governance = False

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

    def test_broker_adapters_require_production_governance_by_default(self):
        # Every real and placeholder adapter must default to requiring governance; a broker can
        # only skip it by explicitly declaring requires_production_governance = False. This is
        # the regression guard for orchestrator.py no longer using a hardcoded {"alpaca","kraken"}
        # name allowlist.
        for adapter in [AlpacaBrokerAdapter(FakeAlpacaClient()), InteractiveBrokersAdapter(), SaxoAdapter(), KrakenAdapter()]:
            self.assertTrue(adapter.requires_production_governance, f"{adapter.name} must default to requiring governance")

    def test_a_hypothetical_new_broker_still_routes_through_governance_by_default(self):
        # Simulates the exact scenario the fix closes: a new adapter implementing the Protocol
        # correctly, with nobody remembering to add its name anywhere - it must still be routed
        # through Strategy Entitlement / Portfolio Manager / Risk Sentinel, and since it is not a
        # permitted broker in STRATEGY_MATURITY_REGISTRY, it must be rejected, not silently
        # auto-approved the way a pre-fix ungoverned broker would have been.
        class HypotheticalNewAdapter(FakeAdapter):
            name = "hypothetical_new_broker"
            requires_production_governance = True

        decision = self.run_decision(proposal(), adapter=HypotheticalNewAdapter())
        self.assertEqual(decision.decision, "rejected")
        self.assertIn("not permitted for broker hypothetical_new_broker", decision.rejection_reason)

    def test_kraken_autonomous_execution_requires_founder_authorization_end_to_end(self):
        # End-to-end proof for the AT-ED-002 "restore and verify Kraken governed live trading"
        # requirement, exercising the exact same three env vars render.yaml now enables
        # (KRAKEN_TRADING_ENABLED/KRAKEN_LIVE_TRADING_APPROVED/KRAKEN_SUBMIT_REAL_ORDERS - see
        # foundation._kraken_crypto_policy_approved()) together with the registry authorization.
        # orchestrator.py routes every non-Alpaca broker through pre_execution_decision_packet
        # with mode="micro_live". Before apply_founder_strategy_authorization() has run, this must
        # reject the proposal outright (autonomous Kraken execution is not silently permitted);
        # after it has run, for exactly the founder-authorized strategy, the same proposal must be
        # approved and routed to the broker.
        class FakeKrakenAdapter(FakeAdapter):
            name = "kraken"
            requires_production_governance = True

            def get_supported_assets(self):
                return ["crypto"]

            def get_supported_markets(self):
                return ["KRAKEN"]

        env_keys = ("KRAKEN_TRADING_ENABLED", "KRAKEN_LIVE_TRADING_APPROVED", "KRAKEN_SUBMIT_REAL_ORDERS")
        previous = {key: os.environ.get(key) for key in env_keys}
        try:
            for key in env_keys:
                os.environ[key] = "true"
            with tempfile.TemporaryDirectory() as tmp:
                db_path = Path(tmp) / "audit.sqlite3"
                seed_due_diligence_context(db_path)
                seed_default_strategy_registry(db_path)
                initialize_foundation_schema(db_path)
                with closing(sqlite3.connect(db_path)) as conn:
                    with conn:
                        conn.execute(
                            "INSERT INTO CRYPTO_MASTER (symbol, name, category, source, active, created_at, updated_at) "
                            "VALUES ('BTC', 'Bitcoin', 'layer1', 'test', 1, ?, ?)",
                            (utc_now_iso(), utc_now_iso()),
                        )
                crypto_proposal = proposal(
                    symbol="BTC", asset_type="crypto", exchange="KRAKEN", strategy_id="crypto_trend_following_2r",
                )
                adapter = FakeKrakenAdapter()
                orchestrator = InvestmentOrchestrator(db_path=db_path, adapters=[adapter])

                # This proposal also fails unrelated pre-existing gates in a from-scratch test
                # database (no due-diligence/investment-score history, no reconciliation state
                # yet) - those are real, legitimate, separate governance checks, not part of what
                # this test isolates. What this test proves specifically: the "not permitted for
                # micro_live execution" strategy-entitlement failure is present before
                # authorization and gone after it - the exact mechanism that would otherwise
                # silently block every autonomous Kraken order regardless of the render.yaml
                # enablement flags.
                before = orchestrator.evaluate_recommendation(crypto_proposal, context(), auto_execute=True)
                self.assertEqual(before.decision, "rejected")
                self.assertIn("not permitted for micro_live execution", before.rejection_reason)
                self.assertEqual(len(adapter.orders), 0)

                apply_founder_strategy_authorization(
                    db_path,
                    strategy_id="crypto_trend_following_2r",
                    target_stage="Micro Live",
                    additional_modes=["micro_live"],
                    reason="test",
                )

                after = orchestrator.evaluate_recommendation(crypto_proposal, context(), auto_execute=True)
                self.assertNotIn("not permitted for micro_live execution", after.rejection_reason or "")
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_kraken_reconciliation_hold_blocks_new_entries_end_to_end(self):
        # Phase 8 safety characterization (ChatGPT/Founder-authorized directive,
        # architecture/AI_TRADER_MODULARISATION_ARCHITECTURE_2026-08-02.md, category 2:
        # "remains blocked by the reconciliation hold where applicable") -- proves
        # orchestrator.evaluate_recommendation genuinely consults KRAKEN_RECONCILIATION_
        # CONTROL.hold_new_entries for Kraken proposals specifically (not just displayed on
        # a status endpoint), and that lifting the hold removes that specific failure
        # reason. Mirrors the existing kill-switch and founder-authorization end-to-end
        # tests above: proves the presence/absence of one specific mechanism's failure
        # reason, not a fully-approved outcome, since a from-scratch test database fails
        # several unrelated, legitimate gates regardless (due diligence, investment score).
        class FakeKrakenAdapter(FakeAdapter):
            name = "kraken"
            requires_production_governance = True

            def get_supported_assets(self):
                return ["crypto"]

            def get_supported_markets(self):
                return ["KRAKEN"]

        env_keys = ("KRAKEN_TRADING_ENABLED", "KRAKEN_LIVE_TRADING_APPROVED", "KRAKEN_SUBMIT_REAL_ORDERS")
        previous = {key: os.environ.get(key) for key in env_keys}
        try:
            for key in env_keys:
                os.environ[key] = "true"
            with tempfile.TemporaryDirectory() as tmp:
                db_path = Path(tmp) / "audit.sqlite3"
                seed_due_diligence_context(db_path)
                seed_default_strategy_registry(db_path)
                initialize_foundation_schema(db_path)
                apply_founder_strategy_authorization(
                    db_path,
                    strategy_id="crypto_trend_following_2r",
                    target_stage="Micro Live",
                    additional_modes=["micro_live"],
                    reason="test",
                )
                with closing(sqlite3.connect(db_path)) as conn:
                    with conn:
                        conn.execute(
                            "INSERT INTO CRYPTO_MASTER (symbol, name, category, source, active, created_at, updated_at) "
                            "VALUES ('BTC', 'Bitcoin', 'layer1', 'test', 1, ?, ?)",
                            (utc_now_iso(), utc_now_iso()),
                        )
                crypto_proposal = proposal(
                    symbol="BTC", asset_type="crypto", exchange="KRAKEN", strategy_id="crypto_trend_following_2r",
                )
                adapter = FakeKrakenAdapter()
                orchestrator = InvestmentOrchestrator(db_path=db_path, adapters=[adapter])

                # KRAKEN_RECONCILIATION_CONTROL defaults to hold_new_entries=True (fail-closed
                # until explicitly verified -- see test_kraken_reconciliation.py's
                # test_default_control_pauses_entries_and_failed_verification_cannot_resume),
                # so establish an explicit "verification already complete" baseline first to
                # isolate this test to the hold mechanism specifically, not the safe default.
                set_reconciliation_hold(db_path, active=False, reason="test: verification complete", status="verified")

                before = orchestrator.evaluate_recommendation(crypto_proposal, context(), auto_execute=True)
                self.assertNotIn("kraken_reconciliation_hold", before.rejection_reason or "")

                set_reconciliation_hold(
                    db_path, active=True, reason="test: unmatched Kraken history under review", status="verification_required"
                )

                held = orchestrator.evaluate_recommendation(crypto_proposal, context(), auto_execute=True)
                self.assertEqual(held.decision, "rejected")
                self.assertIn("kraken_reconciliation_hold", held.rejection_reason)
                self.assertEqual(len(adapter.orders), 0)

                set_reconciliation_hold(db_path, active=False, reason="test: verification complete", status="verified")

                resumed = orchestrator.evaluate_recommendation(crypto_proposal, context(), auto_execute=True)
                self.assertNotIn("kraken_reconciliation_hold", resumed.rejection_reason or "")
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_active_kill_switch_prevents_order_placement_end_to_end(self):
        # Stage 0 safety-unknown resolution (2026-08-02 architecture discovery pack flagged
        # this as unconfirmed either way): proves KILL_SWITCH_STATE is genuinely consulted
        # before a live order reaches the broker, not just displayed on a status endpoint.
        # The real chain: sprint6.production_risk_sentinel_decision reads KILL_SWITCH_STATE
        # and returns decision="blocked" when active -> pre_execution_decision_packet adds
        # "risk_sentinel_blocked: kill_switch_active: ..." to its reasons -> orchestrator.
        # evaluate_recommendation extends its own failures list with those reasons -> the
        # order is never submitted to the adapter.
        class FakeKrakenAdapter(FakeAdapter):
            name = "kraken"
            requires_production_governance = True

            def get_supported_assets(self):
                return ["crypto"]

            def get_supported_markets(self):
                return ["KRAKEN"]

        env_keys = ("KRAKEN_TRADING_ENABLED", "KRAKEN_LIVE_TRADING_APPROVED", "KRAKEN_SUBMIT_REAL_ORDERS")
        previous = {key: os.environ.get(key) for key in env_keys}
        try:
            for key in env_keys:
                os.environ[key] = "true"
            with tempfile.TemporaryDirectory() as tmp:
                db_path = Path(tmp) / "audit.sqlite3"
                seed_due_diligence_context(db_path)
                seed_default_strategy_registry(db_path)
                initialize_foundation_schema(db_path)
                apply_founder_strategy_authorization(
                    db_path,
                    strategy_id="crypto_trend_following_2r",
                    target_stage="Micro Live",
                    additional_modes=["micro_live"],
                    reason="test",
                )
                with closing(sqlite3.connect(db_path)) as conn:
                    with conn:
                        conn.execute(
                            "INSERT INTO CRYPTO_MASTER (symbol, name, category, source, active, created_at, updated_at) "
                            "VALUES ('BTC', 'Bitcoin', 'layer1', 'test', 1, ?, ?)",
                            (utc_now_iso(), utc_now_iso()),
                        )
                crypto_proposal = proposal(
                    symbol="BTC", asset_type="crypto", exchange="KRAKEN", strategy_id="crypto_trend_following_2r",
                )
                adapter = FakeKrakenAdapter()
                orchestrator = InvestmentOrchestrator(db_path=db_path, adapters=[adapter])

                # Baseline: kill switch not yet activated. Whatever this from-scratch test
                # database does or doesn't approve, it must not be blocked *for kill-switch
                # reasons specifically* - proves the reason only appears because of the switch.
                before = orchestrator.evaluate_recommendation(crypto_proposal, context(), auto_execute=True)
                self.assertNotIn("kill_switch_active", before.rejection_reason or "")

                set_kill_switch(db_path, active=True, reason="test emergency stop")

                after = orchestrator.evaluate_recommendation(crypto_proposal, context(), auto_execute=True)
                self.assertEqual(after.decision, "rejected")
                self.assertIn("kill_switch_active", after.rejection_reason)
                self.assertEqual(len(adapter.orders), 0)
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

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


class EquityBasisGuardTests(unittest.TestCase):
    """Stage 0.4 (architecture/AI_TRADER_MODULARISATION_ARCHITECTURE_2026-08-02.md):
    _snapshot_equity_basis_matches_context is the guard orchestrator.py's
    evaluate_recommendation relies on to stop a Kraken whole-account PORTFOLIO_SNAPSHOTS
    figure (which includes pre-existing personal holdings) from being compared against
    the AI's isolated allocation equity. Hosted evidence (2026-08-01) showed this
    mismatch producing a standing false-positive maximum_weekly_loss_exceeded on every
    Kraken candidate before the guard existed; this pins the fix in place directly."""

    def test_whole_account_snapshot_against_isolated_equity_does_not_match(self):
        # £9000 whole-Kraken-account snapshot vs a £100 isolated AI allocation --
        # exactly the order-of-magnitude mismatch that caused the false positive.
        self.assertFalse(_snapshot_equity_basis_matches_context(9000.0, 100.0))

    def test_snapshot_on_the_same_basis_as_context_matches(self):
        # A snapshot genuinely captured on the same (isolated) basis as the current
        # context equity must still be usable by the weekly/monthly/drawdown checks.
        self.assertTrue(_snapshot_equity_basis_matches_context(95.0, 100.0))

    def test_zero_or_negative_account_equity_never_matches(self):
        self.assertFalse(_snapshot_equity_basis_matches_context(100.0, 0.0))
        self.assertFalse(_snapshot_equity_basis_matches_context(100.0, -5.0))


class KrakenMinOrderFloorTests(unittest.TestCase):
    """Founder investigation (2026-08-05/06): every Kraken order attempt was rejected by the
    exchange for "min_order_amount_not_met". Root cause: calculate_capital_allocation's
    risk-based sizing (5% of the small isolated Kraken allocation, e.g. £38.23) produced a
    per-trade notional (~£1.91) smaller than this deployment's configured
    KRAKEN_MIN_ORDER_GBP - a real, checkable-in-advance value, submitted anyway. Each failed
    attempt then permanently locked that proposal_id, compounding the problem every cycle.
    _kraken_min_order_floor_notional is the fix: pins its exact behaviour in isolation, without
    needing to stand up the full governance chain."""

    def test_a_positive_but_undersized_notional_is_raised_to_the_exchange_minimum(self):
        # The exact real numbers observed in hosted evidence: £1.91163 risk-sized notional,
        # £38.23 account equity, a configured £2.00 exchange minimum.
        self.assertEqual(
            _kraken_min_order_floor_notional(approved_notional=1.91163, account_equity=38.23, min_notional=2.0),
            2.0,
        )

    def test_a_notional_already_at_or_above_the_minimum_is_never_changed(self):
        self.assertEqual(
            _kraken_min_order_floor_notional(approved_notional=5.0, account_equity=38.23, min_notional=2.0),
            5.0,
        )

    def test_a_genuinely_zero_or_rejected_notional_is_never_raised_into_a_fabricated_trade(self):
        self.assertEqual(
            _kraken_min_order_floor_notional(approved_notional=0.0, account_equity=38.23, min_notional=2.0),
            0.0,
        )

    def test_never_raises_past_what_the_account_can_actually_afford(self):
        # An account with less equity than the exchange minimum must never have a trade
        # fabricated for it just to clear that minimum.
        self.assertEqual(
            _kraken_min_order_floor_notional(approved_notional=0.5, account_equity=1.5, min_notional=2.0),
            0.5,
        )


class KrakenExchangeMinimumOrderTests(unittest.TestCase):
    """2026-08-10 hosted incident: a proposal correctly floored to KRAKEN_MIN_ORDER_GBP by
    the check above still failed at the exchange itself with "EGeneral:Invalid arguments:
    volume minimum not met" -- the flat GBP guess cleared, but Kraken's real per-pair
    minimum (queried live via pair_minimum_notional) was higher. Proves the exchange's
    real minimum is consulted and, when it is the binding constraint, either raises the
    order to it (when affordable) or fails cleanly before ever reaching the broker."""

    class FakeKrakenAdapter(FakeAdapter):
        name = "kraken"
        requires_production_governance = False

        def __init__(self, *, exchange_minimum):
            super().__init__()
            self._exchange_minimum = exchange_minimum
            self.submitted_requests = []

        def get_supported_assets(self):
            return ["crypto"]

        def get_supported_markets(self):
            return ["KRAKEN"]

        def pair_minimum_notional(self, pair, price):
            return self._exchange_minimum

        def place_bracket_order(self, order_request):
            self.submitted_requests.append(order_request)
            return super().place_bracket_order(order_request)

    def _small_equity_context(self):
        return OrchestratorContext(
            account=AccountContext(equity=38.23, daily_realized_pnl=0, open_positions=[]),
            auto_trade=AutoTradeConfig(enabled=True),
            guardrails=GuardrailConfig(min_confidence_score=0.65),
            now=MARKET_TIME,
        )

    def _small_crypto_proposal(self):
        return proposal(symbol="XLM", asset_type="crypto", exchange="KRAKEN", entry_price=0.12, stop_loss=0.11, position_size=16)

    def test_allocation_is_raised_to_the_real_exchange_minimum_when_affordable(self):
        # A from-scratch test database fails several unrelated, legitimate gates regardless
        # (due diligence, investment score, crypto universe/policy, reconciliation hold -- see
        # the founder-authorization end-to-end test above for the same caveat). What this
        # isolates: the new exchange-minimum failure reason must NOT be one of them, proving
        # the real exchange minimum was successfully applied as a raise rather than a rejection.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            adapter = self.FakeKrakenAdapter(exchange_minimum=3.5)
            orchestrator = InvestmentOrchestrator(db_path=db_path, adapters=[adapter])

            captured = io.StringIO()
            with redirect_stdout(captured):
                decision = orchestrator.evaluate_recommendation(self._small_crypto_proposal(), self._small_equity_context(), auto_execute=True)

            self.assertNotIn("kraken_exchange_minimum_not_tradeable_at_current_limits", decision.rejection_reason or "")
            self.assertIn("stage=kraken_exchange_min_order_floor_applied pair=XLMGBP", captured.getvalue())
            self.assertIn("floored_to=3.5", captured.getvalue())

    def test_a_real_exchange_minimum_beyond_the_configured_ceiling_fails_cleanly_instead_of_being_submitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            # KRAKEN_MAX_ORDER_GBP defaults to 5.0 -- a "minimum" this large could never be
            # traded within this deployment's configured ceiling regardless of equity.
            adapter = self.FakeKrakenAdapter(exchange_minimum=999.0)
            orchestrator = InvestmentOrchestrator(db_path=db_path, adapters=[adapter])

            decision = orchestrator.evaluate_recommendation(self._small_crypto_proposal(), self._small_equity_context(), auto_execute=True)

            self.assertEqual(decision.decision, "rejected")
            self.assertIn("kraken_exchange_minimum_not_tradeable_at_current_limits", decision.rejection_reason)
            self.assertEqual(len(adapter.submitted_requests), 0)

    def test_a_real_exchange_minimum_at_or_below_what_was_already_approved_changes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            adapter = self.FakeKrakenAdapter(exchange_minimum=0.01)
            orchestrator = InvestmentOrchestrator(db_path=db_path, adapters=[adapter])

            decision = orchestrator.evaluate_recommendation(self._small_crypto_proposal(), self._small_equity_context(), auto_execute=True)

            # A negligible exchange minimum must never be the reason for a rejection --
            # unaffected, this new check simply never fires.
            self.assertNotIn("kraken_exchange_minimum_not_tradeable_at_current_limits", decision.rejection_reason or "")


class KrakenPairMinimumNotionalTests(unittest.TestCase):
    """2026-08-10 hosted incident: KRAKEN_MIN_ORDER_GBP is one flat guess applied to every
    pair; Kraken's real minimum order size is published per-pair via the public
    AssetPairs endpoint and can be higher. pair_minimum_notional asks the exchange
    directly instead of guessing, and never re-asks for a pair it has already learned."""

    def test_uses_costmin_when_it_is_the_larger_of_the_two_published_minimums(self):
        adapter = KrakenAdapter()
        # ordermin * price = 30 * 0.01 = 0.30, smaller than costmin here.
        adapter._public_request = lambda path: {"result": {"XLMGBP": {"costmin": "3.50", "ordermin": "30"}}}

        self.assertEqual(adapter.pair_minimum_notional("XLMGBP", price=0.01), 3.5)

    def test_falls_back_to_ordermin_times_price_when_no_costmin_is_published(self):
        adapter = KrakenAdapter()
        adapter._public_request = lambda path: {"result": {"XLMGBP": {"ordermin": "30"}}}

        self.assertAlmostEqual(adapter.pair_minimum_notional("XLMGBP", price=0.12), 3.6)

    def test_uses_ordermin_times_price_when_it_is_larger_than_costmin(self):
        # 2026-08-13 hosted incident, reproduced directly: Kraken enforces costmin and
        # ordermin simultaneously, not as alternatives. XLMGBP really publishes
        # costmin=0.43 alongside ordermin=30 -- at a real market price, 30 XLM units is
        # worth far more than GBP 0.43, so ordermin*price is the actual binding
        # constraint. Using costmin alone (the pre-fix behaviour) floored an order below
        # what Kraken would accept, and the exchange rejected it with "volume minimum
        # not met" despite passing every governance check.
        adapter = KrakenAdapter()
        adapter._public_request = lambda path: {"result": {"XLMGBP": {"costmin": "0.43", "ordermin": "30"}}}

        self.assertAlmostEqual(adapter.pair_minimum_notional("XLMGBP", price=0.1187), 30 * 0.1187)

    def test_caches_so_the_exchange_is_only_asked_once_per_pair(self):
        calls = []

        def fake_public_request(path):
            calls.append(path)
            return {"result": {"XLMGBP": {"costmin": "3.5"}}}

        adapter = KrakenAdapter()
        adapter._public_request = fake_public_request

        adapter.pair_minimum_notional("XLMGBP", price=0.12)
        adapter.pair_minimum_notional("XLMGBP", price=0.12)

        self.assertEqual(len(calls), 1)

    def test_a_network_or_parsing_failure_returns_none_instead_of_raising(self):
        def raise_error(path):
            raise RuntimeError("EQuery:Unknown asset pair")

        adapter = KrakenAdapter()
        adapter._public_request = raise_error

        self.assertIsNone(adapter.pair_minimum_notional("NOTAPAIR", price=1.0))


if __name__ == "__main__":
    unittest.main()
