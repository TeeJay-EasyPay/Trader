import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.broker_adapters import KrakenAdapter
from ai_trader.foundation import (
    calculate_capital_allocation,
    calculate_investment_score,
    create_due_diligence_assessment,
    initialize_foundation_schema,
    load_trading_policy,
    set_risk_policy_value,
)
from ai_trader.models import AccountContext, AutoTradeConfig, GuardrailConfig, OrderRequest, TradeProposal
from ai_trader.orchestrator import InvestmentOrchestrator, OrchestratorContext

from test_orchestrator import seed_due_diligence_context


MARKET_TIME = datetime(2026, 7, 2, 10, 0, tzinfo=ZoneInfo("America/New_York"))


class FakeAdapter:
    name = "fake"
    # Synthetic test double, not a registered broker in STRATEGY_MATURITY_REGISTRY's
    # permitted_brokers - see the matching note in test_orchestrator.py's FakeAdapter.
    requires_production_governance = False

    def __init__(self):
        self.orders = []

    def get_account(self):
        return {"status": "ACTIVE"}

    def get_balances(self):
        return {"cash": 1000}

    def get_positions(self):
        return []

    def get_orders(self):
        return self.orders

    def get_trade_history(self):
        return []

    def get_supported_markets(self):
        return ["NYSE"]

    def get_supported_assets(self):
        return ["stock"]

    def is_asset_available(self, symbol, exchange, asset_type):
        return True

    def is_market_open(self, exchange):
        return True

    def place_order(self, order_request):
        return self.place_bracket_order(order_request)

    def place_bracket_order(self, order_request):
        order = {"id": "foundation-test", "status": "accepted", "qty": order_request.quantity}
        self.orders.append(order)
        return order

    def cancel_order(self, order_id):
        return {"id": order_id, "status": "cancel_requested"}

    def close_position(self, symbol):
        return {"symbol": symbol, "status": "close_requested"}


def proposal(**overrides):
    data = {
        "symbol": "AAPL",
        "side": "buy",
        "entry_price": 100.0,
        "stop_loss": 97.0,
        "take_profit": 106.0,
        "position_size": 10.0,
        "risk_percentage": 0.003,
        "confidence_score": 0.9,
        "philosophy_fit": 0.9,
        "asset_type": "stock",
        "exchange": "NYSE",
        "news_summary": "Fundamental review complete.",
        "market_sentiment_summary": "Positive",
        "technical_summary": "Good",
        "plain_english_reasoning": "Policy-aligned paper trade.",
        "ai_guardrails_passed": True,
    }
    data.update(overrides)
    return TradeProposal(**data).normalized()


def context(equity=100_000, auto_enabled=True):
    return OrchestratorContext(
        account=AccountContext(equity=equity, daily_realized_pnl=0, open_positions=[]),
        auto_trade=AutoTradeConfig(enabled=auto_enabled),
        guardrails=GuardrailConfig(min_confidence_score=0.65),
        now=MARKET_TIME,
    )


