import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.api import LocalApiService
from ai_trader.config import Settings
from ai_trader.models import AccountContext, AutoTradeConfig, GuardrailConfig, TradeProposal
from ai_trader.portfolio_intelligence import upsert_asset_metadata
from ai_trader.trading_intelligence import STRATEGIES, record_historical_candle
from ai_trader.sprint6 import (
    enqueue_learning_workflow,
    generate_founder_operational_report,
    initialize_sprint6_schema,
    normalize_broker_events,
    pre_execution_decision_packet,
    process_learning_outbox,
    production_risk_sentinel_decision,
    refresh_strategy_maturity,
    seed_default_strategy_registry,
    set_kill_switch,
    sprint6_status,
    strategy_entitlement_decision,
    upsert_incident,
)


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
        auto_trade=AutoTradeConfig(),
        database_backend="sqlite",
    )


def proposal(**overrides) -> TradeProposal:
    base = {
        "symbol": "AAPL",
        "side": "buy",
        "entry_price": 100.0,
        "stop_loss": 98.0,
        "take_profit": 106.0,
        "position_size": 0.1,
        "risk_percentage": 0.002,
        "confidence_score": 0.86,
        "news_summary": "No material negative news found.",
        "market_sentiment_summary": "Constructive but not euphoric.",
        "technical_summary": "Price is above the short-term moving average.",
        "plain_english_reasoning": "Strongest argument for: momentum is constructive. Strongest argument against: evidence sample is still small.",
        "ai_guardrails_passed": True,
        "asset_type": "stock",
        "exchange": "NYSE",
        "philosophy_fit": 0.86,
    }
    base.update(overrides)
    return TradeProposal(**base).normalized()


