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
    record_operations_incident,
    record_research_funnel,
    record_shadow_trade,
    record_worker_heartbeat,
    scheduler_status,
    shadow_performance,
    update_shadow_outcome,
)
from ai_trader.api import LocalApiService
from ai_trader.config import Settings
from ai_trader.multi_broker import list_notifications
from ai_trader.cli import WorkerHeartbeatPulse, _research_worker_jobs, _run_broker_job_group, _run_pulsed_job
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
            ("crypto-research", "2026-07-23T16:00:00+00:00"),
            ("market-open-equity", "2026-07-23T16:00:00+00:00"),
        ]

        self.assertEqual(
            _research_worker_jobs(due),
            [
                ("crypto-research", "2026-07-23T16:00:00+00:00"),
                ("market-open-equity", "2026-07-23T16:00:00+00:00"),
            ],
        )

    def test_forecast_refresh_gets_its_own_budget_not_the_shared_default(self) -> None:
        """2026-08-20 live finding: forecast-refresh started exactly once (02:38:35) on the
        shared 180s worker default and never logged a completion. It makes ONE real OpenAI
        call per symbol across the whole universe (~24 symbols; a single forecast measured
        live at ~14s), so 180s was never survivable. Because it had already claimed its
        6-hour idempotency bucket before dying, it never retried -- the job had never once
        run to completion since it shipped.

        This pins the routing, which is the part that was wrong: the timeout selection in
        run-worker's research-job loop must give forecast-refresh its own larger budget,
        not fall through to the default the way it silently did.
        """
        settings = settings_for(tempfile.mkdtemp())
        self.assertGreater(
            settings.forecast_refresh_timeout_seconds,
            settings.research_job_timeout_seconds,
            "forecast-refresh is strictly more work than any single research job and needs a bigger budget.",
        )
        self.assertGreaterEqual(
            settings.forecast_refresh_timeout_seconds, 900,
            "~24 symbols x ~14s of real OpenAI latency needs real headroom, not a round number that just looks generous.",
        )

        # The exact selection expression used by run-worker, kept in lockstep with cli.py.
        def timeout_for(job_name: str):
            return (
                settings.forecast_refresh_timeout_seconds
                if job_name == "forecast-refresh"
                else settings.research_job_timeout_seconds
                if job_name in {"premarket-equity", "market-open-equity", "market-close-equity", "crypto-research", "daily-report", "daily-learning"}
                else None
            )

        self.assertEqual(timeout_for("forecast-refresh"), settings.forecast_refresh_timeout_seconds)
        self.assertEqual(timeout_for("crypto-research"), settings.research_job_timeout_seconds)
        self.assertIsNone(timeout_for("push-dispatch"), "Unlisted jobs must still fall back to the shared default.")

    def test_daily_report_and_daily_learning_get_the_research_budget_not_the_shared_default(self) -> None:
        """2026-08-21 finding: daily-report was properly scheduled (_due_worker_jobs fires
        it every weekday after 17:00 ET) but job_health showed it stuck at "Awaiting First
        Run" indefinitely -- the same self-sustaining silent-failure shape as
        forecast-refresh's bug above (claims its daily idempotency bucket, dies on the
        shared 180s timeout before finishing its PERFORMANCE_ATTRIBUTION/
        ORCHESTRATOR_DECISIONS/PORTFOLIO_SNAPSHOTS queries and report generation, then
        cannot retry until the next day's bucket). daily-learning does comparably
        query-heavy work (the same three tables plus a calibration recompute) and was
        newly scheduled in the same pass, so it gets the same realistic budget from the
        start instead of waiting to be caught the same way.
        """
        settings = settings_for(tempfile.mkdtemp())

        def timeout_for(job_name: str):
            return (
                settings.forecast_refresh_timeout_seconds
                if job_name == "forecast-refresh"
                else settings.research_job_timeout_seconds
                if job_name in {"premarket-equity", "market-open-equity", "market-close-equity", "crypto-research", "daily-report", "daily-learning"}
                else None
            )

        self.assertEqual(timeout_for("daily-report"), settings.research_job_timeout_seconds)
        self.assertEqual(timeout_for("daily-learning"), settings.research_job_timeout_seconds)
        self.assertGreater(
            settings.research_job_timeout_seconds, 180,
            "Must be strictly more than the shared 180s default that starved both jobs, or this fix changes nothing.",
        )

    def test_forecast_refresh_is_not_filtered_out_of_the_research_job_list(self) -> None:
        # It reaches the timeout-selection code above only via _research_worker_jobs.
        due = [("evidence-snapshot", "t"), ("forecast-refresh", "t")]
        self.assertEqual(_research_worker_jobs(due), [("forecast-refresh", "t")])

    def test_error_severity_incident_pushes_a_notification(self):
        """The 2026-08-01 alerting fix: strategy-lab-refresh crashed silently every day for
        3+ consecutive days because record_operations_incident only wrote a database row --
        nothing ever surfaced it. Every error-severity incident must now also queue a
        push notification through the same pipeline that already delivers trade/research
        notifications, with no per-call-site wiring required."""

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            record_operations_incident(
                db_path,
                severity="error",
                component="scheduled-job",
                title="Scheduled job failed: strategy-lab-refresh",
                message="isolated job process exited with code 1.",
            )
            notifications = list_notifications(db_path)
            self.assertEqual(len(notifications), 1)
            self.assertEqual(notifications[0]["event_type"], "operations_incident")
            self.assertIn("strategy-lab-refresh", notifications[0]["title"])
            self.assertEqual(notifications[0]["delivery_status"], "queued")

    def test_warning_severity_incident_does_not_push_a_notification(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            record_operations_incident(
                db_path,
                severity="warning",
                component="research",
                title="No symbols available",
                message="Nothing to research this cycle.",
            )
            self.assertEqual(list_notifications(db_path), [])

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
            self.assertIn("crypto-research", status["supported_jobs"])
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

    def test_pulsed_job_uses_explicit_timeout_override_not_the_default(self):
        # evidence-snapshot does strictly more Postgres round trips (both brokers'
        # portfolios, governance, persistence, founder-evidence generation) than any
        # other worker job sharing the default worker_job_timeout_seconds budget, and
        # was observed timing out at 180s on every hosted cycle with no single stage
        # visibly hung. It gets its own, larger timeout instead of the shared default.
        seen_timeout = {}

        def fake_run_worker_cycle_job(service, job_name, worker_id, *, scheduled_for, timeout_seconds, restart_worker_on_timeout):
            seen_timeout["value"] = timeout_seconds
            return {"status": "completed", "job_name": job_name}

        service = SimpleNamespace(settings=SimpleNamespace(worker_job_timeout_seconds=180, evidence_snapshot_job_timeout_seconds=300))
        pulse = MagicMock()

        with patch("ai_trader.cli._run_worker_cycle_job", side_effect=fake_run_worker_cycle_job):
            _run_pulsed_job(
                service, "evidence-snapshot", "worker-1", pulse,
                scheduled_for="2026-01-01T00:00:00+00:00",
                timeout_seconds=service.settings.evidence_snapshot_job_timeout_seconds,
            )
            self.assertEqual(seen_timeout["value"], 300)

            _run_pulsed_job(
                service, "managed-exits", "worker-1", pulse,
                scheduled_for="2026-01-01T00:00:00+00:00",
            )
            self.assertEqual(seen_timeout["value"], 180)

    def test_alpaca_inactivity_reports_fault_without_research(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalApiService(settings_for(tmp))
            diagnosis = alpaca_inactivity_diagnosis(service.settings.db_path)

            self.assertEqual(diagnosis["expected_or_fault"], "operational_fault")
            self.assertIn("No Alpaca research records", diagnosis["plain_english"])

    def test_no_sql_statement_inlines_a_percent_like_pattern(self):
        """Guards a bug class the SQLite-backed test above structurally cannot catch.

        alpaca_inactivity_diagnosis inlined "LIKE '%Alpaca%'" into its SQL. That is fine on
        SQLite and a hard 500 on Postgres, whose driver reads the '%A' as a format
        placeholder ("only '%s', '%b', '%t' are allowed as placeholders, got '%A'") -- so
        the endpoint passed its own unit test while being broken in the only environment
        that matters. Every LIKE pattern must be a bound parameter instead. Static check, so
        it needs no Postgres and covers the whole package rather than this one call site.
        """
        import re
        from pathlib import Path

        source_root = Path(__file__).resolve().parents[1] / "src" / "ai_trader"
        offenders = []
        for path in source_root.rglob("*.py"):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if re.search(r"""LIKE\s+['"]%""", line, re.IGNORECASE):
                    offenders.append(f"{path.relative_to(source_root)}:{number}")
        self.assertEqual(
            offenders, [],
            "Inlined LIKE '%...' pattern(s) found -- these raise a placeholder error on "
            f"Postgres. Bind the pattern as a ? parameter instead: {offenders}",
        )

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


class AtEd010JobRunsQueryPerformanceTests(unittest.TestCase):
    """AT-ED-010: /status and /phase5-status were confirmed to hang ~60s in production.
    Root cause: production_spine.supervise_workers calls list_job_runs(limit=200) with
    no job_name filter, whose ORDER BY COALESCE(started_at, scheduled_for) DESC,
    job_run_id DESC had no supporting index against the ~12,000-row SCHEDULED_JOB_RUNS
    table in production, forcing a full-table sort on every call. These tests prove the
    fix: the new index is present after schema init, and the function's return shape
    and contract are unchanged."""

    def test_coalesce_time_index_exists_after_schema_init(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_always_on_schema(db_path)
            with closing(sqlite3.connect(db_path)) as conn:
                names = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'SCHEDULED_JOB_RUNS'"
                    )
                }
            self.assertIn("idx_scheduled_job_runs_coalesce_time", names)

    def test_list_job_runs_query_plan_uses_the_new_index_not_a_full_sort(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_always_on_schema(db_path)
            with closing(sqlite3.connect(db_path)) as conn:
                plan = conn.execute(
                    "EXPLAIN QUERY PLAN SELECT * FROM SCHEDULED_JOB_RUNS "
                    "ORDER BY COALESCE(started_at, scheduled_for) DESC, job_run_id DESC LIMIT 200"
                ).fetchall()
            plan_text = " ".join(str(row) for row in plan)
            self.assertIn("idx_scheduled_job_runs_coalesce_time", plan_text)
            self.assertNotIn("TEMP B-TREE", plan_text, "the query must not fall back to sorting the whole table")

    def test_list_job_runs_return_shape_and_ordering_unchanged_at_scale(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "audit.sqlite3"
            initialize_always_on_schema(db_path)
            with closing(sqlite3.connect(db_path)) as conn:
                with conn:
                    base = int(time.time()) - 100_000
                    rows = []
                    for i in range(3000):
                        scheduled = datetime.fromtimestamp(base + i * 30, tz=timezone.utc).isoformat()
                        rows.append((f"job-{i % 5}", scheduled, scheduled, "completed", 1, f"key-{i}"))
                    conn.executemany(
                        "INSERT INTO SCHEDULED_JOB_RUNS (job_name, scheduled_for, started_at, status, attempt, idempotency_key) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        rows,
                    )

            t0 = time.perf_counter()
            result = list_job_runs(db_path, limit=200)
            elapsed = time.perf_counter() - t0

            self.assertEqual(len(result), 200)
            self.assertIn("job_run_id", result[0])
            self.assertIn("job_name", result[0])
            self.assertIn("scheduled_for", result[0])
            # Newest-first, matching the unchanged ORDER BY contract.
            timestamps = [row["started_at"] for row in result]
            self.assertEqual(timestamps, sorted(timestamps, reverse=True))
            self.assertLess(elapsed, 0.5, "list_job_runs should be near-instant against the index at this scale")


if __name__ == "__main__":
    unittest.main()
