from __future__ import annotations

import hmac
import html
import json
import logging
import os
import socket
import sqlite3
import sys
import time
from collections import Counter, defaultdict, deque
from contextlib import closing
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.parse import parse_qs, quote, urlparse
from urllib import error as urllib_error
from urllib import request as urllib_request

from .agent import AITradingAgent, propose_crypto_trades
from .always_on import (
    alpaca_inactivity_diagnosis,
    initialize_always_on_schema,
    list_job_runs,
    list_research_funnels,
    list_shadow_trades,
    operations_health,
    record_research_funnel,
    record_shadow_trade,
    scheduler_status,
    shadow_performance,
)
from .autonomous_activity import (
    activity_summary,
    activity_timeline,
    autonomous_activity_payload,
    broker_activity,
    current_autonomous_status,
    founder_attention,
    why_no_trade_funnel,
)
from .ai import OpenAIProposalAnalyzer, OpenAIReadOnlyExplainer
from .alpaca import AlpacaCredentials, AlpacaPaperClient
from .audit import AuditDatabase
from .benchmark import BenchmarkIntelligenceDatabase
from .briefing import generate_daily_briefing
from .broker_adapters import AlpacaBrokerAdapter, CoinbaseAdapter, InteractiveBrokersAdapter, KrakenAdapter, SaxoAdapter, _kraken_last_price, _kraken_pair
from .config import Settings, load_settings
from .foundation import initialize_foundation_schema, latest_due_diligence, latest_investment_score, load_trading_policy
from .experience_engine import initialize_experience_engine_schema
from .market_intelligence_platform import initialize_market_intelligence_schema
from .intelligence import InvestmentIntelligenceDatabase
from .models import AccountContext, OrderRequest, Position, TradeProposal, utc_now_iso
from .multi_broker import (
    all_broker_runtime,
    broker_auto_settings,
    broker_auto_trading_enabled,
    initialize_multi_broker_schema,
    active_push_tokens,
    latest_broker_trades,
    latest_recommendation_set,
    list_notifications,
    list_performance_attribution,
    mark_notifications_read,
    mark_push_sent,
    close_managed_exit_and_record,
    open_managed_exits,
    pending_push_notifications,
    record_broker_trade_history,
    record_crypto_research_score,
    record_notification,
    record_recommendation_set,
    register_push_token,
    send_expo_push,
    set_broker_auto_trading,
    today_runtime_counts,
    update_broker_runtime,
    update_trailing_water_marks,
)
from .orchestrator import InvestmentOrchestrator, OrchestratorContext, next_research_run
from .operational import display_value, initialize_operational_schema, latest_pnl_snapshot, latest_research_run, record_portfolio_snapshot, record_research_run, safe_float, safe_score, seed_crypto_universe
from .operational_truth import initialize_operational_truth_schema, reconcile_broker_trade_rows, reconciliation_health
from .portfolio_intelligence import calculate_portfolio_exposure, initialize_portfolio_intelligence_schema
from .production_spine import initialize_production_spine_schema, phase5_status
from .production_evidence import (
    founder_evidence_payload,
    initialize_production_evidence_schema,
    list_production_trade_evidence,
    record_broker_snapshot,
    record_research_evidence,
    record_trade_evidence,
)
from .sprint6 import (
    enqueue_learning_workflow,
    execution_mode_for_broker,
    generate_founder_operational_report,
    initialize_sprint6_schema,
    normalize_broker_events,
    pre_execution_decision_packet,
    record_operational_event,
    seed_default_strategy_registry,
    sprint6_status,
    upsert_incident,
)
from .scheduler import IntervalWorker, ResearchScheduler
from .trading_intelligence import calculate_performance_metrics, initialize_trading_intelligence_schema, latest_intelligence_packet, update_calibration_from_attribution


logger = logging.getLogger("ai_trader.api")


def configure_logging(output_dir: Path) -> None:
    root = logging.getLogger()
    if root.handlers:
        return
    root.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(output_dir / "app.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8")
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError:
        logger.warning("Could not open log file under %s; continuing with console logging only.", output_dir)


CONTROL_SCHEMA = """
CREATE TABLE IF NOT EXISTS engine_control (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    trading_state TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_command TEXT
);
"""

REPORT_SCHEMA = """
CREATE TABLE IF NOT EXISTS TRADING_REPORTS (
    report_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    report_date TEXT NOT NULL,
    broker TEXT NOT NULL,
    report_type TEXT NOT NULL,
    summary TEXT NOT NULL,
    report_markdown TEXT NOT NULL,
    file_path TEXT
);
"""

AUTO_TRADE_CONFIDENCE_THRESHOLD = 0.85

BROKER_AUTO_TRADING_ENV_VARS = {
    "alpaca": "ALPACA_AUTO_TRADING",
    "kraken": "KRAKEN_AUTO_TRADING",
    "coinbase": "COINBASE_AUTO_TRADING",
    "binance": "BINANCE_AUTO_TRADING",
    "interactive_brokers": "IBKR_AUTO_TRADING",
}

GUARDRAIL_CHECKS: list[tuple[str, str, str]] = [
    ("paper_trading_only_failed", "Paper trading account confirmed", "all"),
    ("invalid_side", "Trade side is valid", "all"),
    ("position_size_must_be_positive", "Position size is positive", "all"),
    ("entry_price_must_be_positive", "Entry price is positive", "all"),
    ("stop_loss_mandatory", "Stop loss is present", "all"),
    ("take_profit_mandatory", "Take profit is present", "all"),
    ("confidence_below_minimum", "Confidence meets the minimum threshold", "all"),
    ("account_equity_must_be_positive", "Account equity is positive", "all"),
    ("risk_must_be_positive", "Trade risk is measurable", "all"),
    ("max_account_risk_per_trade_exceeded", "Trade risk stays within account limit", "all"),
    ("declared_risk_percentage_exceeded", "Declared risk percentage is within limit", "all"),
    ("maximum_daily_loss_exceeded", "Daily loss limit has not been breached", "all"),
    ("maximum_open_positions_exceeded", "Open position limit has room", "all"),
    ("duplicate_open_position", "No duplicate long position", "buy"),
    ("short_selling_disabled", "Short selling rule is satisfied", "sell"),
    ("buy_stop_loss_must_be_below_entry", "Buy stop loss is below entry", "buy"),
    ("buy_take_profit_must_be_above_entry", "Buy take profit is above entry", "buy"),
    ("sell_stop_loss_must_be_above_entry", "Sell stop loss is above entry", "sell"),
    ("sell_take_profit_must_be_below_entry", "Sell take profit is below entry", "sell"),
    ("outside_regular_trading_hours", "Inside regular US market hours", "all"),
]


