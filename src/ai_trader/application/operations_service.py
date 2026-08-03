from __future__ import annotations

import socket
import sys
from typing import Any, Callable

from ..always_on import operations_health
from ..config import Settings
from ..foundation import load_trading_policy
from ..models import utc_now_iso
from ..multi_broker import (
    active_push_tokens,
    broker_auto_settings,
    list_notifications,
    mark_notifications_read,
    mark_push_sent,
    pending_push_notifications,
    register_push_token,
    send_expo_push,
)
from ..operational import latest_research_run
from ..orchestrator import InvestmentOrchestrator, next_research_run
from ..persistence.query_executor import QueryExecutor
from ..production_evidence import founder_evidence_payload
from ..production_spine import phase5_status
from ..sprint6 import sprint6_status
from .shared_helpers import _int_or_default


def _component(healthy: bool, detail: str) -> dict[str, Any]:
    return {"healthy": healthy, "state": "Healthy" if healthy else "Problem", "detail": detail}


def _port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.25):
            return True
    except OSError:
        return False


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


# Phase 6b (architecture/AI_TRADER_MODULARISATION_ARCHITECTURE_2026-08-02.md): this small
# generic query-param helper is also needed by parts of api/__init__.py's GET/POST route
# dispatch that are out of this phase's scope (44 call sites total across the file), so it
# cannot be imported without a circular import (api/__init__.py imports OperationsService at
# module load time, before its own later-defined functions exist yet). Duplicated verbatim.
# (_int_or_default, previously duplicated alongside this one, was consolidated into
# shared_helpers.py in Phase 9 -- see the import above.)
def _first(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key) or []
    return values[0] if values else None


class OperationsService:
    """Operations/dashboard presentation (architecture/AI_TRADER_MODULARISATION_
    ARCHITECTURE_2026-08-02.md Phase 6b): status, health, activity, notifications, and
    developer dashboards, moved out of LocalApiService. The broker-presentation half of
    Phase 6 (Phase 6a) is a separate, already-extracted BrokerService.

    Thirteen narrow injected dependencies cover cross-references on not-yet-extracted
    LocalApiService state -- `status()` alone touches nearly every other application
    service, since it is the single dashboard aggregator the whole app is built around.
    All are wired as call-time lambdas in LocalApiService.__init__ (not captured bound
    methods), per the pattern every phase from 4 onward established: tests and run_server()
    monkeypatch/reassign instance attributes after construction, which a direct capture
    would not see.
    """

    def __init__(
        self,
        *,
        settings: Settings,
        orchestrator: InvestmentOrchestrator,
        query_executor: QueryExecutor,
        recommendations_lookup: Callable[[int], list[dict[str, Any]]],
        broker_panels_lookup: Callable[[], list[dict[str, Any]]],
        executive_summary_lookup: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
        founder_executive_summary_lookup: Callable[[list[dict[str, Any]], list[dict[str, Any]]], dict[str, Any]],
        connection_readiness_lookup: Callable[[list[dict[str, Any]]], dict[str, Any]],
        founder_experience_payload_lookup: Callable[..., dict[str, Any]],
        world_class_evidence_lookup: Callable[..., dict[str, Any]],
        active_broker_names_lookup: Callable[[], list[str]],
        continuous_research_status_lookup: Callable[[list[dict[str, Any]]], dict[str, Any]],
        due_diligence_status_lookup: Callable[[], str],
        control_state_lookup: Callable[[], dict[str, Any]],
        latest_daily_brief_lookup: Callable[[str], dict[str, Any] | None],
    ) -> None:
        self.settings = settings
        self.orchestrator = orchestrator
        self._query_executor = query_executor
        self._recommendations_lookup = recommendations_lookup
        self._broker_panels_lookup = broker_panels_lookup
        self._executive_summary_lookup = executive_summary_lookup
        self._founder_executive_summary_lookup = founder_executive_summary_lookup
        self._connection_readiness_lookup = connection_readiness_lookup
        self._founder_experience_payload_lookup = founder_experience_payload_lookup
        self._world_class_evidence_lookup = world_class_evidence_lookup
        self._active_broker_names_lookup = active_broker_names_lookup
        self._continuous_research_status_lookup = continuous_research_status_lookup
        self._due_diligence_status_lookup = due_diligence_status_lookup
        self._control_state_lookup = control_state_lookup
        self._latest_daily_brief_lookup = latest_daily_brief_lookup

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

    def status(self) -> dict[str, Any]:
        control = self._control_state_lookup()
        last_trade_analysis = self._query_executor.scalar("SELECT MAX(created_at) FROM trade_audit WHERE event_type IN ('agent_proposal', 'agent_no_trade')")
        last_event_analysis = self._query_executor.scalar("SELECT MAX(created_at) FROM execution_events WHERE event_type IN ('agent_no_trade', 'analysis_completed')")
        last_analysis = max([value for value in [last_trade_analysis, last_event_analysis] if value], default=None)
        last_activity = self._query_executor.rows(
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
        recent_transactions = self._query_executor.rows(
            """
            SELECT created_at, event_type, proposal_id, symbol, side, position_size,
                   ai_confidence, execution_result
            FROM trade_audit
            WHERE event_type IN ('execution_approved', 'execution_rejected', 'agent_proposal', 'agent_no_trade')
            ORDER BY id DESC
            LIMIT 10
            """
        )
        recommendation_rows = self._recommendations_lookup(50)
        active_recommendations = [row for row in recommendation_rows if row["freshness_status"] != "Expired"]
        latest_decision = self.orchestrator.latest_decision()
        latest_morning = self._latest_daily_brief_lookup("morning")
        latest_evening = self._latest_daily_brief_lookup("evening")
        research_run = latest_research_run(self.settings.db_path)
        policy = load_trading_policy(self.settings.db_path, auto_trade=self.settings.auto_trade, guardrails=self.settings.guardrails)
        brokers = self._broker_panels_lookup()
        executive_summary = self._executive_summary_lookup(brokers)
        founder_summary = self._founder_executive_summary_lookup(brokers, executive_summary)
        readiness = self._connection_readiness_lookup(brokers)
        founder_experience = self._founder_experience_payload_lookup(brokers, recommendation_rows, policy, research_run)
        world_class = self._world_class_evidence_lookup(brokers=brokers, recommendations=recommendation_rows)
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
            "selected_active_brokers": self._active_broker_names_lookup(),
            "brokers": brokers,
            "continuous_research": self._continuous_research_status_lookup(brokers),
            "next_scheduled_research_run": (research_run or {}).get("next_scheduled_run") or next_research_run(),
            "last_research_run": research_run,
            "research_status": _research_status(research_run),
            "due_diligence_status": self._due_diligence_status_lookup(),
            "research_assets_reviewed": _research_assets_reviewed(research_run),
            "crypto_projects_reviewed": self._query_executor.count("CRYPTO_MASTER", "active = 1"),
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
            for row in self._query_executor.rows(
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
            for row in self._query_executor.rows(
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

    def developer_status(self) -> dict[str, Any]:
        watchlist_count = self._query_executor.count("INVESTMENT_WATCHLIST", "active = 1")
        theme_count = self._query_executor.count("MARKET_THEMES")
        benchmark_count = self._query_executor.count("BENCHMARK_TRADERS", "active = 1")
        journal_count = self._query_executor.count("trade_audit")
        founder = self._query_executor.row("SELECT briefing_date, created_at FROM daily_briefings ORDER BY id DESC LIMIT 1")
        control = self._control_state_lookup()
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
