import sqlite3
import os
import sys
import tempfile
import unittest
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.always_on import (
    alpaca_inactivity_diagnosis,
    claim_scheduled_job,
    complete_scheduled_job,
    database_backend_status,
    initialize_always_on_schema,
    list_job_runs,
    operations_health,
    record_research_funnel,
    record_shadow_trade,
    record_worker_heartbeat,
    scheduler_status,
    shadow_performance,
    update_shadow_outcome,
)
from ai_trader.api import LocalApiService
from ai_trader.config import Settings
from ai_trader.cli import WorkerHeartbeatPulse, _research_worker_jobs
from ai_trader.models import AutoTradeConfig, GuardrailConfig


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
    )


class AlwaysOnOperationsTests(unittest.TestCase):
    def test_research_worker_jobs_excludes_priority_evidence_snapshot(self) -> None:
        due = [
            ("evidence-snapshot", "2026-07-23T16:00:00+00:00"),
            ("overnight-crypto", "2026-07-23T16:00:00+00:00"),
            ("market-open-equity", "2026-07-23T16:00:00+00:00"),
        ]

        self.assertEqual(
            _research_worker_jobs(due),
            [
                ("overnight-crypto", "2026-07-23T16:00:00+00:00"),
                ("market-open-equity", "2026-07-23T16:00:00+00:00"),
            ],
        )

    def test_scheduled_jobs_are_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            first = claim_scheduled_job(db_path, job_name="midday-equity", scheduled_for="2026-07-17T12:00:00+00:00", worker_id="w1")
            second = claim_scheduled_job(db_path, job_name="midday-equity", scheduled_for="2026-07-17T12:00:00+00:00", worker_id="w2")

            self.assertTrue(first["claimed"])
            self.assertFalse(second["claimed"])
            self.assertEqual(second["status"], "skipped_duplicate")

    def test_job_completion_persists_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            claim = claim_scheduled_job(db_path, job_name="auto-execution", scheduled_for="2026-07-17T12:01:00+00:00")
            completed = complete_scheduled_job(
                db_path,
                claim["job_run_id"],
                status="completed_no_action",
                result={"symbols": ["AAPL", "MSFT"], "proposals": [], "skipped": [{"reason": "no_valid_strategy"}]},
            )

            self.assertEqual(completed["status"], "completed_no_action")
            self.assertEqual(completed["assets_processed"], 2)
            self.assertEqual(completed["rejection_count"], 1)

    def test_worker_health_uses_heartbeat_freshness(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            record_worker_heartbeat(db_path, worker_id="worker-1", worker_type="background-worker")

            health = operations_health(db_path, expected_worker_interval_seconds=120)

            self.assertEqual(health["worker_health"], "healthy")
            self.assertEqual(health["overall"], "healthy")

    def test_worker_heartbeat_pulse_records_current_long_running_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"

            with WorkerHeartbeatPulse(db_path, "worker-pulse", interval_seconds=10) as pulse:
                pulse.set_job("broker-poll")

            with closing(sqlite3.connect(db_path)) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT status, current_job FROM WORKER_HEARTBEATS WHERE worker_id = ?",
                    ("worker-pulse",),
                ).fetchone()

            self.assertEqual(dict(row), {"status": "running", "current_job": "broker-poll"})

    def test_stale_worker_is_attention_needed(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_always_on_schema(db_path)
            old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
            with closing(sqlite3.connect(db_path)) as conn:
                with conn:
                    conn.execute(
                        """
                        INSERT INTO WORKER_HEARTBEATS (
                            worker_id, worker_type, started_at, last_heartbeat_at, status
                        ) VALUES ('worker-old', 'background-worker', ?, ?, 'running')
                        """,
                        (old, old),
                    )

            health = operations_health(db_path, expected_worker_interval_seconds=120)

            self.assertEqual(health["worker_health"], "not_proven")
            self.assertEqual(health["overall"], "attention_needed")

    def test_research_funnel_persists_no_trade_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            row = record_research_funnel(
                db_path,
                broker="alpaca",
                asset_type="stock",
                trigger_type="market-open-equity",
                symbols_examined=42,
                symbols_with_adequate_data=40,
                interesting_ideas=3,
                valid_strategies=1,
                committee_approved=1,
                portfolio_approved=1,
                guardrail_approved=0,
                eligible_for_paper_execution=0,
                submitted=0,
                filled=0,
                rejected=1,
                primary_reason="guardrail_rejected",
            )

            self.assertEqual(row["symbols_examined"], 42)
            self.assertEqual(row["primary_reason"], "guardrail_rejected")

    def test_shadow_trade_lifecycle_remains_separate_from_broker_orders(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            shadow = record_shadow_trade(
                db_path,
                symbol="AAPL",
                asset_type="stock",
                intended_broker="alpaca",
                decision_status="shadow_approved",
                intended_entry=100,
                stop_loss=97,
                take_profit=106,
                quantity=1,
                probability=0.85,
                strongest_argument_for="Trend and catalyst align.",
                strongest_argument_against="Market regime is uncertain.",
            )
            update_shadow_outcome(db_path, shadow["shadow_trade_id"], outcome_status="target", gross_r=2.0)
            perf = shadow_performance(db_path)

            self.assertEqual(perf["shadow_trades_total"], 1)
            self.assertEqual(perf["completed"], 1)
            self.assertEqual(perf["wins"], 1)

    def test_api_exposes_operations_endpoints(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalApiService(settings_for(tmp))
            status, payload = service.get("/operations-health", {})

            self.assertEqual(status, 200)
            self.assertIn("worker_health", payload)

    def test_scheduler_status_lists_supported_jobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            status = scheduler_status(db_path)

            self.assertIn("premarket-equity", status["supported_jobs"])
            self.assertIn("overnight-crypto", status["supported_jobs"])

    def test_alpaca_inactivity_reports_fault_without_research(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalApiService(settings_for(tmp))
            diagnosis = alpaca_inactivity_diagnosis(service.settings.db_path)

            self.assertEqual(diagnosis["expected_or_fault"], "operational_fault")
            self.assertIn("No Alpaca research records", diagnosis["plain_english"])

    def test_postgres_backend_requires_url_and_falls_back_to_sqlite_without_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            previous_backend = os.environ.get("AI_TRADER_DATABASE_BACKEND")
            previous_database_url = os.environ.get("DATABASE_URL")
            try:
                os.environ["AI_TRADER_DATABASE_BACKEND"] = "postgres"
                os.environ.pop("DATABASE_URL", None)
                status = database_backend_status(Path(tmp) / "audit.sqlite3")

                self.assertEqual(status["requested_backend"], "postgres")
                self.assertEqual(status["active_backend"], "sqlite")
                self.assertFalse(status["postgres_configured"])
            finally:
                if previous_backend is None:
                    os.environ.pop("AI_TRADER_DATABASE_BACKEND", None)
                else:
                    os.environ["AI_TRADER_DATABASE_BACKEND"] = previous_backend
                if previous_database_url is None:
                    os.environ.pop("DATABASE_URL", None)
                else:
                    os.environ["DATABASE_URL"] = previous_database_url

    def test_hosted_runtime_refuses_sqlite_startup(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = replace(
                settings_for(tmp),
                process_role="render",
                database_backend="sqlite",
                database_url=None,
            )

            errors = settings.production_startup_errors()

            self.assertEqual(len(errors), 1)
            self.assertIn("requires AI_TRADER_DATABASE_BACKEND=postgres", errors[0])

    def test_hosted_runtime_allows_configured_postgres(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = replace(
                settings_for(tmp),
                process_role="render",
                database_backend="postgres",
                database_url="postgresql://example.invalid/db",
            )

            self.assertEqual(settings.production_startup_errors(), [])


if __name__ == "__main__":
    unittest.main()
