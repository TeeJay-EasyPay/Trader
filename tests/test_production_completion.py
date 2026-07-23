from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.always_on import initialize_always_on_schema
from ai_trader.api import LocalApiService
from ai_trader.canonical_trades import (
    canonical_trade,
    link_broker_order,
    reconcile_canonical_broker_event,
    register_execution_intent,
)
from ai_trader.cli import WorkerJobTimeout, _run_worker_cycle_job
from ai_trader.database import connect, selected_backend
from ai_trader.models import TradeProposal
from ai_trader.sprint6 import enqueue_learning_workflow, initialize_sprint6_schema, process_learning_outbox


def proposal() -> TradeProposal:
    return TradeProposal(
        symbol="AAPL",
        side="buy",
        entry_price=100.0,
        stop_loss=98.0,
        take_profit=106.0,
        position_size=2.0,
        risk_percentage=0.004,
        confidence_score=0.9,
        news_summary="No material negative news found.",
        market_sentiment_summary="Constructive.",
        technical_summary="Trend is positive.",
        plain_english_reasoning=(
            "Strongest argument for: the trend is constructive. "
            "Strongest argument against: volatility could invalidate the setup."
        ),
        ai_guardrails_passed=True,
        asset_type="stock",
        exchange="NYSE",
        philosophy_fit=0.9,
    ).normalized()