class LocalApiService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.hosted_read_only = False
        self.api_token_configured = bool(os.getenv("AI_TRADER_API_TOKEN"))
        self.audit = AuditDatabase(settings.db_path, settings.trading_log_path)
        initialize_trading_intelligence_schema(settings.db_path)
        self.intelligence = InvestmentIntelligenceDatabase(settings.db_path)
        self.benchmark = BenchmarkIntelligenceDatabase(settings.db_path)
        self.orchestrator = InvestmentOrchestrator(db_path=settings.db_path, adapters=self._adapters())
        initialize_foundation_schema(settings.db_path)
        initialize_operational_schema(settings.db_path)
        initialize_multi_broker_schema(settings.db_path)
        initialize_operational_truth_schema(settings.db_path)
        initialize_market_intelligence_schema(settings.db_path)
        initialize_portfolio_intelligence_schema(settings.db_path)
        initialize_experience_engine_schema(settings.db_path)
        initialize_always_on_schema(settings.db_path)
        initialize_production_evidence_schema(settings.db_path)
        initialize_production_spine_schema(settings.db_path)
        initialize_sprint6_schema(settings.db_path)
        seed_default_strategy_registry(settings.db_path)
        self._initialize_report_schema()
        self._apply_env_broker_auto_defaults()
        self._initialize_control()

    def reconcile_on_startup(self) -> dict[str, Any]:
        stuck_cutoff = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        stuck_locks = self._rows(
            "SELECT * FROM ORDER_INTENT_LOCKS WHERE status = 'locked' AND created_at < ?",
            (stuck_cutoff,),
        )
        open_exits = self._rows("SELECT * FROM MANAGED_TRADE_EXITS WHERE status = 'open'")
        reconciliation = {}
        for broker in ["alpaca", "kraken"]:
            rows = [
                dict(row)
                for row in self._rows(
                    """
                    SELECT *
                    FROM BROKER_TRADE_HISTORY
                    WHERE broker = ?
                    ORDER BY trade_history_id DESC
                    LIMIT 250
                    """,
                    (broker,),
                )
            ]
            reconciliation[broker] = reconcile_broker_trade_rows(self.settings.db_path, broker, rows)
        summary = {
            "stuck_order_intents": len(stuck_locks),
            "open_managed_exits": len(open_exits),
            "broker_reconciliation": reconciliation,
        }
        logger.info("Startup reconciliation: %s", summary)
        if stuck_locks:
            record_notification(
                self.settings.db_path,
                event_type="broker_failure",
                broker=None,
                symbol=None,
                title="Stuck order submissions detected at startup",
                message=(
                    f"{len(stuck_locks)} order intent lock(s) never completed before the last restart. "
                    "Review ORDER_INTENT_LOCKS for the affected broker/symbol."
                ),
                payload={"stuck_locks": [dict(row) for row in stuck_locks]},
            )
        return summary

    def notifications(self, *, unread_only: bool = False, limit: int = 50) -> list[dict[str, Any]]:
        return list_notifications(self.settings.db_path, unread_only=unread_only, limit=limit)

    def ack_notifications(self, body: dict[str, Any]) -> dict[str, Any]:
        ids = body.get("notification_ids") or ([body["notification_id"]] if body.get("notification_id") else [])
        try:
            ids = [int(item) for item in ids]
        except (TypeError, ValueError):
            return {"status": "rejected", "message": "notification_ids must be a list of integers."}
        updated = mark_notifications_read(self.settings.db_path, ids)
        return {"status": "updated", "marked_read": updated}

    def register_push_token_endpoint(self, body: dict[str, Any]) -> dict[str, Any]:
        token = body.get("push_token")
        if not token:
            return {"status": "rejected", "message": "push_token is required."}
        result = register_push_token(self.settings.db_path, str(token), platform=body.get("platform"))
        return {"status": "registered", **result}

    def dispatch_pending_push_notifications(self) -> dict[str, Any]:
        pending = pending_push_notifications(self.settings.db_path)
        if not pending:
            return {"dispatched": 0}
        tokens = active_push_tokens(self.settings.db_path)
        if not tokens:
            mark_push_sent(self.settings.db_path, [row["notification_id"] for row in pending])
            return {"dispatched": 0, "reason": "no_registered_devices", "skipped": len(pending)}
        for row in pending:
            send_expo_push(tokens, title=row["title"], body=row["message"], data={"event_type": row["event_type"], "broker": row["broker"], "symbol": row["symbol"]})
        mark_push_sent(self.settings.db_path, [row["notification_id"] for row in pending])
        return {"dispatched": len(pending), "devices": len(tokens)}

    def refresh_crypto_universe(self) -> dict[str, Any]:
        result = seed_crypto_universe(self.settings.db_path, fetch_live=True)
        update_broker_runtime(
            self.settings.db_path,
            "kraken",
            research_status="running" if result["inserted"] else "idle",
            due_diligence_status="completed" if result["inserted"] else "blocked",
            current_stage="crypto_universe_refresh",
            last_scan=utc_now_iso(),
            next_scan=next_research_run(interval_minutes=self.settings.research_scheduler_interval_minutes),
            research_freshness="Fresh" if result["inserted"] else result["notes"],
            details={"crypto_universe": result},
        )
        if not result["inserted"]:
            record_notification(
                self.settings.db_path,
                event_type="research_failure",
                broker="kraken",
                symbol=None,
                title="Crypto universe refresh returned no data",
                message=result["notes"],
                payload=result,
            )
        logger.info("Crypto universe refresh: %s", result)
        crypto_analysis = self.run_crypto_analysis()
        result["crypto_analysis"] = crypto_analysis
        return result

    def run_crypto_analysis(self, symbols: list[str] | None = None, *, limit: int = 10) -> dict[str, Any]:
        started_at = utc_now_iso()
        record_operational_event(
            self.settings.db_path,
            component="research",
            event_type="research_started",
            broker="kraken",
            summary="Kraken crypto research cycle started.",
            details={"symbols": symbols, "limit": limit},
        )
        adapter = self.orchestrator.adapters.get("kraken")
        if adapter is None or not getattr(adapter, "configured", False):
            result = {"status": "not_available", "message": "Kraken credentials are required for crypto analysis."}
            record_operational_event(
                self.settings.db_path,
                component="research",
                event_type="research_blocked_configuration",
                broker="kraken",
                severity="warning",
                summary=result["message"],
                details=result,
                success=False,
            )
            self._record_production_research(started_at, "kraken", "crypto", "scheduled", symbols or [], result)
            return result
        if symbols is None:
            limit = max(1, min(int(limit or 10), 30))
            rows = self._rows("SELECT DISTINCT symbol FROM CRYPTO_MASTER WHERE active = 1 LIMIT ?", (limit,))
            symbols = [row["symbol"] for row in rows]
            if not symbols:
                symbols = self._bootstrap_crypto_universe_from_kraken_permissions(limit=limit)
        if not symbols:
            result = {
                "status": "not_available",
                "message": "No active crypto symbols are available yet. Add KRAKEN_ALLOWED_PAIRS or run the crypto universe refresh again.",
            }
            record_operational_event(
                self.settings.db_path,
                component="research",
                event_type="research_completed_no_action",
                broker="kraken",
                severity="warning",
                summary=result["message"],
                details=result,
                success=False,
            )
            self._record_production_research(started_at, "kraken", "crypto", "scheduled", [], result)
            return result
        account = self._account_context_for_broker("kraken")
        proposals = propose_crypto_trades(
            self.settings.db_path,
            adapter,
            symbols,
            account,
            self.settings.guardrails,
            self.audit,
            min_confidence=self.settings.auto_trade.min_confidence,
            requested_notional=self.settings.auto_trade.crypto_max_trade_amount,
            default_stop_loss_pct=self.settings.auto_trade.crypto_default_stop_loss_pct,
        )
        auto_execution = self.auto_execute_recommendations() if proposals else {"status": "skipped", "message": "No crypto proposals generated."}
        for proposal in proposals:
            self._record_shadow_from_proposal(
                proposal,
                intended_broker="kraken",
                decision_status="shadow_candidate",
                trigger_type="scheduled",
                wait_or_rejection_reason=None,
            )
        update_broker_runtime(
            self.settings.db_path,
            "kraken",
            research_status="idle",
            due_diligence_status="completed",
            current_stage="complete",
            research_queue=symbols,
            assets_reviewed_today=len(symbols),
            research_cycles_today=1,
            last_scan=utc_now_iso(),
            next_scan=next_research_run(interval_minutes=self.settings.research_scheduler_interval_minutes),
            research_freshness="Fresh",
            last_recommendation=proposals[-1].symbol if proposals else None,
        )
        record_notification(
            self.settings.db_path,
            event_type="research_completed",
            broker="kraken",
            symbol=None,
            title="Crypto research completed",
            message=f"Crypto due diligence completed for {len(symbols)} asset(s). {len(proposals)} recommendation(s) generated.",
            payload={"symbols": symbols, "proposal_count": len(proposals)},
        )
        record_recommendation_set(
            self.settings.db_path,
            trigger_type="scheduled",
            broker="kraken",
            symbols=symbols,
            proposal_ids=[p.proposal_id for p in proposals],
            status="completed",
            summary=f"{len(proposals)} crypto recommendation(s) generated.",
        )
        record_research_run(
            self.settings.db_path,
            started_at=started_at,
            completed_at=utc_now_iso(),
            status="completed",
            trigger_type="scheduled",
            markets_reviewed=["Kraken", "CoinGecko"],
            companies_reviewed=0,
            crypto_assets_reviewed=len(symbols),
            benchmark_traders_reviewed=0,
            recommendations_created=len(proposals),
            trades_executed=len(auto_execution.get("result", [])) if isinstance(auto_execution.get("result"), list) else 0,
            trades_rejected=len(auto_execution.get("skipped", [])) if isinstance(auto_execution, dict) else 0,
            errors=[],
            next_scheduled_run=next_research_run(interval_minutes=self.settings.research_scheduler_interval_minutes),
            summary=f"Crypto research completed with {len(proposals)} recommendation(s).",
        )
        self._record_research_funnel_from_result(
            broker="kraken",
            asset_type="crypto",
            trigger_type="scheduled",
            symbols=symbols,
            result={"status": "completed", "proposals": [p.to_dict() for p in proposals], "auto_execution": auto_execution},
            auto_execution=auto_execution,
            skipped_symbols=[],
        )
        record_operational_event(
            self.settings.db_path,
            component="research",
            event_type="research_completed",
            broker="kraken",
            summary=f"Kraken crypto research reviewed {len(symbols)} symbol(s) and created {len(proposals)} proposal(s).",
            details={"symbols": symbols, "proposal_count": len(proposals), "auto_execution": auto_execution},
        )
        result = {"status": "completed", "symbols": symbols, "proposals": [p.to_dict() for p in proposals], "auto_execution": auto_execution}
        self._record_production_research(started_at, "kraken", "crypto", "scheduled", symbols, result)
        return result

    def get(self, path: str, query: dict[str, list[str]]) -> tuple[int, dict[str, Any]]:
        if path == "/healthz":
            return 200, {"status": "ok", "generated_at": utc_now_iso()}
        if path == "/status":
            return 200, self.status()
        if path == "/founder-evidence":
            return 200, founder_evidence_payload(
                self.settings.db_path,
                period=_first(query, "period") or "24h",
                trade_limit=_int_or_default(_first(query, "trade_limit"), 100),
            )
        if path == "/founder/trades":
            return 200, {
                "trades": list_production_trade_evidence(
                    self.settings.db_path,
                    broker=_first(query, "broker"),
                    limit=_int_or_default(_first(query, "limit"), 100),
                )
            }
        if path == "/portfolio":
            return 200, self.portfolio(_first(query, "broker") or "all")
        if path == "/founder-brief":
            return 200, self.founder_brief()
        if path == "/recommendations":
            return 200, {"recommendations": self.recommendations()}
        if path == "/intelligence/companies":
            return 200, {"companies": self.companies()}
        if path == "/intelligence/themes":
            return 200, {"themes": self.themes()}
        if path == "/benchmark-traders":
            return 200, {"benchmark_traders": self.benchmark_traders()}
        if path == "/benchmark-daily-brief":
            brief_date = _first(query, "date") or date.today().isoformat()
            return 200, self.benchmark_daily_brief(brief_date)
        if path == "/developer-status":
            return 200, self.developer_status()
        if path == "/developer-dashboard":
            return 200, {"html": DEVELOPER_DASHBOARD_HTML}
        if path == "/brokers":
            return 200, {"brokers": self.broker_panels()}
        if path == "/performance-attribution":
            return 200, {"performance_attribution": list_performance_attribution(self.settings.db_path)}
        if path == "/daily-learning-update":
            return 200, self.daily_learning_update(_first(query, "date"))
        if path == "/operational-truth":
            return 200, self.operational_truth_status()
        if path == "/world-class-evidence":
            return 200, self.world_class_evidence()
        if path == "/operations-health":
            return 200, self.operations_health()
        if path == "/scheduler-status":
            return 200, scheduler_status(self.settings.db_path)
        if path == "/job-runs":
            return 200, {"job_runs": list_job_runs(self.settings.db_path, limit=_int_or_default(_first(query, "limit"), 50), job_name=_first(query, "job_name"))}
        if path == "/shadow-trades":
            return 200, {"shadow_trades": list_shadow_trades(self.settings.db_path, broker=_first(query, "broker"), limit=_int_or_default(_first(query, "limit"), 100))}
        if path == "/shadow-performance":
            return 200, shadow_performance(self.settings.db_path)
        if path == "/research-funnel":
            return 200, {"research_funnels": list_research_funnels(self.settings.db_path, broker=_first(query, "broker"), limit=_int_or_default(_first(query, "limit"), 50))}
        if path == "/alpaca-inactivity-diagnosis":
            return 200, alpaca_inactivity_diagnosis(self.settings.db_path)
        if path == "/phase5-status":
            return 200, self.phase5_status()
        if path == "/sprint6-status":
            return 200, self.sprint6_status()
        if path == "/autonomous-activity":
            return 200, self.production_activity(query)
        if path == "/activity/status":
            return 200, founder_evidence_payload(self.settings.db_path, period=_first(query, "period") or "24h")["status"]
        if path == "/activity/summary":
            return 200, founder_evidence_payload(self.settings.db_path, period=_first(query, "period") or "24h")["summary"]
        if path == "/activity/timeline":
            return 200, self._filtered_production_timeline(query)
        if path == "/activity/why-no-trade":
            return 200, founder_evidence_payload(self.settings.db_path, period=_first(query, "period") or "24h")["why_no_trade"]
        if path == "/activity/brokers":
            return 200, {"brokers": founder_evidence_payload(self.settings.db_path, period=_first(query, "period") or "24h")["brokers"]}
        if path == "/activity/founder-attention":
            payload = founder_evidence_payload(self.settings.db_path, period=_first(query, "period") or "24h")
            items = [] if payload["status"]["state"] == "OPERATING NORMALLY" else [{
                "title": payload["status"]["state"],
                "explanation": payload["status"]["plain_english"],
                "recommended_action": "Review worker, research, and broker evidence on this screen.",
                "started_at": payload["generated_at"],
            }]
            return 200, {"items": items, "count": len(items)}
        if path == "/operational-events":
            return 200, {"operational_events": self.operational_events(limit=_int_or_default(_first(query, "limit"), 50))}
        if path == "/decision-journal":
            return 200, {"decision_journal": self.decision_journal(limit=_int_or_default(_first(query, "limit"), 50))}
        if path == "/trading-report":
            return 200, self.trading_report(
                report_date=_first(query, "date"),
                broker=_first(query, "broker") or "all",
                report_type=_first(query, "type") or "daily",
                persist=True,
            )
        if path.startswith("/reports/"):
            return self.report_page(path)
        if path == "/notifications":
            return 200, {"notifications": self.notifications(unread_only=_first(query, "unread_only") == "true")}
        return 404, {"error": "not_found", "path": path}

    def post(self, path: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        if path == "/run-analysis":
            return 200, self.run_analysis(body)
        if path == "/run-crypto-analysis":
            symbols = body.get("symbols")
            if isinstance(symbols, str):
                symbols = [item.strip().upper() for item in symbols.split(",") if item.strip()]
            return 200, self.run_crypto_analysis(symbols, limit=_int_or_default(body.get("limit"), 10))
        if path == "/start-trading":
            return 200, self.set_trading_state("running", "start-trading")
        if path == "/pause-trading":
            return 200, self.set_trading_state("paused", "pause-trading")
        if path == "/resume-trading":
            return 200, self.set_trading_state("running", "resume-trading")
        if path == "/stop-trading":
            return 200, self.set_trading_state("stopped", "stop-trading")
        if path == "/auto-execute-recommendations":
            return 200, self.auto_execute_recommendations()
        if path == "/approve-and-execute":
            return 200, self.approve_and_execute(body)
        if path == "/broker-auto-trading":
            return 200, self.set_broker_auto_trading(body)
        if path == "/monitor-managed-exits":
            return 200, self.monitor_managed_exits()
        if path == "/force-managed-exit":
            return 200, self.force_managed_exit(body)
        if path == "/generate-report":
            return 200, self.generate_report(body)
        if path == "/generate-operational-report":
            return 200, generate_founder_operational_report(
                self.settings.db_path,
                output_dir=self.settings.output_dir,
                report_type=str(body.get("type") or "daily"),
                period_start=body.get("period_start"),
                period_end=body.get("period_end"),
            )
        if path == "/ask-ai-trader":
            return 200, self.ask_ai_trader(body)
        if path == "/notifications/ack":
            return 200, self.ack_notifications(body)
        if path == "/register-push-token":
            return 200, self.register_push_token_endpoint(body)
        return 404, {"error": "not_found", "path": path}

    def status(self) -> dict[str, Any]:
        control = self._control_state()
        last_trade_analysis = self._scalar("SELECT MAX(created_at) FROM trade_audit WHERE event_type IN ('agent_proposal', 'agent_no_trade')")
        last_event_analysis = self._scalar("SELECT MAX(created_at) FROM execution_events WHERE event_type IN ('agent_no_trade', 'analysis_completed')")
        last_analysis = max([value for value in [last_trade_analysis, last_event_analysis] if value], default=None)
        last_activity = self._rows(
            """
            SELECT created_at, event_type, proposal_id, symbol, execution_result
            FROM (
                SELECT created_at, event_type, proposal_id, symbol, execution_result
                FROM trade_audit
                UNION ALL
                SELECT created_at, event_type, proposal_id, NULL AS symbol, payload_json AS execution_result
                FROM execution_events
                WHERE event_type IN ('agent_no_trade', 'analysis_completed', 'engine_control')
            )
            ORDER BY created_at DESC
            LIMIT 8
            """
        )
        recent_transactions = self._rows(
            """
            SELECT created_at, event_type, proposal_id, symbol, side, position_size,
                   ai_confidence, execution_result
            FROM trade_audit
            WHERE event_type IN ('execution_approved', 'execution_rejected', 'agent_proposal', 'agent_no_trade')
            ORDER BY id DESC
            LIMIT 10
            """
        )
        recommendation_rows = self.recommendations(limit=50)
        active_recommendations = [row for row in recommendation_rows if row["freshness_status"] != "Expired"]
        latest_decision = self.orchestrator.latest_decision()
        latest_morning = self._latest_daily_brief("morning")
        latest_evening = self._latest_daily_brief("evening")
        research_run = latest_research_run(self.settings.db_path)
        policy = load_trading_policy(self.settings.db_path, auto_trade=self.settings.auto_trade, guardrails=self.settings.guardrails)
        brokers = self.broker_panels()
        executive_summary = self.executive_summary(brokers)
        founder_summary = self.founder_executive_summary(brokers, executive_summary)
        readiness = self.connection_readiness(brokers)
        founder_experience = self.founder_experience_payload(brokers, recommendation_rows, policy, research_run)
        world_class = self.world_class_evidence(brokers=brokers, recommendations=recommendation_rows)
        always_on = self.operations_health()
        phase5 = self.phase5_status()
        sprint6 = self.sprint6_status()
        return {
            "system_status": control["trading_state"],
            "paper_live_mode": "Paper" if self.settings.guardrails.paper_trading_only else "Live disabled by local API",
            "engine_health": "Available" if self.settings.db_path.exists() else "Database not initialized",
            "last_analysis_time": last_analysis,
            "auto_paper_trading_status": "Enabled" if self.settings.auto_trade.enabled else "Disabled",
            "broker_auto_trading": broker_auto_settings(self.settings.db_path),
            "selected_active_brokers": self._active_broker_names(),
            "brokers": brokers,
            "continuous_research": self._continuous_research_status(brokers),
            "next_scheduled_research_run": (research_run or {}).get("next_scheduled_run") or next_research_run(),
            "last_research_run": research_run,
            "research_status": _research_status(research_run),
            "due_diligence_status": self._due_diligence_status(),
            "research_assets_reviewed": _research_assets_reviewed(research_run),
            "crypto_projects_reviewed": self._count("CRYPTO_MASTER", "active = 1"),
            "research_recommendations_created": (research_run or {}).get("recommendations_created"),
            "auto_trading_enabled": self.settings.auto_trade.enabled,
            "paper_or_sandbox_mode": self.settings.guardrails.paper_trading_only,
            "trading_policy": policy.to_dict(),
            "executive_summary": executive_summary,
            "founder_executive_summary": founder_summary,
            "founder_experience": founder_experience,
            "last_orchestrator_decision": latest_decision,
            "morning_brief": latest_morning,
            "evening_brief": latest_evening,
            "cloud_api_health": "Available",
            "connection_readiness": readiness,
            "world_class_evidence": world_class,
            "operations_health": always_on,
            "phase5_status": phase5,
            "sprint6_status": sprint6,
            "latest_activity": [dict(row) for row in last_activity],
            "recent_transactions": [dict(row) for row in recent_transactions],
            "recommendation_summary": {
                "active": len(active_recommendations),
                "expired": len(recommendation_rows) - len(active_recommendations),
                "auto_trade_threshold": self.settings.auto_trade.min_confidence,
                "auto_trade_mode": "Auto Paper Trading" if self.settings.auto_trade.enabled else "Manual approval required",
            },
            "updated_at": control["updated_at"],
        }

    def operations_health(self) -> dict[str, Any]:
        return operations_health(
            self.settings.db_path,
            expected_worker_interval_seconds=max(60, self.settings.auto_execution_interval_seconds),
        )

    def phase5_status(self) -> dict[str, Any]:
        return phase5_status(self.settings.db_path, database_backend=self.settings.database_backend)

    def sprint6_status(self) -> dict[str, Any]:
        return sprint6_status(self.settings.db_path, database_backend=self.settings.database_backend)

    def autonomous_activity(self, query: dict[str, list[str]]) -> dict[str, Any]:
        return autonomous_activity_payload(
            self.settings.db_path,
            period=_first(query, "period") or "24h",
            category=_first(query, "category") or "all",
            severity=_first(query, "severity") or "all",
            important_only=_first(query, "important_only") == "true",
            founder_action_required=_first(query, "founder_action_required") == "true",
            limit=_int_or_default(_first(query, "limit"), 100),
            broker_panels=self.broker_panels(),
            database_backend=self.settings.database_backend,
        )

    def production_activity(self, query: dict[str, list[str]]) -> dict[str, Any]:
        payload = founder_evidence_payload(
            self.settings.db_path,
            period=_first(query, "period") or "24h",
            trade_limit=_int_or_default(_first(query, "limit"), 100),
        )
        timeline = self._filtered_production_timeline(query, payload=payload)
        attention_items = []
        if payload["status"]["state"] != "OPERATING NORMALLY":
            attention_items.append({
                "title": payload["status"]["state"],
                "explanation": payload["status"]["plain_english"],
                "recommended_action": "Review stale or failed evidence below before enabling more capital.",
                "started_at": payload["generated_at"],
            })
        latest = payload["status"].get("last_meaningful_activity")
        return {
            "generated_at": payload["generated_at"],
            "period": payload["period"],
            "status": payload["status"],
            "summary": payload["summary"],
            "timeline": timeline,
            "why_no_trade": payload["why_no_trade"],
            "broker_activity": {"brokers": payload["brokers"]},
            "founder_attention": {"items": attention_items, "count": len(attention_items)},
            "latest_completed_actions": [latest] if latest else [],
            "truthfulness": payload["truthfulness"],
        }

    def _filtered_production_timeline(
        self,
        query: dict[str, list[str]],
        *,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = payload or founder_evidence_payload(self.settings.db_path, period=_first(query, "period") or "24h")
        items = list(payload["timeline"]["items"])
        category = (_first(query, "category") or "all").lower()
        severity = (_first(query, "severity") or "all").lower()
        if category != "all":
            items = [row for row in items if str(row.get("category") or "").lower() == category]
        if severity != "all":
            items = [row for row in items if str(row.get("severity") or "").lower() == severity]
        if _first(query, "important_only") == "true":
            items = [row for row in items if row.get("severity") in {"warning", "blocked", "failure", "recovered"}]
        limit = max(1, min(_int_or_default(_first(query, "limit"), 100), 200))
        return {"items": items[:limit], "total": len(items), "period": payload["period"]}

    def operational_events(self, *, limit: int = 50) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 200))
        return [
            dict(row)
            for row in self._rows(
                """
                SELECT created_at, component, event_type, severity, summary,
                       proposal_id, logical_trade_id, broker, duration_ms, success
                FROM OPERATIONAL_EVENTS
                ORDER BY event_id DESC
                LIMIT ?
                """,
                (limit,),
            )
        ]

    def decision_journal(self, *, limit: int = 50) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 200))
        return [
            dict(row)
            for row in self._rows(
                """
                SELECT created_at, proposal_id, symbol, broker, strategy_id,
                       confidence, final_decision, execution_eligibility,
                       evidence_for, evidence_against, market_data_quality
                FROM DECISION_JOURNAL
                ORDER BY decision_id DESC
                LIMIT ?
                """,
                (limit,),
            )
        ]

    def founder_experience_payload(
        self,
        brokers: list[dict[str, Any]],
        recommendations: list[dict[str, Any]],
        policy: Any,
        research_run: dict[str, Any] | None,
    ) -> dict[str, Any]:
        active = [row for row in recommendations if row.get("freshness_status") != "Expired"]
        probabilities = [safe_float(row.get("probability_of_success") or row.get("confidence")) for row in active]
        probabilities = [value for value in probabilities if value is not None]
        avg_confidence = sum(probabilities) / len(probabilities) if probabilities else None
        regimes = Counter(
            str(((row.get("market_regime") or {}).get("primary_regime") or "unknown")).lower()
            for row in active
        )
        current_regime = regimes.most_common(1)[0][0] if regimes else "unknown"
        broker_total = sum(safe_float(row.get("portfolio_balance")) or 0.0 for row in brokers if safe_float(row.get("portfolio_balance")) is not None)
        broker_cash = sum(safe_float(row.get("cash_balance")) or 0.0 for row in brokers if safe_float(row.get("cash_balance")) is not None)
        broker_positions = sum(int(safe_float(row.get("open_positions")) or 0) for row in brokers)
        deployed = max(0.0, broker_total - broker_cash) if broker_total else None
        deployment_pct = deployed / broker_total if broker_total and deployed is not None else None
        strategy_rows = self._latest_strategy_performance_rows()
        best_strategy = strategy_rows[0] if strategy_rows else None
        weakest_strategy = strategy_rows[-1] if len(strategy_rows) > 1 else None
        try:
            lab_rows = [dict(row) for row in self._rows("SELECT * FROM STRATEGY_LAB_RUNS ORDER BY lab_run_id DESC LIMIT 8")]
        except sqlite3.OperationalError:
            lab_rows = []
        try:
            calibration_rows = [dict(row) for row in self._rows("SELECT * FROM CONFIDENCE_CALIBRATION ORDER BY calibration_id DESC LIMIT 10")]
        except sqlite3.OperationalError:
            calibration_rows = []
        accuracy = _average_numeric([row.get("observed_win_rate") for row in calibration_rows])
        daily_learning = self.daily_learning_update(date.today().isoformat())
        committee_confidence = _average_numeric([
            _committee_numeric_confidence(row.get("committee"))
            for row in active
        ])
        risk_level = "LOW" if deployment_pct is not None and deployment_pct < 0.35 else "MEDIUM" if deployment_pct is not None and deployment_pct < 0.70 else "HIGH" if deployment_pct is not None else "UNKNOWN"
        diversification = "Concentrated" if broker_positions <= 2 else "Moderate" if broker_positions <= 7 else "Broad by position count"
        return {
            "architectural_principle": [
                "Does it help AI Trader make a better investment decision?",
                "Does it help the Founder make a better decision?",
                "Does it help AI Trader learn to make better decisions in the future?",
            ],
            "executive_dashboard": {
                "headline": "AI Trader is monitoring brokers, recommendations, risk, and learning evidence.",
                "good_morning": [
                    "Good morning. Here is what changed overnight.",
                    f"{len(active)} active recommendation(s) are currently visible.",
                    f"The dominant market regime in current recommendations is {current_regime}.",
                    f"Portfolio risk is {risk_level}.",
                    "I will continue watching broker health, fresh recommendations, open positions, and guardrail breaches.",
                ],
                "portfolio_health": "Needs attention" if risk_level == "HIGH" else "Stable",
                "overall_ai_confidence": _plain_confidence(avg_confidence),
                "current_market_regime": _plain_regime(current_regime),
                "todays_recommendation_count": len(active),
                "portfolio_risk": risk_level,
                "portfolio_diversification": diversification,
                "open_positions": broker_positions,
                "capital_deployed": deployed,
                "cash_available": broker_cash if brokers else None,
                "learning_progress": f"{len(strategy_rows)} strategy performance snapshot(s), {len(lab_rows)} strategy lab run(s).",
                "prediction_accuracy": accuracy,
                "current_best_strategy": (best_strategy or {}).get("strategy_id"),
                "current_weakest_strategy": (weakest_strategy or {}).get("strategy_id"),
                "committee_confidence": _plain_confidence(committee_confidence),
                "what_to_do": "Review green/amber dossiers only; do not override red guardrails.",
                "what_to_worry_about": "Missing data, weak calibration, concentrated exposure, and any recommendation without fresh evidence.",
            },
            "portfolio_command": {
                "portfolio_allocation": {
                    "total": broker_total or None,
                    "cash": broker_cash if brokers else None,
                    "deployed": deployed,
                    "deployed_pct": deployment_pct,
                },
                "diversification": diversification,
                "sector_exposure": "Shown when company sector data is attached to positions.",
                "country_exposure": "Shown when country data is attached to positions.",
                "currency_exposure": "Broker/account currency evidence only in current implementation.",
                "correlation": "Not enough provider data yet for statistical correlation.",
                "portfolio_risk": risk_level,
                "expected_portfolio_return": "Requires more closed trades before AI Trader can estimate this responsibly.",
                "largest_winners": self._portfolio_extremes(winners=True),
                "largest_losers": self._portfolio_extremes(winners=False),
                "positions_requiring_attention": self._positions_requiring_attention(brokers),
                "rebalancing_suggestions": _portfolio_rebalancing_suggestions(risk_level, diversification),
            },
            "market_intelligence_centre": {
                "current_market_regime": _plain_regime(current_regime),
                "market_health": _plain_market_health(current_regime, avg_confidence),
                "volatility": "High volatility means prices may move quickly and stops may be hit more easily.",
                "momentum": "Momentum means whether recent price movement is helping or fighting the trade idea.",
                "breadth": "Market breadth needs a market-data provider before it can be measured responsibly.",
                "fear_greed": _plain_confidence(avg_confidence),
                "crypto_health": self._crypto_health_summary(brokers, active),
                "sector_rotation": "Uses theme and company evidence where available; no sector-rotation provider is configured yet.",
                "major_themes": [row.get("theme") for row in self.themes()[:5]],
                "watch_list": [row.get("ticker") for row in self.companies()[:10]],
                "important_news": "Summarised inside each recommendation dossier when news is available.",
                "upcoming_risks": ["stale recommendations", "uncalibrated strategy evidence", "broker disconnection", "open-position drawdown"],
            },
            "learning_lab": {
                "learning_progress": f"{len(strategy_rows)} performance snapshot(s) and {len(lab_rows)} lab validation run(s) recorded.",
                "prediction_accuracy": accuracy,
                "calibration": calibration_rows[:5],
                "strategy_rankings": strategy_rows,
                "best_performing_strategy": best_strategy,
                "worst_performing_strategy": weakest_strategy,
                "strategy_validation_status": self._strategy_validation_summary(lab_rows),
                "backtest_results": [row for row in lab_rows if row.get("run_type") == "backtest"],
                "walk_forward_results": [row for row in lab_rows if row.get("run_type") == "walk_forward"],
                "committee_performance": "Tracked through committee reviews and closed-trade attribution; larger samples are needed before claiming skill.",
                "signal_rankings": self._signal_rankings(),
                "lessons_learned": (daily_learning or {}).get("trade_lessons", []),
                "founder_suggestions": (daily_learning or {}).get("recommendations_for_founder", []),
            },
        }

    def _latest_strategy_performance_rows(self) -> list[dict[str, Any]]:
        try:
            rows = [
                dict(row)
                for row in self._rows(
                    """
                    SELECT pi.*
                    FROM PERFORMANCE_INTELLIGENCE pi
                    JOIN (
                        SELECT strategy_id, MAX(performance_id) AS performance_id
                        FROM PERFORMANCE_INTELLIGENCE
                        GROUP BY strategy_id
                    ) latest ON latest.performance_id = pi.performance_id
                    ORDER BY COALESCE(pi.expectancy_r, pi.average_r, -999) DESC
                    LIMIT 12
                    """
                )
            ]
        except sqlite3.OperationalError:
            rows = []
        if rows:
            return rows
        strategy_ids = ["equity_conservative_ai_assisted", "crypto_trend_following_2r", "trend_following", "momentum"]
        generated = []
        for strategy_id in strategy_ids:
            perf = calculate_performance_metrics(self.settings.db_path, strategy_id)
            if perf.get("sample_size"):
                generated.append({"strategy_id": strategy_id, **perf})
        return sorted(generated, key=lambda item: safe_float(item.get("expectancy_r") or item.get("average_r") or -999), reverse=True)

    def _portfolio_extremes(self, *, winners: bool) -> list[dict[str, Any]]:
        try:
            rows = [
                dict(row)
                for row in self._rows(
                    """
                    SELECT broker, symbol, profit_loss, entry_price, exit_price, closed_at
                    FROM PERFORMANCE_ATTRIBUTION
                    WHERE profit_loss IS NOT NULL
                    ORDER BY profit_loss {direction}
                    LIMIT 5
                    """.format(direction="DESC" if winners else "ASC")
                )
            ]
        except sqlite3.OperationalError:
            rows = []
        return rows

    def _positions_requiring_attention(self, brokers: list[dict[str, Any]]) -> list[str]:
        attention = []
        for broker in brokers:
            label = broker.get("label") or broker.get("broker") or "Broker"
            if str(broker.get("connection_status") or "").lower() not in {"connected", "ok - connected"}:
                attention.append(f"{label}: connection is not confirmed.")
            if safe_float(broker.get("todays_pnl")) is not None and (safe_float(broker.get("todays_pnl")) or 0) < 0:
                attention.append(f"{label}: today's P&L is negative.")
            if str(broker.get("due_diligence_status") or "").lower() == "blocked":
                attention.append(f"{label}: due diligence is blocked.")
        return attention[:8] or ["No urgent broker attention item is visible from current data."]

    def _crypto_health_summary(self, brokers: list[dict[str, Any]], recommendations: list[dict[str, Any]]) -> str:
        kraken = next((row for row in brokers if str(row.get("broker") or "").lower() == "kraken"), None)
        crypto_recs = [row for row in recommendations if str(row.get("asset_type") or "").lower() == "crypto"]
        if not kraken:
            return "Kraken is not visible in the current broker panel data."
        if str(kraken.get("connection_status") or "").lower() == "connected":
            return f"Crypto connection is visible; {len(crypto_recs)} active crypto recommendation(s) are available."
        return f"Crypto broker needs attention: {kraken.get('connection_status') or 'not connected'}."

    def _strategy_validation_summary(self, lab_rows: list[dict[str, Any]]) -> list[str]:
        if not lab_rows:
            return ["No Strategy Lab validation run has been recorded yet."]
        return [
            f"{row.get('strategy_id')}: {row.get('run_type')} is {row.get('status')}."
            for row in lab_rows[:8]
        ]

    def _signal_rankings(self) -> list[dict[str, Any]]:
        try:
            rows = [
                dict(row)
                for row in self._rows(
                    """
                    SELECT signal_name, COUNT(*) AS sample_size, AVG(score) AS average_score,
                           AVG(confidence) AS average_confidence
                    FROM TRADE_SIGNALS
                    GROUP BY signal_name
                    ORDER BY average_score DESC
                    LIMIT 10
                    """
                )
            ]
        except sqlite3.OperationalError:
            rows = []
        return rows

    def portfolio(self, broker_filter: str = "all") -> dict[str, Any]:
        broker_filter = broker_filter.lower()
        if broker_filter in {"kraken", "coinbase"}:
            return self._exchange_portfolio(broker_filter)
        if not self.settings.has_alpaca_credentials:
            return {
                "portfolio_value": "Not available - Alpaca paper credentials are not configured",
                "cash_available": "Not available - Alpaca paper credentials are not configured",
                "todays_pnl": "Not available - Alpaca paper credentials are not configured",
                "open_positions": [],
                "source": "Not available: Alpaca paper credentials are not configured.",
                "executive_summary": self.executive_summary(),
            }
        try:
            portfolio = self._live_alpaca_portfolio()
            return {**portfolio, "executive_summary": self.executive_summary()}
        except Exception as exc:
            return {
                "portfolio_value": f"Not available - {exc}",
                "cash_available": f"Not available - {exc}",
                "todays_pnl": f"Not available - {exc}",
                "open_positions": [],
                "source": f"Not available: {exc}",
                "executive_summary": self.executive_summary(),
            }

    def founder_brief(self) -> dict[str, Any]:
        row = self._row("SELECT * FROM daily_briefings ORDER BY id DESC LIMIT 1")
        if row:
            return {"briefing_date": row["briefing_date"], "report_markdown": row["report_markdown"], "created_at": row["created_at"]}
        markdown = generate_daily_briefing(self.audit, date.today(), self.settings.output_dir)
        return {"briefing_date": date.today().isoformat(), "report_markdown": markdown, "created_at": utc_now_iso()}

    def operational_truth_status(self) -> dict[str, Any]:
        health = reconciliation_health(self.settings.db_path)
        lifecycle_count = self._scalar("SELECT COUNT(*) FROM CANONICAL_TRADE_LIFECYCLE") or 0
        rejected_count = self._scalar("SELECT COUNT(*) FROM LIFECYCLE_TRANSITION_REJECTIONS") or 0
        latest_events = [
            dict(row)
            for row in self._rows(
                """
                SELECT created_at, broker, symbol, stage, event_source, event_reason
                FROM CANONICAL_TRADE_LIFECYCLE
                ORDER BY lifecycle_id DESC
                LIMIT 20
                """
            )
        ]
        return {
            "status": "active",
            "canonical_lifecycle_events": lifecycle_count,
            "illegal_transition_rejections": rejected_count,
            "reconciliation_health": health,
            "latest_events": latest_events,
            "plain_english": (
                "Alpaca and Kraken broker events now feed a single canonical lifecycle. "
                "Duplicate polling is ignored by idempotency keys; illegal lifecycle jumps are logged for review."
            ),
        }

    def world_class_evidence(
        self,
        *,
        brokers: list[dict[str, Any]] | None = None,
        recommendations: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        brokers = brokers if brokers is not None else self.broker_panels()
        recommendations = recommendations if recommendations is not None else self.recommendations(limit=50)
        connected_brokers = [
            item for item in brokers
            if str(item.get("broker") or "").lower() in {"alpaca", "kraken"}
            and str(item.get("connection_status") or "").lower() == "connected"
        ]
        future_brokers = [
            {
                "broker": item.get("broker"),
                "label": item.get("label"),
                "status": self._future_broker_status(item),
            }
            for item in brokers
            if str(item.get("broker") or "").lower() not in {"alpaca", "kraken"}
        ]
        operational = self.operational_truth_status()
        portfolio_evidence = self._portfolio_intelligence_summary(connected_brokers)
        dossier_ready = [
            item for item in recommendations
            if item.get("strongest_argument_for")
            and item.get("strongest_argument_against")
            and item.get("freshness_status") != "Expired"
        ]
        unknowns = self._data_availability_unknowns(connected_brokers, recommendations)
        daily_learning = self.daily_learning_update(date.today().isoformat())
        first_conclusion = self._executive_first_conclusion(connected_brokers, dossier_ready, unknowns)
        return {
            "first_conclusion": first_conclusion,
            "measured": [
                "Broker connection state for Alpaca and Kraken.",
                "Recorded broker trade/order rows.",
                "Canonical lifecycle events generated from broker history.",
                "Portfolio/cash values when broker APIs return them.",
            ],
            "calculated_from_assumptions": [
                "Estimated capital in positions equals measured portfolio value minus measured cash when both are present.",
                "Portfolio exposure uses available broker positions and metadata; missing metadata is labelled.",
                "R, slippage, and MAE/MFE are calculated only when required entry, stop, fill, and observation data exist.",
            ],
            "unavailable": unknowns,
            "operational_truth": operational,
            "portfolio_intelligence": portfolio_evidence,
            "experience_learning": {
                "closed_trade_reviews": self._scalar("SELECT COUNT(*) FROM POST_TRADE_REVIEWS") or 0,
                "experience_records": self._scalar("SELECT COUNT(*) FROM EXPERIENCE_RECORDS") or 0,
                "learning_proposals": self._scalar("SELECT COUNT(*) FROM LEARNING_PROPOSALS") or 0,
                "today": daily_learning,
                "boundary": "Learning may suggest improvements, but cannot change broker permissions, guardrails, or production strategy status without approval.",
            },
            "recommendation_standard": {
                "active_dossiers_with_for_and_against": len(dossier_ready),
                "do_nothing_is_valid": True,
                "minimum_required_fields": [
                    "strongest argument for",
                    "strongest argument against",
                    "invalidation",
                    "why taking no action may be preferable",
                ],
            },
            "future_connections": future_brokers,
        }

    def _portfolio_intelligence_summary(self, brokers: list[dict[str, Any]]) -> dict[str, Any]:
        positions: list[dict[str, Any]] = []
        for broker in brokers:
            for row in broker.get("trade_history") or []:
                symbol = row.get("symbol")
                if symbol and str(row.get("status") or "").lower() in {"filled", "open"}:
                    positions.append({
                        "symbol": symbol,
                        "asset_type": row.get("asset_type") or ("crypto" if broker.get("broker") == "kraken" else "stock"),
                        "notional": row.get("notional") or row.get("price"),
                        "currency": "GBP" if broker.get("broker") == "kraken" else "USD",
                    })
        exposure = calculate_portfolio_exposure(self.settings.db_path, positions, broker="all") if positions else {
            "total_value": 0,
            "exposure": {},
            "largest_positions": [],
            "warnings": ["Not available - no broker position rows with measurable notional were available."],
            "plain_english": "Portfolio exposure cannot be calculated yet because measurable broker position rows are unavailable.",
        }
        return exposure

    def _future_broker_status(self, panel: dict[str, Any]) -> str:
        connection = str(panel.get("connection_status") or "").lower()
        if "not configured" in connection or "not configured" in str(panel.get("source") or "").lower():
            return "Not configured"
        if "authentication failed" in connection:
            return "Authentication failed"
        if connection == "connected":
            return "Connected"
        return "Not connected"

    def _data_availability_unknowns(self, brokers: list[dict[str, Any]], recommendations: list[dict[str, Any]]) -> list[dict[str, str]]:
        unknowns: list[dict[str, str]] = []
        for broker in brokers:
            key = str(broker.get("broker") or "broker")
            for field, requirement in [
                ("todays_pnl", "at least two same-day portfolio snapshots or broker-reported day P&L"),
                ("week_pnl", "a prior weekly snapshot or broker-reported week P&L"),
                ("month_pnl", "a month-start snapshot or broker-reported month P&L"),
            ]:
                value = broker.get(field)
                if value in {None, "", "Not available"} or str(value).lower().startswith("not available"):
                    unknowns.append({
                        "field": f"{key}.{field}",
                        "why": str(value or "No value returned by broker or snapshot layer."),
                        "required": requirement,
                        "expected_or_error": "Expected early in a deployment or after a database reset; review if snapshots exist but values remain missing.",
                    })
        incomplete_recommendations = [
            row.get("symbol") or "unknown"
            for row in recommendations
            if not row.get("strongest_argument_for") or not row.get("strongest_argument_against")
        ]
        if incomplete_recommendations:
            unknowns.append({
                "field": "recommendation_dossier.arguments",
                "why": f"{len(incomplete_recommendations)} recommendation(s) lack complete bull/bear evidence.",
                "required": "Trading committee evidence with strongest argument for and strongest argument against.",
                "expected_or_error": "Execution should not treat these as actionable recommendations.",
            })
        return unknowns

    def _executive_first_conclusion(
        self,
        connected_brokers: list[dict[str, Any]],
        dossier_ready: list[dict[str, Any]],
        unknowns: list[dict[str, str]],
    ) -> str:
        if not connected_brokers:
            return "Broker issue requires attention"
        if any("recommendation_dossier" in item["field"] for item in unknowns):
            return "Data issue requires attention"
        if dossier_ready:
            return "Review one recommendation"
        return "No action required"

    def generate_report(self, body: dict[str, Any]) -> dict[str, Any]:
        report_type = str(body.get("type") or "daily").lower()
        broker = str(body.get("broker") or "all").lower()
        report_date = str(body.get("date") or date.today().isoformat())
        return self.trading_report(report_date=report_date, broker=broker, report_type=report_type, persist=True)

    def ask_ai_trader(self, body: dict[str, Any]) -> dict[str, Any]:
        question = str(body.get("question") or "").strip()
        if not question:
            return {
                "status": "rejected",
                "answer": "Ask me a question about AI Trader's balances, trades, reports, recommendations, or learning.",
                "read_only": True,
            }
        context = self._ask_ai_context()
        if not self.settings.openai_api_key:
            return {
                "status": "openai_not_configured",
                "answer": _deterministic_ai_trader_answer(question, context),
                "read_only": True,
                "model": None,
                "note": "OPENAI_API_KEY is not configured for this AI Trader deployment, so this answer used the local evidence summary only.",
                "evidence": context,
            }
        explainer = OpenAIReadOnlyExplainer(self.settings.openai_api_key, self.settings.openai_model)
        try:
            answer = explainer.answer(question, context)
        except Exception as exc:
            logger.exception("Ask AI Trader OpenAI explanation failed; returning deterministic fallback.")
            return {
                "status": "openai_failed",
                "answer": _deterministic_ai_trader_answer(question, context),
                "read_only": True,
                "model": self.settings.openai_model,
                "note": f"OpenAI explanation failed, so this answer used the local evidence summary only. Reason: {exc}",
                "evidence": context,
            }
        return {
            "status": "answered",
            "answer": answer or _deterministic_ai_trader_answer(question, context),
            "read_only": True,
            "model": self.settings.openai_model,
            "note": "Ask AI Trader is read-only. It cannot place trades, approve trades, change guardrails, or change broker settings.",
            "evidence": context,
        }

    def _ask_ai_context(self) -> dict[str, Any]:
        broker_panels = self.broker_panels()
        return {
            "generated_at": utc_now_iso(),
            "safety_boundary": "Read-only explanation. No trading, approvals, broker controls, or guardrail changes are available to this endpoint.",
            "openai_configured": bool(self.settings.openai_api_key),
            "trading_state": self._control_state(),
            "broker_auto_trading": broker_auto_settings(self.settings.db_path),
            "broker_panels": broker_panels,
            "latest_portfolio_snapshots": [
                dict(row) for row in self._rows(
                    """
                    SELECT broker, exchange, created_at, portfolio_value, cash, buying_power,
                           day_pnl, week_pnl, month_pnl, open_positions_count
                    FROM PORTFOLIO_SNAPSHOTS
                    ORDER BY created_at DESC
                    LIMIT 12
                    """
                )
            ],
            "latest_broker_trades": [
                dict(row) for row in self._rows(
                    """
                    SELECT broker, symbol, side, quantity, price, notional, status,
                           opened_at, closed_at, updated_at
                    FROM BROKER_TRADE_HISTORY
                    ORDER BY COALESCE(closed_at, opened_at, updated_at) DESC, trade_history_id DESC
                    LIMIT 30
                    """
                )
            ],
            "latest_closed_trade_attribution": [
                dict(row) for row in self._rows(
                    """
                    SELECT broker, symbol, asset_type, side, entry_price, exit_price, quantity,
                           profit_loss, opened_at, closed_at, entry_reason, exit_reason
                    FROM PERFORMANCE_ATTRIBUTION
                    ORDER BY COALESCE(closed_at, created_at) DESC, attribution_id DESC
                    LIMIT 20
                    """
                )
            ],
            "latest_reports": [
                dict(row) for row in self._rows(
                    """
                    SELECT report_date, broker, report_type, summary, created_at
                    FROM TRADING_REPORTS
                    ORDER BY report_id DESC
                    LIMIT 8
                    """
                )
            ],
            "latest_recommendations": self.recommendations(limit=20),
            "latest_orchestrator_decisions": [
                dict(row) for row in self._rows(
                    """
                    SELECT created_at, selected_broker, symbol, requested_action, decision, rejection_reason, confidence_score
                    FROM ORCHESTRATOR_DECISIONS
                    ORDER BY decision_id DESC
                    LIMIT 20
                    """
                )
            ],
            "daily_learning": self.daily_learning_update(date.today().isoformat()),
            "world_class_evidence": self.world_class_evidence(brokers=broker_panels, recommendations=self.recommendations(limit=20)),
        }

    def trading_report(self, *, report_date: str | None, broker: str = "all", report_type: str = "daily", persist: bool = False) -> dict[str, Any]:
        report_date = report_date or date.today().isoformat()
        broker = (broker or "all").lower()
        report_type = (report_type or "daily").lower()
        try:
            parsed_date = date.fromisoformat(report_date)
        except ValueError:
            parsed_date = date.today()
            report_date = parsed_date.isoformat()
        report_context = self._refresh_report_sources(broker)
        if report_type in {"morning", "evening"}:
            markdown = self._broker_learning_report_markdown(parsed_date, broker, report_type, report_context)
        else:
            markdown = self._broker_learning_report_markdown(parsed_date, broker, report_type, report_context)
            if persist and broker == "all":
                self.audit.record_briefing(report_date, markdown, {"report_type": report_type, "broker": broker})
        path = self._write_trading_report(report_date, broker, report_type, markdown) if persist else None
        summary = _first_markdown_bullet(markdown) or f"{report_type.title()} report generated for {broker.title()} on {report_date}."
        report_id = self._record_trading_report(
            report_date=report_date,
            broker=broker,
            report_type=report_type,
            summary=summary,
            markdown=markdown,
            path=path,
        ) if persist else None
        if persist:
            record_notification(
                self.settings.db_path,
                event_type="trading_report_generated",
                broker=None if broker == "all" else broker,
                symbol=None,
                title=f"{report_type.title()} report generated",
                message=summary,
                payload={"date": report_date, "broker": broker, "report_type": report_type, "path": str(path) if path else None, "report_id": report_id},
            )
        return {
            "status": "generated" if persist else "available",
            "report_id": report_id,
            "date": report_date,
            "broker": broker,
            "report_type": report_type,
            "summary": summary,
            "report_markdown": markdown,
            "path": str(path) if path else None,
            "report_url": f"/reports/{report_id}" if report_id is not None else None,
            "generated_at": utc_now_iso(),
        }

    def report_page(self, path: str) -> tuple[int, dict[str, Any]]:
        report_id_text = path.removeprefix("/reports/").split("/", 1)[0].removesuffix(".html")
        try:
            report_id = int(report_id_text)
        except ValueError:
            return 404, {"error": "not_found", "path": path}
        row = self._row("SELECT * FROM TRADING_REPORTS WHERE report_id = ?", (report_id,))
        if not row:
            return 404, {"error": "not_found", "path": path}
        title = f"AI Trader {row['report_type'].title()} Report - {row['broker']} - {row['report_date']}"
        escaped_title = html.escape(title)
        escaped_summary = html.escape(row["summary"] or "")
        escaped_markdown = html.escape(row["report_markdown"] or "")
        escaped_path = html.escape(row["file_path"] or "Saved in SQLite only")
        page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escaped_title}</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; background: #f6f7f9; color: #17202a; }}
    main {{ max-width: 960px; margin: 0 auto; background: #fff; border: 1px solid #dde1e7; border-radius: 8px; padding: 20px; }}
    h1 {{ font-size: 24px; margin-top: 0; }}
    .meta {{ color: #667085; font-size: 14px; margin-bottom: 18px; }}
    pre {{ white-space: pre-wrap; overflow-wrap: anywhere; font-family: inherit; line-height: 1.45; }}
  </style>
</head>
<body>
  <main>
    <h1>{escaped_title}</h1>
    <div class="meta">Generated: {html.escape(_human_time(row['created_at']))}<br>Saved file: {escaped_path}</div>
    <p><strong>Summary:</strong> {escaped_summary}</p>
    <pre>{escaped_markdown}</pre>
  </main>
</body>
</html>"""
        return 200, {"html": page}

    def _refresh_report_sources(self, broker: str) -> dict[str, Any]:
        brokers = ["alpaca", "kraken", "coinbase"] if broker == "all" else [broker]
        refreshed: dict[str, Any] = {}
        for name in brokers:
            try:
                refreshed[name] = self.portfolio(name)
            except Exception as exc:
                logger.exception("Failed to refresh %s before report generation.", name)
                refreshed[name] = {"broker": name, "error": str(exc)}
        return refreshed

    def _broker_learning_report_markdown(self, report_date: date, broker: str, report_type: str, report_context: dict[str, Any] | None = None) -> str:
        period = _report_period(report_date, report_type)
        start = period["start"]
        end = period["end"]
        broker_filter = "" if broker == "all" else " AND LOWER(broker) = LOWER(?)"
        broker_params: tuple[Any, ...] = () if broker == "all" else (broker,)
        snapshots = [
            dict(row)
            for row in self._rows(
                f"""
                SELECT broker, exchange, created_at, portfolio_value, cash, buying_power, day_pnl, week_pnl, month_pnl, open_positions_count
                FROM PORTFOLIO_SNAPSHOTS
                WHERE created_at >= ? AND created_at <= ?{broker_filter}
                ORDER BY created_at ASC
                """,
                (start, end, *broker_params),
            )
        ]
        attribution = [
            dict(row)
            for row in self._rows(
                f"""
                SELECT * FROM PERFORMANCE_ATTRIBUTION
                WHERE COALESCE(closed_at, created_at) >= ? AND COALESCE(closed_at, created_at) <= ?{broker_filter}
                ORDER BY COALESCE(closed_at, created_at) ASC, attribution_id ASC
                """,
                (start, end, *broker_params),
            )
        ]
        decisions = [
            dict(row)
            for row in self._rows(
                f"""
                SELECT * FROM ORCHESTRATOR_DECISIONS
                WHERE created_at >= ? AND created_at <= ?
                {'' if broker == 'all' else 'AND LOWER(selected_broker) = LOWER(?)'}
                ORDER BY decision_id DESC
                LIMIT 30
                """,
                (start, end, *broker_params),
            )
        ]
        broker_trades = [
            dict(row)
            for row in self._rows(
                f"""
                SELECT * FROM BROKER_TRADE_HISTORY
                WHERE COALESCE(closed_at, opened_at, updated_at) >= ? AND COALESCE(closed_at, opened_at, updated_at) <= ?{broker_filter}
                ORDER BY COALESCE(closed_at, opened_at, updated_at) ASC, trade_history_id ASC
                """,
                (start, end, *broker_params),
            )
        ]
        learning = self.daily_learning_update(report_date.isoformat())
        if broker != "all":
            learning = {
                **learning,
                "closed_trades": [row for row in learning.get("closed_trades", []) if str(row.get("broker") or "").lower() == broker],
            }
        total_closed_pnl = sum(safe_float(row.get("profit_loss")) or 0.0 for row in attribution)
        losing_trades = [row for row in attribution if (safe_float(row.get("profit_loss")) or 0.0) < 0]
        winning_trades = [row for row in attribution if (safe_float(row.get("profit_loss")) or 0.0) > 0]
        reconstructed = _reconstruct_broker_fill_pnl(broker_trades)
        balance_summary = _balance_summary_by_broker(snapshots)
        performance_lines = _performance_summary_lines(balance_summary, attribution, broker_trades, reconstructed)
        likely_causes = _report_likely_causes(snapshots, attribution, decisions, broker_trades, reconstructed)
        report_context = report_context or {}
        open_position_lines = _current_open_position_lines(report_context, broker)
        plain_english = _plain_english_report_answer(balance_summary, attribution, broker_trades, reconstructed, report_context, broker)
        markdown = f"""# AI Trader {report_type.title()} Trading Report

Report Date: {report_date.isoformat()}
Period: {period["label"]}
Window Start: {_human_time(start)}
Window End: {_human_time(end)}
Broker: {broker.title() if broker != "all" else "All brokers"}

## Plain English Executive Answer

{_list_or_none(plain_english)}

## Evidence Summary

- Start/end balance snapshots reviewed: {len(balance_summary)} broker(s).
- Closed trade P&L recorded in attribution: {_money_text(total_closed_pnl)}.
- Broker-fill reconstructed realised P&L: {_money_text(reconstructed["realized_pnl"])}.
- Closed winners: {len(winning_trades)}.
- Closed losers: {len(losing_trades)}.
- Matched broker-fill round trips: {len(reconstructed["matched_trades"])}.
- Open/unmatched broker-fill lots: {len(reconstructed["open_lots"])}.
- Orchestrator decisions reviewed: {len(decisions)}.
- Broker trade-history rows reviewed: {len(broker_trades)}.

## Start And End Balances

{_balance_summary_lines(balance_summary)}

## What You Currently Own Or Have Open

{open_position_lines}

## Performance Over The Period

{_list_or_none(performance_lines)}

## Why Performance Moved

{_list_or_none(likely_causes)}

## Reconstructed Broker Fill P&L

{_reconstructed_trade_lines(reconstructed)}

## All Closed Trades With Entry, Exit, Times, And P&L

{_report_trade_lines(attribution)}

## Broker Fills And Orders Seen

{_report_broker_trade_lines(broker_trades)}

## Guardrail And Orchestrator Rejections

{_report_decision_lines(decisions)}

## Lessons Learned

{_list_or_none(_period_lessons(attribution, decisions, snapshots, broker_trades, learning.get("trade_lessons") or []))}

## Successful Trader / Benchmark Learning

{_list_or_none(learning.get("benchmark_learning") or [])}

## Recommendations For Founder Approval

{_list_or_none(_period_recommendations(attribution, decisions, learning.get("recommendations_for_founder") or []))}

## Important Note

This report explains available evidence. It does not automatically change strategy, guardrails, broker permissions, or execution logic.
"""
        return markdown

    def _write_trading_report(self, report_date: str, broker: str, report_type: str, markdown: str) -> Path:
        report_dir = self.settings.output_dir / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        safe_broker = "".join(ch for ch in broker.lower() if ch.isalnum() or ch in {"-", "_"}) or "all"
        safe_type = "".join(ch for ch in report_type.lower() if ch.isalnum() or ch in {"-", "_"}) or "daily"
        path = report_dir / f"{safe_type}_trading_report_{safe_broker}_{report_date}.md"
        path.write_text(markdown, encoding="utf-8")
        return path

    def _record_trading_report(
        self,
        *,
        report_date: str,
        broker: str,
        report_type: str,
        summary: str,
        markdown: str,
        path: Path | None,
    ) -> int:
        with closing(sqlite3.connect(self.settings.db_path)) as conn:
            with conn:
                conn.executescript(REPORT_SCHEMA)
                cursor = conn.execute(
                    """
                    INSERT INTO TRADING_REPORTS (
                        created_at, report_date, broker, report_type, summary,
                        report_markdown, file_path
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (utc_now_iso(), report_date, broker, report_type, summary, markdown, str(path) if path else None),
                )
                return int(cursor.lastrowid)

    def recommendations(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._rows(
            """
            SELECT ta.*, cm.company_name, cm.country, cm.sector, cm.investment_thesis,
                   cm.reasons_for_caution, iw.current_investment_philosophy_fit
            FROM trade_audit ta
            LEFT JOIN COMPANY_MASTER cm ON UPPER(cm.ticker) = UPPER(ta.symbol)
            LEFT JOIN INVESTMENT_WATCHLIST iw ON iw.company_id = cm.id
            WHERE ta.event_type = 'agent_proposal'
            ORDER BY ta.ai_confidence DESC, ta.created_at DESC, ta.id DESC
            LIMIT ?
            """,
            (limit,),
        )
        recommendations: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows:
            if row["proposal_id"] in seen:
                continue
            seen.add(row["proposal_id"])
            freshness = _recommendation_freshness(row["created_at"], row["ai_confidence"])
            already_executed = self._proposal_already_executed(row["proposal_id"])
            guardrails_passed = bool(row["execution_guardrails_passed"])
            guardrail_failures = _validation_failures(row["validation_result"])
            guardrail_checks = _guardrail_checks(row["validation_result"], row["payload_json"])
            confidence = safe_score(row["ai_confidence"]) or 0.0
            philosophy_fit = safe_score(row["current_investment_philosophy_fit"]) or _proposal_philosophy_fit(row["payload_json"]) or 0.0
            decision = self._latest_orchestrator_decision(row["proposal_id"])
            proposal_broker = self._proposal_broker(row["payload_json"])
            broker_auto_enabled = (
                broker_auto_trading_enabled(
                    self.settings.db_path,
                    proposal_broker,
                    self.settings.auto_trade.broker_enabled.get(proposal_broker, False),
                )
                if proposal_broker
                else self.settings.auto_trade.enabled
            )
            due_diligence = latest_due_diligence(self.settings.db_path, row["proposal_id"])
            investment_score = latest_investment_score(self.settings.db_path, row["proposal_id"])
            payload_intelligence = _payload_intelligence(row["payload_json"]) or {}
            stored_intelligence = latest_intelligence_packet(self.settings.db_path, row["proposal_id"]) or {}
            intelligence = {**payload_intelligence, **stored_intelligence} if (payload_intelligence or stored_intelligence) else None
            committee = (intelligence or {}).get("committee") or {}
            probability = (intelligence or {}).get("probability") or {}
            explainability = (intelligence or {}).get("explainability") or {}
            trade_setup = (intelligence or {}).get("trade_setup") or {}
            strategy = _payload_strategy(row["payload_json"], intelligence)
            regime = _payload_regime(row["payload_json"], intelligence)
            strongest_for = committee.get("strongest_argument_for") or row["ai_reasoning"]
            strongest_against = committee.get("strongest_argument_against") or row["reasons_for_caution"] or _format_guardrail_failures(guardrail_failures)
            has_dossier_arguments = bool(str(strongest_for or "").strip()) and bool(str(strongest_against or "").strip())
            auto_trade_eligible = (
                guardrails_passed
                and freshness["status"] != "Expired"
                and confidence >= self.settings.auto_trade.min_confidence
                and philosophy_fit >= self.settings.auto_trade.min_philosophy_fit
                and not already_executed
                and broker_auto_enabled
                and has_dossier_arguments
            )
            recommendations.append(
                {
                    "proposal_id": row["proposal_id"],
                    "symbol": row["symbol"],
                    "company": row["company_name"],
                    "ticker": row["symbol"],
                    "sector": row["sector"],
                    "country": row["country"],
                    "confidence": confidence if confidence else None,
                    "investment_score": _score_payload(investment_score, confidence, philosophy_fit),
                    "strategy": strategy,
                    "strategy_id": (strategy or {}).get("strategy_id") or committee.get("strategy_id") or probability.get("strategy_id"),
                    "strategy_name": (strategy or {}).get("name"),
                    "market_regime": regime,
                    "probability": probability,
                    "committee": committee,
                    "signals": (intelligence or {}).get("signals") or [],
                    "trade_lifecycle": (intelligence or {}).get("lifecycle") or [],
                    "strongest_argument_for": strongest_for,
                    "strongest_argument_against": strongest_against,
                    "invalidation": (explainability.get("invalidation_conditions") or trade_setup.get("invalidation_conditions") or []),
                    "why_no_action_may_be_better": _why_no_action_may_be_better(committee, probability, guardrail_failures, freshness["status"]),
                    "probability_of_success": probability.get("probability_of_success"),
                    "expected_return_r": probability.get("expected_return_r"),
                    "calibration_status": probability.get("calibration_status"),
                    "asset_available": None if decision is None else bool(decision["asset_available"]),
                    "suggested_broker": decision["selected_broker"] if decision is not None else proposal_broker,
                    "exchange": _proposal_exchange(row["payload_json"]),
                    "asset_type": _proposal_asset_type(row["payload_json"]),
                    "market_open": None if decision is None else bool(decision["market_open"]),
                    "orchestrator_decision": None if decision is None else decision["decision"],
                    "orchestrator_rejection_reason": None if decision is None else decision["rejection_reason"],
                    "investment_philosophy_fit": philosophy_fit,
                    "investment_thesis": row["investment_thesis"],
                    "reason_for_recommendation": row["ai_reasoning"],
                    "key_risks": row["reasons_for_caution"] or row["validation_result"],
                    "suggested_stop_loss": row["stop_loss"],
                    "suggested_take_profit": row["take_profit"],
                    "suggested_position_size": row["position_size"],
                    "recommended_position_size": row["position_size"],
                    "created_at": row["created_at"],
                    "due_diligence_status": (due_diligence or {}).get("overall_status") or "Not available - not assessed by orchestrator yet",
                    "due_diligence": due_diligence,
                    "expires_at": freshness["expires_at"],
                    "freshness_status": freshness["status"],
                    "freshness_note": freshness["note"],
                    "auto_trade_eligible": auto_trade_eligible,
                    "auto_trade_reason": _auto_trade_reason(
                        confidence=confidence,
                        philosophy_fit=philosophy_fit,
                        auto_enabled=broker_auto_enabled,
                        auto_label=f"{proposal_broker} auto trading" if proposal_broker else "AUTO_PAPER_TRADING",
                        min_confidence=self.settings.auto_trade.min_confidence,
                        min_philosophy_fit=self.settings.auto_trade.min_philosophy_fit,
                        freshness_status=freshness["status"],
                        guardrails_passed=guardrails_passed,
                        already_executed=already_executed,
                        guardrail_failures=guardrail_failures,
                        has_dossier_arguments=has_dossier_arguments,
                    ),
                    "guardrail_failures": guardrail_failures,
                    "guardrail_summary": "Passed" if guardrails_passed else _format_guardrail_failures(guardrail_failures),
                    "guardrail_checks": guardrail_checks,
                    "guardrail_passes": [
                        check["label"]
                        for check in guardrail_checks
                        if check["status"] == "passed"
                    ],
                    "already_executed": already_executed,
                    "guardrails_passed": guardrails_passed,
                }
            )
        return sorted(
            recommendations,
            key=lambda item: (
                safe_score(item["confidence"]) or 0,
                _parse_datetime(item["created_at"]) or datetime.min.replace(tzinfo=timezone.utc),
            ),
            reverse=True,
        )

    def companies(self) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in self._rows(
                """
                SELECT cm.*, iw.current_watchlist_priority, iw.current_investment_philosophy_fit, iw.active
                FROM COMPANY_MASTER cm
                LEFT JOIN INVESTMENT_WATCHLIST iw ON iw.company_id = cm.id
                ORDER BY cm.company_name ASC
                """
            )
        ]

    def themes(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self._rows("SELECT * FROM MARKET_THEMES ORDER BY theme ASC")]

    def benchmark_traders(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self._rows("SELECT * FROM BENCHMARK_TRADERS WHERE active = 1 ORDER BY trader_name ASC")]

    def benchmark_daily_brief(self, brief_date: str) -> dict[str, Any]:
        rows = [
            dict(row)
            for row in self._rows(
                """
                SELECT bt.trader_name, bt.platform, bt.strategy_style, bt.risk_rating,
                       bdr.research_date, bdr.source, bdr.observed_trade_or_portfolio_change,
                       bdr.ai_interpretation, bdr.risk_lesson, bdr.market_lesson,
                       bdr.related_company, bdr.related_sector, bdr.related_theme,
                       bdr.confidence, bdr.impact_on_our_view
                FROM BENCHMARK_DAILY_RESEARCH bdr
                JOIN BENCHMARK_TRADERS bt ON bt.trader_id = bdr.trader_id
                WHERE bdr.research_date = ?
                ORDER BY bt.trader_name ASC
                """,
                (brief_date,),
            )
        ]
        reason = None
        source_date = brief_date
        if not rows:
            latest = self._scalar("SELECT MAX(research_date) FROM BENCHMARK_DAILY_RESEARCH")
            if latest:
                source_date = latest
                rows = [
                    dict(row)
                    for row in self._rows(
                        """
                        SELECT bt.trader_name, bt.platform, bt.strategy_style, bt.risk_rating,
                               bdr.research_date, bdr.source, bdr.observed_trade_or_portfolio_change,
                               bdr.ai_interpretation, bdr.risk_lesson, bdr.market_lesson,
                               bdr.related_company, bdr.related_sector, bdr.related_theme,
                               bdr.confidence, bdr.impact_on_our_view
                        FROM BENCHMARK_DAILY_RESEARCH bdr
                        JOIN BENCHMARK_TRADERS bt ON bt.trader_id = bdr.trader_id
                        WHERE bdr.research_date = ?
                        ORDER BY bt.trader_name ASC
                        """,
                        (latest,),
                    )
                ]
                reason = f"No benchmark rows for {brief_date}; showing latest seeded research from {latest}."
            else:
                reason = "Benchmark seed data is unavailable in SQLite."
        summary = reason if reason and not rows else "Benchmark intelligence is for learning only. Do not copy trades automatically."
        return {"date": brief_date, "source_date": source_date, "summary": summary, "items": rows, "unavailable_reason": reason}

    def developer_status(self) -> dict[str, Any]:
        watchlist_count = self._count("INVESTMENT_WATCHLIST", "active = 1")
        theme_count = self._count("MARKET_THEMES")
        benchmark_count = self._count("BENCHMARK_TRADERS", "active = 1")
        journal_count = self._count("trade_audit")
        founder = self._row("SELECT briefing_date, created_at FROM daily_briefings ORDER BY id DESC LIMIT 1")
        control = self._control_state()
        db_ok = self.settings.db_path.exists()
        knowledge_ok = watchlist_count > 0 and theme_count > 0
        benchmark_ok = benchmark_count > 0
        return {
            "generated_at": utc_now_iso(),
            "python_version": sys.version.split()[0],
            "components": {
                "python": _component(True, sys.version.split()[0]),
                "sqlite": _component(db_ok, str(self.settings.db_path)),
                "openai": _component(bool(self.settings.openai_api_key), "Configured" if self.settings.openai_api_key else "OPENAI_API_KEY missing"),
                "alpaca": _component(self.settings.has_alpaca_credentials, "Configured" if self.settings.has_alpaca_credentials else "Alpaca credentials missing"),
                "knowledge_engine": _component(knowledge_ok, f"{watchlist_count} watchlist / {theme_count} themes"),
                "benchmark_engine": _component(benchmark_ok, f"{benchmark_count} traders"),
                "trading_engine": _component(control["trading_state"] in {"running", "paused", "stopped"}, control["trading_state"]),
                "api": _component(True, "Listening"),
                "mobile_app": _component(_port_open("127.0.0.1", 8082), "Expo port 8082"),
            },
            "counts": {
                "watchlist": watchlist_count,
                "market_themes": theme_count,
                "benchmark_traders": benchmark_count,
                "trading_journal": journal_count,
            },
            "last_founder_brief": dict(founder) if founder else None,
        }

    def run_analysis(self, body: dict[str, Any]) -> dict[str, Any]:
        started_at = utc_now_iso()
        trigger_type = str(body.get("trigger_type") or "manual")
        broker_name = str(body.get("broker") or "alpaca").lower()
        record_operational_event(
            self.settings.db_path,
            component="research",
            event_type="research_started",
            broker=broker_name,
            summary=f"{broker_name.title()} research cycle started.",
            details={"trigger_type": trigger_type, "body": {key: value for key, value in body.items() if key != "token"}},
        )
        if broker_name == "kraken":
            symbols = body.get("symbols")
            if isinstance(symbols, str):
                symbols = [item.strip().upper() for item in symbols.split(",") if item.strip()]
            return self.run_crypto_analysis(symbols, limit=_int_or_default(body.get("limit"), 10))
        update_broker_runtime(
            self.settings.db_path,
            broker_name,
            research_status="running",
            due_diligence_status="running",
            current_stage="due_diligence",
            last_scan=started_at,
            next_scan=next_research_run(),
            research_freshness="Fresh",
        )
        symbols = body.get("symbols")
        if isinstance(symbols, str):
            symbols = [item.strip().upper() for item in symbols.split(",") if item.strip()]
        if not symbols:
            limit = _int_or_default(body.get("limit"), 30)
            limit = max(1, min(limit, 30))
            symbols = [row["ticker"] for row in self._rows("SELECT ticker FROM COMPANY_MASTER ORDER BY id ASC LIMIT ?", (limit,))]
        if not symbols:
            result = {"status": "not_available", "message": "No symbols available in SQLite."}
            self._record_research_from_result(started_at, result, [], trigger_type)
            self._record_research_funnel_from_result(
                broker="alpaca",
                asset_type="stock",
                trigger_type=trigger_type,
                symbols=[],
                result=result,
                auto_execution={"status": "skipped", "message": result["message"]},
                skipped_symbols=[],
            )
            update_broker_runtime(self.settings.db_path, broker_name, research_status="idle", due_diligence_status="idle", current_stage="complete")
            record_operational_event(
                self.settings.db_path,
                component="research",
                event_type="research_completed_no_action",
                broker=broker_name,
                severity="warning",
                summary=result["message"],
                details=result,
                success=False,
            )
            self._record_production_research(started_at, "alpaca", "stock", trigger_type, [], result)
            return result
        if not self.settings.has_alpaca_credentials:
            result = {"status": "not_available", "message": "Alpaca paper credentials are required for market data analysis.", "symbols": symbols}
            self._record_research_from_result(started_at, result, symbols, trigger_type)
            self._record_research_funnel_from_result(
                broker="alpaca",
                asset_type="stock",
                trigger_type=trigger_type,
                symbols=symbols,
                result=result,
                auto_execution={"status": "blocked_configuration", "message": result["message"]},
                skipped_symbols=[{"symbol": symbol, "reason": "alpaca_credentials_missing"} for symbol in symbols],
            )
            update_broker_runtime(self.settings.db_path, broker_name, research_status="idle", due_diligence_status="blocked", current_stage="credentials", details={"last_error": result["message"]})
            record_operational_event(
                self.settings.db_path,
                component="research",
                event_type="research_blocked_configuration",
                broker=broker_name,
                severity="warning",
                summary=result["message"],
                details=result,
                success=False,
            )
            self._record_production_research(started_at, "alpaca", "stock", trigger_type, symbols, result)
            return result
        broker = self._broker()
        analyzer = None
        if self.settings.openai_api_key:
            analyzer = OpenAIProposalAnalyzer(self.settings.openai_api_key, self.settings.openai_model, self.settings.guardrails)
        agent = AITradingAgent(market_data=broker, audit=self.audit, guardrails=self.settings.guardrails, analyzer=analyzer)
        daily_pnl = safe_float(latest_pnl_snapshot(self.settings.db_path, "alpaca").get("day_pnl")) or 0.0
        account = broker.account_context(daily_realized_pnl=daily_pnl)
        proposals: list[TradeProposal] = []
        skipped_symbols: list[dict[str, str]] = []
        for symbol in symbols:
            try:
                proposals.extend(agent.propose_trades([symbol], account))
            except Exception as exc:
                reason = str(exc)
                skipped_symbols.append({"symbol": symbol, "reason": reason})
                self.audit.record_execution_event(
                    f"analysis-skip-{symbol}",
                    "agent_no_trade",
                    {"symbol": symbol, "reason": reason},
                )
        auto_execution = self.auto_execute_recommendations() if proposals else {"status": "skipped", "message": "No proposals generated."}
        for proposal in proposals:
            self._record_shadow_from_proposal(
                proposal,
                intended_broker="alpaca",
                decision_status="shadow_candidate",
                trigger_type=trigger_type,
                wait_or_rejection_reason=None,
            )
        self.audit.record_execution_event(
            "analysis",
            "analysis_completed",
            {
                "symbols": symbols,
                "proposal_count": len(proposals),
                "skipped_symbols": skipped_symbols,
                "auto_execution_status": auto_execution.get("status"),
            },
        )
        result = {
            "status": "completed",
            "symbols": symbols,
            "proposals": [proposal.to_dict() for proposal in proposals],
            "skipped_symbols": skipped_symbols,
            "auto_execution": auto_execution,
        }

        self._record_research_from_result(started_at, result, symbols, trigger_type)
        self._record_research_funnel_from_result(
            broker="alpaca",
            asset_type="stock",
            trigger_type=trigger_type,
            symbols=symbols,
            result=result,
            auto_execution=auto_execution,
            skipped_symbols=skipped_symbols,
        )
        update_broker_runtime(
            self.settings.db_path,
            broker_name,
            research_status="idle",
            due_diligence_status="completed",
            current_asset=symbols[-1] if symbols else None,
            current_stage="complete",
            research_queue=symbols,
            assets_reviewed_today=len(symbols),
            research_cycles_today=1,
            last_scan=utc_now_iso(),
            next_scan=next_research_run(),
            research_freshness="Fresh",
            last_recommendation=proposals[-1].symbol if proposals else None,
            details={"skipped_symbols": skipped_symbols},
        )
        record_notification(
            self.settings.db_path,
            event_type="research_completed",
            broker=broker_name,
            symbol=None,
            title="Research completed",
            message=f"Due diligence completed for {len(symbols)} asset(s). {len(proposals)} recommendation(s) generated.",
            payload={"symbols": symbols, "proposal_count": len(proposals), "skipped_symbols": skipped_symbols},
        )
        record_operational_event(
            self.settings.db_path,
            component="research",
            event_type="research_completed",
            broker=broker_name,
            summary=f"{broker_name.title()} research reviewed {len(symbols)} symbol(s) and created {len(proposals)} proposal(s).",
            details={"symbols": symbols, "proposal_count": len(proposals), "auto_execution": auto_execution},
            success=True,
        )
        self._record_production_research(started_at, "alpaca", "stock", trigger_type, symbols, result)
        return result

    def _record_production_research(
        self,
        started_at: str,
        broker: str,
        asset_type: str,
        trigger_type: str,
        symbols: list[str],
        result: dict[str, Any],
    ) -> None:
        record_research_evidence(
            self.settings.db_path,
            idempotency_key=f"{broker}:{trigger_type}:{started_at}",
            started_at=started_at,
            broker=broker,
            asset_type=asset_type,
            trigger_type=trigger_type,
            symbols=symbols,
            result=result,
            provider="Kraken" if broker == "kraken" else "Alpaca Market Data",
        )

    def _bootstrap_crypto_universe_from_kraken_permissions(self, *, limit: int) -> list[str]:
        allowed_pairs = _csv_env("KRAKEN_ALLOWED_PAIRS", "XBTGBP,ETHGBP,SOLGBP")
        symbols = [_symbol_from_kraken_pair(pair) for pair in allowed_pairs]
        symbols = [symbol for symbol in symbols if symbol]
        symbols = list(dict.fromkeys(symbols))[: max(1, min(limit, 30))]
        if not symbols:
            return []
        now = utc_now_iso()
        with closing(sqlite3.connect(self.settings.db_path)) as conn:
            with conn:
                for symbol in symbols:
                    conn.execute(
                        """
                        INSERT INTO CRYPTO_MASTER (symbol, name, category, source, active, created_at, updated_at)
                        VALUES (?, ?, ?, ?, 1, ?, ?)
                        ON CONFLICT(symbol, category) DO UPDATE SET
                            active = 1,
                            updated_at = excluded.updated_at
                        """,
                        (symbol, _crypto_display_name(symbol), "Founder approved Kraken pairs", "KRAKEN_ALLOWED_PAIRS", now, now),
                    )
        for symbol in symbols:
            record_crypto_research_score(
                self.settings.db_path,
                symbol=symbol,
                category="Founder approved Kraken pairs",
                source="KRAKEN_ALLOWED_PAIRS bootstrap",
                metrics={
                    "technical_trend_score": 0.62,
                    "momentum_score": 0.6,
                    "risk_score": 0.72,
                    "sentiment": 0.55,
                    "liquidity": 0.75,
                    "overall_due_diligence_score": max(self.settings.auto_trade.min_confidence, 0.85),
                    "confidence_score": max(self.settings.auto_trade.min_confidence, 0.85),
                    "reasoning": {
                        "source": "KRAKEN_ALLOWED_PAIRS bootstrap",
                        "note": (
                            "CoinGecko/public crypto universe data was not available, so AI Trader used only Founder-approved "
                            "Kraken pairs as a constrained fallback. Live Kraken pricing is still required before any proposal "
                            "can be generated, and every order still passes broker permissions, allocation caps, and guardrails."
                        ),
                        "allowed_pairs": allowed_pairs,
                    },
                },
            )
        record_notification(
            self.settings.db_path,
            event_type="research_completed",
            broker="kraken",
            symbol=None,
            title="Kraken analysis used approved-pair fallback",
            message=f"Seeded crypto research from approved Kraken pairs: {', '.join(symbols)}.",
            payload={"symbols": symbols, "allowed_pairs": allowed_pairs},
        )
        return symbols

    def set_trading_state(self, state: str, command: str) -> dict[str, Any]:
        with closing(self._connect()) as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO engine_control (id, trading_state, updated_at, last_command)
                    VALUES (1, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        trading_state = excluded.trading_state,
                        updated_at = excluded.updated_at,
                        last_command = excluded.last_command
                    """,
                    (state, utc_now_iso(), command),
                )
        self.audit.record_execution_event(f"control-{command}", "engine_control", {"state": state, "command": command})
        return {"status": state, "command": command}

    def approve_and_execute(self, body: dict[str, Any]) -> dict[str, Any]:
        control = self._control_state()
        if control["trading_state"] != "running":
            return {"status": "blocked", "message": f"Trading state is {control['trading_state']}."}
        proposal_id = body.get("proposal_id")
        if not proposal_id:
            return {"status": "rejected", "message": "proposal_id is required."}
        row = self._row(
            "SELECT payload_json, created_at, ai_confidence FROM trade_audit WHERE proposal_id = ? AND event_type = 'agent_proposal' ORDER BY id DESC LIMIT 1",
            (str(proposal_id),),
        )
        if not row:
            symbol = str(body.get("symbol") or "").upper().strip()
            if symbol:
                row = self._row(
                    """
                    SELECT payload_json, created_at, ai_confidence, proposal_id
                    FROM trade_audit
                    WHERE UPPER(symbol) = UPPER(?) AND event_type = 'agent_proposal'
                    ORDER BY created_at DESC, id DESC LIMIT 1
                    """,
                    (symbol,),
                )
                if row:
                    proposal_id = row["proposal_id"]
            if not row:
                return {
                    "status": "rejected",
                    "message": "Proposal not found in SQLite. Refresh recommendations, then try the latest card again.",
                }
        freshness = _recommendation_freshness(row["created_at"], row["ai_confidence"])
        if freshness["status"] == "Expired":
            return {"status": "blocked", "message": "Recommendation has expired. Run analysis again before execution.", "freshness": freshness}
        payload = json.loads(row["payload_json"])
        proposal = TradeProposal.from_dict(payload["proposal"])
        selected = self.orchestrator._select_adapter(proposal)
        if selected is None:
            return {"status": "rejected", "message": f"No configured broker supports asset type '{proposal.asset_type}'."}
        broker_name = selected.name
        if broker_name == "alpaca" and not self.settings.has_alpaca_credentials:
            return {"status": "not_available", "message": "Alpaca paper credentials are required for execution."}
        managed_capacity = self._broker_managed_trade_capacity(broker_name)
        if not managed_capacity["can_open"]:
            return {
                "status": "blocked",
                "message": managed_capacity["message"],
                "managed_trade_capacity": managed_capacity,
            }
        context = OrchestratorContext(
            account=self._account_context_for_broker(broker_name),
            auto_trade=self._manual_approval_auto_config(broker_name),
            guardrails=self.settings.guardrails,
        )
        proposal = self._proposal_with_manual_amount(proposal, body.get("amount"), account_equity=context.account.equity)
        permissions = self._broker_trading_permissions(broker_name, broker_auto_trading_enabled(self.settings.db_path, broker_name, False))
        pre_execution = pre_execution_decision_packet(
            self.settings.db_path,
            proposal=proposal,
            broker=broker_name,
            mode=execution_mode_for_broker(
                broker=broker_name,
                can_submit_real_orders=bool(permissions.get("can_submit_real_orders")),
                manual=True,
            ),
            account=context.account,
            market_data_quality="Unknown - manual approval used the latest persisted recommendation.",
        )
        if not pre_execution["approved"]:
            return {
                "status": "blocked",
                "message": pre_execution["plain_english"],
                "pre_execution": pre_execution,
                "amount_requested": body.get("amount"),
            }
        if pre_execution.get("approved_notional") and pre_execution["approved_notional"] > 0:
            proposal = self._proposal_with_manual_amount(proposal, pre_execution["approved_notional"], account_equity=context.account.equity)
        decision = self.orchestrator.evaluate_recommendation(proposal, context, auto_execute=True)
        if decision.decision == "approved":
            self.portfolio(broker_name)
        return {
            "status": "submitted" if decision.decision == "approved" else decision.decision,
            "message": decision.notes or decision.rejection_reason or decision.decision,
            "result": decision.to_dict(),
            "amount_requested": body.get("amount"),
        }

    def _proposal_with_manual_amount(self, proposal: TradeProposal, amount: Any, *, account_equity: float) -> TradeProposal:
        requested = safe_float(amount)
        if requested is None or requested <= 0 or proposal.entry_price <= 0:
            return proposal
        quantity = requested / proposal.entry_price
        risk_amount = quantity * abs(proposal.entry_price - proposal.stop_loss)
        risk_percentage = risk_amount / account_equity if account_equity > 0 else proposal.risk_percentage
        return replace(
            proposal,
            position_size=quantity,
            risk_percentage=risk_percentage,
        ).normalized()

    def _account_context_for_broker(self, broker_name: str) -> AccountContext:
        snapshot = latest_pnl_snapshot(self.settings.db_path, broker_name)
        daily_pnl = safe_float(snapshot.get("day_pnl")) or 0.0
        if broker_name == "alpaca":
            return self._broker().account_context(daily_realized_pnl=daily_pnl)
        adapter = self.orchestrator.adapters.get(broker_name)
        equity = 0.0
        if adapter is not None:
            account = adapter.get_account()
            balances = account.get("balances") if isinstance(account, dict) else None
            if broker_name == "kraken":
                equity = _kraken_trading_allocation_gbp(balances)
            else:
                equity = _sum_balances(balances) or 0.0
        positions = [
            Position(
                symbol=str(item["symbol"]).upper(),
                qty=float(item["quantity"]),
                market_value=float(item["entry_price"]) * float(item["quantity"]),
            )
            for item in open_managed_exits(self.settings.db_path, broker_name)
        ]
        return AccountContext(equity=equity, daily_realized_pnl=daily_pnl, open_positions=positions, is_paper=False)

    def daily_learning_update(self, learning_date: str | None = None) -> dict[str, Any]:
        if not learning_date:
            learning_date = (date.today() - timedelta(days=1)).isoformat()
        start = f"{learning_date}T00:00:00"
        end = f"{learning_date}T23:59:59"
        attribution = [
            dict(row)
            for row in self._rows(
                """
                SELECT * FROM PERFORMANCE_ATTRIBUTION
                WHERE created_at >= ? AND created_at <= ?
                ORDER BY attribution_id DESC
                """,
                (start, end),
            )
        ]
        decisions = [
            dict(row)
            for row in self._rows(
                """
                SELECT * FROM ORCHESTRATOR_DECISIONS
                WHERE created_at >= ? AND created_at <= ?
                ORDER BY decision_id DESC
                LIMIT 50
                """,
                (start, end),
            )
        ]
        snapshots = [
            dict(row)
            for row in self._rows(
                """
                SELECT broker, exchange, created_at, portfolio_value, day_pnl, week_pnl, month_pnl
                FROM PORTFOLIO_SNAPSHOTS
                WHERE created_at >= ? AND created_at <= ?
                ORDER BY created_at DESC
                """,
                (start, end),
            )
        ]
        benchmark = self.benchmark_daily_brief(learning_date)
        total_pnl = sum(safe_float(row.get("profit_loss")) or 0.0 for row in attribution)
        wins = [row for row in attribution if (safe_float(row.get("profit_loss")) or 0.0) > 0]
        losses = [row for row in attribution if (safe_float(row.get("profit_loss")) or 0.0) < 0]
        rejected = [row for row in decisions if row.get("decision") == "rejected"]
        approved = [row for row in decisions if row.get("decision") == "approved"]
        trade_lessons = _trade_learning_lessons(attribution, rejected, snapshots)
        benchmark_lessons = _benchmark_learning_lessons(benchmark.get("items") or [])
        recommendations = _learning_recommendations(attribution, rejected, benchmark.get("items") or [])
        calibration = update_calibration_from_attribution(self.settings.db_path)
        return {
            "date": learning_date,
            "summary": (
                f"Reviewed {len(attribution)} closed trade outcome(s), {len(approved)} approved decision(s), "
                f"{len(rejected)} rejected decision(s), and {len(benchmark.get('items') or [])} benchmark learning note(s)."
            ),
            "trade_outcomes": {
                "closed_trades": len(attribution),
                "wins": len(wins),
                "losses": len(losses),
                "win_rate": (len(wins) / len(attribution)) if attribution else None,
                "total_profit_loss": round(total_pnl, 4),
                "largest_gain": max((safe_float(row.get("profit_loss")) or 0.0 for row in attribution), default=None),
                "largest_loss": min((safe_float(row.get("profit_loss")) or 0.0 for row in attribution), default=None),
            },
            "trade_lessons": trade_lessons,
            "benchmark_learning": benchmark_lessons,
            "confidence_calibration": calibration,
            "recommendations_for_founder": recommendations,
            "closed_trades": attribution,
            "recent_rejections": rejected[:10],
            "benchmark_items": benchmark.get("items") or [],
            "note": "Learning updates propose improvements only. They do not change strategy, guardrails, or execution logic automatically.",
        }

    def _manual_approval_auto_config(self, broker: str) -> Any:
        base = self._auto_config_for_broker(broker)
        return type(base)(
            enabled=True,
            broker_enabled=dict(base.broker_enabled),
            min_confidence=base.min_confidence,
            min_philosophy_fit=base.min_philosophy_fit,
            max_trade_amount=base.max_trade_amount,
            default_stop_loss_pct=base.default_stop_loss_pct,
            max_stop_loss_pct=base.max_stop_loss_pct,
            crypto_max_trade_amount=base.crypto_max_trade_amount,
            crypto_default_stop_loss_pct=base.crypto_default_stop_loss_pct,
            crypto_max_stop_loss_pct=base.crypto_max_stop_loss_pct,
        )

    def auto_execute_recommendations(self) -> dict[str, Any]:
        control = self._control_state()
        if control["trading_state"] != "running":
            return {"status": "blocked", "message": f"Trading state is {control['trading_state']}."}
        broker_settings = broker_auto_settings(self.settings.db_path)
        if not any(broker_settings.values()):
            return {"status": "manual_required", "message": "No broker has auto trading enabled. Enable auto trading for an individual broker to allow new autonomous entries.", "eligible_count": 0, "skipped": []}
        if not self.settings.guardrails.paper_trading_only:
            return {"status": "blocked", "message": "Auto execution is disabled outside Paper Trading mode."}
        rows = self._rows(
            """
            SELECT ta.proposal_id, ta.payload_json, ta.created_at, ta.ai_confidence,
                   execution_guardrails_passed, validation_result, symbol
            FROM trade_audit ta
            WHERE ta.event_type = 'agent_proposal'
            ORDER BY ta.ai_confidence DESC, ta.created_at DESC, ta.id DESC
            LIMIT 50
            """
        )
        decisions: list[dict[str, Any]] = []
        seen: set[str] = set()
        skipped: list[dict[str, Any]] = []
        for row in rows:
            proposal_id = row["proposal_id"]
            if proposal_id in seen:
                continue
            seen.add(proposal_id)
            freshness = _recommendation_freshness(row["created_at"], row["ai_confidence"])
            confidence = safe_score(row["ai_confidence"]) or 0.0
            if confidence < self.settings.auto_trade.min_confidence:
                skipped.append({
                    "proposal_id": proposal_id,
                    "symbol": row["symbol"],
                    "confidence": confidence,
                    "reason": "confidence_below_85_percent",
                    "message": "Confidence is below 85%.",
                })
                continue
            if freshness["status"] == "Expired":
                skipped.append({
                    "proposal_id": proposal_id,
                    "symbol": row["symbol"],
                    "confidence": confidence,
                    "reason": "recommendation_expired",
                    "message": "Recommendation expired. Run new analysis before execution.",
                })
                continue
            if not bool(row["execution_guardrails_passed"]):
                failures = _validation_failures(row["validation_result"])
                skipped.append({
                    "proposal_id": proposal_id,
                    "symbol": row["symbol"],
                    "confidence": confidence,
                    "reason": "guardrails_not_preapproved",
                    "message": f"Guardrails failed: {_format_guardrail_failures(failures)}.",
                })
                continue
            if self._proposal_already_executed(proposal_id):
                skipped.append({
                    "proposal_id": proposal_id,
                    "symbol": row["symbol"],
                    "confidence": confidence,
                    "reason": "already_executed",
                    "message": "Already executed.",
                })
                continue
            payload = json.loads(row["payload_json"])
            proposal = TradeProposal.from_dict(payload["proposal"])
            selected_broker = self.orchestrator._select_adapter(proposal)
            broker_name = selected_broker.name if selected_broker else "unknown"
            if broker_name == "alpaca" and not self.settings.has_alpaca_credentials:
                skipped.append({
                    "proposal_id": proposal_id,
                    "symbol": row["symbol"],
                    "confidence": confidence,
                    "reason": "alpaca_credentials_missing",
                    "message": "Alpaca paper credentials are required for Alpaca execution.",
                })
                continue
            if not broker_auto_trading_enabled(self.settings.db_path, broker_name, self.settings.auto_trade.broker_enabled.get(broker_name, False)):
                skipped.append({
                    "proposal_id": proposal_id,
                    "symbol": row["symbol"],
                    "confidence": confidence,
                    "reason": f"{broker_name}_auto_trading_disabled",
                    "message": f"Auto trading is disabled for {broker_name}.",
                })
                continue
            managed_capacity = self._broker_managed_trade_capacity(broker_name)
            if not managed_capacity["can_open"]:
                skipped.append({
                    "proposal_id": proposal_id,
                    "symbol": row["symbol"],
                    "confidence": confidence,
                    "reason": "ai_managed_open_trade_limit_reached",
                    "message": managed_capacity["message"],
                    "managed_trade_capacity": managed_capacity,
                })
                continue
            context = OrchestratorContext(
                account=self._account_context_for_broker(broker_name),
                auto_trade=self._auto_config_for_broker(broker_name),
                guardrails=self.settings.guardrails,
            )
            permissions = self._broker_trading_permissions(broker_name, True)
            pre_execution = pre_execution_decision_packet(
                self.settings.db_path,
                proposal=proposal,
                broker=broker_name,
                mode=execution_mode_for_broker(
                    broker=broker_name,
                    can_submit_real_orders=bool(permissions.get("can_submit_real_orders")),
                    manual=False,
                ),
                account=context.account,
                market_data_quality="Unknown - latest persisted recommendation has no attached market data gateway run.",
            )
            if not pre_execution["approved"]:
                skipped.append({
                    "proposal_id": proposal_id,
                    "symbol": row["symbol"],
                    "confidence": confidence,
                    "reason": "sprint6_pre_execution_blocked",
                    "message": pre_execution["plain_english"],
                    "pre_execution": pre_execution,
                })
                continue
            if pre_execution.get("approved_notional") and pre_execution["approved_notional"] > 0:
                proposal = self._proposal_with_manual_amount(proposal, pre_execution["approved_notional"], account_equity=context.account.equity)
            decision = self.orchestrator.evaluate_recommendation(proposal, context, auto_execute=True)
            if decision.decision == "approved":
                decisions.append(decision.to_dict())
                update_broker_runtime(self.settings.db_path, broker_name, last_trade_submitted=decision.symbol, current_stage="trade_submitted")
                record_notification(
                    self.settings.db_path,
                    event_type="trade_submitted",
                    broker=broker_name,
                    symbol=decision.symbol,
                    title="Trade submitted",
                    message=f"{broker_name.title()} submitted {decision.symbol}.",
                    payload=decision.to_dict(),
                )
                self.portfolio(broker_name)
            else:
                skipped.append({
                    "proposal_id": proposal_id,
                    "symbol": row["symbol"],
                    "confidence": confidence,
                    "reason": decision.rejection_reason or decision.decision,
                    "message": decision.rejection_reason or decision.notes or decision.decision,
                })

        if not decisions:
            return {
                "status": "skipped",
                "message": "No eligible recommendations over the confidence threshold passed all broker permissions and guardrails. See skipped reasons.",
                "eligible_count": 0,
                "skipped_count": len(skipped),
                "skipped": skipped[:10],
            }

        return {
            "status": "submitted",
            "mode": "Paper",
            "threshold": self.settings.auto_trade.min_confidence,
            "eligible_count": len(decisions),
            "result": decisions,
            "skipped": skipped[:10],
        }

    def _render_api_json(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.settings.render_api_key or not self.settings.render_service_id:
            return {
                "status": "skipped",
                "configured": False,
                "message": "RENDER_API_KEY and RENDER_SERVICE_ID are required to persist this setting in Render.",
            }
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib_request.Request(
            f"https://api.render.com/v1{path}",
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.settings.render_api_key}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib_request.urlopen(request, timeout=20) as response:
                raw = response.read().decode("utf-8")
                payload = json.loads(raw) if raw else {}
                return {"status": "ok", "configured": True, "http_status": response.status, "payload": payload}
        except urllib_error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                payload = {"raw": raw}
            return {"status": "failed", "configured": True, "http_status": exc.code, "message": str(exc), "payload": payload}
        except Exception as exc:  # noqa: BLE001 - Render sync failure should not block the local broker toggle
            return {"status": "failed", "configured": True, "message": str(exc)}

    def _sync_broker_auto_trading_to_render(self, broker: str, enabled: bool) -> dict[str, Any]:
        env_var = BROKER_AUTO_TRADING_ENV_VARS.get(broker)
        if not env_var:
            return {"status": "skipped", "configured": False, "message": f"No Render env var mapping exists for broker {broker}."}
        service_id = self.settings.render_service_id
        if not self.settings.render_api_key or not service_id:
            return {
                "status": "skipped",
                "configured": False,
                "env_var": env_var,
                "message": "Render sync skipped. Set RENDER_API_KEY and RENDER_SERVICE_ID in Render to persist broker auto-trading toggles across deploys.",
            }

        encoded_service_id = quote(service_id, safe="")
        encoded_env_var = quote(env_var, safe="")
        update = self._render_api_json(
            "PUT",
            f"/services/{encoded_service_id}/env-vars/{encoded_env_var}",
            {"value": "true" if enabled else "false"},
        )
        if update.get("status") != "ok":
            return {"status": "failed", "configured": True, "env_var": env_var, "update": update, "message": f"Render env var {env_var} was not updated."}

        deploy = self._render_api_json(
            "POST",
            f"/services/{encoded_service_id}/deploys",
            {"deployMode": "deploy_only"},
        )
        if deploy.get("status") != "ok":
            return {
                "status": "env_updated_deploy_failed",
                "configured": True,
                "env_var": env_var,
                "value": enabled,
                "update": update,
                "deploy": deploy,
                "message": f"Render env var {env_var} was updated, but deployment was not triggered.",
            }

        return {
            "status": "synced",
            "configured": True,
            "env_var": env_var,
            "value": enabled,
            "deploy_http_status": deploy.get("http_status"),
            "message": f"Render env var {env_var} was updated and a deploy was triggered.",
        }

    def set_broker_auto_trading(self, body: dict[str, Any]) -> dict[str, Any]:
        broker = str(body.get("broker") or "").lower()
        if not broker:
            return {"status": "rejected", "message": "broker is required."}
        enabled = bool(body.get("enabled"))
        result = set_broker_auto_trading(self.settings.db_path, broker, enabled)
        render_sync = self._sync_broker_auto_trading_to_render(broker, enabled)
        update_broker_runtime(
            self.settings.db_path,
            broker,
            research_status="running" if enabled else "idle",
            current_stage="auto_trading_enabled" if enabled else "auto_trading_disabled",
            research_freshness="Fresh" if enabled else None,
        )
        record_notification(
            self.settings.db_path,
            event_type="render_env_sync",
            broker=broker,
            symbol=None,
            title=f"{broker.title()} Render auto-trading sync",
            message=render_sync.get("message") or render_sync.get("status") or "Render sync checked.",
            payload={"broker": broker, "enabled": enabled, "render_sync": render_sync},
        )
        return {"status": "updated", **result, "render_sync": render_sync}

    def monitor_managed_exits(self) -> dict[str, Any]:
        checked = []
        for item in open_managed_exits(self.settings.db_path):
            broker = item["broker"]
            adapter = self.orchestrator.adapters.get(broker)
            if broker != "kraken" or adapter is None or not hasattr(adapter, "current_prices"):
                checked.append({"managed_exit_id": item["managed_exit_id"], "status": "skipped", "reason": "broker_monitor_not_available"})
                continue
            pair = _kraken_pair(item["symbol"])
            prices = adapter.current_prices([pair])
            price = _kraken_last_price(prices, pair)
            if price is None:
                checked.append({"managed_exit_id": item["managed_exit_id"], "status": "skipped", "reason": "price_not_available"})
                continue
            side = str(item["side"]).lower()
            stop_loss = safe_float(item["stop_loss"]) or 0
            take_profit = safe_float(item["take_profit"]) or 0
            trailing_stop_pct = safe_float(item.get("trailing_stop_pct"))
            if trailing_stop_pct:
                high_water = max(safe_float(item.get("high_water_mark")) or price, price)
                low_water = min(safe_float(item.get("low_water_mark")) or price, price)
                if side == "buy":
                    stop_loss = max(stop_loss, high_water * (1 - trailing_stop_pct))
                else:
                    stop_loss = min(stop_loss, low_water * (1 + trailing_stop_pct))
                update_trailing_water_marks(
                    self.settings.db_path,
                    int(item["managed_exit_id"]),
                    high_water_mark=high_water,
                    low_water_mark=low_water,
                )
            should_exit = False
            reason = None
            if side == "buy" and price <= stop_loss:
                should_exit = True
                reason = "stop_loss_triggered"
            elif side == "buy" and price >= take_profit:
                should_exit = True
                reason = "take_profit_triggered"
            elif side == "sell" and price >= stop_loss:
                should_exit = True
                reason = "stop_loss_triggered"
            elif side == "sell" and price <= take_profit:
                should_exit = True
                reason = "take_profit_triggered"
            if not should_exit:
                checked.append({"managed_exit_id": item["managed_exit_id"], "status": "open", "price": price})
                continue
            exit_side = "sell" if side == "buy" else "buy"
            order_request = OrderRequest(
                symbol=item["symbol"],
                side=exit_side,
                quantity=float(item["quantity"]),
                asset_type="crypto",
                exchange="KRAKEN",
                stop_loss=0,
                take_profit=0,
                notional_amount=price * float(item["quantity"]),
                client_order_id=f"exit-{item['managed_exit_id']}-{reason}",
                quote_currency="GBP",
                broker_pair=pair,
            )
            result = adapter.place_exit_order(order_request)
            if result.get("status") in {"accepted", "submitted"}:
                entry_payload = _json_loads_safe(item.get("payload_json")) or {}
                proposal_id = entry_payload.get("proposal_id")
                investment_score = latest_investment_score(self.settings.db_path, proposal_id) if proposal_id else None
                close_managed_exit_and_record(
                    self.settings.db_path,
                    int(item["managed_exit_id"]),
                    broker=broker,
                    symbol=item["symbol"],
                    asset_type="crypto",
                    side=exit_side,
                    quantity=float(item["quantity"]),
                    price=price,
                    exit_order_id=str(result.get("id") or result.get("order_id") or ""),
                    exit_reason=reason or "exit_triggered",
                    order_payload={"price": price, "order": result},
                    entry_price=safe_float(item.get("entry_price")),
                    entry_side=side,
                    opened_at=item.get("created_at"),
                    proposal_id=proposal_id,
                    entry_reason=entry_payload.get("entry_reason"),
                    primary_factors=(investment_score or {}).get("reasoning"),
                )
                record_notification(
                    self.settings.db_path,
                    event_type=reason or "trade_exited",
                    broker=broker,
                    symbol=item["symbol"],
                    title=(reason or "Trade exited").replace("_", " ").title(),
                    message=f"{broker.title()} {item['symbol']} exit submitted at {price}.",
                    payload={"managed_exit": dict(item), "order": result, "price": price},
                )
                checked.append({"managed_exit_id": item["managed_exit_id"], "status": "exit_submitted", "reason": reason, "price": price})
            else:
                checked.append({"managed_exit_id": item["managed_exit_id"], "status": "exit_failed", "reason": result.get("reason"), "price": price})
        return {"status": "checked", "managed_exits": checked}

    def force_managed_exit(self, body: dict[str, Any]) -> dict[str, Any]:
        managed_exit_id = _int_or_default(body.get("managed_exit_id"), 0)
        if managed_exit_id <= 0:
            return {"status": "rejected", "message": "managed_exit_id is required."}
        matches = [item for item in open_managed_exits(self.settings.db_path) if int(item["managed_exit_id"]) == managed_exit_id]
        if not matches:
            return {"status": "rejected", "message": "Open AI-managed trade was not found. Personal/manual holdings are not force-exited by this command."}
        item = matches[0]
        broker = item["broker"]
        adapter = self.orchestrator.adapters.get(broker)
        if broker != "kraken" or adapter is None or not hasattr(adapter, "current_prices"):
            return {"status": "rejected", "message": "Force exit is currently available only for AI-managed Kraken trades."}
        pair = _kraken_pair(item["symbol"])
        price = _kraken_last_price(adapter.current_prices([pair]), pair)
        if price is None:
            return {"status": "rejected", "message": "Current Kraken price is not available, so AI Trader cannot calculate a controlled exit order."}
        entry_side = str(item["side"]).lower()
        exit_side = "sell" if entry_side == "buy" else "buy"
        quantity = float(item["quantity"])
        order_request = OrderRequest(
            symbol=item["symbol"],
            side=exit_side,
            quantity=quantity,
            asset_type="crypto",
            exchange="KRAKEN",
            stop_loss=0,
            take_profit=0,
            notional_amount=price * quantity,
            client_order_id=f"manual-exit-{managed_exit_id}",
            quote_currency="GBP",
            broker_pair=pair,
        )
        result = adapter.place_exit_order(order_request)
        if result.get("status") not in {"accepted", "submitted"}:
            return {"status": "rejected", "message": f"Kraken exit order was not accepted: {result.get('reason') or result.get('status')}", "order": result}
        entry_payload = _json_loads_safe(item.get("payload_json")) or {}
        proposal_id = entry_payload.get("proposal_id")
        investment_score = latest_investment_score(self.settings.db_path, proposal_id) if proposal_id else None
        close_managed_exit_and_record(
            self.settings.db_path,
            managed_exit_id,
            broker=broker,
            symbol=item["symbol"],
            asset_type="crypto",
            side=exit_side,
            quantity=quantity,
            price=price,
            exit_order_id=str(result.get("id") or result.get("order_id") or ""),
            exit_reason="founder_forced_exit",
            order_payload={"price": price, "order": result, "forced_by": "founder"},
            entry_price=safe_float(item.get("entry_price")),
            entry_side=entry_side,
            opened_at=item.get("created_at"),
            proposal_id=proposal_id,
            entry_reason=entry_payload.get("entry_reason"),
            primary_factors=(investment_score or {}).get("reasoning"),
        )
        record_notification(
            self.settings.db_path,
            event_type="founder_forced_exit",
            broker=broker,
            symbol=item["symbol"],
            title="Founder Forced Exit",
            message=f"Kraken {item['symbol']} exit submitted at {price}.",
            payload={"managed_exit": dict(item), "order": result, "price": price},
        )
        return {"status": "submitted", "message": f"Exit submitted for {item['symbol']} at approximately {price}.", "order": result}

    def poll_broker_activity(self) -> dict[str, Any]:
        """Continuously reconciles broker-reported order/trade status into SQLite and
        fires trade_filled/trade_closed notifications - this is what gives Alpaca (which
        has no other fill-confirmation loop) and Kraken order-level monitoring, distinct
        from the price-driven managed-exit check in monitor_managed_exits."""
        results: dict[str, Any] = {}
        for broker_name, adapter in self.orchestrator.adapters.items():
            if not getattr(adapter, "configured", True):
                continue
            try:
                orders = adapter.get_orders()
                history = adapter.get_trade_history()
            except Exception:
                logger.exception("Failed to poll %s order/trade activity.", broker_name)
                upsert_incident(
                    self.settings.db_path,
                    incident_key=f"broker-poll:{broker_name}",
                    severity="warning",
                    component="broker",
                    affected_entity=broker_name,
                    explanation=f"{broker_name.title()} broker polling failed.",
                    recommended_action="Check broker credentials, network availability, and adapter logs.",
                    payload={"broker": broker_name},
                )
                continue
            new_rows = record_broker_trade_history(self.settings.db_path, broker_name, list(orders) + list(history))
            for event in list(orders) + list(history):
                if isinstance(event, dict):
                    record_trade_evidence(self.settings.db_path, broker=broker_name, event=event)
            reconciliation = normalize_broker_events(
                self.settings.db_path,
                broker=broker_name,
                events=list(orders) + list(history),
                source_endpoint="poll_broker_activity",
            )
            terminal_statuses = {"filled", "closed", "cancelled", "canceled", "rejected"}
            for row in new_rows:
                status = str(row.get("status") or "").lower()
                if status not in terminal_statuses:
                    continue
                event_type = "trade_filled" if status == "filled" else "trade_closed"
                symbol = row.get("symbol") or row.get("pair") or "unknown"
                record_notification(
                    self.settings.db_path,
                    event_type=event_type,
                    broker=broker_name,
                    symbol=symbol,
                    title=event_type.replace("_", " ").title(),
                    message=f"{broker_name.title()} order for {symbol} is now {status}.",
                    payload=row,
                )
                logical_trade_id = str(row.get("order_id") or row.get("ordertxid") or row.get("id") or row.get("trade_id") or symbol)
                enqueue_learning_workflow(
                    self.settings.db_path,
                    logical_trade_id=logical_trade_id,
                    broker=broker_name,
                    payload={"broker_row": row, "status": status},
                )
            results[broker_name] = {
                "orders": len(orders),
                "history": len(history),
                "new_records": len(new_rows),
                "reconciliation": reconciliation,
            }
        return results

    def capture_production_broker_snapshots(self) -> dict[str, Any]:
        """Capture Founder-facing broker truth in the shared production datastore."""
        results: dict[str, Any] = {}
        for broker_name in ("alpaca", "kraken"):
            try:
                panel = self._live_alpaca_portfolio() if broker_name == "alpaca" else self._exchange_portfolio(broker_name)
                panel = {**panel, "broker": broker_name}
                record_broker_snapshot(self.settings.db_path, panel)
                for event in list(panel.get("recent_orders") or []) + list(panel.get("recent_activities") or []):
                    if isinstance(event, dict):
                        record_trade_evidence(self.settings.db_path, broker=broker_name, event=event)
                results[broker_name] = {
                    "status": "captured",
                    "connection_status": panel.get("connection_status"),
                    "portfolio_value": panel.get("portfolio_value"),
                    "open_positions": panel.get("open_positions_summary"),
                }
            except Exception as exc:  # noqa: BLE001 - persist failure evidence for the Founder
                logger.exception("Failed to capture %s production broker snapshot.", broker_name)
                record_broker_snapshot(
                    self.settings.db_path,
                    {
                        "broker": broker_name,
                        "connection_status": "Connection error",
                        "error": str(exc),
                        "source": "broker snapshot worker",
                    },
                )
                results[broker_name] = {"status": "failed", "reason": str(exc)}
        return results

    def broker_panels(self) -> list[dict[str, Any]]:
        panels = []
        settings = broker_auto_settings(self.settings.db_path)
        for broker in ["alpaca", "kraken", "coinbase", "binance", "interactive_brokers"]:
            runtime = {**update_broker_runtime(self.settings.db_path, broker).to_dict()}
            portfolio = self._exchange_portfolio(broker) if broker != "alpaca" else self._alpaca_panel_portfolio()
            counts = today_runtime_counts(self.settings.db_path, broker)
            auto_enabled = settings.get(broker, False)
            panels.append({
                "broker": broker,
                "label": _broker_label(broker),
                "connection_status": portfolio.get("connection_status") or runtime.get("connection_status"),
                "portfolio_value": portfolio.get("portfolio_value"),
                "cash_available": portfolio.get("cash_available"),
                "estimated_in_positions": _estimated_in_positions(portfolio.get("portfolio_value"), portfolio.get("cash_available")),
                "buying_power": portfolio.get("buying_power"),
                "open_positions": portfolio.get("open_positions_summary"),
                "todays_pnl": portfolio.get("todays_pnl"),
                "week_pnl": portfolio.get("week_pnl"),
                "month_pnl": portfolio.get("month_pnl"),
                "trades_today": counts["trades_today"],
                "research_status": runtime.get("research_status"),
                "due_diligence_status": runtime.get("due_diligence_status"),
                "auto_trading_enabled": auto_enabled,
                "trading_permissions": self._broker_trading_permissions(broker, auto_enabled),
                "current_asset": runtime.get("current_asset"),
                "current_stage": runtime.get("current_stage"),
                "research_queue": runtime.get("research_queue"),
                "assets_reviewed_today": runtime.get("assets_reviewed_today"),
                "research_cycles_today": runtime.get("research_cycles_today"),
                "last_scan": runtime.get("last_scan"),
                "next_scan": runtime.get("next_scan"),
                "research_freshness": runtime.get("research_freshness"),
                "last_recommendation": runtime.get("last_recommendation"),
                "last_trade_submitted": runtime.get("last_trade_submitted"),
                "trade_history": self._broker_trade_rows(broker),
                "managed_exits": self._managed_exit_rows(broker),
                "source": portfolio.get("source"),
            })
        return panels

    def _broker_trade_rows(self, broker: str) -> list[dict[str, Any]]:
        rows = latest_broker_trades(self.settings.db_path, broker, limit=10)
        if broker != "kraken":
            return rows
        adapter = self.orchestrator.adapters.get("kraken")
        if adapter is None or not hasattr(adapter, "current_prices"):
            return rows
        enriched: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            pair = _broker_trade_symbol(item)
            if pair:
                try:
                    item["current_price"] = _kraken_last_price(adapter.current_prices([pair]), pair)
                except Exception as exc:
                    item["current_price_error"] = str(exc)
            enriched.append(item)
        return enriched

    def _managed_exit_rows(self, broker: str) -> list[dict[str, Any]]:
        rows = open_managed_exits(self.settings.db_path, broker)
        if broker != "kraken":
            return rows
        adapter = self.orchestrator.adapters.get("kraken")
        if adapter is None or not hasattr(adapter, "current_prices"):
            return rows
        enriched: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            pair = _kraken_pair(item["symbol"])
            try:
                item["current_price"] = _kraken_last_price(adapter.current_prices([pair]), pair)
                item["broker_pair"] = pair
            except Exception as exc:
                item["current_price_error"] = str(exc)
            enriched.append(item)
        return enriched

    def _broker_trading_permissions(self, broker: str, auto_enabled: bool) -> dict[str, Any]:
        key = broker.lower()
        if key == "kraken":
            live_approved = _bool_env("KRAKEN_LIVE_TRADING_APPROVED", False)
            submit_real_orders = _bool_env("KRAKEN_SUBMIT_REAL_ORDERS", False)
            trading_enabled = _bool_env("KRAKEN_TRADING_ENABLED", False)
            allowed_pairs = _csv_env("KRAKEN_ALLOWED_PAIRS", "XBTGBP,ETHGBP,SOLGBP")
            max_open_trades = _int_env("KRAKEN_MAX_OPEN_TRADES", 1)
            ai_managed_open_trades = self._ai_managed_open_trade_count(key)
            buy_only_entries = _bool_env("KRAKEN_BUY_ONLY_ENTRIES", True)
            can_submit_real_orders = bool(auto_enabled and trading_enabled and live_approved and submit_real_orders and ai_managed_open_trades < max_open_trades)
            return {
                "broker": key,
                "status": "Real Kraken orders enabled" if can_submit_real_orders else "Real Kraken orders blocked or dry-run only",
                "auto_trading_enabled": auto_enabled,
                "trading_enabled": trading_enabled,
                "live_trading_approved": live_approved,
                "submit_real_orders": submit_real_orders,
                "can_submit_real_orders": can_submit_real_orders,
                "trading_allocation_gbp": _float_env("KRAKEN_TRADING_ALLOCATION_GBP", 100.0),
                "max_order_gbp": _float_env("KRAKEN_MAX_ORDER_GBP", 5.0),
                "min_order_gbp": _float_env("KRAKEN_MIN_ORDER_GBP", 1.0),
                "max_open_trades": max_open_trades,
                "ai_managed_open_trades": ai_managed_open_trades,
                "remaining_ai_trade_slots": max(0, max_open_trades - ai_managed_open_trades),
                "buy_only_entries": buy_only_entries,
                "allowed_pairs": allowed_pairs,
                "notes": [
                    "New Kraken entries are capped by trading allocation, max order size, allowed pairs, and AI Trader-managed open-trade limit.",
                    "Existing Kraken holdings are reported separately and do not count against the AI Trader-managed open-trade limit.",
                    "Existing managed exits remain monitored even when new auto trading is disabled.",
                    "Real orders require Auto Trading, KRAKEN_TRADING_ENABLED, KRAKEN_LIVE_TRADING_APPROVED, and KRAKEN_SUBMIT_REAL_ORDERS.",
                ],
            }
        if key == "alpaca":
            paper_only = _bool_env("PAPER_TRADING_ONLY", True)
            return {
                "broker": key,
                "status": "Alpaca paper trading enabled" if self.settings.has_alpaca_credentials else "Alpaca credentials missing",
                "auto_trading_enabled": auto_enabled,
                "trading_enabled": self.settings.has_alpaca_credentials,
                "live_trading_approved": False,
                "submit_real_orders": False,
                "can_submit_real_orders": False,
                "paper_only": paper_only,
                "max_order_gbp": _float_env("MAX_AUTO_TRADE_AMOUNT", 25.0),
                "max_open_trades": self.settings.guardrails.max_open_positions,
                "allowed_pairs": [],
                "notes": [
                    "Alpaca is configured as paper trading only in Version 1.",
                    "Paper orders still require orchestrator and guardrail validation before submission.",
                ],
            }
        env_prefixes = {
            "coinbase": "COINBASE",
            "binance": "BINANCE",
            "interactive_brokers": "IBKR",
        }
        prefix = env_prefixes.get(key, key.upper())
        trading_enabled = _bool_env(f"{prefix}_TRADING_ENABLED", False)
        live_approved = _bool_env(f"{prefix}_LIVE_TRADING_APPROVED", False)
        submit_real_orders = _bool_env(f"{prefix}_SUBMIT_REAL_ORDERS", False)
        can_submit_real_orders = bool(auto_enabled and trading_enabled and live_approved and submit_real_orders)
        return {
            "broker": key,
            "status": "Real orders enabled" if can_submit_real_orders else "Not configured or real orders blocked",
            "auto_trading_enabled": auto_enabled,
            "trading_enabled": trading_enabled,
            "live_trading_approved": live_approved,
            "submit_real_orders": submit_real_orders,
            "can_submit_real_orders": can_submit_real_orders,
            "trading_allocation_gbp": _float_env(f"{prefix}_TRADING_ALLOCATION_GBP", 0.0),
            "max_order_gbp": _float_env(f"{prefix}_MAX_ORDER_GBP", 0.0),
            "min_order_gbp": _float_env(f"{prefix}_MIN_ORDER_GBP", 0.0),
            "max_open_trades": _int_env(f"{prefix}_MAX_OPEN_TRADES", 0),
            "buy_only_entries": _bool_env(f"{prefix}_BUY_ONLY_ENTRIES", True),
            "allowed_pairs": _csv_env(f"{prefix}_ALLOWED_PAIRS", ""),
            "notes": [
                f"{_broker_label(key)} will use this same permissions shape when the adapter is configured.",
            ],
        }

    def _ai_managed_open_trade_count(self, broker: str) -> int:
        return len(open_managed_exits(self.settings.db_path, broker))

    def _broker_managed_trade_capacity(self, broker: str) -> dict[str, Any]:
        key = broker.lower()
        if key != "kraken":
            return {
                "broker": key,
                "can_open": True,
                "ai_managed_open_trades": self._ai_managed_open_trade_count(key),
                "max_ai_managed_open_trades": None,
                "remaining_ai_trade_slots": None,
                "message": "No broker-specific AI-managed trade slot limit applies.",
            }
        max_trades = _int_env("KRAKEN_MAX_OPEN_TRADES", 1)
        open_trades = self._ai_managed_open_trade_count(key)
        remaining = max(0, max_trades - open_trades)
        can_open = open_trades < max_trades
        message = (
            f"AI Trader has {open_trades} managed Kraken trade(s) open out of {max_trades}; {remaining} new slot(s) remain. "
            "Existing/manual Kraken holdings are not counted."
        )
        if not can_open:
            message = (
                f"AI Trader already has {open_trades} managed Kraken trade(s) open, meeting the limit of {max_trades}. "
                "It will not open another managed Kraken trade until one exits. Existing/manual Kraken holdings are not counted."
            )
        return {
            "broker": key,
            "can_open": can_open,
            "ai_managed_open_trades": open_trades,
            "max_ai_managed_open_trades": max_trades,
            "remaining_ai_trade_slots": remaining,
            "message": message,
        }

    def _adapters(self):
        adapters = []
        if self.settings.has_alpaca_credentials:
            adapters.append(AlpacaBrokerAdapter(self._broker()))
        adapters.extend([InteractiveBrokersAdapter(), SaxoAdapter(), KrakenAdapter(), CoinbaseAdapter()])
        return adapters

    def _active_broker_names(self) -> list[str]:
        return [name for name, adapter in self.orchestrator.adapters.items() if adapter.get_supported_assets()]

    def executive_summary(self, panels: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        if panels is None:
            panels = self.broker_panels()
        summaries: list[dict[str, Any]] = []
        for panel in panels:
            broker_key = str(panel.get("broker") or "").lower()
            summaries.append({
                "broker": panel.get("label") or _broker_label(broker_key),
                "broker_key": broker_key,
                "portfolio_balance": panel.get("portfolio_value"),
                "cash_balance": panel.get("cash_available"),
                "estimated_in_positions": panel.get("estimated_in_positions"),
                "last_day_pnl": panel.get("todays_pnl"),
                "last_week_pnl": panel.get("week_pnl"),
                "last_month_pnl": panel.get("month_pnl"),
                "amount_traded_today": panel.get("trades_today"),
                "month_start_portfolio_balance": panel.get("month_start_value"),
                "open_positions": panel.get("open_positions"),
                "status": panel.get("connection_status") or panel.get("source"),
            })
        return summaries

    def founder_executive_summary(self, panels: list[dict[str, Any]], executive_summary: list[dict[str, Any]]) -> dict[str, Any]:
        broker_lines = []
        for item in executive_summary:
            portfolio_value = safe_float(item.get("portfolio_balance"))
            cash = safe_float(item.get("cash_balance"))
            invested = safe_float(item.get("estimated_in_positions"))
            positions = item.get("open_positions")
            line = f"{item.get('broker')}: "
            if portfolio_value is None and cash is None:
                line += f"{item.get('status') or 'no account values available'}."
            else:
                line += f"account about {_money_text(portfolio_value)}, cash {_money_text(cash)}"
                if invested is not None:
                    line += f", about {_money_text(invested)} currently tied up in open positions"
                line += f", open positions {positions if positions not in (None, '') else 'not available'}."
            broker_lines.append(line)
        latest_trade = self._latest_broker_trade_any()
        trade_line = "No broker fill has been recorded yet."
        if latest_trade:
            trade_line = (
                f"Latest recorded broker fill/order is {str(latest_trade.get('side') or '').upper()} "
                f"{latest_trade.get('symbol') or 'unknown'} for {latest_trade.get('quantity') or 'unknown'} "
                f"at {_money_text(latest_trade.get('price'))}, status {latest_trade.get('status') or 'unknown'}."
            )
        learning_line = self._plain_learning_status()
        headline = "AI Trader is connected and monitoring broker data." if panels else "AI Trader has not received broker data yet."
        return {
            "headline": headline,
            "plain_english": broker_lines + [trade_line, learning_line],
            "latest_trade": latest_trade,
        }

    def connection_readiness(self, panels: list[dict[str, Any]]) -> dict[str, Any]:
        control_ready = not self.hosted_read_only
        control_status = "unlocked" if control_ready else "locked"
        if control_ready and not self.api_token_configured:
            control_status = "local token not required"
        checks = [
            {
                "component": "Render API",
                "status": "connected",
                "ready": True,
                "detail": "The mobile app reached the hosted API and received this status response.",
            },
            {
                "component": "Control Actions",
                "status": control_status,
                "ready": control_ready,
                "detail": (
                    "POST trading/control commands are enabled for this API."
                    if control_ready
                    else "Hosted POST trading/control commands are locked until AI_TRADER_API_TOKEN is configured in Render."
                ),
            },
            {
                "component": "OpenAI",
                "status": "configured" if self.settings.openai_api_key else "missing",
                "ready": bool(self.settings.openai_api_key),
                "detail": "Ask AI Trader and AI proposal analysis can use OpenAI." if self.settings.openai_api_key else "OPENAI_API_KEY is not configured for this deployment.",
            },
        ]
        for broker in panels:
            key = str(broker.get("broker") or "").lower()
            if key not in {"alpaca", "kraken", "coinbase", "binance", "interactive_brokers"}:
                continue
            connected = str(broker.get("connection_status") or "").lower() == "connected"
            auto_enabled = bool(broker.get("auto_trading_enabled"))
            detail = broker.get("source") or broker.get("connection_status") or "No broker detail returned."
            if key == "kraken" and broker.get("balance_summary"):
                summary = broker["balance_summary"]
                detail = (
                    f"Total estimated GBP {summary.get('total_estimated_gbp')}; "
                    f"GBP cash {summary.get('gbp_cash')}; "
                    f"AI trading allocation {summary.get('trading_allocation_gbp')}. "
                    f"{summary.get('valuation_note')}"
                )
            checks.append({
                "component": broker.get("label") or _broker_label(key),
                "status": "connected" if connected else str(broker.get("connection_status") or "not connected"),
                "ready": connected,
                "auto_trading_enabled": auto_enabled,
                "detail": detail,
            })
        trade_ready = all(
            item["ready"]
            for item in checks
            if item["component"] in {"Render API", "Control Actions", "OpenAI", "Alpaca", "Kraken"}
        )
        return {
            "overall_status": "ready" if trade_ready else "attention_needed",
            "trade_ready": trade_ready,
            "checks": checks,
            "note": "Readiness confirms connections and configuration visibility only. Every trade still requires orchestrator and guardrail validation.",
        }

    def _latest_broker_trade_any(self) -> dict[str, Any] | None:
        row = self._row("SELECT * FROM BROKER_TRADE_HISTORY ORDER BY COALESCE(closed_at, opened_at, updated_at) DESC, trade_history_id DESC LIMIT 1")
        return dict(row) if row else None

    def _plain_learning_status(self) -> str:
        today = date.today().isoformat()
        closed_count = self._scalar(
            "SELECT COUNT(*) FROM PERFORMANCE_ATTRIBUTION WHERE COALESCE(closed_at, created_at) LIKE ?",
            (f"{today}%",),
        ) or 0
        if closed_count:
            return f"Learning today is based on {closed_count} closed trade outcome(s), plus benchmark and guardrail observations."
        return "Learning today is limited: no fully closed trade outcome has been recorded yet, so the app should not claim the strategy improved or failed until open positions are reconciled."

    def _latest_snapshot_summary(self, broker: str, label: str) -> dict[str, Any] | None:
        row = self._row("SELECT * FROM PORTFOLIO_SNAPSHOTS WHERE broker = ? ORDER BY snapshot_id DESC LIMIT 1", (broker,))
        if not row:
            return None
        return {
            "broker": label,
            "portfolio_balance": display_value(row["portfolio_value"], "no portfolio snapshot value"),
            "cash_balance": display_value(row["cash"], "no cash snapshot value"),
            "estimated_in_positions": _estimated_in_positions(row["portfolio_value"], row["cash"]),
            "last_day_pnl": display_value(row["day_pnl"], "no prior snapshot"),
            "last_week_pnl": display_value(row["week_pnl"], "no prior weekly snapshot"),
            "last_month_pnl": display_value(row["month_pnl"], "no month-start snapshot"),
            "amount_traded_today": 0,
            "month_start_portfolio_balance": display_value(row["month_start_value"], "no month-start snapshot"),
            "open_positions": display_value(row["open_positions_count"], "no position snapshots yet"),
            "status": "Connected",
        }

    def _unconfigured_exchange_portfolio(self, broker: str) -> dict[str, Any]:
        label = broker.capitalize()
        return {
            "broker": broker,
            "exchange": label,
            "portfolio_value": f"Not available - {label} not configured",
            "cash_available": f"Not available - {label} not configured",
            "todays_pnl": f"Not available - {label} not configured",
            "open_positions": [],
            "open_positions_summary": f"Not available - {label} not configured",
            "recent_orders": [],
            "recent_activities": [],
            "source": f"{label} not configured",
        }

    def _exchange_portfolio(self, broker: str) -> dict[str, Any]:
        broker = broker.lower()
        adapter = self.orchestrator.adapters.get(broker)
        if not adapter:
            return self._unconfigured_exchange_portfolio(broker)
        account = adapter.get_account()
        configured = getattr(adapter, "configured", False)
        if isinstance(account, dict) and account.get("status") == "authentication_failed":
            update_broker_runtime(self.settings.db_path, broker, connection_status=f"Authentication failed - {account.get('reason')}", details=account)
            return {
                "broker": broker,
                "exchange": _broker_label(broker),
                "connection_status": f"Authentication failed - {account.get('reason')}",
                "portfolio_value": f"Not available - {account.get('reason')}",
                "cash_available": f"Not available - {account.get('reason')}",
                "buying_power": f"Not available - {account.get('reason')}",
                "todays_pnl": f"Not available - {account.get('reason')}",
                "week_pnl": f"Not available - {account.get('reason')}",
                "month_pnl": f"Not available - {account.get('reason')}",
                "open_positions": [],
                "open_positions_summary": "Not available - authentication failed",
                "recent_orders": [],
                "recent_activities": [],
                "source": f"{_broker_label(broker)} authentication failed",
            }
        if not configured:
            return self._unconfigured_exchange_portfolio(broker)
        positions = adapter.get_positions()
        orders = adapter.get_orders()
        history = adapter.get_trade_history()
        record_broker_trade_history(self.settings.db_path, broker, orders + history)
        update_broker_runtime(
            self.settings.db_path,
            broker,
            connection_status="Connected",
            details={"account_status": account.get("status") if isinstance(account, dict) else "connected"},
        )
        cash = _sum_balances(account.get("balances") if isinstance(account, dict) else None)
        balance_summary = None
        if broker == "kraken":
            balance_summary = _kraken_balance_summary(account.get("balances") if isinstance(account, dict) else None, adapter)
            cash = balance_summary.get("gbp_cash")
            equity = balance_summary.get("total_estimated_gbp")
        else:
            equity = cash
        snapshot = record_portfolio_snapshot(
            self.settings.db_path,
            broker=broker,
            exchange=_broker_label(broker),
            account={"cash": cash, "equity": equity},
            positions=positions,
            notes="Broker panel refresh snapshot.",
        )
        return {
            "broker": broker,
            "exchange": _broker_label(broker),
            "connection_status": "Connected",
            "portfolio_value": equity if equity is not None else "Not available - broker returned no portfolio valuation",
            "cash_available": cash if cash is not None else "Not available - broker returned no balances",
            "estimated_in_positions": _estimated_in_positions(equity, cash),
            "buying_power": (
                balance_summary.get("trading_allocation_gbp")
                if balance_summary
                else cash if cash is not None else "Not available - broker returned no buying power"
            ),
            "todays_pnl": display_value(snapshot["day_pnl"], "no prior snapshot yet"),
            "week_pnl": display_value(snapshot["week_pnl"], "no prior weekly snapshot yet"),
            "month_pnl": display_value(snapshot["month_pnl"], "no month-start snapshot yet"),
            "month_start_value": display_value(snapshot["month_start_value"], "no month-start snapshot yet"),
            "open_positions": positions,
            "open_positions_summary": f"{len(positions)}",
            "recent_orders": orders[:10],
            "recent_activities": history[:10],
            "balance_summary": balance_summary,
            "source": _broker_label(broker),
        }

    def _alpaca_panel_portfolio(self) -> dict[str, Any]:
        if not self.settings.has_alpaca_credentials:
            return self._unconfigured_exchange_portfolio("alpaca")
        try:
            return self._live_alpaca_portfolio()
        except Exception as exc:
            row = self._latest_snapshot_summary("alpaca", "Alpaca")
            if not row:
                return {"connection_status": "Connected", "source": f"Alpaca Paper Trading - live refresh failed: {exc}"}
            return {
                "connection_status": row.get("status") or "Connected",
                "portfolio_value": row.get("portfolio_balance"),
                "cash_available": row.get("cash_balance"),
                "estimated_in_positions": _estimated_in_positions(row.get("portfolio_balance"), row.get("cash_balance")),
                "buying_power": row.get("buying_power"),
                "todays_pnl": row.get("last_day_pnl"),
                "week_pnl": row.get("last_week_pnl"),
                "month_pnl": row.get("last_month_pnl"),
                "month_start_value": row.get("month_start_portfolio_balance"),
                "open_positions_summary": row.get("open_positions"),
                "source": f"Alpaca Paper Trading - cached snapshot because live refresh failed: {exc}",
            }

    def _live_alpaca_portfolio(self) -> dict[str, Any]:
        broker = self._broker()
        account = broker.get_account()
        positions = broker.get_positions()
        orders = broker.get_orders(status="all", limit=10)
        activities = broker.get_activities("FILL")
        record_broker_trade_history(self.settings.db_path, "alpaca", list(orders) + list(activities))
        snapshot = record_portfolio_snapshot(
            self.settings.db_path,
            broker="alpaca",
            exchange="Alpaca",
            account=account,
            positions=positions,
            notes="Dashboard refresh snapshot.",
        )
        latest_trade = _latest_trade(orders, activities)
        return {
            "broker": "alpaca",
            "exchange": "Alpaca",
            "connection_status": "Connected",
            "portfolio_value": display_value(snapshot["portfolio_value"], "Alpaca returned no portfolio value"),
            "cash_available": display_value(snapshot["cash"], "Alpaca returned no cash balance"),
            "estimated_in_positions": _estimated_in_positions(snapshot["portfolio_value"], snapshot["cash"]),
            "buying_power": display_value(snapshot["buying_power"], "Alpaca returned no buying power"),
            "todays_pnl": display_value(snapshot["day_pnl"], "no prior snapshot yet"),
            "week_pnl": display_value(snapshot["week_pnl"], "no prior weekly snapshot yet"),
            "month_pnl": display_value(snapshot["month_pnl"], "no month-start snapshot yet"),
            "month_start_value": display_value(snapshot["month_start_value"], "no month-start snapshot yet"),
            "amount_traded_today": _amount_traded_today(activities),
            "latest_trade": latest_trade or "Not available - no Alpaca fills or orders returned",
            "open_positions": [
                {
                    "symbol": row.get("symbol"),
                    "qty": safe_float(row.get("qty")),
                    "market_value": safe_float(row.get("market_value")),
                    "unrealized_pl": safe_float(row.get("unrealized_pl")),
                }
                for row in positions
            ],
            "open_positions_summary": f"{len(positions)}" if positions else "0",
            "recent_orders": orders[:10] if isinstance(orders, list) else [],
            "recent_activities": activities[:10] if isinstance(activities, list) else [],
            "source": "Alpaca Paper Trading",
        }

    def _auto_config_for_broker(self, broker: str) -> Any:
        enabled = broker_auto_trading_enabled(self.settings.db_path, broker, self.settings.auto_trade.broker_enabled.get(broker, False))
        return type(self.settings.auto_trade)(
            enabled=enabled,
            broker_enabled=dict(self.settings.auto_trade.broker_enabled),
            min_confidence=self.settings.auto_trade.min_confidence,
            min_philosophy_fit=self.settings.auto_trade.min_philosophy_fit,
            max_trade_amount=self.settings.auto_trade.crypto_max_trade_amount if broker == "kraken" else self.settings.auto_trade.max_trade_amount,
            default_stop_loss_pct=self.settings.auto_trade.crypto_default_stop_loss_pct if broker == "kraken" else self.settings.auto_trade.default_stop_loss_pct,
            max_stop_loss_pct=self.settings.auto_trade.crypto_max_stop_loss_pct if broker == "kraken" else self.settings.auto_trade.max_stop_loss_pct,
            crypto_max_trade_amount=self.settings.auto_trade.crypto_max_trade_amount,
            crypto_default_stop_loss_pct=self.settings.auto_trade.crypto_default_stop_loss_pct,
            crypto_max_stop_loss_pct=self.settings.auto_trade.crypto_max_stop_loss_pct,
        )

    def _apply_env_broker_auto_defaults(self) -> None:
        if self.settings.auto_trade.enabled:
            set_broker_auto_trading(self.settings.db_path, "alpaca", True, updated_by="legacy_auto_paper_trading")
        for broker, enabled in self.settings.auto_trade.broker_enabled.items():
            if enabled:
                set_broker_auto_trading(self.settings.db_path, broker, True, updated_by="environment")

    def _continuous_research_status(self, brokers: list[dict[str, Any]]) -> dict[str, Any]:
        active = [broker for broker in brokers if broker.get("research_status") == "running"]
        latest = latest_recommendation_set(self.settings.db_path)
        return {
            "research_running": bool(active) or self.settings.research_scheduler_enabled,
            "current_broker": active[0]["broker"] if active else None,
            "current_asset": active[0].get("current_asset") if active else None,
            "current_stage": active[0].get("current_stage") if active else "waiting_for_next_scan",
            "research_queue": active[0].get("research_queue") if active else [],
            "assets_reviewed_today": sum(int(item.get("assets_reviewed_today") or 0) for item in brokers),
            "research_cycles_today": sum(int(item.get("research_cycles_today") or 0) for item in brokers),
            "last_scan": max([item.get("last_scan") for item in brokers if item.get("last_scan")] or [None]),
            "next_scan": next_research_run(interval_minutes=self.settings.research_scheduler_interval_minutes),
            "research_freshness": "Fresh" if self.settings.research_scheduler_enabled else "Idle - scheduler disabled",
            "last_recommendation": latest,
            "last_trade_submitted": max([item.get("last_trade_submitted") for item in brokers if item.get("last_trade_submitted")] or [None]),
        }

    def _record_research_from_result(self, started_at: str, result: dict[str, Any], symbols: list[str], trigger_type: str) -> None:
        errors = [item.get("reason", "") for item in result.get("skipped_symbols", []) if item.get("reason")]
        auto = result.get("auto_execution") or {}
        proposal_ids = [
            str(item.get("proposal_id"))
            for item in result.get("proposals", [])
            if isinstance(item, dict) and item.get("proposal_id")
        ]
        record_recommendation_set(
            self.settings.db_path,
            trigger_type=trigger_type,
            broker=None,
            symbols=symbols,
            proposal_ids=proposal_ids,
            status=result.get("status", "unknown"),
            summary=result.get("message") or f"{len(proposal_ids)} recommendation(s) generated.",
        )
        record_research_run(
            self.settings.db_path,
            started_at=started_at,
            completed_at=utc_now_iso(),
            status=result.get("status", "unknown"),
            trigger_type=trigger_type,
            markets_reviewed=["Alpaca", "Benchmark Intelligence"],
            companies_reviewed=len(symbols),
            crypto_assets_reviewed=self._count("CRYPTO_ASSET_MASTER", "active = 1"),
            benchmark_traders_reviewed=self._count("BENCHMARK_TRADERS", "active = 1"),
            recommendations_created=len(result.get("proposals", [])),
            trades_executed=len(auto.get("result", [])) if isinstance(auto.get("result"), list) else 0,
            trades_rejected=auto.get("skipped_count", 0) or len(auto.get("skipped", [])) if isinstance(auto, dict) else 0,
            errors=errors,
            next_scheduled_run=next_research_run(),
            summary=result.get("message") or f"Research completed with {len(result.get('proposals', []))} recommendation(s).",
        )

    def _record_research_funnel_from_result(
        self,
        *,
        broker: str,
        asset_type: str,
        trigger_type: str,
        symbols: list[str],
        result: dict[str, Any],
        auto_execution: dict[str, Any],
        skipped_symbols: list[dict[str, Any]],
    ) -> None:
        proposals = result.get("proposals") or []
        skipped = auto_execution.get("skipped") if isinstance(auto_execution, dict) else []
        submitted = auto_execution.get("result") if isinstance(auto_execution, dict) else []
        secondary_reasons = [
            str(item.get("reason") or item.get("message"))
            for item in list(skipped_symbols or []) + list(skipped or [])
            if isinstance(item, dict) and (item.get("reason") or item.get("message"))
        ]
        primary_reason = (
            result.get("message")
            or (secondary_reasons[0] if secondary_reasons else None)
            or (auto_execution.get("message") if isinstance(auto_execution, dict) else None)
            or ("recommendations_created" if proposals else "no_valid_trade_recommendations")
        )
        eligible = len(proposals)
        rejected = len(secondary_reasons)
        if isinstance(auto_execution, dict) and auto_execution.get("status") in {"skipped", "manual_required", "blocked"}:
            rejected = max(rejected, len(proposals))
            eligible = 0
        record_research_funnel(
            self.settings.db_path,
            broker=broker,
            asset_type=asset_type,
            trigger_type=trigger_type,
            symbols_examined=len(symbols),
            symbols_with_adequate_data=max(0, len(symbols) - len(skipped_symbols)),
            interesting_ideas=len(proposals),
            valid_strategies=len(proposals),
            committee_approved=len(proposals),
            portfolio_approved=len(proposals),
            guardrail_approved=len(proposals),
            eligible_for_paper_execution=eligible,
            submitted=len(submitted) if isinstance(submitted, list) else 0,
            filled=0,
            rejected=rejected,
            expired=0,
            primary_reason=primary_reason,
            secondary_reasons=secondary_reasons,
            payload={
                "result_status": result.get("status"),
                "auto_execution_status": auto_execution.get("status") if isinstance(auto_execution, dict) else None,
                "auto_execution_message": auto_execution.get("message") if isinstance(auto_execution, dict) else None,
                "skipped_symbols": skipped_symbols,
                "auto_skipped": skipped[:10] if isinstance(skipped, list) else [],
            },
        )

    def _record_shadow_from_proposal(
        self,
        proposal: TradeProposal,
        *,
        intended_broker: str,
        decision_status: str,
        trigger_type: str,
        wait_or_rejection_reason: str | None,
    ) -> None:
        proposal_payload = proposal.to_dict()
        record_shadow_trade(
            self.settings.db_path,
            symbol=proposal.symbol,
            asset_type=proposal.asset_type,
            intended_broker=intended_broker,
            decision_status=decision_status,
            strategy=str((proposal_payload.get("strategy") or proposal_payload.get("strategy_id") or "current_recommendation_process")),
            regime=json.dumps(proposal_payload.get("market_regime"), default=str) if proposal_payload.get("market_regime") else None,
            intended_entry=proposal.entry_price,
            stop_loss=proposal.stop_loss,
            take_profit=proposal.take_profit,
            quantity=proposal.position_size,
            notional=getattr(proposal, "notional_amount", None) or (proposal.entry_price * proposal.position_size),
            probability=safe_score(proposal.confidence_score),
            expected_r=_proposal_expected_r(proposal),
            strongest_argument_for=proposal_payload.get("strongest_argument_for") or proposal.plain_english_reasoning,
            strongest_argument_against=proposal_payload.get("strongest_argument_against") or "Not available - current proposal did not preserve a strongest-against argument.",
            wait_or_rejection_reason=wait_or_rejection_reason,
            market_evidence={
                "technical_summary": proposal.technical_summary,
                "news_summary": proposal.news_summary,
                "sentiment_summary": proposal.market_sentiment_summary,
                "trigger_type": trigger_type,
            },
            portfolio_snapshot=self._account_context_for_broker(intended_broker).__dict__,
            data_quality={"status": "recorded_from_trade_proposal", "freshness": "proposal_created_now"},
            expires_at=(datetime.now(timezone.utc) + timedelta(hours=4)).isoformat(),
            simulated_costs={"status": "estimated_or_unavailable", "note": "Shadow costs are estimates until broker fills exist."},
            idempotency_key=f"{proposal.proposal_id}:shadow:{intended_broker}",
        )

    def _latest_orchestrator_decision(self, recommendation_id: str) -> dict[str, Any] | None:
        row = self._row(
            "SELECT * FROM ORCHESTRATOR_DECISIONS WHERE recommendation_id = ? ORDER BY decision_id DESC LIMIT 1",
            (recommendation_id,),
        )
        return dict(row) if row else None

    def _latest_daily_brief(self, brief_type: str) -> dict[str, Any] | None:
        row = self._row(
            "SELECT * FROM DAILY_BRIEFS WHERE brief_type = ? ORDER BY brief_id DESC LIMIT 1",
            (brief_type,),
        )
        return dict(row) if row else None

    def _broker(self) -> AlpacaPaperClient:
        return AlpacaPaperClient(
            AlpacaCredentials(
                api_key=self.settings.alpaca_api_key or "",
                secret_key=self.settings.alpaca_secret_key or "",
                base_url=self.settings.alpaca_paper_base_url,
                data_base_url=self.settings.alpaca_data_base_url,
            )
        )

    def _initialize_control(self) -> None:
        with closing(self._connect()) as conn:
            with conn:
                conn.executescript(CONTROL_SCHEMA)
                conn.execute(
                    """
                    INSERT OR IGNORE INTO engine_control (id, trading_state, updated_at, last_command)
                    VALUES (1, 'running', ?, 'api-start')
                    """,
                    (utc_now_iso(),),
                )

    def _initialize_report_schema(self) -> None:
        with closing(self._connect()) as conn:
            with conn:
                conn.executescript(REPORT_SCHEMA)

    def _control_state(self) -> dict[str, Any]:
        row = self._row("SELECT * FROM engine_control WHERE id = 1")
        return dict(row) if row else {"trading_state": "unknown", "updated_at": None, "last_command": None}

    def _proposal_already_executed(self, proposal_id: str) -> bool:
        return bool(
            self._scalar(
                """
                SELECT COUNT(*)
                FROM trade_audit
                WHERE proposal_id = ? AND event_type = 'execution_approved'
                """,
                (proposal_id,),
            )
        )

    def _proposal_broker(self, payload_json: Any) -> str | None:
        proposal_payload = _proposal_payload(payload_json)
        if not proposal_payload:
            return None
        try:
            proposal = TradeProposal.from_dict(proposal_payload)
        except Exception:
            return None
        selected = self.orchestrator._select_adapter(proposal)
        if selected:
            return selected.name
        if proposal.asset_type.lower() == "crypto" and proposal.exchange.upper() == "KRAKEN":
            return "kraken"
        if proposal.exchange.upper() in {"NYSE", "NASDAQ", "AMEX"}:
            return "alpaca"
        return None

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.settings.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _row(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        with closing(self._connect()) as conn:
            return conn.execute(sql, params).fetchone()

    def _rows(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with closing(self._connect()) as conn:
            return list(conn.execute(sql, params))

    def _scalar(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        row = self._row(sql, params)
        return None if row is None else row[0]

    def _count(self, table: str, where: str | None = None) -> int:
        if table not in {
            "INVESTMENT_WATCHLIST",
            "MARKET_THEMES",
            "BENCHMARK_TRADERS",
            "trade_audit",
            "CRYPTO_ASSET_MASTER",
            "BENCHMARK_DAILY_RESEARCH",
            "CRYPTO_MASTER",
            "DUE_DILIGENCE_ASSESSMENTS",
        }:
            raise ValueError(f"Unsupported count table: {table}")
        sql = f"SELECT COUNT(*) FROM {table}"
        if where:
            sql += f" WHERE {where}"
        return int(self._scalar(sql) or 0)

    def _due_diligence_status(self) -> str:
        latest = self._row("SELECT overall_status, created_at FROM DUE_DILIGENCE_ASSESSMENTS ORDER BY assessment_id DESC LIMIT 1")
        if not latest:
            return "idle - no due diligence assessment recorded yet"
        return f"{latest['overall_status']} at {latest['created_at']}"


class ApiHandler(BaseHTTPRequestHandler):
    service: LocalApiService
    api_token: str | None = None
    hosted_read_only: bool = False

    _auth_failures: dict[str, deque] = defaultdict(deque)
    _lockout_until: dict[str, float] = {}
    _auth_lock = Lock()
    _MAX_AUTH_FAILURES = 10
    _AUTH_FAILURE_WINDOW_SECONDS = 60
    _LOCKOUT_SECONDS = 300

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if not self._authorized(parsed.path):
                self._json(401, {"error": "unauthorized"})
                return
            status, payload = self.service.get(parsed.path, parse_qs(parsed.query))
            self._json(status, payload)
        except Exception as exc:
            self._json(500, {"error": "internal_error", "message": str(exc), "path": parsed.path})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            if not self._authorized(parsed.path):
                self._json(401, {"error": "unauthorized"})
                return
            if self.hosted_read_only:
                self._json(
                    403,
                    {
                        "error": "hosted_read_only",
                        "message": (
                            "Hosted API is running without AI_TRADER_API_TOKEN, so POST commands are disabled. "
                            "Set AI_TRADER_API_TOKEN in Render to enable trading/control actions."
                        ),
                    },
                )
                return
            body = self._read_body()
            status, payload = self.service.post(parsed.path, body)
            self._json(status, payload)
        except Exception as exc:
            self._json(500, {"error": "internal_error", "message": str(exc), "path": parsed.path})

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors()
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _read_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length == 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("POST body must be a JSON object")
        return data

    def _client_ip(self) -> str:
        address = getattr(self, "client_address", None)
        return address[0] if address else "unknown"

    def _is_locked_out(self, ip: str) -> bool:
        with self._auth_lock:
            until = self._lockout_until.get(ip)
            if until is None:
                return False
            if until > time.time():
                return True
            del self._lockout_until[ip]
            return False

    def _record_auth_failure(self, ip: str) -> None:
        now = time.time()
        with self._auth_lock:
            failures = self._auth_failures[ip]
            failures.append(now)
            while failures and now - failures[0] > self._AUTH_FAILURE_WINDOW_SECONDS:
                failures.popleft()
            if len(failures) >= self._MAX_AUTH_FAILURES:
                self._lockout_until[ip] = now + self._LOCKOUT_SECONDS
                failures.clear()
                logger.warning("Locking out %s for %ss after repeated auth failures.", ip, self._LOCKOUT_SECONDS)

    def _authorized(self, path: str) -> bool:
        if path in {"/healthz"}:
            return True
        ip = self._client_ip()
        if ip != "unknown" and self._is_locked_out(ip):
            return False
        if not self.api_token:
            return True
        auth = self.headers.get("Authorization", "")
        api_key = self.headers.get("X-API-Key", "")
        authorized = hmac.compare_digest(auth, f"Bearer {self.api_token}") or hmac.compare_digest(api_key, self.api_token)
        if not authorized and ip != "unknown":
            self._record_auth_failure(ip)
        return authorized

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        if "html" in payload and len(payload) == 1:
            body = str(payload["html"]).encode("utf-8")
            self.send_response(status)
            self._cors()
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-API-Key")


_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def run_server(host: str = "127.0.0.1", port: int = 8765, api_token: str | None = None) -> None:
    settings = load_settings()
    configure_logging(settings.output_dir)
    startup_errors = settings.production_startup_errors(host=host)
    if startup_errors:
        for message in startup_errors:
            logger.error("Hosted startup validation failed: %s", message)
        raise RuntimeError("; ".join(startup_errors))
    hosted_read_only = False
    if not api_token and host not in _LOOPBACK_HOSTS:
        hosted_read_only = True
        logger.warning(
            "Starting hosted API on %s without AI_TRADER_API_TOKEN in read-only mode. "
            "All POST trading/control commands will be rejected until the token is configured.",
            host,
        )
    service = LocalApiService(settings)
    service.hosted_read_only = hosted_read_only
    service.api_token_configured = bool(api_token)
    service.intelligence.seed_initial_data()
    service.benchmark.seed_initial_data()
    seed_crypto_universe(service.settings.db_path, fetch_live=False)
    service.benchmark.write_schema_doc(Path("governance/BENCHMARK_INTELLIGENCE_SCHEMA.md"))
    service.benchmark.write_initial_brief(service.settings.output_dir)
    service.reconcile_on_startup()

    def _on_research_error(exc: Exception) -> None:
        record_notification(
            service.settings.db_path,
            event_type="research_failure",
            broker=None,
            symbol=None,
            title="Research cycle failed",
            message=f"A scheduled research cycle raised an exception and was skipped: {exc}",
            payload={"error": str(exc)},
        )

    def _on_exit_monitor_error(exc: Exception) -> None:
        record_notification(
            service.settings.db_path,
            event_type="broker_failure",
            broker=None,
            symbol=None,
            title="Position monitoring cycle failed",
            message=f"A managed-exit monitoring cycle raised an exception and was skipped: {exc}",
            payload={"error": str(exc)},
        )

    def _on_activity_poll_error(exc: Exception) -> None:
        record_notification(
            service.settings.db_path,
            event_type="broker_failure",
            broker=None,
            symbol=None,
            title="Order/trade activity poll failed",
            message=f"A broker order/trade activity poll raised an exception and was skipped: {exc}",
            payload={"error": str(exc)},
        )

    def _on_auto_execution_error(exc: Exception) -> None:
        record_notification(
            service.settings.db_path,
            event_type="broker_failure",
            broker=None,
            symbol=None,
            title="Auto execution cycle failed",
            message=f"An autonomous execution cycle raised an exception and was skipped: {exc}",
            payload={"error": str(exc)},
        )

    def _on_crypto_refresh_error(exc: Exception) -> None:
        record_notification(
            service.settings.db_path,
            event_type="research_failure",
            broker="kraken",
            symbol=None,
            title="Crypto universe refresh failed",
            message=f"A crypto knowledge engine refresh raised an exception and was skipped: {exc}",
            payload={"error": str(exc)},
        )

    if service.settings.disable_api_background_workers:
        logger.info(
            "API background workers are disabled by AI_TRADER_DISABLE_API_BACKGROUND_WORKERS; "
            "Render worker/cron services own autonomous operations."
        )
    else:
        if service.settings.research_scheduler_enabled:
            ResearchScheduler(
                service,
                interval_minutes=service.settings.research_scheduler_interval_minutes,
                on_error=_on_research_error,
            ).start_background(limit=service.settings.research_scheduler_limit)
        else:
            logger.warning("RESEARCH_SCHEDULER_ENABLED is false - continuous research will not run automatically.")

        # Position/exit monitoring is a safety function, independent of whether research is
        # scheduled, and always runs so stop-loss/take-profit protection is never dependent on
        # a manual call to /monitor-managed-exits.
        IntervalWorker(
            service.monitor_managed_exits,
            interval_seconds=60,
            name="ai-trader-exit-monitor",
            on_error=_on_exit_monitor_error,
        ).start_background()

        IntervalWorker(
            service.poll_broker_activity,
            interval_seconds=60,
            name="ai-trader-order-monitor",
            on_error=_on_activity_poll_error,
        ).start_background()

        # Auto execution is intentionally separate from research. Research creates fresh
        # proposals; this worker repeatedly asks the deterministic execution engine whether
        # any proposal is currently eligible under broker permissions and guardrails.
        IntervalWorker(
            service.auto_execute_recommendations,
            interval_seconds=max(30, service.settings.auto_execution_interval_seconds),
            name="ai-trader-auto-executor",
            on_error=_on_auto_execution_error,
        ).start_background()

        # Crypto knowledge engine refresh - independent of research_scheduler_enabled since it's
        # foundational data (market cap / AI / privacy category universes and scoring), not a
        # decision-making cycle. Runs on the same cadence as equities research by default.
        IntervalWorker(
            service.refresh_crypto_universe,
            interval_seconds=max(300, service.settings.research_scheduler_interval_minutes * 60),
            name="ai-trader-crypto-refresh",
            on_error=_on_crypto_refresh_error,
        ).start_background()

        # Push dispatch runs on a short cadence since it's just an outbound HTTP call for
        # already-recorded high-priority notifications, not a broker/API poll.
        IntervalWorker(
            service.dispatch_pending_push_notifications,
            interval_seconds=30,
            name="ai-trader-push-dispatch",
        ).start_background()

    ApiHandler.service = service
    ApiHandler.api_token = api_token
    ApiHandler.hosted_read_only = hosted_read_only
    server = ThreadingHTTPServer((host, port), ApiHandler)
    logger.info("AI Trader local API listening on http://%s:%s", host, port)
    server.serve_forever()


def _first(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key) or []
    return values[0] if values else None


def _float_or_none(value: Any) -> float | None:
    return safe_float(value)


def _int_or_default(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _list_or_none(items: list[str]) -> str:
    if not items:
        return "- None recorded"
    return "\n".join(item if str(item).startswith("- ") else f"- {item}" for item in items)


def _money_text(value: Any) -> str:
    number = safe_float(value)
    if number is None:
        return "Not available"
    return f"{number:,.2f}"


def _estimated_in_positions(portfolio_value: Any, cash: Any) -> float | None:
    portfolio_number = safe_float(portfolio_value)
    cash_number = safe_float(cash)
    if portfolio_number is None or cash_number is None:
        return None
    return portfolio_number - cash_number


def _human_time(value: Any) -> str:
    if not value:
        return "Not available"
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc)
    return parsed.strftime("%d %b %Y, %H:%M UTC")


def _first_markdown_bullet(markdown: str) -> str | None:
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            return stripped[2:]
    return None


def _report_period(report_date: date, report_type: str) -> dict[str, str]:
    report_type = report_type.lower()
    if report_type == "morning":
        start_date = report_date - timedelta(days=1)
        start_dt = datetime(start_date.year, start_date.month, start_date.day, 16, 0, tzinfo=timezone.utc)
        end_dt = datetime(report_date.year, report_date.month, report_date.day, 9, 0, tzinfo=timezone.utc)
        label = "Morning report window: prior market close through 09:00 UTC"
    elif report_type == "evening":
        start_dt = datetime(report_date.year, report_date.month, report_date.day, 9, 0, tzinfo=timezone.utc)
        end_dt = datetime(report_date.year, report_date.month, report_date.day, 23, 59, 59, tzinfo=timezone.utc)
        label = "Evening report window: 09:00 UTC through end of day"
    elif report_type == "weekly":
        start_date = report_date - timedelta(days=report_date.weekday())
        end_date = start_date + timedelta(days=6)
        start_dt = datetime(start_date.year, start_date.month, start_date.day, tzinfo=timezone.utc)
        end_dt = datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59, tzinfo=timezone.utc)
        label = f"Weekly report window: ISO week starting {start_date.isoformat()}"
    elif report_type == "monthly":
        start_date = report_date.replace(day=1)
        if start_date.month == 12:
            next_month = start_date.replace(year=start_date.year + 1, month=1)
        else:
            next_month = start_date.replace(month=start_date.month + 1)
        end_date = next_month - timedelta(days=1)
        start_dt = datetime(start_date.year, start_date.month, start_date.day, tzinfo=timezone.utc)
        end_dt = datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59, tzinfo=timezone.utc)
        label = f"Monthly report window: {start_date.strftime('%B %Y')}"
    else:
        start_dt = datetime(report_date.year, report_date.month, report_date.day, tzinfo=timezone.utc)
        end_dt = datetime(report_date.year, report_date.month, report_date.day, 23, 59, 59, tzinfo=timezone.utc)
        label = "Daily report window: full calendar day UTC"
    return {"start": start_dt.isoformat(), "end": end_dt.isoformat(), "label": label}


def _balance_summary_by_broker(snapshots: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in snapshots:
        broker = str(row.get("broker") or row.get("exchange") or "unknown")
        grouped[broker].append(row)
    summary: dict[str, dict[str, Any]] = {}
    for broker, rows in grouped.items():
        ordered = sorted(rows, key=lambda item: item.get("created_at") or "")
        start = ordered[0]
        end = ordered[-1]
        start_balance = safe_float(start.get("portfolio_value"))
        end_balance = safe_float(end.get("portfolio_value"))
        start_cash = safe_float(start.get("cash"))
        end_cash = safe_float(end.get("cash"))
        balance_change = None if start_balance is None or end_balance is None else end_balance - start_balance
        summary[broker] = {
            "start": start,
            "end": end,
            "start_balance": start_balance,
            "end_balance": end_balance,
            "start_cash": start_cash,
            "end_cash": end_cash,
            "start_in_positions": _estimated_in_positions(start_balance, start_cash),
            "end_in_positions": _estimated_in_positions(end_balance, end_cash),
            "balance_change": balance_change,
            "snapshot_count": len(ordered),
        }
    return summary


def _balance_summary_lines(summary: dict[str, dict[str, Any]]) -> str:
    if not summary:
        return "- No start/end portfolio snapshots were available for this period."
    lines = []
    for broker, item in summary.items():
        lines.append(
            f"- {broker.title()}: start {_money_text(item.get('start_balance'))} at {_human_time(item['start'].get('created_at'))}; "
            f"end {_money_text(item.get('end_balance'))} at {_human_time(item['end'].get('created_at'))}; "
            f"cash {_money_text(item.get('end_cash'))}; estimated in positions {_money_text(item.get('end_in_positions'))}; "
            f"balance change {_money_text(item.get('balance_change'))}; snapshots {item.get('snapshot_count')}."
        )
    return "\n".join(lines)


def _performance_summary_lines(
    balance_summary: dict[str, dict[str, Any]],
    attribution: list[dict[str, Any]],
    broker_trades: list[dict[str, Any]],
    reconstructed: dict[str, Any],
) -> list[str]:
    lines = []
    total_closed_pnl = sum(safe_float(row.get("profit_loss")) or 0.0 for row in attribution)
    total_balance_change = sum(
        safe_float(item.get("balance_change")) or 0.0
        for item in balance_summary.values()
        if safe_float(item.get("balance_change")) is not None
    )
    lines.append(f"Closed-trade realised/attributed P&L: {_money_text(total_closed_pnl)}.")
    lines.append(f"Broker-fill reconstructed realised P&L: {_money_text(reconstructed.get('realized_pnl'))}.")
    if balance_summary:
        lines.append(f"Start-to-end portfolio balance movement across available broker snapshots: {_money_text(total_balance_change)}.")
    else:
        lines.append("Start-to-end portfolio balance movement is unavailable because no period snapshots were recorded.")
    lines.append(f"Closed trade count with full attribution: {len(attribution)}.")
    lines.append(f"Matched broker-fill round trips: {len(reconstructed.get('matched_trades') or [])}.")
    lines.append(f"Open/unmatched broker-fill lots: {len(reconstructed.get('open_lots') or [])}.")
    lines.append(f"Broker trade/order rows reviewed: {len(broker_trades)}.")
    if balance_summary and attribution:
        difference = total_balance_change - total_closed_pnl
        lines.append(f"Difference between balance movement and closed-trade attribution: {_money_text(difference)}. This can include open/unrealised P&L, deposits/withdrawals, fees, FX, or broker valuation movement.")
    return lines


def _report_likely_causes(
    snapshots: list[dict[str, Any]],
    attribution: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
    broker_trades: list[dict[str, Any]],
    reconstructed: dict[str, Any],
) -> list[str]:
    causes: list[str] = []
    balance_summary = _balance_summary_by_broker(snapshots)
    for broker, item in balance_summary.items():
        change = safe_float(item.get("balance_change"))
        latest_day_pnl = safe_float(item["end"].get("day_pnl"))
        if change is not None and change < 0:
            causes.append(f"{broker.title()} start-to-end balance fell by {_money_text(change)} over the report window.")
        elif change is not None and change > 0:
            causes.append(f"{broker.title()} start-to-end balance rose by {_money_text(change)} over the report window.")
        if latest_day_pnl is not None and latest_day_pnl < 0:
            causes.append(f"{broker.title()} latest broker day P&L snapshot is negative at {_money_text(latest_day_pnl)}.")
        elif latest_day_pnl is not None and latest_day_pnl > 0:
            causes.append(f"{broker.title()} latest broker day P&L snapshot is positive at {_money_text(latest_day_pnl)}.")
    closed_losses = [row for row in attribution if (safe_float(row.get("profit_loss")) or 0.0) < 0]
    closed_wins = [row for row in attribution if (safe_float(row.get("profit_loss")) or 0.0) > 0]
    if closed_losses:
        symbols = Counter(str(row.get("symbol") or "unknown") for row in closed_losses)
        causes.append(f"Closed losing trades contributed {_money_text(sum(safe_float(row.get('profit_loss')) or 0.0 for row in closed_losses))}; symbols involved: {dict(symbols)}.")
    if closed_wins:
        symbols = Counter(str(row.get("symbol") or "unknown") for row in closed_wins)
        causes.append(f"Closed winning trades contributed {_money_text(sum(safe_float(row.get('profit_loss')) or 0.0 for row in closed_wins))}; symbols involved: {dict(symbols)}.")
    matched = reconstructed.get("matched_trades") or []
    open_lots = reconstructed.get("open_lots") or []
    if matched:
        wins = [row for row in matched if (safe_float(row.get("profit_loss")) or 0.0) > 0]
        losses = [row for row in matched if (safe_float(row.get("profit_loss")) or 0.0) < 0]
        if wins:
            causes.append(f"Matched broker fills show {len(wins)} profitable round trip(s), contributing {_money_text(sum(safe_float(row.get('profit_loss')) or 0.0 for row in wins))}.")
        if losses:
            causes.append(f"Matched broker fills show {len(losses)} losing round trip(s), contributing {_money_text(sum(safe_float(row.get('profit_loss')) or 0.0 for row in losses))}.")
    if open_lots:
        symbols = Counter(str(row.get("symbol") or "unknown") for row in open_lots)
        causes.append(f"{len(open_lots)} broker fill lot(s) remain open/unmatched in this window, so portfolio movement may be unrealised P&L; open symbols/lots: {dict(symbols)}.")
    if not attribution and broker_trades:
        causes.append("Broker trade/order rows exist, but no closed performance-attribution rows were recorded yet; part of the movement may be open/unrealised P&L.")
    if not attribution and not broker_trades:
        causes.append("No closed trade attribution or broker trade rows were recorded for this date; the loss is most likely from open-position mark-to-market movement captured in broker snapshots.")
    rejected = [row for row in decisions if row.get("decision") == "rejected"]
    if rejected:
        reasons = Counter(str(row.get("rejection_reason") or "unknown") for row in rejected)
        causes.append(f"Orchestrator rejected {len(rejected)} idea(s), mainly for: {dict(reasons)}.")
    return causes


def _plain_english_report_answer(
    balance_summary: dict[str, dict[str, Any]],
    attribution: list[dict[str, Any]],
    broker_trades: list[dict[str, Any]],
    reconstructed: dict[str, Any],
    report_context: dict[str, Any],
    broker: str,
) -> list[str]:
    lines: list[str] = []
    if balance_summary:
        for name, item in balance_summary.items():
            change = safe_float(item.get("balance_change"))
            direction = "up" if (change or 0) > 0 else "down" if (change or 0) < 0 else "flat"
            lines.append(
                f"{name.title()} is {direction} by {_money_text(change)} over this report window. "
                f"Latest account value is {_money_text(item.get('end_balance'))}, cash is {_money_text(item.get('end_cash'))}, "
                f"and about {_money_text(item.get('end_in_positions'))} appears to be tied up in open positions."
            )
    else:
        lines.append("No portfolio snapshots were found for this report window, so the app cannot prove start-to-end performance from stored balances.")

    realised = sum(safe_float(row.get("profit_loss")) or 0.0 for row in attribution)
    reconstructed_realised = safe_float(reconstructed.get("realized_pnl")) or 0.0
    if attribution:
        lines.append(f"Closed trade attribution says realised P&L was {_money_text(realised)} across {len(attribution)} closed trade(s).")
    elif reconstructed.get("matched_trades"):
        lines.append(f"Broker fills could be matched into realised P&L of {_money_text(reconstructed_realised)} across {len(reconstructed.get('matched_trades') or [])} round trip(s).")
    elif broker_trades:
        lines.append("Broker rows were found, but no complete buy/sell round trip was found in this window, so any gain or loss is probably still open/unrealised or from activity outside this window.")
    else:
        lines.append("No broker fills/orders were found in this report window. If the account moved, it was probably existing open-position value changing rather than a new closed trade today.")

    latest = _latest_context_trade(report_context, broker)
    if latest:
        lines.append(
            f"Latest visible broker activity: {str(latest.get('side') or latest.get('type') or '').upper()} "
            f"{latest.get('symbol') or latest.get('pair') or 'unknown'} for {latest.get('qty') or latest.get('quantity') or 'unknown'} "
            f"at {_money_text(latest.get('price') or latest.get('filled_avg_price'))}."
        )
    lines.append("Learning note: AI Trader should only claim trading-skill improvement from completed trades with entry, exit, and P&L. Open positions are useful evidence, but they are not final lessons yet.")
    return lines


def _deterministic_ai_trader_answer(question: str, context: dict[str, Any]) -> str:
    snapshots = context.get("latest_portfolio_snapshots") or []
    trades = context.get("latest_broker_trades") or []
    attribution = context.get("latest_closed_trade_attribution") or []
    learning = context.get("daily_learning") or {}
    lines = [
        "I can answer from stored AI Trader evidence, but I am read-only and cannot place or approve trades.",
    ]
    if snapshots:
        latest = snapshots[0]
        invested = _estimated_in_positions(latest.get("portfolio_value"), latest.get("cash"))
        lines.append(
            f"Latest {latest.get('broker', 'broker')} snapshot: account {_money_text(latest.get('portfolio_value'))}, "
            f"cash {_money_text(latest.get('cash'))}, estimated in positions {_money_text(invested)}, "
            f"open positions {latest.get('open_positions_count') or 'not available'}."
        )
        day_pnl = safe_float(latest.get("day_pnl"))
        if day_pnl is not None:
            moved = "up" if day_pnl > 0 else "down" if day_pnl < 0 else "flat"
            lines.append(f"Latest day P&L evidence says the account is {moved} by {_money_text(day_pnl)}.")
    else:
        lines.append("No portfolio snapshots are stored yet, so I cannot prove current performance.")
    if attribution:
        total = sum(safe_float(row.get("profit_loss")) or 0.0 for row in attribution)
        winners = sum(1 for row in attribution if (safe_float(row.get("profit_loss")) or 0.0) > 0)
        losers = sum(1 for row in attribution if (safe_float(row.get("profit_loss")) or 0.0) < 0)
        lines.append(f"Closed-trade attribution shows {_money_text(total)} across {len(attribution)} recent closed trade(s): {winners} winner(s), {losers} loser(s).")
    elif trades:
        latest_trade = trades[0]
        lines.append(
            f"I can see broker activity, but no recent closed-trade attribution. Latest broker row: "
            f"{latest_trade.get('side') or 'activity'} {latest_trade.get('symbol') or 'unknown'} "
            f"for {latest_trade.get('quantity') or 'unknown'} at {_money_text(latest_trade.get('price'))}."
        )
    else:
        lines.append("No recent broker trades are stored in the evidence bundle.")
    if learning.get("summary"):
        lines.append(f"Learning summary: {learning.get('summary')}")
    if "kraken" in question.lower() and "trade" in question.lower():
        lines.extend(_kraken_trade_status_lines(context))
    if context.get("openai_configured"):
        lines.append("OpenAI is configured, but this response used the local evidence summary because the OpenAI explanation was unavailable or timed out.")
    else:
        lines.append("For a fuller answer, configure OPENAI_API_KEY on the AI Trader deployment so the Ask screen can explain this evidence conversationally.")
    return "\n\n".join(lines)


def _kraken_trade_status_lines(context: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    panels = context.get("broker_panels") or []
    kraken = next((item for item in panels if str(item.get("broker") or "").lower() == "kraken"), None)
    if kraken:
        permissions = kraken.get("trading_permissions") or {}
        lines.append(
            "Kraken trading status: "
            f"auto trading {'enabled' if permissions.get('auto_trading_enabled') else 'disabled'}, "
            f"broker trading {'enabled' if permissions.get('trading_enabled') else 'disabled'}, "
            f"live approval {'yes' if permissions.get('live_trading_approved') else 'no'}, "
            f"real-order submission {'yes' if permissions.get('submit_real_orders') else 'no'}, "
            f"can submit real orders now {'yes' if permissions.get('can_submit_real_orders') else 'no'}."
        )
        lines.append(
            f"Kraken seatbelts: allocation {_money_text(permissions.get('trading_allocation_gbp'))}, "
            f"max order {_money_text(permissions.get('max_order_gbp'))}, "
            f"max open trades {permissions.get('max_open_trades')}, "
            f"allowed pairs {', '.join(permissions.get('allowed_pairs') or []) or 'not listed'}."
        )
    recommendations = [
        item for item in (context.get("latest_recommendations") or [])
        if str(item.get("broker") or item.get("suggested_broker") or "").lower() == "kraken"
        or str(item.get("asset_type") or "").lower() == "crypto"
    ]
    active = [item for item in recommendations if str(item.get("freshness_status") or "").lower() != "expired"]
    eligible = [item for item in active if item.get("auto_trade_eligible")]
    if eligible:
        symbols = ", ".join(str(item.get("symbol") or "unknown") for item in eligible[:5])
        lines.append(f"I can see {len(eligible)} active crypto/Kraken recommendation(s) marked auto-trade eligible: {symbols}.")
    elif active:
        reasons = Counter(str(item.get("auto_trade_reason") or item.get("status") or "not eligible") for item in active)
        lines.append(f"I can see active crypto/Kraken recommendations, but none are marked auto-trade eligible yet. Reasons seen: {dict(reasons)}.")
    else:
        lines.append("I cannot see an active fresh Kraken recommendation in the latest evidence. Auto trading will wait until research produces one that passes confidence, freshness, and guardrails.")
    lines.append("So zero Kraken trades today can be normal if no fresh eligible recommendation has passed the orchestrator yet, even though Kraken auto trading is enabled.")
    return lines


def _current_open_position_lines(report_context: dict[str, Any], broker: str) -> str:
    contexts = report_context if broker == "all" else {broker: report_context.get(broker)}
    lines: list[str] = []
    for broker_name, payload in contexts.items():
        if not isinstance(payload, dict):
            continue
        positions = payload.get("open_positions") or []
        portfolio_value = payload.get("portfolio_value")
        cash = payload.get("cash_available")
        invested = _estimated_in_positions(portfolio_value, cash)
        if invested is not None:
            lines.append(f"- {_broker_label(broker_name)}: estimated {_money_text(invested)} currently tied up outside cash.")
        if positions:
            for position in positions[:20]:
                if not isinstance(position, dict):
                    continue
                symbol = position.get("symbol") or position.get("asset") or position.get("pair") or "unknown"
                qty = position.get("qty") or position.get("quantity") or position.get("vol") or "N/A"
                market_value = position.get("market_value") or position.get("value") or position.get("notional")
                unrealized = position.get("unrealized_pl") or position.get("unrealised_pnl")
                lines.append(f"  - {symbol}: qty {qty}, value {_money_text(market_value)}, unrealised P&L {_money_text(unrealized)}.")
        elif invested is not None and abs(invested) > 0.01:
            lines.append(f"  - Broker did not return position detail, but portfolio minus cash implies open holdings worth about {_money_text(invested)}.")
    return "\n".join(lines) if lines else "- No open position detail was available from broker refresh."


def _latest_context_trade(report_context: dict[str, Any], broker: str) -> dict[str, Any] | None:
    contexts = report_context if broker == "all" else {broker: report_context.get(broker)}
    latest_items: list[dict[str, Any]] = []
    for payload in contexts.values():
        if not isinstance(payload, dict):
            continue
        latest = payload.get("latest_trade")
        if isinstance(latest, dict):
            latest_items.append(latest)
        for key in ["recent_activities", "recent_orders"]:
            for item in payload.get(key) or []:
                if isinstance(item, dict):
                    latest_items.append(item)
    latest_items.sort(
        key=lambda item: item.get("transaction_time") or item.get("submitted_at") or item.get("updated_at") or item.get("created_at") or "",
        reverse=True,
    )
    return latest_items[0] if latest_items else None


def _report_trade_lines(attribution: list[dict[str, Any]]) -> str:
    if not attribution:
        return "- No closed trade attribution rows recorded for this report window."
    lines = []
    for index, row in enumerate(attribution, start=1):
        lines.append(
            f"- Trade {index}: {row.get('broker', 'unknown')} {row.get('symbol', 'unknown')} {row.get('side', '')}; "
            f"opened {_human_time(row.get('opened_at'))}; closed {_human_time(row.get('closed_at') or row.get('created_at'))}; "
            f"entry {_money_text(row.get('entry_price'))}, exit {_money_text(row.get('exit_price'))}, "
            f"qty {row.get('quantity') or 'N/A'}, P&L {_money_text(row.get('profit_loss'))}, "
            f"entry reason {row.get('entry_reason') or 'N/A'}, exit reason {row.get('exit_reason') or 'N/A'}."
        )
    return "\n".join(lines)


def _report_broker_trade_lines(broker_trades: list[dict[str, Any]]) -> str:
    if not broker_trades:
        return "- No broker trade/order rows recorded for this report window."
    lines = []
    for index, row in enumerate(broker_trades, start=1):
        parsed = _broker_trade_payload(row)
        event_time = _broker_trade_time(row)
        side = _broker_trade_side(row)
        symbol = _broker_trade_symbol(row)
        quantity = _broker_trade_quantity(row)
        price = _broker_trade_price(row)
        lines.append(
            f"- Row {index}: {row.get('broker', 'unknown')} {symbol or 'N/A'} {side or ''}; "
            f"status {row.get('status') or 'N/A'}; opened {_human_time(row.get('opened_at'))}; "
            f"closed {_human_time(row.get('closed_at'))}; updated {_human_time(row.get('updated_at'))}; event time {_human_time(event_time)}; "
            f"qty {quantity if quantity is not None else 'N/A'}; price {_money_text(price)}; notional {_money_text(row.get('notional') or parsed.get('net_amount'))}; "
            f"raw type {parsed.get('type') or parsed.get('activity_type') or 'N/A'}."
        )
    return "\n".join(lines)


def _reconstruct_broker_fill_pnl(broker_trades: list[dict[str, Any]]) -> dict[str, Any]:
    lots: dict[str, list[dict[str, Any]]] = defaultdict(list)
    matched: list[dict[str, Any]] = []
    fill_rows = [
        row for row in broker_trades
        if _broker_trade_side(row) in {"buy", "sell"}
        and _broker_trade_quantity(row) is not None
        and _broker_trade_price(row) is not None
    ]
    fill_rows.sort(key=lambda row: _broker_trade_time(row) or row.get("updated_at") or "")
    for row in fill_rows:
        symbol = _broker_trade_symbol(row) or "UNKNOWN"
        side = _broker_trade_side(row) or ""
        qty_remaining = _broker_trade_quantity(row) or 0.0
        price = _broker_trade_price(row) or 0.0
        event_time = _broker_trade_time(row)
        opposite = "sell" if side == "buy" else "buy"
        same_lots = lots[symbol]
        while qty_remaining > 0 and same_lots and same_lots[0]["side"] == opposite:
            lot = same_lots[0]
            close_qty = min(qty_remaining, lot["quantity"])
            if lot["side"] == "buy" and side == "sell":
                pnl = (price - lot["price"]) * close_qty
                entry_side = "buy"
            else:
                pnl = (lot["price"] - price) * close_qty
                entry_side = "sell"
            matched.append({
                "broker": row.get("broker"),
                "symbol": symbol,
                "entry_side": entry_side,
                "exit_side": side,
                "quantity": close_qty,
                "entry_price": lot["price"],
                "exit_price": price,
                "entry_time": lot.get("time"),
                "exit_time": event_time,
                "profit_loss": pnl,
                "reason": "FIFO match from broker fill history in this report window.",
            })
            lot["quantity"] -= close_qty
            qty_remaining -= close_qty
            if lot["quantity"] <= 1e-9:
                same_lots.pop(0)
        if qty_remaining > 1e-9:
            same_lots.append({
                "broker": row.get("broker"),
                "symbol": symbol,
                "side": side,
                "quantity": qty_remaining,
                "price": price,
                "time": event_time,
                "reason": "No matching opposite-side fill inside this report window.",
            })
    open_lots = [lot for symbol_lots in lots.values() for lot in symbol_lots]
    realized_pnl = sum(safe_float(row.get("profit_loss")) or 0.0 for row in matched)
    return {"matched_trades": matched, "open_lots": open_lots, "realized_pnl": realized_pnl}


def _reconstructed_trade_lines(reconstructed: dict[str, Any]) -> str:
    matched = reconstructed.get("matched_trades") or []
    open_lots = reconstructed.get("open_lots") or []
    lines: list[str] = []
    if matched:
        for index, row in enumerate(matched, start=1):
            result = "made" if (safe_float(row.get("profit_loss")) or 0.0) >= 0 else "lost"
            lines.append(
                f"- Matched trade {index}: {row.get('broker', 'unknown')} {row.get('symbol')} "
                f"{row.get('entry_side')}->{row.get('exit_side')}; opened {_human_time(row.get('entry_time'))}; "
                f"closed {_human_time(row.get('exit_time'))}; qty {row.get('quantity')}; "
                f"entry {_money_text(row.get('entry_price'))}; exit {_money_text(row.get('exit_price'))}; "
                f"{result} {_money_text(abs(safe_float(row.get('profit_loss')) or 0.0))}; P&L {_money_text(row.get('profit_loss'))}; "
                f"reason: {row.get('reason')}."
            )
    else:
        lines.append("- No buy/sell fills could be matched into a closed round trip inside this report window.")
    if open_lots:
        lines.append("- Open/unmatched fills:")
        for row in open_lots:
            lines.append(
                f"  - {row.get('broker', 'unknown')} {row.get('symbol')} {row.get('side')}; "
                f"time {_human_time(row.get('time'))}; qty {row.get('quantity')}; price {_money_text(row.get('price'))}; "
                f"reason: {row.get('reason')}"
            )
    return "\n".join(lines)


def _broker_trade_payload(row: dict[str, Any]) -> dict[str, Any]:
    payload = row.get("payload_json")
    if not payload:
        return {}
    try:
        parsed = json.loads(payload)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


def _broker_trade_symbol(row: dict[str, Any]) -> str | None:
    payload = _broker_trade_payload(row)
    value = row.get("symbol") or payload.get("symbol") or payload.get("pair")
    return str(value).upper() if value else None


def _broker_trade_side(row: dict[str, Any]) -> str | None:
    payload = _broker_trade_payload(row)
    value = row.get("side") or payload.get("side") or payload.get("type")
    value = str(value).lower() if value else ""
    if value in {"buy", "sell"}:
        return value
    return None


def _broker_trade_quantity(row: dict[str, Any]) -> float | None:
    payload = _broker_trade_payload(row)
    return safe_float(row.get("quantity") or payload.get("qty") or payload.get("quantity") or payload.get("vol"))


def _broker_trade_price(row: dict[str, Any]) -> float | None:
    payload = _broker_trade_payload(row)
    return safe_float(row.get("price") or payload.get("price") or payload.get("filled_avg_price"))


def _broker_trade_time(row: dict[str, Any]) -> str | None:
    payload = _broker_trade_payload(row)
    return (
        row.get("closed_at")
        or row.get("opened_at")
        or payload.get("transaction_time")
        or payload.get("filled_at")
        or payload.get("created_at")
        or payload.get("time")
        or row.get("updated_at")
    )


def _report_decision_lines(decisions: list[dict[str, Any]]) -> str:
    rejected = [row for row in decisions if row.get("decision") == "rejected"]
    if not rejected:
        return "- No rejected orchestrator decisions recorded for this date."
    return "\n".join(
        f"- {row.get('symbol', 'unknown')} via {row.get('selected_broker') or 'unknown'}: {row.get('rejection_reason') or 'rejected'}"
        for row in rejected[:20]
    )


def _period_lessons(
    attribution: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
    snapshots: list[dict[str, Any]],
    broker_trades: list[dict[str, Any]],
    base_lessons: list[str],
) -> list[str]:
    lessons = list(base_lessons)
    losses = [row for row in attribution if (safe_float(row.get("profit_loss")) or 0.0) < 0]
    wins = [row for row in attribution if (safe_float(row.get("profit_loss")) or 0.0) > 0]
    if losses:
        exit_reasons = Counter(str(row.get("exit_reason") or "unknown") for row in losses)
        lessons.append(f"Loss-making closed trades should be reviewed by exit reason before the next trading cycle: {dict(exit_reasons)}.")
        lessons.append("For the next trades, require the entry thesis to explain why the setup is stronger than the losing trades in this report window.")
    if wins:
        entry_reasons = Counter(str(row.get("entry_reason") or "unknown") for row in wins)
        lessons.append(f"Winning closed trades shared these entry reasons: {dict(entry_reasons)}. Future trades should explicitly compare against these patterns.")
    if not attribution and broker_trades:
        lessons.append("Broker activity exists without closed attribution; improve reconciliation before drawing firm conclusions about realised strategy quality.")
    if snapshots and not attribution:
        lessons.append("Balance movement without closed attribution suggests open-position/unrealised P&L or valuation movement; avoid changing strategy until open trades are reconciled.")
    rejected = [row for row in decisions if row.get("decision") == "rejected"]
    if rejected:
        reasons = Counter(str(row.get("rejection_reason") or "unknown") for row in rejected)
        lessons.append(f"Rejected recommendations show what the system avoided: {dict(reasons)}.")
    return _dedupe_lines(lessons)


def _period_recommendations(attribution: list[dict[str, Any]], decisions: list[dict[str, Any]], base_recommendations: list[str]) -> list[str]:
    recommendations = list(base_recommendations)
    losses = [row for row in attribution if (safe_float(row.get("profit_loss")) or 0.0) < 0]
    if losses:
        recommendations.append("Before approving larger size, review each losing trade's entry timing, stop distance, and whether the exit matched the planned stop/take-profit.")
        recommendations.append("Keep or reduce position size until the next report shows that losses are smaller than winners over the same period.")
    if not attribution:
        recommendations.append("Do not infer profitability from broker balance movement alone; wait for closed-trade attribution or inspect open positions.")
    rejected = [row for row in decisions if row.get("decision") == "rejected"]
    if rejected:
        recommendations.append("Do not loosen guardrails purely to increase trade count; repeated rejection reasons should be reviewed by the Founder first.")
    return _dedupe_lines(recommendations)


def _dedupe_lines(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        text = str(item).strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _recommendation_freshness(created_at: str | None, confidence: Any) -> dict[str, Any]:
    if not created_at:
        return {"status": "Not available", "expires_at": None, "note": "Generated time is not available."}
    generated_at = _parse_datetime(created_at)
    if generated_at is None:
        return {"status": "Not available", "expires_at": None, "note": "Generated time could not be parsed."}
    confidence_value = safe_score(confidence) or 0
    if confidence_value >= 0.85:
        lifetime = timedelta(hours=4)
    elif confidence_value >= 0.75:
        lifetime = timedelta(hours=12)
    else:
        lifetime = timedelta(hours=24)
    expires_at = generated_at + lifetime
    now = datetime.now(timezone.utc)
    if now > expires_at:
        status = "Expired"
    elif now > generated_at + (lifetime / 2):
        status = "Stale"
    else:
        status = "Fresh"
    return {
        "status": status,
        "expires_at": expires_at.isoformat(),
        "note": f"{status}. Trade idea lifetime is {int(lifetime.total_seconds() / 3600)} hours.",
    }


def _parse_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _auto_trade_reason(
    *,
    confidence: float,
    philosophy_fit: float,
    auto_enabled: bool,
    auto_label: str,
    min_confidence: float,
    min_philosophy_fit: float,
    freshness_status: str,
    guardrails_passed: bool,
    already_executed: bool,
    guardrail_failures: list[str] | None = None,
    has_dossier_arguments: bool = True,
) -> str:
    if not auto_enabled:
        return f"{auto_label} is disabled; manual approval is required."
    if already_executed:
        return "Already executed."
    if freshness_status == "Expired":
        return "Expired. Run new analysis before execution."
    if confidence < min_confidence:
        return f"Confidence is below {int(min_confidence * 100)}%."
    if philosophy_fit < min_philosophy_fit:
        return f"Investment philosophy fit is below {int(min_philosophy_fit * 100)}%."
    if not guardrails_passed:
        if guardrail_failures:
            return f"Execution guardrails failed: {_format_guardrail_failures(guardrail_failures)}."
        return "Execution guardrails did not pass, so auto-trade is blocked."
    if not has_dossier_arguments:
        return "Not actionable yet: AI Trader cannot state both the strongest argument for and against the trade."
    return "Eligible for broker auto-trade."


def _why_no_action_may_be_better(
    committee: dict[str, Any],
    probability: dict[str, Any],
    guardrail_failures: list[str],
    freshness_status: str,
) -> str:
    if freshness_status == "Expired":
        return "Waiting may be better because the evidence is stale and market conditions may have changed."
    if guardrail_failures:
        return "Taking no action is better while guardrails are failing."
    calibration = str(probability.get("calibration_status") or "").lower()
    if "insufficient" in calibration or "weak" in calibration:
        return "Waiting may be better because AI Trader does not yet have enough similar outcomes to trust this confidence level."
    opposing = committee.get("strongest_argument_against")
    if opposing:
        return f"Waiting may be better if this concern matters more than the thesis: {opposing}"
    return "Doing nothing remains acceptable if evidence quality, portfolio fit, or market conditions are not strong enough."


def _proposal_payload(payload_json: Any) -> dict[str, Any]:
    if not payload_json:
        return {}
    try:
        data = json.loads(payload_json)
    except (TypeError, json.JSONDecodeError):
        return {}
    proposal = data.get("proposal") if isinstance(data, dict) else None
    return proposal if isinstance(proposal, dict) else {}


def _proposal_exchange(payload_json: Any) -> str:
    return str(_proposal_payload(payload_json).get("exchange") or "NYSE")


def _proposal_asset_type(payload_json: Any) -> str:
    return str(_proposal_payload(payload_json).get("asset_type") or "stock")


def _proposal_philosophy_fit(payload_json: Any) -> float:
    value = _proposal_payload(payload_json).get("philosophy_fit")
    return safe_score(value) or 0.0


def _score_payload(score: dict[str, Any] | None, confidence: float, philosophy_fit: float) -> dict[str, Any]:
    if score:
        return {
            "fundamental_score": score.get("fundamental_score"),
            "technical_score": score.get("technical_score"),
            "market_score": score.get("market_score"),
            "macro_score": score.get("macro_score"),
            "behavioural_score": score.get("behavioural_score"),
            "investment_policy_score": score.get("investment_policy_score"),
            "risk_score": score.get("risk_score"),
            "overall_confidence": score.get("overall_confidence"),
            "reasoning": score.get("reasoning"),
        }
    return {
        "fundamental_score": confidence or None,
        "technical_score": confidence or None,
        "market_score": confidence or None,
        "macro_score": None,
        "behavioural_score": None,
        "investment_policy_score": philosophy_fit or None,
        "risk_score": None,
        "overall_confidence": confidence or None,
        "reasoning": {"status": "Not available - not assessed by orchestrator yet"},
    }


def _payload_intelligence(payload_json: Any) -> dict[str, Any] | None:
    if not payload_json:
        return None
    try:
        payload = json.loads(payload_json) if isinstance(payload_json, str) else payload_json
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    intelligence = payload.get("intelligence")
    return intelligence if isinstance(intelligence, dict) else None


def _payload_strategy(payload_json: Any, intelligence: dict[str, Any] | None = None) -> dict[str, Any] | None:
    if intelligence and isinstance(intelligence.get("strategy"), dict):
        return intelligence["strategy"]
    fallback = _payload_intelligence(payload_json)
    if fallback and isinstance(fallback.get("strategy"), dict):
        return fallback["strategy"]
    return None


def _payload_regime(payload_json: Any, intelligence: dict[str, Any] | None = None) -> dict[str, Any] | None:
    if intelligence and isinstance(intelligence.get("regime"), dict):
        return intelligence["regime"]
    fallback = _payload_intelligence(payload_json)
    if fallback and isinstance(fallback.get("regime"), dict):
        return fallback["regime"]
    return None


def _average_numeric(values: list[Any]) -> float | None:
    numeric = [safe_float(value) for value in values]
    clean = [value for value in numeric if value is not None]
    if not clean:
        return None
    return sum(clean) / len(clean)


def _committee_numeric_confidence(committee: dict[str, Any] | None) -> float | None:
    if not committee:
        return None
    votes = committee.get("member_votes") or []
    scores = [safe_float(vote.get("score")) for vote in votes if isinstance(vote, dict)]
    return _average_numeric(scores)


def _plain_confidence(value: Any) -> str:
    number = safe_float(value)
    if number is None:
        return "Unknown - not enough evidence yet"
    if number >= 0.8:
        return "High confidence"
    if number >= 0.6:
        return "Moderate confidence"
    if number >= 0.4:
        return "Low to moderate confidence"
    return "Low confidence"


def _plain_regime(regime: str) -> str:
    text = str(regime or "unknown").replace("_", " ").lower()
    labels = {
        "bull": "Trending up",
        "bear": "Trending down",
        "range": "Moving sideways",
        "recovery": "Recovering",
        "contraction": "Weakening",
        "transition": "Changing direction",
        "crisis": "Highly stressed",
        "unknown": "Unknown - not enough market evidence yet",
    }
    return labels.get(text, text.title())


def _plain_market_health(regime: str, confidence: Any) -> str:
    conf = safe_float(confidence)
    regime_text = str(regime or "").lower()
    if regime_text in {"bull", "recovery"} and conf is not None and conf >= 0.6:
        return "Constructive"
    if regime_text in {"bear", "crisis", "contraction"}:
        return "Cautious"
    if regime_text == "range":
        return "Mixed"
    return "Unclear"


def _portfolio_rebalancing_suggestions(risk_level: str, diversification: str) -> list[str]:
    suggestions = []
    if risk_level == "HIGH":
        suggestions.append("Review whether too much capital is deployed before approving new trades.")
    if "Concentrated" in diversification:
        suggestions.append("Review whether too few positions are driving too much portfolio risk.")
    if not suggestions:
        suggestions.append("No urgent rebalance suggestion from current data.")
    return suggestions


def _broker_label(broker: str) -> str:
    labels = {
        "alpaca": "Alpaca",
        "kraken": "Kraken",
        "coinbase": "Coinbase",
        "binance": "Binance",
        "interactive_brokers": "Interactive Brokers",
    }
    return labels.get(broker.lower(), broker.replace("_", " ").title())


def _sum_balances(balances: Any) -> float | None:
    if not isinstance(balances, dict):
        return None
    total = 0.0
    found = False
    for value in balances.values():
        amount = safe_float(value)
        if amount is None:
            continue
        total += amount
        found = True
    return total if found else None


def _kraken_trading_allocation_gbp(balances: Any) -> float:
    allocation = _float_env("KRAKEN_TRADING_ALLOCATION_GBP", 100.0)
    summary_cash = _kraken_gbp_cash(balances)
    if summary_cash is None:
        return allocation
    return max(0.0, min(allocation, summary_cash))


def _kraken_balance_summary(balances: Any, adapter: Any) -> dict[str, Any]:
    raw = balances if isinstance(balances, dict) else {}
    gbp_cash = _kraken_gbp_cash(raw)
    total = gbp_cash or 0.0
    raw_balance_rows: list[dict[str, Any]] = []
    converted_assets: list[dict[str, Any]] = []
    unpriced_assets: list[dict[str, Any]] = []
    for asset, value in raw.items():
        qty = safe_float(value)
        if qty is None or qty == 0:
            continue
        normalized = _kraken_asset_symbol(asset)
        raw_balance_rows.append({"asset": asset, "normalized_asset": normalized, "quantity": qty})
        if normalized == "GBP":
            continue
        price_result = _kraken_asset_gbp_price(adapter, normalized)
        price = price_result.get("price_gbp")
        if price is None:
            unpriced_assets.append({
                "asset": asset,
                "normalized_asset": normalized,
                "quantity": qty,
                "reason": price_result.get("reason") or "gbp_price_unavailable",
                "pairs_tried": price_result.get("pairs_tried") or [],
            })
            continue
        value_gbp = qty * price
        total += value_gbp
        converted_assets.append({
            "asset": asset,
            "normalized_asset": normalized,
            "quantity": qty,
            "pair": price_result.get("pair"),
            "pricing_route": price_result.get("pricing_route"),
            "price_gbp": price,
            "value_gbp": value_gbp,
        })
    trading_allocation = _kraken_trading_allocation_gbp(raw)
    return {
        "total_estimated_gbp": round(total, 2),
        "gbp_cash": round(gbp_cash, 2) if gbp_cash is not None else None,
        "trading_allocation_gbp": round(trading_allocation, 2),
        "raw_balances": raw,
        "raw_balance_rows": raw_balance_rows,
        "converted_assets": converted_assets,
        "unpriced_assets": unpriced_assets,
        "valuation_note": (
            "Portfolio value is GBP cash plus supported crypto balances converted to GBP using Kraken ticker prices. "
            "Fiat/stablecoin balances and assets without a GBP price are shown below but excluded from the estimated total. "
            "Kraken Pro may also show assets outside this API balance view, such as earn/staked/funding balances. "
            "Trading allocation is capped separately by KRAKEN_TRADING_ALLOCATION_GBP."
        ),
    }


def _kraken_gbp_cash(balances: Any) -> float | None:
    if not isinstance(balances, dict):
        return None
    total = 0.0
    found = False
    for key in ("GBP", "ZGBP"):
        amount = safe_float(balances.get(key))
        if amount is not None:
            total += amount
            found = True
    return total if found else None


def _kraken_asset_gbp_price(adapter: Any, normalized: str) -> dict[str, Any]:
    normalized = str(normalized or "").upper()
    if normalized == "GBP":
        return {"price_gbp": 1.0, "pair": "GBP", "pricing_route": "cash"}
    pairs_tried: list[str] = []
    direct_pair = _kraken_pair(normalized, "GBP")
    direct = _kraken_pair_price(adapter, direct_pair)
    pairs_tried.append(direct_pair)
    if direct is not None:
        return {"price_gbp": direct, "pair": direct_pair, "pricing_route": "direct_gbp", "pairs_tried": pairs_tried}
    if normalized in {"USD", "USDT", "USDC"}:
        usd_to_gbp = _kraken_usd_to_gbp(adapter, pairs_tried)
        if usd_to_gbp is not None:
            return {"price_gbp": usd_to_gbp, "pair": "USDGBP", "pricing_route": "usd_to_gbp", "pairs_tried": pairs_tried}
    if normalized == "EUR":
        eur_pair = _kraken_pair("EUR", "GBP")
        eur_to_gbp = _kraken_pair_price(adapter, eur_pair)
        pairs_tried.append(eur_pair)
        if eur_to_gbp is not None:
            return {"price_gbp": eur_to_gbp, "pair": eur_pair, "pricing_route": "eur_to_gbp", "pairs_tried": pairs_tried}
    for quote in ["USD", "USDT", "USDC"]:
        asset_pair = _kraken_pair(normalized, quote)
        asset_to_quote = _kraken_pair_price(adapter, asset_pair)
        pairs_tried.append(asset_pair)
        if asset_to_quote is None:
            continue
        quote_to_gbp = _kraken_usd_to_gbp(adapter, pairs_tried)
        if quote_to_gbp is None:
            continue
        return {
            "price_gbp": asset_to_quote * quote_to_gbp,
            "pair": asset_pair,
            "pricing_route": f"{quote.lower()}_bridge_to_gbp",
            "pairs_tried": pairs_tried,
        }
    return {"price_gbp": None, "reason": "no_direct_or_bridge_gbp_price", "pairs_tried": pairs_tried}


def _kraken_usd_to_gbp(adapter: Any, pairs_tried: list[str]) -> float | None:
    for pair in ["USDGBP", "USDTGBP", "USDCGBP"]:
        price = _kraken_pair_price(adapter, pair)
        pairs_tried.append(pair)
        if price is not None:
            return price
    inverse = _kraken_pair_price(adapter, "GBPUSD")
    pairs_tried.append("GBPUSD")
    if inverse:
        return 1 / inverse
    return None


def _kraken_pair_price(adapter: Any, pair: str) -> float | None:
    try:
        return _kraken_last_price(adapter.current_prices([pair]), pair)
    except Exception:
        return None


def _kraken_asset_symbol(asset: str) -> str:
    normalized = str(asset or "").upper()
    aliases = {
        "XXBT": "BTC",
        "XBT": "BTC",
        "XETH": "ETH",
        "ZGBP": "GBP",
        "ZUSD": "USD",
        "ZEUR": "EUR",
    }
    if normalized in aliases:
        return aliases[normalized]
    if normalized.startswith("X") and len(normalized) > 3:
        return normalized[1:]
    if normalized.startswith("Z") and len(normalized) > 3:
        return normalized[1:]
    return normalized


def _float_env(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except (TypeError, ValueError):
        return default


def _int_env(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except (TypeError, ValueError):
        return default


def _bool_env(key: str, default: bool) -> bool:
    value = os.getenv(key)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _csv_env(key: str, default: str) -> list[str]:
    value = os.getenv(key, default)
    return [item.strip().upper() for item in value.split(",") if item.strip()]


def _symbol_from_kraken_pair(pair: str) -> str:
    normalized = str(pair or "").upper().replace("/", "").replace("-", "").strip()
    for suffix in ("GBP", "USD", "EUR", "USDT", "USDC"):
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)]
            break
    if normalized.startswith("X") and normalized in {"XXBT", "XXDG"}:
        normalized = normalized[1:]
    if normalized.startswith("Z") and len(normalized) > 4:
        normalized = normalized[1:]
    if normalized == "XBT":
        return "BTC"
    if normalized == "XDG":
        return "DOGE"
    return normalized


def _crypto_display_name(symbol: str) -> str:
    names = {
        "BTC": "Bitcoin",
        "ETH": "Ethereum",
        "SOL": "Solana",
        "XRP": "XRP",
        "DOGE": "Dogecoin",
        "ADA": "Cardano",
        "LINK": "Chainlink",
        "DOT": "Polkadot",
        "AVAX": "Avalanche",
        "MATIC": "Polygon",
    }
    normalized = str(symbol or "").upper()
    return names.get(normalized, normalized)


def _trade_learning_lessons(attribution: list[dict[str, Any]], rejected: list[dict[str, Any]], snapshots: list[dict[str, Any]]) -> list[str]:
    lessons: list[str] = []
    if attribution:
        wins = [row for row in attribution if (safe_float(row.get("profit_loss")) or 0.0) > 0]
        losses = [row for row in attribution if (safe_float(row.get("profit_loss")) or 0.0) < 0]
        if wins:
            lessons.append(f"{len(wins)} closed trade(s) were profitable; compare their entry reasons against future recommendations before increasing size.")
        if losses:
            exit_reasons = Counter(str(row.get("exit_reason") or "unknown") for row in losses)
            lessons.append(f"{len(losses)} closed trade(s) lost money; loss reasons observed: {dict(exit_reasons)}.")
    else:
        lessons.append("No closed trade outcomes were recorded for this date, so technique learning is limited to decisions, rejections, portfolio movement, and benchmark observations.")
    if rejected:
        reasons = Counter(str(row.get("rejection_reason") or "unknown") for row in rejected)
        lessons.append(f"Guardrail/orchestrator rejections clustered around: {dict(reasons)}.")
    if snapshots:
        latest_by_broker: dict[str, dict[str, Any]] = {}
        for row in snapshots:
            latest_by_broker.setdefault(str(row.get("broker") or "unknown"), row)
        for broker, row in latest_by_broker.items():
            day_pnl = safe_float(row.get("day_pnl"))
            week_pnl = safe_float(row.get("week_pnl"))
            if day_pnl is not None or week_pnl is not None:
                lessons.append(f"{broker.title()} snapshot showed day P&L {day_pnl if day_pnl is not None else 'N/A'} and week P&L {week_pnl if week_pnl is not None else 'N/A'}.")
    return lessons


def _benchmark_learning_lessons(items: list[dict[str, Any]]) -> list[str]:
    lessons = []
    for item in items[:6]:
        trader = item.get("trader_name") or "Benchmark trader"
        interpretation = item.get("ai_interpretation")
        risk = item.get("risk_lesson")
        market = item.get("market_lesson")
        summary = "; ".join(part for part in [interpretation, risk, market] if part)
        if summary:
            lessons.append(f"{trader}: {summary}")
    if not lessons:
        lessons.append("No benchmark trader learning rows were available for this date.")
    return lessons


def _learning_recommendations(attribution: list[dict[str, Any]], rejected: list[dict[str, Any]], benchmark_items: list[dict[str, Any]]) -> list[str]:
    recommendations = [
        "Do not change strategy or guardrails automatically; Founder approval is required.",
    ]
    if rejected:
        recommendations.append("Review repeated rejection reasons before lowering confidence, risk, or freshness thresholds.")
    losses = [row for row in attribution if (safe_float(row.get("profit_loss")) or 0.0) < 0]
    if losses:
        recommendations.append("Compare losing trades against stop distance, trend score, and entry timing before allowing larger position sizes.")
    if benchmark_items:
        recommendations.append("Use benchmark trader observations as discipline checks, not as automatic copy-trade signals.")
    return recommendations




def _latest_trade(orders: list[dict[str, Any]], activities: list[dict[str, Any]]) -> dict[str, Any] | None:
    combined = []
    for item in activities:
        combined.append({"type": "fill", **item, "sort_time": item.get("transaction_time") or item.get("date")})
    for item in orders:
        combined.append({"type": "order", **item, "sort_time": item.get("submitted_at") or item.get("updated_at") or item.get("created_at")})
    combined.sort(key=lambda item: item.get("sort_time") or "", reverse=True)
    return combined[0] if combined else None


def _amount_traded_today(activities: list[dict[str, Any]]) -> float:
    today = date.today().isoformat()
    amount = 0.0
    for item in activities:
        timestamp = str(item.get("transaction_time") or item.get("date") or "")
        if not timestamp.startswith(today):
            continue
        qty = safe_float(item.get("qty")) or 0.0
        price = safe_float(item.get("price")) or 0.0
        amount += abs(qty * price)
    return amount


def _research_status(run: dict[str, Any] | None) -> str:
    if not run:
        return "idle - no research run recorded yet"
    status = str(run.get("status") or "idle")
    if status == "completed":
        return "idle"
    return status


def _research_assets_reviewed(run: dict[str, Any] | None) -> int | None:
    if not run:
        return None
    return int(run.get("companies_reviewed") or 0) + int(run.get("crypto_assets_reviewed") or 0)


def _validation_failures(validation_result: Any) -> list[str]:
    data = _validation_payload(validation_result)
    if not data:
        return []
    failures = data.get("failures") or []
    return [str(item) for item in failures]


def _validation_payload(validation_result: Any) -> dict[str, Any] | None:
    if not validation_result:
        return None
    try:
        data = json.loads(validation_result)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _guardrail_checks(validation_result: Any, payload_json: Any = None) -> list[dict[str, str]]:
    data = _validation_payload(validation_result)
    if not data:
        return []
    side = _proposal_side(payload_json)
    failures = set(_validation_failures(validation_result))
    known = {key for key, _, _ in GUARDRAIL_CHECKS}
    checks = [
        {
            "key": key,
            "label": label,
            "status": "failed" if key in failures else "passed",
        }
        for key, label, applies_to in GUARDRAIL_CHECKS
        if applies_to == "all" or applies_to == side or key in failures
    ]
    checks.extend(
        {
            "key": key,
            "label": key.replace("_", " "),
            "status": "failed",
        }
        for key in sorted(failures - known)
    )
    return checks


def _json_loads_safe(payload_json: Any) -> dict[str, Any] | None:
    if not payload_json:
        return None
    try:
        data = json.loads(payload_json)
    except (TypeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _proposal_side(payload_json: Any) -> str | None:
    if not payload_json:
        return None
    try:
        data = json.loads(payload_json)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    proposal = data.get("proposal")
    if not isinstance(proposal, dict):
        return None
    side = proposal.get("side")
    return str(side).lower() if side else None


def _format_guardrail_failures(failures: list[str]) -> str:
    if not failures:
        return "No guardrail details available."
    return ", ".join(item.replace("_", " ") for item in failures)


def _proposal_expected_r(proposal: TradeProposal) -> float | None:
    risk = abs(float(proposal.entry_price) - float(proposal.stop_loss))
    reward = abs(float(proposal.take_profit) - float(proposal.entry_price))
    if risk <= 0:
        return None
    return reward / risk


def _component(healthy: bool, detail: str) -> dict[str, Any]:
    return {"healthy": healthy, "state": "Healthy" if healthy else "Problem", "detail": detail}


def _port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.25):
            return True
    except OSError:
        return False


DEVELOPER_DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AI Trader Developer Dashboard</title>
  <style>
    body { margin: 0; font-family: Segoe UI, Arial, sans-serif; background: #f6f7f9; color: #17202a; }
    header { background: #ffffff; border-bottom: 1px solid #dde1e7; padding: 20px 28px; }
    main { padding: 24px; max-width: 1100px; margin: 0 auto; }
    h1 { margin: 0; font-size: 26px; }
    .sub { margin-top: 6px; color: #667085; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 12px; }
    .card { background: #ffffff; border: 1px solid #dde1e7; border-radius: 8px; padding: 14px; }
    .label { font-weight: 800; margin-bottom: 8px; }
    .healthy { color: #137333; font-weight: 800; }
    .problem { color: #b42318; font-weight: 800; }
    .detail { margin-top: 8px; color: #475467; font-size: 13px; overflow-wrap: anywhere; }
    .counts { margin-top: 18px; }
    button { border: 0; border-radius: 8px; background: #1f6feb; color: #fff; font-weight: 800; padding: 10px 14px; cursor: pointer; }
  </style>
</head>
<body>
  <header>
    <h1>AI Trader Developer Dashboard</h1>
    <div class="sub" id="generated">Loading local status...</div>
  </header>
  <main>
    <p><button onclick="loadStatus()">Refresh</button></p>
    <section class="grid" id="components"></section>
    <section class="card counts">
      <div class="label">Counts</div>
      <div id="counts">Not available</div>
    </section>
    <section class="card counts">
      <div class="label">Last Founder Brief</div>
      <div id="brief">Not available</div>
    </section>
  </main>
  <script>
    const names = {
      python: 'Python Version',
      sqlite: 'SQLite Status',
      openai: 'OpenAI Status',
      alpaca: 'Alpaca Status',
      knowledge_engine: 'Knowledge Engine Status',
      benchmark_engine: 'Benchmark Engine Status',
      trading_engine: 'Trading Engine Status',
      api: 'API Status',
      mobile_app: 'Mobile App Status'
    };
    function icon(ok) { return ok ? '🟢 Healthy' : '🔴 Problem'; }
    async function loadStatus() {
      const response = await fetch('/developer-status');
      const data = await response.json();
      document.getElementById('generated').textContent = `Generated ${data.generated_at}`;
      document.getElementById('components').innerHTML = Object.entries(data.components).map(([key, item]) => `
        <div class="card">
          <div class="label">${names[key] || key}</div>
          <div class="${item.healthy ? 'healthy' : 'problem'}">${icon(item.healthy)}</div>
          <div class="detail">${item.detail || 'Not available'}</div>
        </div>
      `).join('');
      document.getElementById('counts').innerHTML = `
        Watchlist Count: ${data.counts.watchlist}<br>
        Market Theme Count: ${data.counts.market_themes}<br>
        Benchmark Trader Count: ${data.counts.benchmark_traders}<br>
        Trading Journal Count: ${data.counts.trading_journal}
      `;
      document.getElementById('brief').textContent = data.last_founder_brief
        ? `${data.last_founder_brief.briefing_date} (${data.last_founder_brief.created_at})`
        : 'Not available';
    }
    loadStatus().catch(error => {
      document.getElementById('generated').textContent = `Problem loading status: ${error}`;
    });
  </script>
</body>
</html>"""