class FoundationSprintTests(unittest.TestCase):
    def test_foundation_schema_and_policy_tables_are_seeded(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_foundation_schema(db_path)

            with closing(sqlite3.connect(db_path)) as conn:
                tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
                investment_count = conn.execute("SELECT COUNT(*) FROM INVESTMENT_POLICIES").fetchone()[0]
                risk_count = conn.execute("SELECT COUNT(*) FROM RISK_POLICIES").fetchone()[0]

            self.assertIn("DUE_DILIGENCE_ASSESSMENTS", tables)
            self.assertIn("INVESTMENT_SCORES", tables)
            # 2026-09-02: CRYPTO_TOKENOMICS was removed along with nine other tables that were
            # declared, never written and never read -- all zero rows in production. Asserting
            # its ABSENCE now, because a schema test that demands an unused table is what kept
            # the clutter alive. The idea behind it is recorded in governance/DEFERRED_IDEAS.md
            # rather than as empty schema; see tests/test_unused_tables_removed.py.
            self.assertNotIn("CRYPTO_TOKENOMICS", tables)
            self.assertGreater(investment_count, 0)
            self.assertGreater(risk_count, 0)

    def test_due_diligence_and_investment_score_are_numeric(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_foundation_schema(db_path)
            seed_due_diligence_context(db_path)

            dd = create_due_diligence_assessment(db_path, proposal())
            score = calculate_investment_score(db_path, proposal())

            self.assertEqual(dd["overall_status"], "completed")
            self.assertIsInstance(score["fundamental_score"], float)
            self.assertIsInstance(score["overall_confidence"], float)

    def test_due_diligence_reports_insufficient_data_without_real_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_foundation_schema(db_path)
            # Deliberately NOT calling seed_due_diligence_context - there is no macro/
            # behavioural data source backing this symbol.

            dd = create_due_diligence_assessment(db_path, proposal())
            score = calculate_investment_score(db_path, proposal())

            self.assertEqual(dd["macro_status"], "insufficient_data")
            self.assertEqual(dd["behavioural_status"], "insufficient_data")
            self.assertEqual(dd["overall_status"], "incomplete")
            self.assertEqual(score["macro_score"], 0.0, "Macro score must not be floored when there is no macro data source.")
            self.assertEqual(score["behavioural_score"], 0.0, "Behavioural score must not be floored when there is no behavioural data source.")

    def test_capital_allocation_caps_position_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            policy = load_trading_policy(db_path, auto_trade=AutoTradeConfig(enabled=True), guardrails=GuardrailConfig())

            allocation = calculate_capital_allocation(db_path, proposal(position_size=10_000), policy, account_equity=10_000)

            self.assertLessEqual(allocation["approved_notional"], 500)
            self.assertEqual(allocation["result"], "approved")

    def test_set_risk_policy_value_updates_an_already_seeded_row_and_takes_effect(self):
        # 2026-08-16: _seed_policies' INSERT OR IGNORE means a code-level default
        # change never reaches an already-seeded row -- this is the only real writer,
        # found while reconciling Kraken's disagreeing "max open positions" settings.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_foundation_schema(db_path)  # seeds maximum_concurrent_positions=10
            before = load_trading_policy(db_path, auto_trade=AutoTradeConfig(enabled=True), guardrails=GuardrailConfig())
            # 2026-09-02, Founder-directed ("for point 2 it should be 10"): the seeded default
            # was 3 while Render said 10 and the live database row said 5. All three now agree.
            self.assertEqual(before.max_concurrent_positions, 10)

            result = set_risk_policy_value(db_path, "maximum_concurrent_positions", 5)

            self.assertEqual(result["status"], "updated")
            self.assertEqual(result["previous_value"], "10")
            after = load_trading_policy(db_path, auto_trade=AutoTradeConfig(enabled=True), guardrails=GuardrailConfig())
            self.assertEqual(after.max_concurrent_positions, 5)

    def test_set_risk_policy_value_does_not_create_an_unknown_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_foundation_schema(db_path)

            result = set_risk_policy_value(db_path, "not_a_real_policy_key", 5)

            self.assertEqual(result["status"], "not_found")
            with closing(sqlite3.connect(db_path)) as conn:
                count = conn.execute("SELECT COUNT(*) FROM RISK_POLICIES WHERE policy_key = 'not_a_real_policy_key'").fetchone()[0]
            self.assertEqual(count, 0)

    def test_orchestrator_records_foundation_decisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            seed_due_diligence_context(db_path)
            adapter = FakeAdapter()
            orchestrator = InvestmentOrchestrator(db_path=db_path, adapters=[adapter])
            decision = orchestrator.evaluate_recommendation(proposal(), context(), auto_execute=True)

            self.assertEqual(decision.decision, "approved")
            with closing(sqlite3.connect(db_path)) as conn:
                dd_count = conn.execute("SELECT COUNT(*) FROM DUE_DILIGENCE_ASSESSMENTS").fetchone()[0]
                score_count = conn.execute("SELECT COUNT(*) FROM INVESTMENT_SCORES").fetchone()[0]
                allocation_count = conn.execute("SELECT COUNT(*) FROM CAPITAL_ALLOCATION_HISTORY").fetchone()[0]
                execution_count = conn.execute("SELECT COUNT(*) FROM EXECUTION_DECISIONS").fetchone()[0]
            self.assertEqual(dd_count, 1)
            self.assertEqual(score_count, 1)
            self.assertEqual(allocation_count, 1)
            self.assertEqual(execution_count, 1)

    def test_emergency_shutdown_rejects_trade(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_foundation_schema(db_path)
            with closing(sqlite3.connect(db_path)) as conn:
                with conn:
                    conn.execute(
                        "UPDATE RISK_POLICIES SET policy_value = '1000' WHERE policy_key = 'emergency_shutdown_balance'"
                    )
            decision = InvestmentOrchestrator(db_path=db_path, adapters=[FakeAdapter()]).evaluate_recommendation(
                proposal(),
                context(equity=500),
                auto_execute=True,
            )

            self.assertEqual(decision.decision, "rejected")
            self.assertIn("emergency_shutdown_balance_breached", decision.rejection_reason)

    def test_propose_crypto_trades_passes_guardrails_with_real_market_data(self):
        # Regression test for three bugs found while smoke-testing the crypto research
        # pipeline end to end: (1) the equity trading-hours guardrail was incorrectly
        # applied to 24/7 crypto, (2) risk_percentage was set to the stop-loss distance
        # instead of capital-at-risk, tripping declared_risk_percentage_exceeded, and
        # (3) paper_trading_only incorrectly blocked Kraken's genuinely non-paper account.
        # All three silently meant Kraken could never produce an executable proposal.
        from ai_trader.agent import propose_crypto_trades
        from ai_trader.audit import AuditDatabase
        from ai_trader.multi_broker import record_crypto_research_score

        class FakeKrakenPriceAdapter:
            def current_prices(self, pairs):
                return {pairs[0]: {"c": ["50000.0", "1.0"]}}

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_foundation_schema(db_path)
            audit = AuditDatabase(db_path, None)
            record_crypto_research_score(
                db_path,
                symbol="BTC",
                category="Top 20 by market cap",
                metrics={
                    "technical_trend_score": 0.75,
                    "momentum_score": 0.6,
                    "volatility": 0.2,
                    "liquidity": 0.8,
                    "risk_score": 0.8,
                    "overall_due_diligence_score": 0.9,
                    "confidence_score": 0.9,
                },
                source="test",
            )
            account = AccountContext(equity=1000, daily_realized_pnl=0, open_positions=[], is_paper=False)

            proposals = propose_crypto_trades(
                db_path,
                FakeKrakenPriceAdapter(),
                ["BTC"],
                account,
                GuardrailConfig(),
                audit,
                min_confidence=0.85,
                requested_notional=5.0,
                default_stop_loss_pct=0.02,
            )

            self.assertEqual(len(proposals), 1)
            self.assertTrue(proposals[0].ai_guardrails_passed, proposals[0].ai_guardrail_failures)
            self.assertLessEqual(proposals[0].risk_percentage, GuardrailConfig().max_risk_per_trade_pct)

    def test_propose_crypto_trades_enriches_reasoning_with_real_context_without_changing_the_trade(self):
        # Phase D: a passing crypto proposal's reasoning text gains real historical-
        # analogue/backtest/external-intelligence/knowledge-base context -- informational
        # only, never a gate; that part of the pipeline must never change entry/stop/
        # target/size on its own. Volatility-scaled stops (2026-08-15, a real and
        # deliberate trade-terms change, separate from Phase D context) DO change stop_loss/
        # take_profit here on purpose -- this fixture's volatility=0.2 is asserted against
        # explicitly below rather than the old flat-2% value.
        from ai_trader.agent import propose_crypto_trades
        from ai_trader.audit import AuditDatabase
        from ai_trader.experience_engine import record_experience
        from ai_trader.multi_broker import record_crypto_research_score

        class FakeKrakenPriceAdapter:
            def current_prices(self, pairs):
                return {pairs[0]: {"c": ["50000.0", "1.0"]}}

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_foundation_schema(db_path)
            audit = AuditDatabase(db_path, None)
            record_crypto_research_score(
                db_path,
                symbol="BTC",
                category="Top 20 by market cap",
                metrics={
                    "technical_trend_score": 0.75,
                    "momentum_score": 0.6,
                    "volatility": 0.2,
                    "liquidity": 0.8,
                    "risk_score": 0.8,
                    "overall_due_diligence_score": 0.9,
                    "confidence_score": 0.9,
                },
                source="test",
            )
            record_experience(
                db_path,
                symbol="BTC",
                decision_context={"note": "prior BTC trade"},
                result_context={"outcome": "win", "pnl": 42.0},
            )
            account = AccountContext(equity=1000, daily_realized_pnl=0, open_positions=[], is_paper=False)

            proposals = propose_crypto_trades(
                db_path,
                FakeKrakenPriceAdapter(),
                ["BTC"],
                account,
                GuardrailConfig(),
                audit,
                min_confidence=0.85,
                requested_notional=5.0,
                default_stop_loss_pct=0.02,
            )

            self.assertEqual(len(proposals), 1)
            proposal = proposals[0]
            self.assertIn("Additional context:", proposal.plain_english_reasoning)
            self.assertIn("outcome=win", proposal.plain_english_reasoning)
            # 2026-08-15 incident: reference_material (the curated knowledge-base excerpts)
            # was fetched by build_proposal_context but never included in the text below --
            # silently dropped before it ever reached this proposal's own reasoning, unlike
            # every other piece of context. "Reference material:" and a real excerpt title
            # from the committed knowledge/ library must now both appear.
            self.assertIn("Reference material:", proposal.plain_english_reasoning)
            self.assertIn("Momentum vs. Mean-Reversion", proposal.plain_english_reasoning)
            self.assertEqual(proposal.entry_price, 50000.0)
            # 2026-09-03: the stop is sized from ATR measured on the coin's own candles now,
            # not from the stored "volatility" score times a 1.0-2.0 multiplier. That formula
            # could only ever produce 1.5%-3.0% however the coin behaved, and rated BTC as more
            # volatile than ADA. See volatility_stops.
            #
            # This fixture seeds no candles, so ATR cannot be measured and the sizing falls back
            # to default_stop_loss_pct (0.02) -- deliberately the cautious middle rather than an
            # extreme, because a stop sized from no data is a guess. What this test is really
            # about is the REASONING text, and that is unchanged; the trade shape simply moved
            # from 2.4% to the 2.0% fallback.
            self.assertEqual(proposal.stop_loss, round(50000.0 * (1 - 0.02), 8))
            self.assertEqual(proposal.take_profit, round(50000.0 * (1 + 0.02 * 2), 8))
            self.assertEqual(proposal.position_size, 5.0 / 50000.0)

    def test_unavailable_kraken_pair_does_not_abort_crypto_research(self):
        from ai_trader.agent import propose_crypto_trades
        from ai_trader.audit import AuditDatabase
        from ai_trader.multi_broker import record_crypto_research_score

        class UnsupportedPairAdapter:
            def current_prices(self, pairs):
                raise RuntimeError("EQuery:Unknown asset pair")

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_foundation_schema(db_path)
            audit = AuditDatabase(db_path, None)
            record_crypto_research_score(
                db_path,
                symbol="BNB",
                category="Founder approved Kraken pairs",
                metrics={
                    "technical_trend_score": 0.9,
                    "momentum_score": 0.9,
                    "volatility": 0.2,
                    "liquidity": 0.9,
                    "risk_score": 0.9,
                    "overall_due_diligence_score": 0.9,
                    "confidence_score": 0.9,
                },
                source="test",
            )

            proposals = propose_crypto_trades(
                db_path,
                UnsupportedPairAdapter(),
                ["BNB"],
                AccountContext(equity=1000, daily_realized_pnl=0, open_positions=[], is_paper=False),
                GuardrailConfig(),
                audit,
                min_confidence=0.85,
                requested_notional=5.0,
                default_stop_loss_pct=0.02,
            )

            self.assertEqual(proposals, [])

    def test_kraken_accepts_private_key_env_name_but_trading_stays_disabled(self):
        previous = {key: os.environ.get(key) for key in ["KRAKEN_API_KEY", "KRAKEN_PRIVATE_KEY", "KRAKEN_API_SECRET", "KRAKEN_TRADING_ENABLED"]}
        try:
            os.environ["KRAKEN_API_KEY"] = "key"
            os.environ["KRAKEN_PRIVATE_KEY"] = "private"
            os.environ.pop("KRAKEN_API_SECRET", None)
            os.environ["KRAKEN_TRADING_ENABLED"] = "false"

            adapter = KrakenAdapter()
            result = adapter.place_order(OrderRequest("BTC", "buy", 1, "crypto", "KRAKEN", 90, 120))

            self.assertTrue(adapter.configured)
            self.assertEqual(result["status"], "disabled")
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