class ProductionCompletionTests(unittest.TestCase):
    def test_broker_poll_writes_production_evidence_only_for_changed_rows(self):
        event = {"id": "order-1", "status": "new", "symbol": "AAPL"}
        changed = {**event, "status": "filled"}
        adapter = SimpleNamespace(
            configured=True,
            get_orders=lambda: [event],
            get_trade_history=lambda: [event],
        )
        service = LocalApiService.__new__(LocalApiService)
        service.settings = SimpleNamespace(db_path=Path("unused.sqlite3"))
        service.orchestrator = SimpleNamespace(adapters={"alpaca": adapter})

        with (
            patch("ai_trader.api.record_broker_trade_history", return_value=[changed]),
            patch("ai_trader.api.record_trade_evidence") as evidence,
            patch("ai_trader.api.normalize_broker_events", return_value={"status": "reconciled"}),
            patch("ai_trader.api.record_notification"),
        ):
            result = service.poll_broker_activity()

        evidence.assert_called_once_with(
            Path("unused.sqlite3"),
            broker="alpaca",
            event=changed,
        )
        self.assertEqual(result["alpaca"]["events_processed"], 1)
        self.assertEqual(result["alpaca"]["new_records"], 1)

    def test_broker_snapshot_does_not_duplicate_trade_evidence(self):
        service = LocalApiService.__new__(LocalApiService)
        service.settings = SimpleNamespace(db_path=Path("unused.sqlite3"))
        service._live_alpaca_portfolio = lambda: {
            "connection_status": "Connected",
            "portfolio_value": 100_000,
            "recent_orders": [{"id": "order-1"}],
        }
        service._exchange_portfolio = lambda broker: {
            "connection_status": "Connected",
            "portfolio_value": 4_000,
            "recent_activities": [{"id": "trade-1"}],
        }

        with (
            patch("ai_trader.api.record_broker_snapshot") as snapshot,
            patch("ai_trader.api.record_trade_evidence") as evidence,
        ):
            result = service.capture_production_broker_snapshots()

        self.assertEqual(snapshot.call_count, 2)
        evidence.assert_not_called()
        self.assertEqual(result["alpaca"]["status"], "captured")
        self.assertEqual(result["kraken"]["status"], "captured")

    def test_hosted_runtime_refuses_sqlite(self):
        with patch.dict(
            os.environ,
            {"RENDER": "true", "AI_TRADER_DATABASE_BACKEND": "sqlite"},
            clear=True,
        ):
            with self.assertRaisesRegex(RuntimeError, "requires Postgres"):
                selected_backend()

    def test_local_runtime_retains_isolated_sqlite(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {"AI_TRADER_DATABASE_BACKEND": "sqlite"},
            clear=True,
        ):
            db_path = Path(tmp) / "local.sqlite3"
            with closing(connect(db_path)) as conn:
                with conn:
                    conn.execute("CREATE TABLE evidence (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
                    conn.execute("INSERT INTO evidence (id, value) VALUES (?, ?)", (1, "local"))
                    row = conn.execute("SELECT value FROM evidence WHERE id = ?", (1,)).fetchone()
            self.assertEqual(row[0], "local")

    def test_canonical_trade_aggregates_partial_fills_costs_and_terminal_exit_once(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {"AI_TRADER_DATABASE_BACKEND": "sqlite"},
            clear=True,
        ):
            db_path = Path(tmp) / "audit.sqlite3"
            idea = proposal()
            logical_id = register_execution_intent(
                db_path,
                proposal=idea,
                broker="alpaca",
                decision_context={"portfolio": "approved", "risk": "approved", "sentinel": "approved"},
            )
            link_broker_order(
                db_path,
                logical_trade_id=logical_id,
                broker_order_id="entry-1",
                payload={"status": "submitted"},
            )
            first = reconcile_canonical_broker_event(
                db_path,
                broker="alpaca",
                source="test",
                event={
                    "proposal_id": logical_id,
                    "order_id": "entry-1",
                    "fill_id": "entry-fill-1",
                    "status": "partially_filled",
                    "symbol": "AAPL",
                    "side": "buy",
                    "filled_quantity": 1,
                    "average_fill_price": 100,
                    "broker_fee": 0.2,
                    "fill_role": "entry",
                },
            )
            second = reconcile_canonical_broker_event(
                db_path,
                broker="alpaca",
                source="test",
                event={
                    "proposal_id": logical_id,
                    "order_id": "entry-1",
                    "fill_id": "entry-fill-2",
                    "status": "fully_filled",
                    "symbol": "AAPL",
                    "side": "buy",
                    "filled_quantity": 1,
                    "average_fill_price": 102,
                    "broker_fee": 0.2,
                    "fill_role": "entry",
                },
            )
            self.assertFalse(first["terminal"])
            self.assertFalse(second["terminal"])
            closed_event = {
                "proposal_id": logical_id,
                "order_id": "exit-1",
                "fill_id": "exit-fill-1",
                "status": "fully_filled",
                "symbol": "AAPL",
                "side": "sell",
                "filled_quantity": 2,
                "average_fill_price": 106,
                "exchange_fee": 0.4,
                "fill_role": "exit",
            }
            closed = reconcile_canonical_broker_event(
                db_path,
                broker="alpaca",
                source="test",
                event=closed_event,
            )
            duplicate = reconcile_canonical_broker_event(
                db_path,
                broker="alpaca",
                source="test",
                event=closed_event,
            )
            trade = canonical_trade(db_path, logical_id)

            self.assertTrue(closed["terminal"])
            self.assertEqual(duplicate["fill"]["status"], "duplicate")
            self.assertAlmostEqual(trade["average_entry_price"], 101.0)
            self.assertAlmostEqual(trade["average_exit_price"], 106.0)
            self.assertAlmostEqual(trade["gross_pnl"], 10.0)
            self.assertAlmostEqual(trade["net_pnl"], 9.2)
            self.assertEqual(trade["entry_filled_quantity"], 2.0)
            self.assertEqual(trade["exit_filled_quantity"], 2.0)

    def test_terminal_learning_queue_is_exactly_once(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {"AI_TRADER_DATABASE_BACKEND": "sqlite"},
            clear=True,
        ):
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_sprint6_schema(db_path)
            # Historical broker rows may lack the evidence required for full
            # attribution. They still terminate exactly once as explicitly
            # insufficient rather than remaining stuck or inventing metrics.
            payload = {"symbol": "AAPL", "observations": []}
            first = enqueue_learning_workflow(db_path, logical_trade_id="trade-1", broker="alpaca", payload=payload)
            second = enqueue_learning_workflow(db_path, logical_trade_id="trade-1", broker="alpaca", payload=payload)
            self.assertEqual(first["status"], "queued")
            self.assertEqual(second["status"], "duplicate")
            processed = process_learning_outbox(db_path, worker_id="test-worker")
            repeated = process_learning_outbox(db_path, worker_id="test-worker")
            self.assertEqual(processed["processed"], 1)
            self.assertEqual(repeated["processed"], 0)

    def test_slow_worker_job_times_out_and_records_evidence(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {"AI_TRADER_DATABASE_BACKEND": "sqlite"},
            clear=True,
        ):
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_always_on_schema(db_path)
            service = SimpleNamespace(settings=SimpleNamespace(db_path=db_path))

            def slow_job(*args, **kwargs):
                time.sleep(1.5)
                return {"status": "completed"}

            with patch("ai_trader.cli._run_named_job", side_effect=slow_job):
                result = _run_worker_cycle_job(
                    service,
                    "broker-poll",
                    "test-worker",
                    scheduled_for="2026-07-20T10:00:00+00:00",
                    timeout_seconds=1,
                )
            self.assertEqual(result["status"], "timed_out")

    def test_production_worker_timeout_requests_clean_process_restart(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {"AI_TRADER_DATABASE_BACKEND": "sqlite"},
            clear=True,
        ):
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_always_on_schema(db_path)
            service = SimpleNamespace(settings=SimpleNamespace(db_path=db_path))

            def slow_job(*args, **kwargs):
                time.sleep(1.5)
                return {"status": "completed"}

            with patch("ai_trader.cli._run_named_job", side_effect=slow_job):
                with self.assertRaises(WorkerJobTimeout):
                    _run_worker_cycle_job(
                        service,
                        "broker-poll",
                        "production-worker",
                        scheduled_for="2026-07-20T10:01:00+00:00",
                        timeout_seconds=1,
                        restart_worker_on_timeout=True,
                    )


if __name__ == "__main__":
    unittest.main()
