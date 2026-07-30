import sqlite3
import os
import sys
import tempfile
import time
import unittest
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_trader.always_on import (
    alpaca_inactivity_diagnosis,
    claim_scheduled_job,
    classify_worker_presence,
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
from ai_trader.cli import WorkerHeartbeatPulse, _research_worker_jobs, _run_broker_job_group
from ai_trader.models import AutoTradeConfig, GuardrailConfig
from unittest.mock import MagicMock, patch


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
            self.assertIn("broker-poll-alpaca", status["supported_jobs"])
            self.assertIn("broker-poll-kraken", status["supported_jobs"])
            self.assertIn("auto-execution-alpaca", status["supported_jobs"])
            self.assertIn("auto-execution-kraken", status["supported_jobs"])
            # The combined legacy names must not return to automatic scheduling.
            self.assertNotIn("broker-poll", status["supported_jobs"])
            self.assertNotIn("auto-execution", status["supported_jobs"])

    def test_classify_worker_presence_distinguishes_live_stale_and_historical(self):
        # AT-ED-003 corrective session, Part 3: Render never deletes a previous
        # deployment's heartbeat row, so a dead worker from an old deploy must never
        # be presented as the live scheduler merely because its row exists.
        now = datetime.now(timezone.utc)
        rows = [
            {"worker_id": "w-live", "deployment_commit": "cccccccc", "last_heartbeat_at": (now - timedelta(seconds=30)).isoformat()},
            {"worker_id": "w-recent-but-dead", "deployment_commit": "bbbbbbbb", "last_heartbeat_at": (now - timedelta(minutes=30)).isoformat()},
            {"worker_id": "w-ancient", "deployment_commit": "aaaaaaaa", "last_heartbeat_at": (now - timedelta(days=2)).isoformat()},
        ]

        classified = classify_worker_presence(rows, now=now)

        self.assertEqual(classified[0]["presence_status"], "Live")
        self.assertEqual(classified[0]["worker_id"], "w-live")
        self.assertEqual(classified[1]["presence_status"], "Historical")
        self.assertEqual(classified[2]["presence_status"], "Historical")

    def test_classify_worker_presence_marks_freshest_as_stale_when_no_worker_is_live(self):
        now = datetime.now(timezone.utc)
        rows = [
            {"worker_id": "w-old", "deployment_commit": "aaaaaaaa", "last_heartbeat_at": (now - timedelta(hours=2)).isoformat()},
        ]

        classified = classify_worker_presence(rows, now=now)

        self.assertEqual(classified[0]["presence_status"], "Stale")

    def test_scheduler_status_exposes_live_worker_not_a_stale_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_always_on_schema(db_path)
            now = datetime.now(timezone.utc)
            old = (now - timedelta(hours=3)).isoformat()
            fresh = now.isoformat()
            with closing(sqlite3.connect(db_path)) as conn:
                with conn:
                    conn.execute(
                        """INSERT INTO WORKER_HEARTBEATS (worker_id, worker_type, started_at, last_heartbeat_at, status, current_job, deployment_commit)
                        VALUES ('worker-old-deploy', 'background-worker', ?, ?, 'running', 'auto-execution', 'aaaaaaaa')""",
                        (old, old),
                    )
                    conn.execute(
                        """INSERT INTO WORKER_HEARTBEATS (worker_id, worker_type, started_at, last_heartbeat_at, status, current_job, deployment_commit)
                        VALUES ('worker-current-deploy', 'background-worker', ?, ?, 'running', 'auto-execution-alpaca', 'cccccccc')""",
                        (fresh, fresh),
                    )

            status = scheduler_status(db_path)

            self.assertEqual(status["status"], "active")
            self.assertIsNotNone(status["live_worker"])
            self.assertEqual(status["live_worker"]["worker_id"], "worker-current-deploy")
            self.assertEqual(status["live_worker"]["deployment_commit"], "cccccccc")
            self.assertEqual(status["live_worker"]["presence_status"], "Live")


class BrokerJobGroupConcurrencyTests(unittest.TestCase):
    """AT-ED-003 corrective session, Part 2: broker-poll-alpaca/-kraken and
    auto-execution-alpaca/-kraken must run as a controlled concurrent group so one
    broker's slow API cannot roughly double the worker cycle's wall-clock time, while
    each job still keeps its own independent claim, timeout, status, and failure
    reason exactly as when run sequentially."""

    def test_group_runs_jobs_concurrently_on_postgres(self):
        job_calls: list[tuple[str, str, float]] = []

        def fake_run_worker_cycle_job(service, job_name, worker_id, *, scheduled_for, timeout_seconds, restart_worker_on_timeout):
            job_calls.append(("start", job_name, time.monotonic()))
            time.sleep(0.25)
            job_calls.append(("end", job_name, time.monotonic()))
            return {"status": "completed", "job_name": job_name}

        service = SimpleNamespace(settings=SimpleNamespace(worker_job_timeout_seconds=180))
        pulse = MagicMock()

        with (
            patch("ai_trader.cli.selected_backend", return_value="postgres"),
            patch("ai_trader.cli._run_worker_cycle_job", side_effect=fake_run_worker_cycle_job),
        ):
            start = time.monotonic()
            results = _run_broker_job_group(
                service, "broker-poll", ["broker-poll-alpaca", "broker-poll-kraken"],
                "worker-1", pulse, scheduled_for="2026-01-01T00:00:00+00:00",
            )
            elapsed = time.monotonic() - start

        # Sequential would take ~0.5s (2 x 0.25s); concurrent stays close to 0.25s.
        self.assertLess(elapsed, 0.45)
        self.assertEqual(results["broker-poll-alpaca"]["status"], "completed")
        self.assertEqual(results["broker-poll-kraken"]["status"], "completed")
        # Both jobs must have started before either finished -- proof of real overlap,
        # not two fast sequential calls that happen to land under the time budget.
        starts = {name: t for kind, name, t in job_calls if kind == "start"}
        ends = {name: t for kind, name, t in job_calls if kind == "end"}
        self.assertLess(starts["broker-poll-kraken"], ends["broker-poll-alpaca"])

    def test_group_isolates_one_jobs_timeout_from_the_others_result(self):
        def fake_run_worker_cycle_job(service, job_name, worker_id, *, scheduled_for, timeout_seconds, restart_worker_on_timeout):
            if job_name == "auto-execution-kraken":
                time.sleep(0.05)
                return {"status": "timed_out", "job_name": job_name, "reason": "Worker job exceeded its 180 second execution boundary."}
            return {"status": "completed", "job_name": job_name, "eligible_count": 1}

        service = SimpleNamespace(settings=SimpleNamespace(worker_job_timeout_seconds=180))
        pulse = MagicMock()

        with (
            patch("ai_trader.cli.selected_backend", return_value="postgres"),
            patch("ai_trader.cli._run_worker_cycle_job", side_effect=fake_run_worker_cycle_job),
        ):
            results = _run_broker_job_group(
                service, "auto-execution", ["auto-execution-alpaca", "auto-execution-kraken"],
                "worker-1", pulse, scheduled_for="2026-01-01T00:00:00+00:00",
            )

        # A timed-out Kraken job must not change Alpaca's own completed status.
        self.assertEqual(results["auto-execution-alpaca"]["status"], "completed")
        self.assertEqual(results["auto-execution-kraken"]["status"], "timed_out")

    def test_group_falls_back_to_sequential_execution_off_postgres(self):
        call_order: list[str] = []

        def fake_run_worker_cycle_job(service, job_name, worker_id, *, scheduled_for, timeout_seconds, restart_worker_on_timeout):
            call_order.append(job_name)
            return {"status": "completed", "job_name": job_name}

        service = SimpleNamespace(settings=SimpleNamespace(worker_job_timeout_seconds=180))
        pulse = MagicMock()

        with (
            patch("ai_trader.cli.selected_backend", return_value="sqlite"),
            patch("ai_trader.cli._run_worker_cycle_job", side_effect=fake_run_worker_cycle_job),
        ):
            results = _run_broker_job_group(
                service, "broker-poll", ["broker-poll-alpaca", "broker-poll-kraken"],
                "worker-1", pulse, scheduled_for="2026-01-01T00:00:00+00:00",
            )

        self.assertEqual(call_order, ["broker-poll-alpaca", "broker-poll-kraken"])
        self.assertEqual(results["broker-poll-alpaca"]["status"], "completed")
        self.assertEqual(results["broker-poll-kraken"]["status"], "completed")

    def test_group_members_each_keep_independent_scheduled_job_claim(self):
        # The real duplicate-prevention mechanism: claim_scheduled_job's idempotency
        # key is job_name:scheduled_for, so each job in a group is claimed
        # independently and a second concurrent attempt at the same job_name and
        # scheduled_for is skipped as a duplicate, not run twice.
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            scheduled_for = "2026-01-01T00:00:00+00:00"
            first_alpaca = claim_scheduled_job(db_path, job_name="broker-poll-alpaca", scheduled_for=scheduled_for, worker_id="w1")
            second_alpaca = claim_scheduled_job(db_path, job_name="broker-poll-alpaca", scheduled_for=scheduled_for, worker_id="w2")
            first_kraken = claim_scheduled_job(db_path, job_name="broker-poll-kraken", scheduled_for=scheduled_for, worker_id="w1")

            self.assertTrue(first_alpaca["claimed"])
            self.assertFalse(second_alpaca["claimed"])
            self.assertEqual(second_alpaca["status"], "skipped_duplicate")
            # A different broker's job at the same scheduled_for is a distinct
            # idempotency key and claims independently.
            self.assertTrue(first_kraken["claimed"])
            self.assertNotEqual(first_alpaca["job_run_id"], first_kraken["job_run_id"])

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

    def test_database_backend_status_selects_postgres_from_database_url_alone(self):
        # Regression guard for the backend-selection consolidation: database_backend_status()
        # must now agree with database.py:selected_backend() when only DATABASE_URL is set and
        # AI_TRADER_DATABASE_BACKEND is absent. Before the fix, always_on.py's independent
        # _use_postgres() defaulted to "sqlite" in exactly this scenario.
        with tempfile.TemporaryDirectory() as tmp:
            previous_backend = os.environ.get("AI_TRADER_DATABASE_BACKEND")
            previous_database_url = os.environ.get("DATABASE_URL")
            try:
                os.environ.pop("AI_TRADER_DATABASE_BACKEND", None)
                os.environ["DATABASE_URL"] = "postgresql://example.invalid/db"
                status = database_backend_status(Path(tmp) / "audit.sqlite3")

                self.assertEqual(status["requested_backend"], "postgres")
                self.assertEqual(status["active_backend"], "postgres")
                self.assertTrue(status["postgres_configured"])
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
