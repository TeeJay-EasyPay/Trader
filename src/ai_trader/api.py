from __future__ import annotations

import hmac
import json
import logging
import os
import socket
import sqlite3
import sys
import time
from collections import Counter, defaultdict, deque
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.parse import parse_qs, urlparse

from .agent import AITradingAgent, propose_crypto_trades
from .ai import OpenAIProposalAnalyzer
from .alpaca import AlpacaCredentials, AlpacaPaperClient
from .audit import AuditDatabase
from .benchmark import BenchmarkIntelligenceDatabase
from .briefing import generate_daily_briefing
from .broker_adapters import AlpacaBrokerAdapter, CoinbaseAdapter, InteractiveBrokersAdapter, KrakenAdapter, SaxoAdapter, _kraken_last_price, _kraken_pair
from .config import Settings, load_settings
from .foundation import initialize_foundation_schema, latest_due_diligence, latest_investment_score, load_trading_policy
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
from .scheduler import IntervalWorker, ResearchScheduler


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

AUTO_TRADE_CONFIDENCE_THRESHOLD = 0.85

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
        self.audit = AuditDatabase(settings.db_path, settings.trading_log_path)
        self.intelligence = InvestmentIntelligenceDatabase(settings.db_path)
        self.benchmark = BenchmarkIntelligenceDatabase(settings.db_path)
        self.orchestrator = InvestmentOrchestrator(db_path=settings.db_path, adapters=self._adapters())
        initialize_foundation_schema(settings.db_path)
        initialize_operational_schema(settings.db_path)
        initialize_multi_broker_schema(settings.db_path)
        self._apply_env_broker_auto_defaults()
        self._initialize_control()

    def reconcile_on_startup(self) -> dict[str, Any]:
        stuck_cutoff = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        stuck_locks = self._rows(
            "SELECT * FROM ORDER_INTENT_LOCKS WHERE status = 'locked' AND created_at < ?",
            (stuck_cutoff,),
        )
        open_exits = self._rows("SELECT * FROM MANAGED_TRADE_EXITS WHERE status = 'open'")
        summary = {
            "stuck_order_intents": len(stuck_locks),
            "open_managed_exits": len(open_exits),
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

    def run_crypto_analysis(self, symbols: list[str] | None = None) -> dict[str, Any]:
        started_at = utc_now_iso()
        adapter = self.orchestrator.adapters.get("kraken")
        if adapter is None or not getattr(adapter, "configured", False):
            return {"status": "not_available", "message": "Kraken credentials are required for crypto analysis."}
        if symbols is None:
            rows = self._rows("SELECT DISTINCT symbol FROM CRYPTO_MASTER WHERE active = 1 LIMIT 30")
            symbols = [row["symbol"] for row in rows]
        if not symbols:
            return {"status": "not_available", "message": "No active symbols in CRYPTO_MASTER yet."}
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
        return {"status": "completed", "symbols": symbols, "proposals": [p.to_dict() for p in proposals], "auto_execution": auto_execution}

    def get(self, path: str, query: dict[str, list[str]]) -> tuple[int, dict[str, Any]]:
        if path == "/healthz":
            return 200, {"status": "ok", "generated_at": utc_now_iso()}
        if path == "/status":
            return 200, self.status()
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
            return 200, self.run_crypto_analysis(symbols)
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
        executive_summary = self.executive_summary()
        policy = load_trading_policy(self.settings.db_path, auto_trade=self.settings.auto_trade, guardrails=self.settings.guardrails)
        brokers = self.broker_panels()
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
            "last_orchestrator_decision": latest_decision,
            "morning_brief": latest_morning,
            "evening_brief": latest_evening,
            "cloud_api_health": "Available",
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
            broker = self._broker()
            account = broker.get_account()
            positions = broker.get_positions()
            orders = broker.get_orders(status="all", limit=10)
            activities = broker.get_activities("FILL")
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
                "portfolio_value": display_value(snapshot["portfolio_value"], "Alpaca returned no portfolio value"),
                "cash_available": display_value(snapshot["cash"], "Alpaca returned no cash balance"),
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
                "open_positions_summary": f"{len(positions)}" if positions else "Not available - Alpaca returned no open positions",
                "recent_orders": orders[:10] if isinstance(orders, list) else [],
                "recent_activities": activities[:10] if isinstance(activities, list) else [],
                "executive_summary": self.executive_summary(),
                "source": "Alpaca Paper Trading",
            }
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
            due_diligence = latest_due_diligence(self.settings.db_path, row["proposal_id"])
            investment_score = latest_investment_score(self.settings.db_path, row["proposal_id"])
            auto_trade_eligible = (
                guardrails_passed
                and freshness["status"] != "Expired"
                and confidence >= self.settings.auto_trade.min_confidence
                and philosophy_fit >= self.settings.auto_trade.min_philosophy_fit
                and not already_executed
                and self.settings.auto_trade.enabled
            )
            recommendations.append(
                {
                    "proposal_id": row["proposal_id"],
                    "company": row["company_name"],
                    "ticker": row["symbol"],
                    "sector": row["sector"],
                    "country": row["country"],
                    "confidence": confidence if confidence else None,
                    "investment_score": _score_payload(investment_score, confidence, philosophy_fit),
                    "asset_available": None if decision is None else bool(decision["asset_available"]),
                    "suggested_broker": None if decision is None else decision["selected_broker"],
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
                        auto_enabled=self.settings.auto_trade.enabled,
                        min_confidence=self.settings.auto_trade.min_confidence,
                        min_philosophy_fit=self.settings.auto_trade.min_philosophy_fit,
                        freshness_status=freshness["status"],
                        guardrails_passed=guardrails_passed,
                        already_executed=already_executed,
                        guardrail_failures=guardrail_failures,
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
            update_broker_runtime(self.settings.db_path, broker_name, research_status="idle", due_diligence_status="idle", current_stage="complete")
            return result
        if not self.settings.has_alpaca_credentials:
            result = {"status": "not_available", "message": "Alpaca paper credentials are required for market data analysis.", "symbols": symbols}
            self._record_research_from_result(started_at, result, symbols, trigger_type)
            update_broker_runtime(self.settings.db_path, broker_name, research_status="idle", due_diligence_status="blocked", current_stage="credentials", details={"last_error": result["message"]})
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
        return result

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
            return {"status": "rejected", "message": "Proposal not found in SQLite."}
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
        context = OrchestratorContext(
            account=self._account_context_for_broker(broker_name),
            auto_trade=self._manual_approval_auto_config(broker_name),
            guardrails=self.settings.guardrails,
        )
        decision = self.orchestrator.evaluate_recommendation(proposal, context, auto_execute=True)
        if decision.decision == "approved":
            self.portfolio(broker_name)
        return {
            "status": "submitted" if decision.decision == "approved" else decision.decision,
            "result": decision.to_dict(),
            "amount_requested": body.get("amount"),
        }

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
            context = OrchestratorContext(
                account=self._account_context_for_broker(broker_name),
                auto_trade=self._auto_config_for_broker(broker_name),
                guardrails=self.settings.guardrails,
            )
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
                "message": "No eligible paper recommendations over 85%. See skipped reasons.",
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

    def set_broker_auto_trading(self, body: dict[str, Any]) -> dict[str, Any]:
        broker = str(body.get("broker") or "").lower()
        if not broker:
            return {"status": "rejected", "message": "broker is required."}
        enabled = bool(body.get("enabled"))
        result = set_broker_auto_trading(self.settings.db_path, broker, enabled)
        update_broker_runtime(
            self.settings.db_path,
            broker,
            research_status="running" if enabled else "idle",
            current_stage="auto_trading_enabled" if enabled else "auto_trading_disabled",
            research_freshness="Fresh" if enabled else None,
        )
        return {"status": "updated", **result}

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
                continue
            new_rows = record_broker_trade_history(self.settings.db_path, broker_name, list(orders) + list(history))
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
            results[broker_name] = {"orders": len(orders), "history": len(history), "new_records": len(new_rows)}
        return results

    def broker_panels(self) -> list[dict[str, Any]]:
        panels = []
        settings = broker_auto_settings(self.settings.db_path)
        for broker in ["alpaca", "kraken", "coinbase", "binance", "interactive_brokers"]:
            runtime = {**update_broker_runtime(self.settings.db_path, broker).to_dict()}
            portfolio = self._exchange_portfolio(broker) if broker != "alpaca" else self._alpaca_panel_portfolio()
            counts = today_runtime_counts(self.settings.db_path, broker)
            panels.append({
                "broker": broker,
                "label": _broker_label(broker),
                "connection_status": portfolio.get("connection_status") or runtime.get("connection_status"),
                "portfolio_value": portfolio.get("portfolio_value"),
                "cash_available": portfolio.get("cash_available"),
                "buying_power": portfolio.get("buying_power"),
                "open_positions": portfolio.get("open_positions_summary"),
                "todays_pnl": portfolio.get("todays_pnl"),
                "week_pnl": portfolio.get("week_pnl"),
                "month_pnl": portfolio.get("month_pnl"),
                "trades_today": counts["trades_today"],
                "research_status": runtime.get("research_status"),
                "due_diligence_status": runtime.get("due_diligence_status"),
                "auto_trading_enabled": settings.get(broker, False),
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
                "trade_history": latest_broker_trades(self.settings.db_path, broker, limit=10),
                "source": portfolio.get("source"),
            })
        return panels

    def _adapters(self):
        adapters = []
        if self.settings.has_alpaca_credentials:
            adapters.append(AlpacaBrokerAdapter(self._broker()))
        adapters.extend([InteractiveBrokersAdapter(), SaxoAdapter(), KrakenAdapter(), CoinbaseAdapter()])
        return adapters

    def _active_broker_names(self) -> list[str]:
        return [name for name, adapter in self.orchestrator.adapters.items() if adapter.get_supported_assets()]

    def executive_summary(self) -> list[dict[str, Any]]:
        alpaca = self._latest_snapshot_summary("alpaca", "Alpaca")
        summaries = [alpaca or {"broker": "Alpaca", "status": "Not configured" if not self.settings.has_alpaca_credentials else "Not available - no portfolio snapshots yet"}]
        for broker in ["kraken", "coinbase", "binance", "interactive_brokers"]:
            portfolio = self._exchange_portfolio(broker)
            summaries.append({
                "broker": _broker_label(broker),
                "portfolio_balance": portfolio.get("portfolio_value"),
                "cash_balance": portfolio.get("cash_available"),
                "last_day_pnl": portfolio.get("todays_pnl"),
                "last_week_pnl": portfolio.get("week_pnl"),
                "last_month_pnl": portfolio.get("month_pnl"),
                "open_positions": portfolio.get("open_positions_summary"),
                "status": portfolio.get("connection_status") or portfolio.get("source"),
            })
        return summaries

    def _latest_snapshot_summary(self, broker: str, label: str) -> dict[str, Any] | None:
        row = self._row("SELECT * FROM PORTFOLIO_SNAPSHOTS WHERE broker = ? ORDER BY snapshot_id DESC LIMIT 1", (broker,))
        if not row:
            return None
        return {
            "broker": label,
            "portfolio_balance": display_value(row["portfolio_value"], "no portfolio snapshot value"),
            "cash_balance": display_value(row["cash"], "no cash snapshot value"),
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
            "buying_power": (
                balance_summary.get("trading_allocation_gbp")
                if balance_summary
                else cash if cash is not None else "Not available - broker returned no buying power"
            ),
            "todays_pnl": display_value(snapshot["day_pnl"], "no prior snapshot yet"),
            "week_pnl": display_value(snapshot["week_pnl"], "no prior weekly snapshot yet"),
            "month_pnl": display_value(snapshot["month_pnl"], "no month-start snapshot yet"),
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
        row = self._latest_snapshot_summary("alpaca", "Alpaca")
        if not row:
            return {"connection_status": "Connected", "source": "Alpaca Paper Trading"}
        return {
            "connection_status": row.get("status"),
            "portfolio_value": row.get("portfolio_balance"),
            "cash_available": row.get("cash_balance"),
            "buying_power": None,
            "todays_pnl": row.get("last_day_pnl"),
            "week_pnl": row.get("last_week_pnl"),
            "month_pnl": row.get("last_month_pnl"),
            "open_positions_summary": row.get("open_positions"),
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
    hosted_read_only = False
    if not api_token and host not in _LOOPBACK_HOSTS:
        hosted_read_only = True
        logger.warning(
            "Starting hosted API on %s without AI_TRADER_API_TOKEN in read-only mode. "
            "All POST trading/control commands will be rejected until the token is configured.",
            host,
        )
    service = LocalApiService(settings)
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
    min_confidence: float,
    min_philosophy_fit: float,
    freshness_status: str,
    guardrails_passed: bool,
    already_executed: bool,
    guardrail_failures: list[str] | None = None,
) -> str:
    if not auto_enabled:
        return "AUTO_PAPER_TRADING is false; manual approval is required."
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
    return "Eligible for paper auto-trade."


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
    converted_assets: list[dict[str, Any]] = []
    unpriced_assets: list[dict[str, Any]] = []
    for asset, value in raw.items():
        qty = safe_float(value)
        if qty is None or qty == 0:
            continue
        normalized = _kraken_asset_symbol(asset)
        if normalized == "GBP":
            continue
        if normalized in {"USD", "EUR", "USDT", "USDC"}:
            unpriced_assets.append({"asset": asset, "normalized_asset": normalized, "quantity": qty, "reason": "fiat_or_stablecoin_not_converted_to_gbp"})
            continue
        pair = _kraken_pair(normalized)
        price = None
        try:
            price = _kraken_last_price(adapter.current_prices([pair]), pair)
        except Exception:
            price = None
        if price is None:
            unpriced_assets.append({"asset": asset, "normalized_asset": normalized, "quantity": qty, "reason": "gbp_price_unavailable"})
            continue
        value_gbp = qty * price
        total += value_gbp
        converted_assets.append({
            "asset": asset,
            "normalized_asset": normalized,
            "quantity": qty,
            "pair": pair,
            "price_gbp": price,
            "value_gbp": value_gbp,
        })
    trading_allocation = _kraken_trading_allocation_gbp(raw)
    return {
        "total_estimated_gbp": round(total, 2),
        "gbp_cash": round(gbp_cash, 2) if gbp_cash is not None else None,
        "trading_allocation_gbp": round(trading_allocation, 2),
        "raw_balances": raw,
        "converted_assets": converted_assets,
        "unpriced_assets": unpriced_assets,
        "valuation_note": (
            "Portfolio value converts supported crypto balances to GBP using Kraken ticker prices. "
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
