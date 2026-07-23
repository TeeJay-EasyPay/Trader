from __future__ import annotations

import argparse
import json
import queue
import threading
import time
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .agent import AITradingAgent
from .ai import OpenAIProposalAnalyzer
from .alpaca import AlpacaCredentials, AlpacaPaperClient, MockAlpacaPaperClient
from .audit import AuditDatabase
from .benchmark import BenchmarkIntelligenceDatabase
from .briefing import generate_daily_briefing, generate_session_brief
from .config import Settings, load_settings
from .execution import ExecutionEngine
from .intelligence import InvestmentIntelligenceDatabase
from .proposals import load_proposals, save_proposals
from .scheduler import ResearchScheduler
from .always_on import (
    claim_scheduled_job,
    complete_scheduled_job,
    default_worker_id,
    record_operations_incident,
    record_worker_heartbeat,
)
from .sprint6 import process_learning_outbox
from .production_evidence import record_learning_evidence


DEMO_MARKET_TIME = datetime(2026, 7, 2, 10, 0, tzinfo=ZoneInfo("America/New_York"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ai-trader")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("config")

    propose = sub.add_parser("propose")
    propose.add_argument("--symbols", required=True)
    propose.add_argument("--output", default="data/proposals.json")
    propose.add_argument("--demo", action="store_true")

    execute = sub.add_parser("execute")
    execute.add_argument("--proposals", required=True)
    execute.add_argument("--demo", action="store_true")

    run_once = sub.add_parser("run-once")
    run_once.add_argument("--symbols", required=True)
    run_once.add_argument("--output", default="data/proposals.json")
    run_once.add_argument("--demo", action="store_true")

    briefing = sub.add_parser("briefing")
    briefing.add_argument("--date", default=date.today().isoformat())

    morning_brief = sub.add_parser("morning-brief")
    morning_brief.add_argument("--date", default=date.today().isoformat())

    evening_brief = sub.add_parser("evening-brief")
    evening_brief.add_argument("--date", default=date.today().isoformat())

    intelligence_init = sub.add_parser("intelligence-init")
    intelligence_init.add_argument("--report", action="store_true")

    intelligence_refresh = sub.add_parser("intelligence-refresh")
    intelligence_refresh.add_argument("--date", default=date.today().isoformat())
    intelligence_refresh.add_argument("--updates")
    intelligence_refresh.add_argument("--report", action="store_true")

    sub.add_parser("intelligence-report")

    benchmark_init = sub.add_parser("benchmark-init")
    benchmark_init.add_argument("--report", action="store_true")

    serve_api = sub.add_parser("serve-api")
    serve_api.add_argument("--host", default=None)
    serve_api.add_argument("--port", default=None, type=int)

    research_once = sub.add_parser("research-once")
    research_once.add_argument("--limit", default=30, type=int)

    run_worker = sub.add_parser("run-worker")
    run_worker.add_argument("--sleep-seconds", default=60, type=int)
    run_worker.add_argument("--once", action="store_true")

    run_job = sub.add_parser("run-job")
    run_job.add_argument("job_name")
    run_job.add_argument("--scheduled-for", default=None)
    run_job.add_argument("--limit", default=30, type=int)
    run_job.add_argument("--report-type", default="daily")

    migrate_database = sub.add_parser("migrate-sqlite-to-postgres")
    migrate_database.add_argument("--source", required=True)

    args = parser.parse_args(argv)
    settings = load_settings()

    if args.command == "config":
        print(_safe_config(settings))
        return 0

    if args.command == "propose":
        audit = AuditDatabase(settings.db_path, settings.trading_log_path)
        proposals = _propose(args, settings, audit)
        save_proposals(Path(args.output), proposals)
        print(json.dumps({"proposals": len(proposals), "output": args.output}, indent=2))
        return 0

    if args.command == "execute":
        audit = AuditDatabase(settings.db_path, settings.trading_log_path)
        proposals = load_proposals(Path(args.proposals))
        results = _execute(args, settings, audit, proposals)
        print(json.dumps(results, indent=2, sort_keys=True))
        return 0

    if args.command == "run-once":
        audit = AuditDatabase(settings.db_path, settings.trading_log_path)
        proposals = _propose(args, settings, audit)
        save_proposals(Path(args.output), proposals)
        results = _execute(args, settings, audit, proposals)
        print(json.dumps({"proposals": len(proposals), "results": results}, indent=2, sort_keys=True))
        return 0

    if args.command == "briefing":
        audit = AuditDatabase(settings.db_path, settings.trading_log_path)
        report = generate_daily_briefing(audit, date.fromisoformat(args.date), settings.output_dir)
        print(report)
        return 0

    if args.command == "morning-brief":
        report = generate_session_brief(
            db_path=settings.db_path,
            output_dir=settings.output_dir,
            brief_type="morning",
            briefing_date=date.fromisoformat(args.date),
        )
        print(report)
        return 0

    if args.command == "evening-brief":
        report = generate_session_brief(
            db_path=settings.db_path,
            output_dir=settings.output_dir,
            brief_type="evening",
            briefing_date=date.fromisoformat(args.date),
        )
        print(report)
        return 0

    if args.command == "intelligence-init":
        intelligence = InvestmentIntelligenceDatabase(settings.db_path)
        result = intelligence.seed_initial_data()
        payload = {"status": "initialized", **result}
        if args.report:
            payload["report"] = str(intelligence.write_report(settings.output_dir))
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    if args.command == "intelligence-refresh":
        intelligence = InvestmentIntelligenceDatabase(settings.db_path)
        update_path = Path(args.updates) if args.updates else None
        result = intelligence.daily_refresh(date.fromisoformat(args.date), update_path)
        payload = {"status": "refreshed", **result}
        if args.report:
            payload["report"] = str(intelligence.write_report(settings.output_dir))
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    if args.command == "intelligence-report":
        intelligence = InvestmentIntelligenceDatabase(settings.db_path)
        print(intelligence.write_report(settings.output_dir))
        return 0

    if args.command == "benchmark-init":
        benchmark = BenchmarkIntelligenceDatabase(settings.db_path)
        result = benchmark.seed_initial_data()
        benchmark.write_schema_doc(Path("governance/BENCHMARK_INTELLIGENCE_SCHEMA.md"))
        payload = {"status": "initialized", **result}
        if args.report:
            payload["report"] = str(benchmark.write_initial_brief(settings.output_dir))
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    if args.command == "serve-api":
        from .api import run_server

        import os

        host = args.host or os.getenv("AI_TRADER_API_HOST", "127.0.0.1")
        port = args.port or int(os.getenv("PORT", os.getenv("AI_TRADER_API_PORT", "8765")))
        run_server(host, port, api_token=os.getenv("AI_TRADER_API_TOKEN"))
        return 0

    if args.command == "research-once":
        from .api import LocalApiService

        service = LocalApiService(settings)
        service.intelligence.seed_initial_data()
        service.benchmark.seed_initial_data()
        result = ResearchScheduler(service).run_once(limit=args.limit)
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
        return 0

    if args.command == "run-worker":
        from .api import LocalApiService

        _raise_if_invalid_hosted_runtime(settings)
        service = LocalApiService(settings)
        worker_id = default_worker_id("background-worker")
        print(json.dumps({"status": "started", "worker_id": worker_id}, indent=2))
        with WorkerHeartbeatPulse(
            settings.db_path,
            worker_id,
            interval_seconds=settings.worker_heartbeat_interval_seconds,
        ) as pulse:
            while True:
                try:
                    pulse.set_job("starting")
                    now = datetime.now(timezone.utc)
                    exits = _run_pulsed_job(
                        service,
                        "managed-exits",
                        worker_id,
                        pulse,
                        scheduled_for=_time_bucket(now, max(60, settings.auto_execution_interval_seconds)),
                    )
                    scheduled_results = {}
                    due_jobs = _due_worker_jobs(settings, now)
                    broker_poll = _run_pulsed_job(
                        service,
                        "broker-poll",
                        worker_id,
                        pulse,
                        scheduled_for=_time_bucket(now, max(300, settings.broker_poll_interval_seconds)),
                    )
                    snapshot_schedule = next((value for name, value in due_jobs if name == "evidence-snapshot"), None)
                    if snapshot_schedule:
                        scheduled_results["evidence-snapshot"] = _run_pulsed_job(
                            service,
                            "evidence-snapshot",
                            worker_id,
                            pulse,
                            scheduled_for=snapshot_schedule,
                        )
                    auto = _run_pulsed_job(
                        service,
                        "auto-execution",
                        worker_id,
                        pulse,
                        scheduled_for=_time_bucket(now, max(60, settings.auto_execution_interval_seconds)),
                    )
                    for job_name, scheduled_for in _research_worker_jobs(due_jobs):
                        scheduled_results[job_name] = _run_pulsed_job(
                            service,
                            job_name,
                            worker_id,
                            pulse,
                            scheduled_for=scheduled_for,
                        )
                    pulse.set_job("learning")
                    learning = process_learning_outbox(settings.db_path, worker_id=worker_id, limit=10)
                    if int(learning.get("processed") or 0) > 0:
                        record_learning_evidence(settings.db_path, learning, worker_id=worker_id)
                    pulse.set_job("idle")
                    record_worker_heartbeat(
                        settings.db_path,
                        worker_id=worker_id,
                        worker_type="background-worker",
                        current_job="idle",
                        last_successful_job="background-cycle",
                        payload={
                            "broker_poll": _job_summary(broker_poll),
                            "managed_exits": _job_summary(exits),
                            "auto_execution": _job_summary(auto),
                            "scheduled": {name: _job_summary(value) for name, value in scheduled_results.items()},
                            "learning": _job_summary(learning),
                        },
                    )
                except Exception as exc:  # noqa: BLE001 - worker must persist and record failures
                    pulse.set_status("degraded", current_job="background-cycle")
                    record_worker_heartbeat(
                        settings.db_path,
                        worker_id=worker_id,
                        worker_type="background-worker",
                        status="degraded",
                        current_job="background-cycle",
                        last_error=str(exc),
                    )
                    record_operations_incident(
                        settings.db_path,
                        severity="warning",
                        component="background-worker",
                        title="Background worker cycle failed",
                        message=str(exc),
                        payload={"worker_id": worker_id},
                    )
                if args.once:
                    return 0
                time.sleep(max(10, int(args.sleep_seconds)))

    if args.command == "run-job":
        from .api import LocalApiService

        _raise_if_invalid_hosted_runtime(settings)
        service = LocalApiService(settings)
        worker_id = default_worker_id("scheduled-job")
        claim = claim_scheduled_job(
            settings.db_path,
            job_name=args.job_name,
            scheduled_for=args.scheduled_for,
            worker_id=worker_id,
            assets_requested=args.limit,
            payload={"limit": args.limit},
        )
        if not claim.get("claimed"):
            print(json.dumps(claim, indent=2, sort_keys=True))
            return 0
        try:
            result = _run_named_job(service, args.job_name, limit=args.limit, report_type=args.report_type)
            status = "completed_no_action" if result.get("status") in {"skipped", "manual_required", "not_available"} else "completed"
            completed = complete_scheduled_job(settings.db_path, int(claim["job_run_id"]), status=status, result=result)
            record_worker_heartbeat(
                settings.db_path,
                worker_id=worker_id,
                worker_type="scheduled-job",
                status="completed",
                last_successful_job=args.job_name,
                payload=completed,
            )
            print(json.dumps({"job": completed, "result": result}, indent=2, sort_keys=True))
            return 0
        except Exception as exc:  # noqa: BLE001 - persist job failure before surfacing
            failed = complete_scheduled_job(settings.db_path, int(claim["job_run_id"]), status="failed", result={}, failure_reason=str(exc))
            record_operations_incident(
                settings.db_path,
                severity="error",
                component="scheduled-job",
                title=f"Scheduled job failed: {args.job_name}",
                message=str(exc),
                payload=failed,
            )
            print(json.dumps({"job": failed, "error": str(exc)}, indent=2, sort_keys=True))
            return 1

    if args.command == "migrate-sqlite-to-postgres":
        from .api import LocalApiService
        from .database_migration import migrate_sqlite_runtime_to_postgres

        _raise_if_invalid_hosted_runtime(settings)
        # Initialize every authoritative production repository before copying
        # historical rows. The migration itself refuses missing target tables.
        LocalApiService(settings)
        result = migrate_sqlite_runtime_to_postgres(Path(args.source))
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    return 1


def _run_named_job(service, job_name: str, *, limit: int, report_type: str = "daily") -> dict:
    job_name = job_name.strip().lower()
    if job_name in {"premarket-equity", "market-open-equity", "midday-equity", "market-close-equity"}:
        return service.run_analysis({"limit": limit, "trigger_type": job_name, "broker": "alpaca"})
    if job_name == "overnight-crypto":
        return service.run_crypto_analysis(limit=limit)
    if job_name == "daily-learning":
        return service.daily_learning_update(date.today().isoformat())
    if job_name in {"daily-report", "weekly-report", "monthly-report"}:
        selected_type = {"weekly-report": "weekly", "monthly-report": "monthly"}.get(job_name, report_type or "daily")
        return service.trading_report(report_date=date.today().isoformat(), broker="all", report_type=selected_type, persist=True)
    if job_name == "auto-execution":
        return service.auto_execute_recommendations()
    if job_name == "broker-poll":
        return service.poll_broker_activity()
    if job_name == "evidence-snapshot":
        return service.capture_production_broker_snapshots()
    if job_name == "managed-exits":
        return service.monitor_managed_exits()
    raise ValueError(f"Unsupported scheduled job: {job_name}")


def _run_worker_cycle_job(
    service,
    job_name: str,
    worker_id: str,
    *,
    scheduled_for: str | None = None,
    timeout_seconds: int | None = None,
) -> dict:
    scheduled_for = scheduled_for or datetime.now(timezone.utc).replace(second=0, microsecond=0).isoformat()
    claim = claim_scheduled_job(
        service.settings.db_path,
        job_name=job_name,
        scheduled_for=scheduled_for,
        worker_id=worker_id,
    )
    if not claim.get("claimed"):
        return {"status": "skipped_duplicate", "job_name": job_name}
    record_worker_heartbeat(service.settings.db_path, worker_id=worker_id, worker_type="background-worker", current_job=job_name)
    try:
        if timeout_seconds and timeout_seconds > 0:
            outcome: queue.Queue[tuple[str, object]] = queue.Queue(maxsize=1)

            def execute_job() -> None:
                try:
                    outcome.put(("result", _run_named_job(service, job_name, limit=0)))
                except BaseException as exc:  # noqa: BLE001 - move the exception to the owning worker thread
                    outcome.put(("error", exc))

            job_thread = threading.Thread(
                target=execute_job,
                name=f"worker-job-{job_name}",
                daemon=True,
            )
            job_thread.start()
            try:
                outcome_type, value = outcome.get(timeout=max(1, int(timeout_seconds)))
            except queue.Empty:
                message = f"Worker job exceeded its {int(timeout_seconds)} second execution boundary."
                timed_out = complete_scheduled_job(
                    service.settings.db_path,
                    int(claim["job_run_id"]),
                    status="timed_out",
                    result={},
                    failure_reason=message,
                )
                record_operations_incident(
                    service.settings.db_path,
                    severity="error",
                    component="background-worker",
                    title=f"Worker job timed out: {job_name}",
                    message=message,
                    payload={"worker_id": worker_id, "job": timed_out},
                )
                return {"status": "timed_out", "job_name": job_name, "reason": message}
            if outcome_type == "error":
                raise value
            result = value
        else:
            result = _run_named_job(service, job_name, limit=0)
        complete_scheduled_job(service.settings.db_path, int(claim["job_run_id"]), status="completed", result=result)
        return result
    except Exception as exc:
        complete_scheduled_job(service.settings.db_path, int(claim["job_run_id"]), status="failed", result={}, failure_reason=str(exc))
        raise


def _run_pulsed_job(service, job_name: str, worker_id: str, pulse: "WorkerHeartbeatPulse", *, scheduled_for: str) -> dict:
    pulse.set_job(job_name)
    return _run_worker_cycle_job(
        service,
        job_name,
        worker_id,
        scheduled_for=scheduled_for,
        timeout_seconds=service.settings.worker_job_timeout_seconds,
    )


class WorkerHeartbeatPulse:
    """Keep liveness evidence current while a broker or provider call is slow."""

    def __init__(self, db_path: Path, worker_id: str, *, interval_seconds: int = 30) -> None:
        self.db_path = db_path
        self.worker_id = worker_id
        self.interval_seconds = max(10, int(interval_seconds))
        self._current_job = "starting"
        self._status = "running"
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="worker-heartbeat", daemon=True)

    def __enter__(self) -> "WorkerHeartbeatPulse":
        self._write()
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self._stop.set()
        self._thread.join(timeout=self.interval_seconds + 1)

    def set_job(self, job_name: str) -> None:
        with self._lock:
            self._current_job = job_name
            self._status = "running"
        self._write()

    def set_status(self, status: str, *, current_job: str | None = None) -> None:
        with self._lock:
            self._status = status
            if current_job is not None:
                self._current_job = current_job
        self._write()

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            try:
                self._write()
            except Exception:  # The main worker records persistent failures and incidents.
                continue

    def _write(self) -> None:
        with self._lock:
            current_job = self._current_job
            status = self._status
        record_worker_heartbeat(
            self.db_path,
            worker_id=self.worker_id,
            worker_type="background-worker",
            status=status,
            current_job=current_job,
        )


def _due_worker_jobs(settings: Settings, now: datetime | None = None) -> list[tuple[str, str]]:
    """Return durable work buckets owned by the worker, independent of the mobile app."""
    now = now or datetime.now(timezone.utc)
    due = [
        (
            "evidence-snapshot",
            _time_bucket(now, max(60, settings.production_snapshot_interval_seconds)),
        )
    ]
    if not settings.worker_research_enabled:
        return due
    research_seconds = max(300, settings.research_scheduler_interval_minutes * 60)
    due.append(("overnight-crypto", _time_bucket(now, research_seconds)))
    market_now = now.astimezone(ZoneInfo("America/New_York"))
    if market_now.weekday() >= 5:
        return due
    day = market_now.date().isoformat()
    minutes = market_now.hour * 60 + market_now.minute
    if 8 * 60 <= minutes < 9 * 60 + 30:
        due.append(("premarket-equity", f"{day}T08:00:00-04:00"))
    elif 9 * 60 + 30 <= minutes < 16 * 60:
        due.append(("market-open-equity", _time_bucket(now, research_seconds)))
    elif 16 * 60 <= minutes < 17 * 60:
        due.append(("market-close-equity", f"{day}T16:00:00-04:00"))
    if minutes >= 17 * 60:
        due.append(("daily-report", f"{day}T17:00:00-04:00"))
    return due


def _research_worker_jobs(due_jobs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Defer slow research until operational truth has been published."""
    return [(name, scheduled_for) for name, scheduled_for in due_jobs if name != "evidence-snapshot"]


def _time_bucket(now: datetime, interval_seconds: int) -> str:
    epoch = int(now.timestamp())
    bucket = epoch - (epoch % interval_seconds)
    return datetime.fromtimestamp(bucket, tz=timezone.utc).isoformat()


def _job_summary(result: object) -> object:
    if not isinstance(result, dict):
        return result
    keys = ("status", "message", "reason", "processed", "submitted", "rejected", "symbols", "recommendations_created")
    summary = {key: result.get(key) for key in keys if key in result}
    if "proposals" in result and isinstance(result.get("proposals"), list):
        summary["proposal_count"] = len(result["proposals"])
    return summary or {"status": "completed", "items": len(result)}


def _raise_if_invalid_hosted_runtime(settings: Settings) -> None:
    errors = settings.production_startup_errors()
    if errors:
        raise RuntimeError("; ".join(errors))


def _propose(args: argparse.Namespace, settings: Settings, audit: AuditDatabase):
    symbols = [item.strip().upper() for item in args.symbols.split(",") if item.strip()]
    broker = _broker(settings, demo=args.demo)
    analyzer = None
    if settings.openai_api_key and not args.demo:
        analyzer = OpenAIProposalAnalyzer(settings.openai_api_key, settings.openai_model, settings.guardrails)
    agent = AITradingAgent(
        market_data=broker,
        audit=audit,
        guardrails=settings.guardrails,
        analyzer=analyzer,
    )
    now = DEMO_MARKET_TIME if args.demo else None
    return agent.propose_trades(symbols, broker.account_context(), demo=args.demo, now=now)


def _execute(args: argparse.Namespace, settings: Settings, audit: AuditDatabase, proposals):
    broker = _broker(settings, demo=args.demo)
    engine = ExecutionEngine(broker=broker, audit=audit, guardrails=settings.guardrails)
    now = DEMO_MARKET_TIME if args.demo else None
    return engine.execute_proposals(proposals, now=now)


def _broker(settings: Settings, *, demo: bool):
    if demo:
        return MockAlpacaPaperClient()
    if not settings.has_alpaca_credentials:
        raise SystemExit("Missing ALPACA_API_KEY and ALPACA_SECRET_KEY. Use --demo for local mock paper testing.")
    return AlpacaPaperClient(
        AlpacaCredentials(
            api_key=settings.alpaca_api_key or "",
            secret_key=settings.alpaca_secret_key or "",
            base_url=settings.alpaca_paper_base_url,
            data_base_url=settings.alpaca_data_base_url,
        )
    )


def _safe_config(settings: Settings) -> str:
    payload = {
        "alpaca_credentials_present": settings.has_alpaca_credentials,
        "alpaca_paper_base_url": settings.alpaca_paper_base_url,
        "alpaca_data_base_url": settings.alpaca_data_base_url,
        "openai_key_present": bool(settings.openai_api_key),
        "openai_model": settings.openai_model,
        "database_backend": settings.database_backend,
        "database_url_present": bool(settings.database_url),
        "uses_postgres": settings.uses_postgres,
        "db_path": str(settings.db_path),
        "output_dir": str(settings.output_dir),
        "trading_log_path": str(settings.trading_log_path),
        "guardrails": settings.guardrails.__dict__,
        "auto_trade": settings.auto_trade.__dict__,
        "research_scheduler_enabled": settings.research_scheduler_enabled,
        "research_scheduler_interval_minutes": settings.research_scheduler_interval_minutes,
        "research_scheduler_limit": settings.research_scheduler_limit,
    }
    return json.dumps(payload, indent=2, sort_keys=True)


if __name__ == "__main__":
    raise SystemExit(main())