class Sprint6InstitutionalSpineTests(unittest.TestCase):
    def test_strategy_entitlement_allows_paper_but_blocks_micro_live_without_promotion(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            seed_default_strategy_registry(db_path)
            paper = strategy_entitlement_decision(db_path, proposal=proposal(), broker="alpaca", mode="paper")
            micro = strategy_entitlement_decision(db_path, proposal=proposal(asset_type="crypto", exchange="KRAKEN"), broker="kraken", mode="micro_live")

            self.assertEqual(paper["decision"], "approved")
            self.assertEqual(micro["decision"], "blocked")
            self.assertIn("not permitted for micro_live", micro["reason"])

    def test_every_named_strategy_is_registered_and_entitled_for_paper(self):
        # Regression guard for the strategy_id wiring: once TradeProposal carries the real
        # strategy_id selected by Trading Intelligence (instead of always falling back to the
        # single generic bucket), every one of the 14 named strategies must already have a
        # STRATEGY_MATURITY_REGISTRY row, or every real proposal would suddenly be blocked with
        # "not registered in the maturity registry".
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            seed_default_strategy_registry(db_path)
            with closing(sqlite3.connect(db_path)) as conn:
                registered = {row[0] for row in conn.execute("SELECT strategy_id FROM STRATEGY_MATURITY_REGISTRY").fetchall()}
            for strategy_id in STRATEGIES:
                self.assertIn(strategy_id, registered, f"{strategy_id} has no maturity registry row")

            for strategy_id, definition in STRATEGIES.items():
                asset_type = "crypto" if "crypto" in definition["supported_assets"] else "stock"
                broker = "kraken" if asset_type == "crypto" else "alpaca"
                decision = strategy_entitlement_decision(
                    db_path,
                    proposal=proposal(strategy_id=strategy_id, asset_type=asset_type, exchange="KRAKEN" if asset_type == "crypto" else "NYSE"),
                    broker=broker,
                    mode="paper",
                )
                self.assertEqual(decision["decision"], "approved", f"{strategy_id}: {decision['reason']}")
                self.assertEqual(decision["strategy_id"], strategy_id)

    def test_refresh_strategy_maturity_holds_on_thin_evidence_and_promotes_on_strong_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            seed_default_strategy_registry(db_path)

            thin = refresh_strategy_maturity(db_path, strategy_id="trend_following", evidence={"sample_size": 3, "expectancy": 0.1, "profit_factor": 1.5, "max_drawdown": 0.05, "calibration_error": 0.02})
            self.assertFalse(thin["stage_changed"])
            self.assertEqual(thin["promotion"]["decision"], "hold")

            # Bootstrap stage is "Paper"; the next stage in STRATEGY_STAGES is "Micro Live", which
            # requires real capital. Even with strong evidence this must NOT auto-apply - it
            # should surface as pending Founder approval instead (see _MAX_AUTOMATIC_STAGE).
            strong = refresh_strategy_maturity(
                db_path,
                strategy_id="trend_following",
                evidence={"sample_size": 120, "expectancy": 0.3, "profit_factor": 1.6, "max_drawdown": 0.05, "calibration_error": 0.02},
            )
            self.assertFalse(strong["stage_changed"])
            self.assertTrue(strong["requires_founder_approval"])
            self.assertEqual(strong["status"], "pending_founder_approval")
            self.assertEqual(strong["promotion"]["proposed_stage"], "Micro Live")
            self.assertEqual(strong["promotion"]["decision"], "promote")

            with closing(sqlite3.connect(db_path)) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute("SELECT * FROM STRATEGY_MATURITY_REGISTRY WHERE strategy_id = ?", ("trend_following",)).fetchone()
            # Registry stage is untouched - the promotion recommendation is fully logged in
            # STRATEGY_PROMOTION_DECISIONS (asserted below) but not applied without a human.
            self.assertEqual(row["current_stage"], "Paper")
            self.assertEqual(row["sample_size"], 120)

            with closing(sqlite3.connect(db_path)) as conn:
                conn.row_factory = sqlite3.Row
                decisions = conn.execute(
                    "SELECT * FROM STRATEGY_PROMOTION_DECISIONS WHERE strategy_id = ?",
                    ("trend_following",),
                ).fetchall()
            self.assertTrue(any(row["decision"] == "promote" and row["proposed_stage"] == "Micro Live" for row in decisions))

    def test_refresh_strategy_maturity_auto_applies_promotion_at_or_below_paper(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            seed_default_strategy_registry(db_path)
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute("UPDATE STRATEGY_MATURITY_REGISTRY SET current_stage = 'Shadow' WHERE strategy_id = ?", ("momentum",))
                conn.commit()

            result = refresh_strategy_maturity(
                db_path,
                strategy_id="momentum",
                evidence={"sample_size": 40, "expectancy": 0.2, "profit_factor": 1.4, "max_drawdown": 0.05, "calibration_error": 0.02},
            )

            self.assertTrue(result["stage_changed"])
            self.assertFalse(result["requires_founder_approval"])
            self.assertEqual(result["promotion"]["proposed_stage"], "Paper")
            with closing(sqlite3.connect(db_path)) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute("SELECT current_stage, qualification_date FROM STRATEGY_MATURITY_REGISTRY WHERE strategy_id = ?", ("momentum",)).fetchone()
            self.assertEqual(row["current_stage"], "Paper")
            self.assertIsNotNone(row["qualification_date"])

    def test_refresh_strategy_maturity_reports_unregistered_strategy(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            seed_default_strategy_registry(db_path)
            result = refresh_strategy_maturity(db_path, strategy_id="does_not_exist", evidence={})
            self.assertEqual(result["status"], "not_registered")

    def test_risk_sentinel_kill_switch_blocks_before_broker_submission(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_sprint6_schema(db_path)
            set_kill_switch(db_path, active=True, reason="Founder emergency stop", activated_by="test")

            decision = production_risk_sentinel_decision(
                db_path,
                proposal=proposal(),
                broker="alpaca",
                account=AccountContext(equity=10000, daily_realized_pnl=0),
            )

            self.assertEqual(decision["decision"], "blocked")
            self.assertIn("kill_switch_active", decision["reason"])

    def test_pre_execution_packet_records_decision_journal(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            seed_default_strategy_registry(db_path)
            account = AccountContext(equity=10000, daily_realized_pnl=0, open_positions=[])
            for item in [
                ("AAPL", "stock", "Technology", "US", "USD"),
                ("BTC", "crypto", "Digital Assets", "Global", "GBP"),
                ("GLD", "commodity", "Commodities", "US", "USD"),
                ("GBP", "cash", "Cash", "UK", "GBP"),
                ("BND", "bond", "Fixed Income", "US", "USD"),
            ]:
                symbol, asset_type, sector, country, currency = item
                upsert_asset_metadata(
                    db_path,
                    symbol=symbol,
                    source="test",
                    payload={
                        "asset_class": asset_type,
                        "sector": sector,
                        "country": country,
                        "trading_currency": currency,
                    },
                )

            packet = pre_execution_decision_packet(
                db_path,
                proposal=proposal(),
                broker="alpaca",
                mode="paper",
                account=account,
                positions=[
                    {"symbol": "AAPL", "broker": "alpaca", "asset_type": "stock", "market_value": 2000},
                    {"symbol": "BTC", "broker": "kraken", "asset_type": "crypto", "market_value": 2000},
                    {"symbol": "GLD", "broker": "alpaca", "asset_type": "commodity", "market_value": 2000},
                    {"symbol": "GBP", "broker": "cash", "asset_type": "cash", "market_value": 2000},
                    {"symbol": "BND", "broker": "alpaca", "asset_type": "bond", "market_value": 2000},
                ],
                market_data_quality="Approved - test candles valid.",
            )

            self.assertTrue(packet["approved"])
            with closing(sqlite3.connect(db_path)) as conn:
                rows = conn.execute("SELECT final_decision, execution_eligibility FROM DECISION_JOURNAL").fetchall()
            self.assertEqual(rows, [("approved", "eligible")])

    def test_pre_execution_packet_activates_correlation_check_once_candle_history_exists(self):
        # Regression guard for return_series wiring: before this, portfolio_manager_decision was
        # always called with return_series=None, so correlation_warning() could never do anything
        # but report "insufficient_history" regardless of how much price history actually existed.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            seed_default_strategy_registry(db_path)
            account = AccountContext(equity=10000, daily_realized_pnl=0, open_positions=[])
            for symbol in ("AAPL", "MSFT"):
                price = 100.0
                for day in range(1, 26):
                    price += 0.5 if day % 3 else -0.3
                    record_historical_candle(
                        db_path,
                        symbol=symbol,
                        asset_type="stock",
                        timeframe="1d",
                        observed_at=f"2026-06-{day:02d}T00:00:00Z",
                        close=price,
                        source="test",
                    )

            packet = pre_execution_decision_packet(
                db_path,
                proposal=proposal(symbol="AAPL"),
                broker="alpaca",
                mode="paper",
                account=account,
                positions=[{"symbol": "MSFT", "broker": "alpaca", "asset_type": "stock", "market_value": 2000}],
            )

            correlation = packet["portfolio_manager"]["evidence"]["correlation"]
            self.assertEqual(correlation["status"], "complete")
            self.assertEqual(correlation["pairs"][0]["sample_size"], 24)

    def test_broker_event_normalization_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            event = {
                "id": "order-1",
                "symbol": "AAPL",
                "side": "buy",
                "status": "filled",
                "qty": "1",
                "price": "100",
                "updated_at": "2026-07-18T10:00:00+00:00",
            }

            first = normalize_broker_events(db_path, broker="alpaca", events=[event], source_endpoint="test")
            second = normalize_broker_events(db_path, broker="alpaca", events=[event], source_endpoint="test")

            self.assertEqual(first["inserted"], 1)
            self.assertEqual(second["duplicates"], 1)

    def test_learning_outbox_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            first = enqueue_learning_workflow(db_path, logical_trade_id="alpaca-order-1", broker="alpaca", payload={"status": "filled"})
            second = enqueue_learning_workflow(db_path, logical_trade_id="alpaca-order-1", broker="alpaca", payload={"status": "filled"})

            self.assertEqual(first["status"], "queued")
            self.assertEqual(second["status"], "duplicate")

    def test_learning_processor_preserves_payload_and_marks_incomplete_evidence_for_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            original_payload = {"broker": "alpaca", "status": "filled"}
            queued = enqueue_learning_workflow(
                db_path,
                logical_trade_id="alpaca-order-1",
                broker="alpaca",
                payload=original_payload,
            )

            result = process_learning_outbox(db_path, worker_id="test-worker")

            self.assertEqual(result["manual_review"], 0)
            self.assertEqual(result["processed"], 1)
            with closing(sqlite3.connect(db_path)) as conn:
                row = conn.execute(
                    "SELECT status, payload_json, last_error FROM SPRINT6_WORKFLOW_OUTBOX WHERE workflow_id = ?",
                    (queued["workflow_id"],),
                ).fetchone()
            self.assertEqual(row[0], "completed_insufficient_evidence")
            self.assertEqual(json.loads(row[1]), original_payload)
            self.assertIsNone(row[2])

    def test_learning_processor_completes_deterministic_terminal_trade_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            payload = {
                "broker": "alpaca",
                "symbol": "AAPL",
                "attribution": {
                    "proposal_id": "p-1",
                    "side": "buy",
                    "quantity": 1,
                    "entry_price": 100,
                    "exit_price": 104,
                    "actual_average_entry_price": 100,
                    "actual_average_exit_price": 104,
                    "broker_fee": 0,
                    "exchange_fee": 0,
                    "profit_loss": 4,
                },
                "decision_context": {
                    "proposal_id": "p-1",
                    "asset_type": "stock",
                    "strategy_id": "breakout",
                    "regime_id": "fragile_uptrend",
                    "side": "buy",
                    "entry_price": 100,
                    "intended_entry_price": 100,
                    "stop_loss": 98,
                    "original_stop": 98,
                    "take_profit": 106,
                    "expected_r": 3,
                    "strongest_argument_for": "Breakout held above resistance.",
                    "strongest_argument_against": "Market breadth was mixed.",
                },
                "observations": [
                    {"time": "2026-07-18T10:00:00+00:00", "low": 99, "high": 103},
                    {"time": "2026-07-18T11:00:00+00:00", "low": 101, "high": 105},
                ],
            }
            queued = enqueue_learning_workflow(
                db_path,
                logical_trade_id="alpaca-order-1",
                broker="alpaca",
                payload=payload,
            )

            first = process_learning_outbox(db_path, worker_id="test-worker")
            second = process_learning_outbox(db_path, worker_id="test-worker")

            self.assertEqual(first["processed"], 1)
            self.assertEqual(second["claimed"], 0)
            with closing(sqlite3.connect(db_path)) as conn:
                workflow = conn.execute(
                    "SELECT status, payload_json FROM SPRINT6_WORKFLOW_OUTBOX WHERE workflow_id = ?",
                    (queued["workflow_id"],),
                ).fetchone()
                learning_runs = conn.execute(
                    "SELECT COUNT(*) FROM CLOSED_LOOP_LEARNING_RUNS WHERE logical_trade_id = 'alpaca-order-1'"
                ).fetchone()[0]
            self.assertEqual(workflow[0], "completed")
            self.assertEqual(json.loads(workflow[1]), payload)
            self.assertEqual(learning_runs, 1)

    def test_incident_lifecycle_deduplicates_repeated_faults(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            upsert_incident(
                db_path,
                incident_key="worker:stale",
                severity="warning",
                component="worker",
                explanation="Worker heartbeat is stale.",
                recommended_action="Restart worker.",
            )
            upsert_incident(
                db_path,
                incident_key="worker:stale",
                severity="warning",
                component="worker",
                explanation="Worker heartbeat is still stale.",
                recommended_action="Restart worker.",
            )

            with closing(sqlite3.connect(db_path)) as conn:
                row = conn.execute("SELECT occurrence_count, status FROM INCIDENT_LIFECYCLE WHERE incident_key = 'worker:stale'").fetchone()
            self.assertEqual(row, (2, "open"))

    def test_founder_operational_report_is_persisted_and_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            pre_execution_decision_packet(
                db_path,
                proposal=proposal(),
                broker="alpaca",
                mode="paper",
                account=AccountContext(equity=10000, daily_realized_pnl=0),
            )

            report = generate_founder_operational_report(db_path, output_dir=Path(tmp), report_type="daily")

            self.assertEqual(report["status"], "generated")
            self.assertTrue(Path(report["file_path"]).exists())
            self.assertIn("decision packet", report["summary"])

    def test_api_exposes_sprint6_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalApiService(settings_for(tmp))
            status, payload = service.get("/sprint6-status", {})

            self.assertEqual(status, 200)
            self.assertIn("strategy_registry", payload)
            self.assertEqual(payload["database_backend"], "sqlite")

    def test_sprint6_status_explains_sqlite_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            status = sprint6_status(db_path, database_backend="sqlite")

            self.assertEqual(status["overall"], "attention_needed")
            self.assertIn("SQLite", status["shared_runtime_truth"])


if __name__ == "__main__":
    unittest.main()
