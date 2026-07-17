import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ai_trader.audit import AuditDatabase
from ai_trader.models import AccountContext, AutoTradeConfig, GuardrailConfig, Position, TradeProposal
from ai_trader.multi_broker import initialize_multi_broker_schema
from ai_trader.orchestrator import InvestmentOrchestrator, OrchestratorContext
from ai_trader.trading_intelligence import (
    analyze_price_series,
    calculate_calibration_metrics,
    evaluate_trade_intelligence,
    initialize_trading_intelligence_schema,
    latest_intelligence_packet,
    record_lifecycle_stage,
    record_historical_candle,
    run_walk_forward_validation,
    run_strategy_backtest,
)

from test_orchestrator import FakeAdapter, seed_due_diligence_context


MARKET_TIME = datetime(2026, 7, 2, 10, 0, tzinfo=ZoneInfo("America/New_York"))


def proposal(**overrides):
    data = {
        "symbol": "AAPL",
        "side": "buy",
        "entry_price": 100.0,
        "stop_loss": 97.0,
        "take_profit": 106.0,
        "position_size": 1.0,
        "risk_percentage": 0.0003,
        "confidence_score": 0.9,
        "philosophy_fit": 0.9,
        "asset_type": "stock",
        "exchange": "NYSE",
        "news_summary": "Apple demand and services revenue reviewed.",
        "market_sentiment_summary": "Market sentiment is constructive.",
        "technical_summary": "Price is above the latest reference level.",
        "plain_english_reasoning": "The setup has positive technical and news evidence with defined risk.",
        "ai_guardrails_passed": True,
    }
    data.update(overrides)
    return TradeProposal(**data).normalized()


def rising_candles(count: int = 40):
    rows = []
    price = 100.0
    for index in range(count):
        price += 0.6
        rows.append(
            {
                "observed_at": f"2026-06-{index + 1:02d}",
                "open": price - 0.3,
                "high": price + 0.8,
                "low": price - 0.8,
                "close": price,
                "volume": 1000 + index * 25,
            }
        )
    return rows


