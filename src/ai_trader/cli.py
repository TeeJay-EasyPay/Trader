from __future__ import annotations

import argparse
import json
import time
from datetime import date, datetime
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

    args = parser.parse_args(argv)
    settings = load_settings()
    audit = AuditDatabase(settings.db_path, settings.trading_log_path)

    if args.command == "config":
        print(_safe_config(settings))
        return 0

    if args.command == "propose":
        proposals = _propose(args, settings, audit)
        save_proposals(Path(args.output), proposals)
        print(json.dumps({"proposals": len(proposals), "output": args.output}, indent=2))
        return 0

    if args.command == "execute":
        proposals = load_proposals(Path(args.proposals))
        results = _execute(args, settings, audit, proposals)
        print(json.dumps(results, indent=2, sort_keys=True))
        return 0

    if args.command == "run-once":
        proposals = _propose(args, settings, audit)
        save_proposals(Path(args.output), proposals)
        results = _execute(args, settings, audit, proposals)
        print(json.dumps({"proposals": len(proposals), "results": results}, indent=2, sort_keys=True))
        return 0

    if args.command == "briefing":
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
        while True:
            try:
                broker_poll = _run_worker_cycle_job(service, "broker-poll", worker_id)
                exits = _run_worker_cycle_job(service, "managed-exits", worker_id)
                auto = _run_worker_cycle_job(service, "auto-execution", worker_id)
                learning = process_learning_outbox(settings.db_path, worker_id=worker_id, limit=10)
                record_worker_heartbeat(
                    settings.db_path,
                    worker_id=worker_id,
                    worker_type="background-worker",
                    current_job="idle",
                    last_successful_job="background-cycle",
                    payload={"broker_poll": broker_poll, "managed_exits": exits, "auto_execution": auto, "learning": learning},
                )
            except Exception as exc:  # noqa: BLE001 - worker must persist and record failures
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
    if job_name == "managed-exits":
        return service.monitor_managed_exits()
    raise ValueError(f"Unsupported scheduled job: {job_name}")


def _run_worker_cycle_job(service, job_name: str, worker_id: str) -> dict:
    scheduled_for = datetime.now().replace(second=0, microsecond=0).isoformat()
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
        result = _run_named_job(service, job_name, limit=0)
        complete_scheduled_job(service.settings.db_path, int(claim["job_run_id"]), status="completed", result=result)
        return result
    except Exception as exc:
        complete_scheduled_job(service.settings.db_path, int(claim["job_run_id"]), status="failed", result={}, failure_reason=str(exc))
        raise


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
