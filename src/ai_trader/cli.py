from __future__ import annotations

import argparse
import json
import queue
import subprocess
import sys
import threading
import traceback
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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
from .database import selected_backend
from .execution import ExecutionEngine
from .external_intelligence import run_external_intelligence_refresh
from .intelligence import InvestmentIntelligenceDatabase
from .proposals import load_proposals, save_proposals
from .scheduler import ResearchScheduler
from .always_on import (
    claim_scheduled_job,
    complete_scheduled_job,
    default_worker_id,
    get_scheduled_job_run,
    record_operations_incident,
    record_worker_heartbeat,
)
from .sprint6 import process_learning_outbox
from .production_evidence import record_learning_evidence
from .kraken_reconciliation import replay_persisted_kraken_evidence


DEMO_MARKET_TIME = datetime(2026, 7, 2, 10, 0, tzinfo=ZoneInfo("America/New_York"))


class WorkerJobTimeout(RuntimeError):
    """Backward-compatible timeout type retained for external imports."""


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
    run_job.add_argument("--claimed-job-run-id", default=None, type=int, help=argparse.SUPPRESS)
    run_job.add_argument("--worker-id", default=None, help=argparse.SUPPRESS)

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
        # 2026-08-14 incident: nothing in the production run-worker startup path ever called
        # seed_initial_data() -- it only ran once, manually, via the standalone
        # `intelligence-init` CLI command when this deployment was first set up. Editing
        # intelligence_data.py's COMPANIES list (e.g. adding real Alpaca-tradable candidates)
        # had zero effect in production: COMPANY_MASTER stayed frozen at whatever it held from
        # that one-time seed, forever, across every subsequent deploy and restart. seed_initial_
        # data() is an idempotent upsert (ON CONFLICT DO UPDATE per ticker+exchange, matches
        # research-once's own pattern below) -- safe and cheap to run on every worker startup,
        # so watchlist edits actually take effect on the next deploy without a manual step.
        service.intelligence.seed_initial_data()
        # 2026-08-21: the identical gap, missed here -- service.benchmark.seed_initial_data()
        # was never added alongside the fix above, even though research-once (below) has
        # always called both together. BENCHMARK_TRADERS happened to already be populated in
        # this deployment from a past manual benchmark-init run, so this was not the cause of
        # the due-diligence finding it was found alongside (see benchmark.py's
        # record_daily_research, ai.py's BenchmarkResearchAnalyzer) -- but a genuinely fresh
        # database would have had an empty BENCHMARK_TRADERS table with no automatic recovery.
        # Same idempotent-upsert safety as the call above.
        service.benchmark.seed_initial_data()
        worker_id = default_worker_id("background-worker")
        print(json.dumps({"status": "started", "worker_id": worker_id}, indent=2))
        with (
            # 2026-08-19 Founder-directed fix: evidence-snapshot runs on its own thread/timer
            # here, independent of the main loop below -- see EvidenceSnapshotScheduler's
            # docstring for why the old in-loop scheduling left the mobile app reading stale
            # for part of every cycle.
            EvidenceSnapshotScheduler(
                service,
                worker_id,
                interval_seconds=settings.production_snapshot_interval_seconds,
            ),
            WorkerHeartbeatPulse(
                settings.db_path,
                worker_id,
                interval_seconds=settings.worker_heartbeat_interval_seconds,
            ) as pulse,
        ):
            pulse.set_job("kraken-startup-reconciliation")
            try:
                startup_reconciliation = _run_pulsed_job(
                    service,
                    "kraken-startup-reconciliation",
                    worker_id,
                    pulse,
                    scheduled_for=_time_bucket(
                        datetime.now(timezone.utc),
                        max(60, settings.kraken_startup_reconciliation_timeout_seconds),
                    ),
                    timeout_seconds=settings.kraken_startup_reconciliation_timeout_seconds,
                )
            except Exception as exc:  # noqa: BLE001 - preserve worker availability and surface the fault
                startup_reconciliation = {
                    "status": "failed",
                    "error": str(exc),
                    "broker_orders_submitted": 0,
                }
                pulse.set_status("degraded", current_job="kraken-startup-reconciliation")
                record_operations_incident(
                    settings.db_path,
                    severity="warning",
                    component="kraken-reconciliation",
                    title="Kraken startup reconciliation failed",
                    message=str(exc),
                    payload={
                        "worker_id": worker_id,
                        "new_entries_remain_paused": True,
                        "broker_orders_submitted": 0,
                    },
                )
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
                    # broker-poll and auto-execution are scheduled per broker so
                    # one broker's slow API or transient failure cannot delay or
                    # starve the other broker's cycle, and each broker gets its
                    # own run-history/idempotency trail (AT-ED-003 Section 1 items
                    # 3-4). The old combined "broker-poll"/"auto-execution" job
                    # names are retired from this automatic loop; they remain
                    # dispatchable only for manual/debug `run-job` invocation.
                    # Alpaca and Kraken are independent brokers with no shared state,
                    # so each pair runs as a controlled concurrent group (Postgres
                    # only) instead of strictly sequentially -- this was confirmed to
                    # roughly double worker-cycle wall-clock time when run
                    # sequentially, delaying evidence-snapshot/managed-exits/etc. far
                    # past their configured cadence (AT-ED-003 corrective session).
                    broker_poll_results = _run_broker_job_group(
                        service,
                        "broker-poll",
                        ["broker-poll-alpaca", "broker-poll-kraken"],
                        worker_id,
                        pulse,
                        scheduled_for=_time_bucket(now, max(300, settings.broker_poll_interval_seconds)),
                    )
                    broker_poll_alpaca = broker_poll_results["broker-poll-alpaca"]
                    broker_poll_kraken = broker_poll_results["broker-poll-kraken"]
                    # evidence-snapshot no longer runs here as of 2026-08-19 -- it has its
                    # own independent scheduler (EvidenceSnapshotScheduler, started alongside
                    # this loop in the run-worker command) so its cadence never has to wait
                    # for this loop's own jobs to finish. See that class's docstring.
                    auto_execution_results = _run_broker_job_group(
                        service,
                        "auto-execution",
                        ["auto-execution-alpaca", "auto-execution-kraken"],
                        worker_id,
                        pulse,
                        scheduled_for=_time_bucket(now, max(60, settings.auto_execution_interval_seconds)),
                        # trade_audit candidates are evaluated one at a time through the full
                        # Strategy/Portfolio/Risk/Sentinel governance chain (~50-55s each even
                        # after fixing the schema-reinit costs found 2026-08-01) -- the shared
                        # 180s default gave auto-execution-kraken time for only 1-2 of up to 47
                        # queued candidates before every single run timed out.
                        timeout_seconds=service.settings.auto_execution_job_timeout_seconds,
                    )
                    auto_alpaca = auto_execution_results["auto-execution-alpaca"]
                    auto_kraken = auto_execution_results["auto-execution-kraken"]
                    # Runs in the worker's own job loop, not the API's background-worker
                    # set, because AI_TRADER_DISABLE_API_BACKGROUND_WORKERS=true on every
                    # hosted service means that set never starts in production -- without
                    # this, no incident or trade notification the system records ever
                    # actually reaches the Founder's phone (CRITICAL_REMEDIATION_PLAN.md P0-5).
                    push = _run_pulsed_job(
                        service,
                        "push-dispatch",
                        worker_id,
                        pulse,
                        scheduled_for=_time_bucket(now, 30),
                    )
                    for job_name, scheduled_for in _research_worker_jobs(due_jobs):
                        scheduled_results[job_name] = _run_pulsed_job(
                            service,
                            job_name,
                            worker_id,
                            pulse,
                            scheduled_for=scheduled_for,
                            # Equity/crypto research evaluates up to 30 symbols, each
                            # potentially a real OpenAI call, on top of the same ~120s
                            # fixed subprocess overhead evidence-snapshot has -- the
                            # shared default budget left it with no realistic chance of
                            # completing before generating a single proposal (2026-07-31
                            # follow-up: same root cause class as evidence-snapshot).
                            # forecast-refresh needs its own, larger budget again: it is
                            # one real OpenAI call per symbol across the whole universe,
                            # which is strictly more work than any single research job.
                            # Confirmed live 2026-08-20 -- on the shared 180s default it
                            # started once and never completed, and having already claimed
                            # its 6-hour bucket it never retried, so it had never run to
                            # completion since shipping.
                            # 2026-08-21: daily-report was in this exact same trap -- properly
                            # scheduled (see _due_worker_jobs above) but stuck on job_health's
                            # "Awaiting First Run" indefinitely, the same self-sustaining
                            # silent-failure shape as forecast-refresh's bug (claims its daily
                            # idempotency bucket, dies on the shared 180s timeout before
                            # finishing its PERFORMANCE_ATTRIBUTION/ORCHESTRATOR_DECISIONS/
                            # PORTFOLIO_SNAPSHOTS queries and report generation, then cannot
                            # retry until the next day's bucket). daily-learning is newly
                            # scheduled in this same pass and does comparably query-heavy work
                            # (the same three tables plus a calibration recompute), so it gets
                            # the same realistic budget from the start rather than waiting to
                            # be caught the same way.
                            # benchmark-research-refresh: 4 real OpenAI calls with the
                            # web_search_preview tool (BenchmarkResearchAnalyzer, ai.py),
                            # each bounded at 60s client-side -- ~240s worst case, well
                            # inside the same research budget the other query/LLM-heavy
                            # jobs above already get.
                            timeout_seconds=(
                                service.settings.forecast_refresh_timeout_seconds
                                if job_name == "forecast-refresh"
                                else service.settings.research_job_timeout_seconds
                                if job_name in {"premarket-equity", "market-open-equity", "market-close-equity", "crypto-research", "daily-report", "daily-learning", "benchmark-research-refresh", "external-intelligence-refresh"}
                                # 2026-08-23: external-intelligence-refresh timed out on the
                                # shared 180s budget. It makes many small sequential HTTP
                                # calls in one run -- SEC EDGAR per symbol, Alpaca News
                                # across the watchlist, a FRED series each, plus the crypto
                                # RSS feeds -- so it belongs with the other multi-call jobs,
                                # not on the default meant for single-query work. Same
                                # reasoning that already moved forecast-refresh and
                                # benchmark-research-refresh off the shared budget.
                                else None
                            ),
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
                            "broker_poll_alpaca": _job_summary(broker_poll_alpaca),
                            "broker_poll_kraken": _job_summary(broker_poll_kraken),
                            "managed_exits": _job_summary(exits),
                            "auto_execution_alpaca": _job_summary(auto_alpaca),
                            "auto_execution_kraken": _job_summary(auto_kraken),
                            "push_dispatch": _job_summary(push),
                            "scheduled": {name: _job_summary(value) for name, value in scheduled_results.items()},
                            "learning": _job_summary(learning),
                            "kraken_startup_reconciliation": _job_summary(startup_reconciliation),
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
        worker_id = args.worker_id or default_worker_id("scheduled-job")
        if args.claimed_job_run_id is not None:
            claim = {
                "claimed": True,
                "job_run_id": int(args.claimed_job_run_id),
                "message": "Executing a job already claimed by the worker supervisor.",
            }
        else:
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
            # 2026-08-24: str(exc) alone loses where it happened -- an Alpaca 422 read as
            # a bare message with no indication of which candidate or which call raised it.
            # The traceback is what turns "the job failed" into a fix, and the child process
            # is the only place that still has one.
            detail = f"{exc}\n{traceback.format_exc()}"
            failed = complete_scheduled_job(settings.db_path, int(claim["job_run_id"]), status="failed", result={}, failure_reason=detail[:4000])
            record_operations_incident(
                settings.db_path,
                severity="error",
                component="scheduled-job",
                title=f"Scheduled job failed: {args.job_name}",
                message=detail[:4000],
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
    if job_name == "crypto-research":
        return service.run_crypto_analysis(limit=limit)
    if job_name == "rejection-outcome-review":
        return service.review_crypto_rejections()
    if job_name == "rejection-outcome-rollup":
        return service.rollup_crypto_rejections()
    if job_name == "daily-learning":
        return service.daily_learning_update(date.today().isoformat())
    if job_name in {"daily-report", "weekly-report", "monthly-report"}:
        selected_type = {"weekly-report": "weekly", "monthly-report": "monthly"}.get(job_name, report_type or "daily")
        return service.trading_report(report_date=date.today().isoformat(), broker="all", report_type=selected_type, persist=True)
    if job_name == "auto-execution":
        # Retired from automatic scheduling in favor of the broker-specific jobs
        # below (AT-ED-003 Section 1 item 4). Left dispatchable for manual/debug
        # `run-job` invocation only -- the worker loop never calls this name.
        return service.auto_execute_recommendations()
    if job_name == "auto-execution-alpaca":
        return service.auto_execute_recommendations_alpaca()
    if job_name == "auto-execution-kraken":
        return service.auto_execute_recommendations_kraken()
    if job_name == "broker-poll":
        # Retired from automatic scheduling in favor of the broker-specific jobs
        # below (AT-ED-003 Section 1 item 3). Left dispatchable for manual/debug
        # `run-job` invocation only -- the worker loop never calls this name.
        return service.poll_broker_activity()
    if job_name == "broker-poll-alpaca":
        return service.poll_broker_activity_alpaca()
    if job_name == "broker-poll-kraken":
        return service.poll_broker_activity_kraken()
    if job_name == "evidence-snapshot":
        return service.capture_production_broker_snapshots()
    if job_name == "managed-exits":
        return service.monitor_managed_exits()
    if job_name == "kraken-startup-reconciliation":
        return replay_persisted_kraken_evidence(service.settings.db_path)
    if job_name == "push-dispatch":
        return service.dispatch_pending_push_notifications()
    if job_name == "strategy-lab-refresh":
        return service.refresh_strategy_lab()
    if job_name == "crypto-universe-refresh":
        return service.refresh_crypto_universe()
    if job_name == "crypto-candle-refresh":
        return service.refresh_crypto_candle_history()
    if job_name == "forecast-refresh":
        return service.refresh_market_forecasts()
    if job_name == "benchmark-research-refresh":
        return service.refresh_benchmark_research()
    if job_name == "external-intelligence-refresh":
        # A true no-op (no HTTP calls, no writes) whenever
        # settings.external_intelligence_enabled is False -- see
        # run_external_intelligence_refresh's own docstring.
        return run_external_intelligence_refresh(service.settings.db_path, service.settings)
    raise ValueError(f"Unsupported scheduled job: {job_name}")


def _run_worker_cycle_job(
    service,
    job_name: str,
    worker_id: str,
    *,
    scheduled_for: str | None = None,
    timeout_seconds: int | None = None,
    restart_worker_on_timeout: bool = False,
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
        if restart_worker_on_timeout and timeout_seconds and timeout_seconds > 0:
            process_result = _run_claimed_job_process(
                job_name=job_name,
                job_run_id=int(claim["job_run_id"]),
                worker_id=worker_id,
                timeout_seconds=max(1, int(timeout_seconds)),
            )
            if process_result["status"] == "timed_out":
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
                    payload={
                        "worker_id": worker_id,
                        "job": timed_out,
                        "child_process_terminated": True,
                    },
                )
                return {"status": "timed_out", "job_name": job_name, "reason": message}
            if process_result["status"] != "completed":
                # 2026-08-24: the child already records the real failure (its own except
                # branch writes failure_reason and an operations incident) -- and this
                # message then overwrote it, so the job run read "exited with code 1" and
                # nothing else. The actual cause that night was an Alpaca 422, "fractional
                # orders must be DAY orders", recoverable only because the incident row
                # survived alongside the clobbered job run. Prefer what the child said; it
                # knows what happened and this frame does not.
                child_run = get_scheduled_job_run(service.settings.db_path, int(claim["job_run_id"])) or {}
                child_reason = child_run.get("failure_reason")
                raise RuntimeError(
                    f"{job_name}: {child_reason}" if child_reason
                    else f"{job_name}: isolated job process exited with code {process_result.get('returncode')}."
                )
            completed = get_scheduled_job_run(service.settings.db_path, int(claim["job_run_id"]))
            if completed.get("status") == "failed":
                raise RuntimeError(
                    f"{job_name}: {completed.get('failure_reason') or 'isolated job failed'}"
                )
            return completed
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


def _run_claimed_job_process(
    *,
    job_name: str,
    job_run_id: int,
    worker_id: str,
    timeout_seconds: int,
) -> dict:
    """Run one already-claimed job in a process that can be stopped safely.

    Child stdout/stderr are inherited (not discarded) so job output reaches Render's log
    viewer, and "-u" keeps the child unbuffered so output is flushed as it happens rather than
    lost if the process is later killed on timeout. This function itself only logs the
    started/completed/failed/timed-out envelope around the child process, since it is the only
    place that actually observes a timeout firing; job-internal detail (symbols processed,
    proposals generated, etc.) is logged by the job's own code, inside the child.
    """
    command = [
        sys.executable,
        "-u",
        "-m",
        "ai_trader",
        "run-job",
        job_name,
        "--claimed-job-run-id",
        str(int(job_run_id)),
        "--worker-id",
        worker_id,
        "--limit",
        "0",
    ]
    print(f"[worker] job={job_name} run_id={job_run_id} status=started timeout={int(timeout_seconds)}s", flush=True)
    start = time.monotonic()
    process = subprocess.Popen(command)
    try:
        returncode = process.wait(timeout=max(1, int(timeout_seconds)))
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
        elapsed = time.monotonic() - start
        print(f"[worker] job={job_name} run_id={job_run_id} status=timed_out elapsed={elapsed:.1f}s", flush=True)
        return {"status": "timed_out", "returncode": process.returncode}
    elapsed = time.monotonic() - start
    status = "completed" if returncode == 0 else "failed"
    print(f"[worker] job={job_name} run_id={job_run_id} status={status} elapsed={elapsed:.1f}s returncode={returncode}", flush=True)
    return {
        "status": status,
        "returncode": returncode,
    }


def _run_pulsed_job(
    service,
    job_name: str,
    worker_id: str,
    pulse: "WorkerHeartbeatPulse",
    *,
    scheduled_for: str,
    timeout_seconds: int | None = None,
) -> dict:
    pulse.set_job(job_name)
    return _run_worker_cycle_job(
        service,
        job_name,
        worker_id,
        scheduled_for=scheduled_for,
        timeout_seconds=timeout_seconds or service.settings.worker_job_timeout_seconds,
        restart_worker_on_timeout=True,
    )


def _run_broker_job_group(
    service,
    group_name: str,
    job_names: list[str],
    worker_id: str,
    pulse: "WorkerHeartbeatPulse",
    *,
    scheduled_for: str,
    timeout_seconds: int | None = None,
) -> dict[str, dict]:
    """Run independent broker-specific jobs concurrently within one named group.

    Each job keeps its own scheduled-job claim (own idempotency key job_name:scheduled_for),
    own isolated subprocess, own timeout, own status, and own failure reason -- identical to
    running _run_pulsed_job sequentially. Only the wait is concurrent: a slow or failed Kraken
    job cannot block, delay, or change the completion status of the Alpaca job in the same
    group, and vice versa (each job's timeout clock starts independently when its own thread
    starts waiting on its own subprocess). Concurrency is only used to shrink worker-cycle
    wall-clock time; it introduces no new shared mutable state between jobs, since each job
    still runs in its own OS process exactly as before.

    Postgres only: SQLite (local dev/tests) has no busy-timeout configured, so concurrent
    writers from separate subprocesses can raise "database is locked". This mirrors the same
    guard already used for the concurrent Alpaca/Kraken portfolio fetch in
    capture_production_broker_snapshots().
    """
    pulse.set_job(f"{group_name}[{'+'.join(job_names)}]")
    print(f"[worker] group={group_name} status=started jobs={','.join(job_names)}", flush=True)
    group_start = time.monotonic()
    effective_timeout = timeout_seconds if timeout_seconds is not None else service.settings.worker_job_timeout_seconds
    results: dict[str, dict] = {}
    if selected_backend() != "postgres":
        for job_name in job_names:
            job_start = time.monotonic()
            results[job_name] = _run_worker_cycle_job(
                service, job_name, worker_id,
                scheduled_for=scheduled_for,
                timeout_seconds=effective_timeout,
                restart_worker_on_timeout=True,
            )
            print(f"[worker] group={group_name} job={job_name} status={results[job_name].get('status')} elapsed={time.monotonic() - job_start:.1f}s", flush=True)
    else:
        job_starts = {job_name: time.monotonic() for job_name in job_names}
        with ThreadPoolExecutor(max_workers=len(job_names)) as pool:
            futures = {
                pool.submit(
                    _run_worker_cycle_job, service, job_name, worker_id,
                    scheduled_for=scheduled_for,
                    timeout_seconds=effective_timeout,
                    restart_worker_on_timeout=True,
                ): job_name
                for job_name in job_names
            }
            for future in as_completed(futures):
                job_name = futures[future]
                try:
                    results[job_name] = future.result()
                except Exception as exc:  # noqa: BLE001 - isolate one job's failure from the rest of the group
                    results[job_name] = {"status": "failed", "job_name": job_name, "reason": str(exc)}
                print(f"[worker] group={group_name} job={job_name} status={results[job_name].get('status')} elapsed={time.monotonic() - job_starts[job_name]:.1f}s", flush=True)
    elapsed = time.monotonic() - group_start
    summary = {job_name: results[job_name].get("status") for job_name in job_names}
    print(f"[worker] group={group_name} status=completed elapsed={elapsed:.1f}s results={summary}", flush=True)
    return results


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


class EvidenceSnapshotScheduler:
    """Runs evidence-snapshot on its own independent timer, off the main worker loop.

    2026-08-19 Founder-directed fix. Two compounding problems, confirmed live the same day:
    (1) production_snapshot_interval_seconds defaulted to 1200s (20 min) while the mobile
    app's own staleness threshold (FOUNDER_SNAPSHOT_MAX_AGE_SECONDS, production_evidence.py)
    is 900s (15 min) -- a snapshot refreshing every 20 minutes against a 15-minute staleness
    bar guarantees the app reads "stale" for part of every cycle, by construction, regardless
    of how fast anything else runs. (2) even a correctly-configured interval only got a
    chance to fire once per lap of the shared sequential `while True:` worker loop -- and
    that lap's OTHER jobs (auto-execution, research) routinely took 20-40+ minutes once real
    trading activity was happening (confirmed live: auto-execution-alpaca 582s,
    crypto-research 242s, market-open-equity still running past 11 minutes, same day), so
    evidence-snapshot's own turn arrived far less often than even the misconfigured interval
    intended.

    Runs on its own daemon thread with its own timer, calling the exact same
    _run_worker_cycle_job() the main loop used to call inline -- same idempotency claiming,
    subprocess isolation, and timeout enforcement, just no longer waiting behind whatever the
    main loop's other jobs are doing. Safe to run concurrently with the main loop: every
    write in this codebase already opens its own database connection per call (no shared
    connection state across threads), the same property that already lets
    auto-execution-alpaca/-kraken run concurrently via _run_broker_job_group.
    """

    def __init__(self, service, worker_id: str, *, interval_seconds: int) -> None:
        self.service = service
        self.worker_id = worker_id
        self.interval_seconds = max(60, int(interval_seconds))
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="evidence-snapshot-scheduler", daemon=True)

    def __enter__(self) -> "EvidenceSnapshotScheduler":
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self._stop.set()
        self._thread.join(timeout=self.interval_seconds + 30)

    def _run(self) -> None:
        while True:
            try:
                now = datetime.now(timezone.utc)
                result = _run_worker_cycle_job(
                    self.service,
                    "evidence-snapshot",
                    self.worker_id,
                    scheduled_for=_time_bucket(now, self.interval_seconds),
                    timeout_seconds=self.service.settings.evidence_snapshot_job_timeout_seconds,
                    restart_worker_on_timeout=True,
                )
                print(f"[evidence-snapshot-scheduler] status={result.get('status')}", flush=True)
            except Exception as exc:  # noqa: BLE001 - one failed cycle must never kill this thread
                print(f"[evidence-snapshot-scheduler] status=failed error={exc!r}", flush=True)
            if self._stop.wait(self.interval_seconds):
                return


def _due_worker_jobs(settings: Settings, now: datetime | None = None) -> list[tuple[str, str]]:
    """Return durable work buckets owned by the worker, independent of the mobile app.

    evidence-snapshot is deliberately NOT included here as of 2026-08-19 -- it now runs on
    its own independent timer (EvidenceSnapshotScheduler) rather than waiting for a turn in
    this shared sequential loop's due-jobs list. See that class's docstring for why.
    """
    now = now or datetime.now(timezone.utc)
    due: list[tuple[str, str]] = []
    if not settings.worker_research_enabled:
        return due
    research_seconds = max(300, settings.research_scheduler_interval_minutes * 60)
    # 2026-08-22: this job existed only as an IntervalWorker inside the API process, and
    # hosted production runs the API with AI_TRADER_DISABLE_BACKGROUND_WORKERS set -- so it
    # had never actually run anywhere. Without it CRYPTO_MASTER is never populated from the
    # live public universe, and crypto-research silently falls back to the handful of pairs
    # in KRAKEN_ALLOWED_PAIRS. Confirmed live: 33 of the last 50 notifications were that
    # "approved-pair fallback", with research examining 9 symbols an hour and producing
    # essentially zero ideas. Listed BEFORE crypto-research so that on any cycle where both
    # are due, the shopping list is refreshed before research reads it.
    due.append(("crypto-universe-refresh", _time_bucket(now, research_seconds)))
    # Phase 1 of the CIO-level forecasting build (2026-08-20): real Kraken OHLC candle
    # ingestion. Crypto-only, hourly, on a plain UTC clock like crypto-research below
    # (crypto trades 24/7, so this must not be gated behind the NYSE weekday check
    # further down).
    #
    # 2026-08-28: MOVED ABOVE crypto-research, for exactly the reason the universe refresh
    # above it already gives. This job was originally "purely additive -- writes to
    # MARKET_DATA_OBSERVATIONS, which nothing else reads yet", so its position did not
    # matter. It now also writes CRYPTO_RESEARCH_SCORES, which crypto-research reads to
    # decide what to propose, and leaving it below meant every proposal was judged on scores
    # from the PREVIOUS hour.
    #
    # Confirmed live: research ran at 17:45 on scores written at 15:42-16:39 and rejected all
    # 19 coins, while the fresh scores carrying real order-book liquidity landed at 17:47 --
    # two minutes too late to be used. A permanent one-cycle lag, not a one-off, and my own
    # regression from making this job do the scoring.
    due.append(("crypto-candle-refresh", _time_bucket(now, 3600)))
    due.append(("crypto-research", _time_bucket(now, research_seconds)))
    # Phase 3 of the CIO-level forecasting build (2026-08-20): real CIO-style market
    # forecasts. Every 6 hours, not hourly -- each symbol costs a real OpenAI call, and a
    # multi-day directional view does not meaningfully change within an hour. Covers both
    # asset classes, so like crypto-candle-refresh it sits above the NYSE weekday gate.
    due.append(("forecast-refresh", _time_bucket(now, 6 * 3600)))
    if settings.external_intelligence_enabled:
        # Hourly, same bucket cadence as crypto-research's default. The job itself
        # is also a defensive no-op when the flag is off (see
        # run_external_intelligence_refresh), but there is no reason to even claim
        # a scheduled-job slot for it every cycle while a human has it switched off.
        due.append(("external-intelligence-refresh", _time_bucket(now, 3600)))
    # Crypto-only, so scheduled on a plain UTC clock rather than the NYSE calendar the
    # equity jobs below use -- crypto research (and therefore its rejections) runs
    # every day, weekends included. Bounded 1-hour windows (not "rest of day" the way
    # daily-report/strategy-lab-refresh below are) to avoid claiming a job slot on
    # nearly every one of the day's worker cycles for something that only needs to
    # run once; a missed window just means it runs the following day/month instead.
    # 2026-08-21 Founder-directed fix: real, web-grounded benchmark-trader research
    # (BenchmarkResearchAnalyzer, ai.py) replacing the static one-time-seeded content
    # that was silently blocking every Alpaca due-diligence assessment --
    # _behavioural_context_available (foundation.py) only reports "completed" for a row
    # dated exactly today, and nothing ever wrote one before this. This only affects
    # EQUITY due diligence -- crypto's behavioural check reads
    # CRYPTO_RESEARCH_SCORES.sentiment instead and is unaffected either way. Scheduled
    # early in the UTC day (10:00, before even premarket-equity's earliest possible
    # ET-8am window in either DST offset) so equity due diligence has a real today-dated
    # row to read for the rest of the day. Scheduled on the plain UTC clock rather than
    # gated behind the NYSE weekday check below, simply so a missed weekday window
    # (worker restart, etc.) still has weekend days available to catch up before
    # Monday's premarket-equity run needs it.
    if now.hour == 10:
        due.append(("benchmark-research-refresh", f"{now.date().isoformat()}T10:00:00+00:00"))
    if 3 <= now.hour < 4:
        due.append(("rejection-outcome-review", f"{now.date().isoformat()}T03:00:00+00:00"))
    if now.day == 1 and 4 <= now.hour < 5:
        due.append(("rejection-outcome-rollup", f"{now.strftime('%Y-%m')}-01T04:00:00+00:00"))
    # 2026-08-21 Founder-directed fix: daily-learning has a working dispatch handler
    # (daily_learning_update, below) and was reachable via manual/debug `run-job`, but
    # nothing in this schedule ever added it to the due list -- job_health showed it stuck
    # at "Awaiting First Run" indefinitely, not because it failed, but because it was never
    # once called automatically. Runs once near the end of the UTC day (this project's
    # day-boundary convention throughout -- see utc_now_iso()) so it captures nearly the
    # full day's activity before the date rolls over. Scheduled on the plain UTC clock, not
    # gated behind the NYSE weekday check below, since crypto trades every day and its own
    # performance/rejection review should not skip weekends just because equities do.
    if now.hour == 23:
        due.append(("daily-learning", f"{now.date().isoformat()}T23:00:00+00:00"))
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
        due.append(("strategy-lab-refresh", f"{day}T17:30:00-04:00"))
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