class TradingIntelligenceTests(unittest.TestCase):
    def test_schema_seeds_strategy_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_trading_intelligence_schema(db_path)

            with closing(sqlite3.connect(db_path)) as conn:
                count = conn.execute("SELECT COUNT(*) FROM STRATEGY_REGISTRY").fetchone()[0]

            self.assertGreaterEqual(count, 10)

    def test_market_intelligence_calculates_price_metrics_without_using_ai_confidence(self):
        metrics = analyze_price_series(rising_candles())

        self.assertGreater(metrics["trend_score"], 0.5)
        self.assertGreater(metrics["momentum_score"], 0.5)
        self.assertIsNotNone(metrics["atr_pct"])
        self.assertIsNotNone(metrics["support"])
        self.assertIsNotNone(metrics["resistance"])

    def test_intelligence_packet_requires_and_records_bull_and_bear_case(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            item = proposal()

            packet = evaluate_trade_intelligence(
                db_path,
                item,
                AccountContext(equity=100_000, daily_realized_pnl=0),
                market={"history": {"AAPL": rising_candles()}},
                news={"news": [{"headline": "Apple headline"}]},
            )

            self.assertIsNotNone(packet)
            self.assertIn("market_intelligence", packet.to_dict())
            self.assertNotEqual(packet.regime["primary_regime"], "unknown")
            self.assertTrue(packet.committee["strongest_argument_for"])
            self.assertTrue(packet.committee["strongest_argument_against"])
            signal_scores = {signal["score"] for signal in packet.signals}
            self.assertGreater(len(signal_scores), 1)
            self.assertNotEqual(signal_scores, {item.confidence_score})
            stored = latest_intelligence_packet(db_path, item.proposal_id)
            self.assertEqual(stored["committee"]["strongest_argument_for"], packet.committee["strongest_argument_for"])
            self.assertGreaterEqual(len(stored["signals"]), 1)

    def test_agent_payload_can_store_intelligence_without_breaking_trade_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            audit = AuditDatabase(db_path)
            item = proposal()
            packet = evaluate_trade_intelligence(db_path, item, AccountContext(equity=100_000, daily_realized_pnl=0))

            audit.record_trade_event("agent_proposal", item, intelligence=packet.to_dict())

            with closing(sqlite3.connect(db_path)) as conn:
                raw = conn.execute("SELECT payload_json FROM trade_audit WHERE proposal_id = ?", (item.proposal_id,)).fetchone()[0]
            payload = json.loads(raw)
            self.assertIn("intelligence", payload)
            self.assertEqual(payload["intelligence"]["committee"]["strongest_argument_against"], packet.committee["strongest_argument_against"])

    def test_committee_records_disagreement_when_portfolio_has_duplicate_position(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            item = proposal()

            packet = evaluate_trade_intelligence(
                db_path,
                item,
                AccountContext(equity=100_000, daily_realized_pnl=0, open_positions=[Position(symbol="AAPL", qty=3, market_value=300)]),
                market={"history": {"AAPL": rising_candles()}},
            )

            self.assertIsNotNone(packet)
            self.assertTrue(packet.portfolio["duplicate_position"])
            self.assertTrue(packet.committee["disagreements"])

    def test_probability_reflects_small_sample_uncertainty(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            item = proposal(confidence_score=0.95)

            packet = evaluate_trade_intelligence(
                db_path,
                item,
                AccountContext(equity=100_000, daily_realized_pnl=0),
                market={"history": {"AAPL": rising_candles()}},
            )

            self.assertEqual(packet.probability["calibration_status"], "uncalibrated_small_sample")
            interval_width = packet.probability["confidence_interval_high"] - packet.probability["confidence_interval_low"]
            self.assertGreaterEqual(interval_width, 0.3)

    def test_strategy_backtest_records_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            for candle in rising_candles():
                record_historical_candle(
                    db_path,
                    symbol="AAPL",
                    asset_type="stock",
                    timeframe="1d",
                    observed_at=candle["observed_at"],
                    open=candle["open"],
                    high=candle["high"],
                    low=candle["low"],
                    close=candle["close"],
                    volume=candle["volume"],
                    source="unit_test",
                )

            result = run_strategy_backtest(db_path, strategy_id="trend_following", symbol="AAPL", asset_type="stock")

            self.assertGreater(result["trades"], 0)
            with closing(sqlite3.connect(db_path)) as conn:
                count = conn.execute("SELECT COUNT(*) FROM STRATEGY_BACKTEST_RESULTS").fetchone()[0]
            self.assertEqual(count, 1)

    def test_strategy_selection_is_evidence_driven_and_records_alternatives(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            item = proposal(symbol="BREAK", technical_summary="Price is breaking above resistance on rising volume.")
            candles = rising_candles(45)
            candles[-1]["high"] = candles[-1]["close"]
            candles[-1]["volume"] = candles[-2]["volume"] * 3

            packet = evaluate_trade_intelligence(
                db_path,
                item,
                AccountContext(equity=100_000, daily_realized_pnl=0),
                market={"history": {"BREAK": candles}},
            )

            self.assertIsNotNone(packet)
            self.assertNotEqual(packet.strategy["strategy_id"], "equity_conservative_ai_assisted")
            self.assertTrue(packet.strategy["selection_reason"])
            self.assertGreaterEqual(len(packet.strategy["candidate_scores"]), 3)
            self.assertGreaterEqual(len(packet.strategy["rejected_strategies"]), 1)

    def test_walk_forward_validation_records_institutional_strategy_lab_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            for candle in rising_candles(120):
                record_historical_candle(
                    db_path,
                    symbol="AAPL",
                    asset_type="stock",
                    timeframe="1d",
                    observed_at=candle["observed_at"],
                    open=candle["open"],
                    high=candle["high"],
                    low=candle["low"],
                    close=candle["close"],
                    volume=candle["volume"],
                    source="unit_test",
                )

            result = run_walk_forward_validation(
                db_path,
                strategy_id="trend_following",
                symbol="AAPL",
                asset_type="stock",
                train_window=40,
                test_window=30,
            )

            self.assertEqual(result["run_type"], "walk_forward")
            self.assertTrue(result["bias_controls"]["no_look_ahead_bias"])
            self.assertIn("benchmark", result)
            self.assertGreater(result["window_count"], 0)
            with closing(sqlite3.connect(db_path)) as conn:
                row = conn.execute("SELECT run_type, status FROM STRATEGY_LAB_RUNS ORDER BY lab_run_id DESC LIMIT 1").fetchone()
            self.assertEqual(row[0], "walk_forward")
            self.assertIn(row[1], {"passed_validation", "research_only"})

    def test_portfolio_intelligence_includes_exposure_and_diversification(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            item = proposal(symbol="MSFT", entry_price=250.0, position_size=10.0)

            packet = evaluate_trade_intelligence(
                db_path,
                item,
                AccountContext(
                    equity=100_000,
                    daily_realized_pnl=0,
                    open_positions=[
                        Position(symbol="AAPL", qty=20, market_value=4_000),
                        Position(symbol="NVDA", qty=5, market_value=5_000),
                    ],
                ),
                market={"history": {"MSFT": rising_candles()}},
            )

            self.assertIsNotNone(packet)
            self.assertIn("diversification_status", packet.portfolio)
            self.assertIn("proposed_risk_contribution_pct", packet.portfolio)
            self.assertIn("capital_efficiency_note", packet.portfolio)

    def test_calibration_metrics_compute_brier_score(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            seed_due_diligence_context(db_path)
            initialize_multi_broker_schema(db_path)
            item = proposal()
            evaluate_trade_intelligence(db_path, item, AccountContext(equity=100_000, daily_realized_pnl=0))
            with closing(sqlite3.connect(db_path)) as conn:
                with conn:
                    conn.execute(
                        """
                        INSERT INTO PERFORMANCE_ATTRIBUTION (
                            created_at, proposal_id, broker, symbol, asset_type, side,
                            entry_price, exit_price, quantity, profit_loss, opened_at,
                            closed_at, holding_period_seconds, entry_reason, exit_reason,
                            primary_factors_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            "2026-07-02T10:00:00+00:00",
                            item.proposal_id,
                            "alpaca",
                            "AAPL",
                            "stock",
                            "buy",
                            100.0,
                            106.0,
                            1.0,
                            6.0,
                            "2026-07-02T10:00:00+00:00",
                            "2026-07-02T15:00:00+00:00",
                            18000,
                            "test entry",
                            "target",
                            "{}",
                        ),
                    )

            metrics = calculate_calibration_metrics(db_path, "equity_conservative_ai_assisted")

            self.assertEqual(metrics["sample_size"], 1)
            self.assertIsNotNone(metrics["brier_score"])

    def test_lifecycle_records_trade_measurement_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            item = proposal()

            record_lifecycle_stage(
                db_path,
                item,
                stage="closed",
                reason="Unit test closed trade.",
                strategy_id="equity_conservative_ai_assisted",
                fees=0.12,
                slippage=0.03,
                r_multiple=1.5,
                mae=-0.2,
                mfe=1.8,
                holding_time_seconds=3600,
                payload={"source": "unit_test"},
            )

            with closing(sqlite3.connect(db_path)) as conn:
                row = conn.execute(
                    "SELECT fees, slippage, r_multiple, mae, mfe, holding_time_seconds FROM TRADE_LIFECYCLE"
                ).fetchone()

            self.assertEqual(row, (0.12, 0.03, 1.5, -0.2, 1.8, 3600.0))

    def test_orchestrator_records_lifecycle_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            seed_due_diligence_context(db_path)
            item = proposal()
            evaluate_trade_intelligence(db_path, item, AccountContext(equity=100_000, daily_realized_pnl=0))
            orchestrator = InvestmentOrchestrator(db_path=db_path, adapters=[FakeAdapter()])

            decision = orchestrator.evaluate_recommendation(
                item,
                OrchestratorContext(
                    account=AccountContext(equity=100_000, daily_realized_pnl=0),
                    auto_trade=AutoTradeConfig(enabled=True),
                    guardrails=GuardrailConfig(min_confidence_score=0.65),
                    now=MARKET_TIME,
                ),
                auto_execute=True,
            )

            self.assertEqual(decision.decision, "approved")
            with closing(sqlite3.connect(db_path)) as conn:
                stages = [row[0] for row in conn.execute("SELECT stage FROM TRADE_LIFECYCLE WHERE proposal_id = ? ORDER BY lifecycle_id", (item.proposal_id,))]
            self.assertIn("candidate", stages)
            self.assertIn("submitted", stages)


if __name__ == "__main__":
    unittest.main()
