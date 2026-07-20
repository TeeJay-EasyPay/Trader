from __future__ import annotations

import json
import sqlite3
from .database import connect
from collections import Counter
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .always_on import (
    list_job_runs,
    list_research_funnels,
    list_worker_heartbeats,
    operations_health,
)
from .models import utc_now_iso


PERIODS = {
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}

IMPORTANT_SEVERITIES = {"warning", "blocked", "failure", "failed", "error", "incident", "recovered"}


def autonomous_activity_payload(
    db_path: Path,
    *,
    period: str = "24h",
    category: str = "all",
    severity: str = "all",
    important_only: bool = False,
    founder_action_required: bool = False,
    limit: int = 100,
    broker_panels: list[dict[str, Any]] | None = None,
    database_backend: str = "sqlite",
) -> dict[str, Any]:
    window = activity_window(period)
    events = activity_timeline(
        db_path,
        period=period,
        category=category,
        severity=severity,
        important_only=important_only,
        founder_action_required=founder_action_required,
        limit=limit,
        include_all_events=True,
    )
    status = current_autonomous_status(db_path, period=period, broker_panels=broker_panels, database_backend=database_backend)
    summary = activity_summary(db_path, period=period)
    no_trade = why_no_trade_funnel(db_path, period=period)
    brokers = broker_activity(db_path, period=period, broker_panels=broker_panels)
    attention = founder_attention(db_path, period=period, broker_panels=broker_panels)
    all_events = events.pop("all_events", [])
    latest = latest_completed_actions(all_events)
    events["source_event_count"] = len(all_events)
    return {
        "generated_at": utc_now_iso(),
        "period": period,
        "period_start": window["start"].isoformat(),
        "period_end": window["end"].isoformat(),
        "status": status,
        "summary": summary,
        "timeline": events,
        "why_no_trade": no_trade,
        "broker_activity": brokers,
        "founder_attention": attention,
        "latest_completed_actions": latest,
        "truthfulness": {
            "source": "persisted application records",
            "mock_data_used": False,
            "synthetic_activity_used": False,
            "note": "If a source table has no rows, the Activity screen shows that absence instead of inventing events.",
        },
    }


def current_autonomous_status(
    db_path: Path,
    *,
    period: str = "24h",
    broker_panels: list[dict[str, Any]] | None = None,
    database_backend: str = "sqlite",
) -> dict[str, Any]:
    health = operations_health(db_path)
    window = activity_window(period)
    all_events = _all_activity_events(db_path, window["start"], window["end"])
    latest_meaningful = _latest_meaningful_activity(all_events)
    unresolved = founder_attention(db_path, period=period, broker_panels=broker_panels)
    worker_health = health.get("worker_health") or "not_proven"
    scheduler_state = "active" if any(_timestamp(row.get("started_at") or row.get("scheduled_for")) for row in health.get("last_job_runs") or []) else "not_proven"
    last_research = _latest_event_time(all_events, {"Research"})
    last_broker_poll = _latest_job_time(health.get("last_job_runs") or [], "broker-poll")
    last_report = _latest_event_time(all_events, {"Reports"})
    database_status = (health.get("database_backend") or {}).get("active_backend") or database_backend

    if worker_health != "healthy":
        state = "NOT OPERATING"
        reason = "AI Trader is not operating normally. No healthy background-worker heartbeat is currently proven."
    elif unresolved["items"]:
        state = "OPERATING WITH WARNINGS"
        reason = f"AI Trader is operating, but {len(unresolved['items'])} item(s) need attention."
    elif not all_events:
        state = "STATUS UNKNOWN"
        reason = "No autonomous activity has been recorded in the selected period."
    else:
        state = "OPERATING NORMALLY"
        reason = "AI Trader is operating. Worker heartbeats and persisted activity are visible."

    return {
        "state": state,
        "plain_english": reason,
        "last_meaningful_activity": latest_meaningful,
        "worker_status": worker_health,
        "scheduler_status": scheduler_state,
        "database_status": database_status,
        "database_durability": health.get("database_durability"),
        "last_successful_research_run": last_research,
        "last_broker_poll": last_broker_poll,
        "last_report_generated": last_report,
        "unresolved_incident_count": len(unresolved["items"]),
    }


def activity_summary(db_path: Path, *, period: str = "24h") -> dict[str, Any]:
    window = activity_window(period)
    jobs = _period_rows(list_job_runs(db_path, limit=500), window, "started_at", fallback_key="scheduled_for")
    funnels = _period_rows(list_research_funnels(db_path, limit=500), window, "created_at")
    events = _period_rows(_sqlite_rows(db_path, "OPERATIONAL_EVENTS", "created_at", 500), window, "created_at")
    incidents = _period_rows(_sqlite_rows(db_path, "INCIDENT_LIFECYCLE", "last_observed_at", 500), window, "last_observed_at")
    decisions = _period_rows(_sqlite_rows(db_path, "DECISION_JOURNAL", "created_at", 500), window, "created_at")
    pm_decisions = _period_rows(_sqlite_rows(db_path, "PORTFOLIO_MANAGER_DECISIONS", "created_at", 500), window, "created_at")
    reports = _period_rows(_sqlite_rows(db_path, "FOUNDER_OPERATIONAL_REPORTS", "created_at", 200), window, "created_at")
    reports += _period_rows(_sqlite_rows(db_path, "TRADING_REPORTS", "created_at", 200), window, "created_at")
    broker_trades = _period_rows(_sqlite_rows(db_path, "BROKER_TRADE_HISTORY", "updated_at", 500), window, "updated_at")

    risk_rejections = _count_decisions(decisions, "risk", {"rejected", "blocked"})
    portfolio_rejections = _count_portfolio(pm_decisions, {"reject", "rejected", "wait", "manual_review"})
    portfolio_approvals = _count_portfolio(pm_decisions, {"approve", "approved", "approve_smaller"})
    submitted = _sum_int(jobs, "paper_orders_submitted") + len([row for row in broker_trades if _lower(row.get("status")) in {"submitted", "accepted", "new"}])
    filled = _sum_int(jobs, "paper_orders_filled") + len([row for row in broker_trades if "filled" in _lower(row.get("status"))])
    closed = len([row for row in broker_trades if _lower(row.get("status")) in {"closed", "target_exit", "stop_exit", "manual_exit"}])
    incidents_opened = len([row for row in incidents if _lower(row.get("status")) not in {"resolved", "closed"}])
    incidents_resolved = len([row for row in incidents if _lower(row.get("status")) in {"resolved", "closed"}])

    return {
        "research": {
            "runs": len([job for job in jobs if _job_category(job.get("job_name")) == "Research"]),
            "assets_analysed": max(_sum_int(funnels, "symbols_examined"), _sum_int(jobs, "assets_processed")),
            "candidates": _sum_int(funnels, "interesting_ideas") + _sum_int(funnels, "valid_strategies"),
            "recommendations_created": _sum_int(jobs, "recommendations_created"),
        },
        "decisions": {
            "portfolio_manager_approvals": portfolio_approvals,
            "portfolio_manager_rejections": portfolio_rejections,
            "risk_engine_approvals": _count_decisions(decisions, "risk", {"approved", "approve"}),
            "risk_engine_rejections": risk_rejections,
            "sentinel_blocks": _count_event_types(events, {"sentinel_block", "production_risk_block"}),
        },
        "execution": {
            "orders_submitted": submitted,
            "orders_rejected": _sum_int(funnels, "rejected") + _count_event_types(events, {"order_rejected", "execution_rejected"}),
            "orders_filled": filled,
            "trades_closed": closed,
        },
        "operations": {
            "broker_polls": len([job for job in jobs if _lower(job.get("job_name")) == "broker-poll"]),
            "learning_reviews_completed": len([job for job in jobs if _lower(job.get("job_name")) == "daily-learning" and _lower(job.get("status")).startswith("completed")]),
            "reports_generated": len(reports),
            "incidents_opened": incidents_opened,
            "incidents_resolved": incidents_resolved,
        },
        "raw_evidence_counts": {
            "job_runs": len(jobs),
            "research_funnels": len(funnels),
            "operational_events": len(events),
            "decision_journal": len(decisions),
            "broker_trade_rows": len(broker_trades),
            "reports": len(reports),
        },
    }


def activity_timeline(
    db_path: Path,
    *,
    period: str = "24h",
    category: str = "all",
    severity: str = "all",
    important_only: bool = False,
    founder_action_required: bool = False,
    limit: int = 100,
    include_all_events: bool = False,
) -> dict[str, Any]:
    window = activity_window(period)
    events = _all_activity_events(db_path, window["start"], window["end"])
    filtered = [
        event for event in events
        if _matches_filters(event, category=category, severity=severity, important_only=important_only, founder_action_required=founder_action_required)
    ]
    filtered.sort(key=lambda item: (item["timestamp"] or "", item["activity_id"]), reverse=True)
    payload = {
        "items": filtered[: max(1, int(limit))],
        "total": len(filtered),
        "returned": min(len(filtered), max(1, int(limit))),
        "source_event_count": len(events),
        "filters": {
            "period": period,
            "category": category,
            "severity": severity,
            "important_only": important_only,
            "founder_action_required": founder_action_required,
        },
        "empty_state": _timeline_empty_state(events, filtered, period),
    }
    if include_all_events:
        payload["all_events"] = events
    return payload


def why_no_trade_funnel(db_path: Path, *, period: str = "24h") -> dict[str, Any]:
    window = activity_window(period)
    funnels = _period_rows(list_research_funnels(db_path, limit=500), window, "created_at")
    jobs = _period_rows(list_job_runs(db_path, limit=500), window, "started_at", fallback_key="scheduled_for")
    broker_rows = _period_rows(_sqlite_rows(db_path, "BROKER_TRADE_HISTORY", "updated_at", 500), window, "updated_at")
    submitted = _sum_int(funnels, "submitted") + _sum_int(jobs, "paper_orders_submitted")
    filled = _sum_int(funnels, "filled") + _sum_int(jobs, "paper_orders_filled")
    completed = len([row for row in broker_rows if _lower(row.get("status")) in {"closed", "target_exit", "stop_exit", "manual_exit"}])
    assets = _sum_int(funnels, "symbols_examined")
    candidates = _sum_int(funnels, "interesting_ideas")
    valid = _sum_int(funnels, "valid_strategies")
    eligible = _sum_int(funnels, "eligible_for_paper_execution")
    reasons = Counter()
    for row in funnels:
        primary = row.get("primary_reason")
        if primary:
            reasons[str(primary)] += 1
        for reason in _json_list(row.get("secondary_reasons_json")):
            reasons[str(reason)] += 1
    for row in jobs:
        if row.get("failure_reason"):
            reasons[str(row["failure_reason"])] += 1
        if _lower(row.get("status")).startswith("blocked"):
            reasons[_lower(row.get("status"))] += 1

    if submitted or filled or completed:
        state = "order_submitted_or_trade_completed"
        conclusion = "At least one order or completed trade is recorded in the selected period."
    elif not funnels:
        state = "research_did_not_run"
        conclusion = "No trades were placed because no research funnel was recorded in the selected period."
    elif candidates <= 0:
        state = "no_opportunity_found"
        conclusion = f"AI Trader reviewed {assets} asset(s), but no opportunity progressed to a candidate."
    elif valid <= 0:
        state = "opportunity_found_but_rejected"
        conclusion = "AI Trader found possible opportunities, but none became a valid strategy setup."
    elif eligible <= 0:
        state = "approved_or_candidate_blocked"
        conclusion = "Opportunities reached later review stages, but none passed every execution gate."
    else:
        state = "approved_but_not_submitted"
        conclusion = "At least one opportunity appears eligible, but no submitted order was recorded. Review execution settings and broker permissions."

    return {
        "state": state,
        "conclusion": conclusion,
        "counts": {
            "assets_analysed": assets,
            "adequate_data": _sum_int(funnels, "symbols_with_adequate_data"),
            "interesting_ideas": candidates,
            "valid_strategies": valid,
            "committee_approved": _sum_int(funnels, "committee_approved"),
            "portfolio_approved": _sum_int(funnels, "portfolio_approved"),
            "guardrail_approved": _sum_int(funnels, "guardrail_approved"),
            "eligible_for_paper_execution": eligible,
            "orders_submitted": submitted,
            "orders_filled": filled,
            "trades_closed": completed,
            "rejected": _sum_int(funnels, "rejected"),
            "expired": _sum_int(funnels, "expired"),
        },
        "top_reasons": [{"reason": reason, "count": count} for reason, count in reasons.most_common(8)],
    }


def broker_activity(
    db_path: Path,
    *,
    period: str = "24h",
    broker_panels: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    window = activity_window(period)
    jobs = _period_rows(list_job_runs(db_path, limit=500), window, "started_at", fallback_key="scheduled_for")
    broker_rows = _period_rows(_sqlite_rows(db_path, "BROKER_TRADE_HISTORY", "updated_at", 500), window, "updated_at")
    panels_by_broker = {str(panel.get("broker") or "").lower(): panel for panel in broker_panels or []}
    results = []
    for broker in ["alpaca", "kraken"]:
        panel = panels_by_broker.get(broker, {})
        rows = [row for row in broker_rows if _lower(row.get("broker")) == broker]
        broker_jobs = [row for row in jobs if _lower(row.get("job_name")) == "broker-poll"]
        latest_error = _latest_error_for_broker(rows, broker_jobs, broker)
        last_submission = _latest_trade_time(rows, statuses={"submitted", "accepted", "new", "filled", "partially_filled"})
        last_fill = _latest_trade_time([row for row in rows if "filled" in _lower(row.get("status"))])
        results.append({
            "broker": broker,
            "label": panel.get("label") or broker.title(),
            "connection_status": panel.get("connection_status") or "Not available - broker panel evidence is not present in this payload.",
            "account_mode": _broker_mode(broker, panel),
            "last_successful_poll": _latest_completed_job_time(broker_jobs),
            "polling_freshness": _freshness_label(_latest_completed_job_time(broker_jobs), minutes=10),
            "autonomous_execution": "Enabled" if panel.get("auto_trading_enabled") else "Disabled",
            "orders_submitted": len([row for row in rows if _lower(row.get("status")) in {"submitted", "accepted", "new"}]) + _sum_int(broker_jobs, "paper_orders_submitted"),
            "fills_received": len([row for row in rows if "filled" in _lower(row.get("status"))]) + _sum_int(broker_jobs, "paper_orders_filled"),
            "open_positions": panel.get("open_positions"),
            "reconciliation_status": panel.get("reconciliation_status") or "Not available - no broker reconciliation summary was returned for this broker.",
            "latest_broker_error": latest_error,
            "current_blocker": _broker_blocker(broker, panel, latest_error),
            "last_order_submission": last_submission,
            "last_fill": last_fill,
            "last_no_trade_reason": _latest_no_trade_reason(db_path, broker),
        })
    return {"brokers": results}


def founder_attention(
    db_path: Path,
    *,
    period: str = "24h",
    broker_panels: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    health = operations_health(db_path)
    items: list[dict[str, Any]] = []
    if health.get("worker_health") != "healthy":
        items.append(_attention("Worker heartbeat stale", "Background research, broker polling and managed exits may not be running.", "Check the Render background worker logs and restart the worker if needed.", "System", "failure"))
    if (health.get("database_backend") or {}).get("active_backend") != "postgres":
        items.append(_attention("Durable database not proven", "API and worker may not be sharing the same production truth.", "Confirm DATABASE_URL and AI_TRADER_DATABASE_BACKEND=postgres on every Render service.", "System", "warning"))
    for broker in broker_panels or []:
        name = str(broker.get("broker") or "broker").lower()
        connection = _lower(broker.get("connection_status"))
        if name in {"alpaca", "kraken"} and "connected" not in connection:
            items.append(_attention(f"{name.title()} connection requires attention", f"{name.title()} is not reporting a connected state.", "Check broker credentials and Render environment variables.", "Brokers", "warning", broker=name))
        if name == "alpaca" and not broker.get("auto_trading_enabled"):
            items.append(_attention("Alpaca paper auto-trading disabled", "Alpaca may research but will not submit new paper orders automatically.", "Enable Alpaca auto-trading only if you want paper orders submitted after all gates pass.", "Execution", "info", broker=name))
    for incident in _sqlite_rows(db_path, "INCIDENT_LIFECYCLE", "last_observed_at", 100):
        if _lower(incident.get("status")) not in {"resolved", "closed"}:
            items.append({
                "title": incident.get("explanation") or incident.get("incident_key") or "Open incident",
                "impact": incident.get("affected_entity") or "Operational issue is unresolved.",
                "began_at": incident.get("first_detected_at"),
                "recommended_action": incident.get("recommended_action") or "Review the incident evidence.",
                "component": incident.get("component") or "System",
                "severity": incident.get("severity") or "warning",
                "broker": None,
                "navigation_target": {"screen": "Activity", "source_table": "INCIDENT_LIFECYCLE", "source_record_id": incident.get("incident_key")},
            })
    return {
        "items": items,
        "plain_english": "No Founder action is currently required." if not items else f"{len(items)} item(s) require Founder attention.",
    }


def activity_window(period: str) -> dict[str, datetime]:
    end = datetime.now(timezone.utc)
    delta = PERIODS.get(period, PERIODS["24h"])
    return {"start": end - delta, "end": end}


def _all_activity_events(db_path: Path, start: datetime, end: datetime) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for row in _period_rows(list_job_runs(db_path, limit=500), {"start": start, "end": end}, "started_at", fallback_key="scheduled_for"):
        events.append(_job_event(row))
    for row in _period_rows(list_research_funnels(db_path, limit=500), {"start": start, "end": end}, "created_at"):
        events.append(_research_funnel_event(row))
    for row in _period_rows(_sqlite_rows(db_path, "OPERATIONAL_EVENTS", "created_at", 500), {"start": start, "end": end}, "created_at"):
        events.append(_operational_event(row))
    for row in _period_rows(_sqlite_rows(db_path, "DECISION_JOURNAL", "created_at", 500), {"start": start, "end": end}, "created_at"):
        events.append(_decision_event(row))
    for row in _period_rows(_sqlite_rows(db_path, "PORTFOLIO_MANAGER_DECISIONS", "created_at", 500), {"start": start, "end": end}, "created_at"):
        events.append(_portfolio_event(row))
    for row in _period_rows(_sqlite_rows(db_path, "BROKER_TRADE_HISTORY", "updated_at", 500), {"start": start, "end": end}, "updated_at"):
        events.append(_broker_trade_event(row))
    for row in _period_rows(_sqlite_rows(db_path, "CANONICAL_RECONCILIATION_CASES", "created_at", 500), {"start": start, "end": end}, "created_at"):
        events.append(_reconciliation_event(row))
    for row in _period_rows(_sqlite_rows(db_path, "CLOSED_LOOP_LEARNING_RUNS", "created_at", 500), {"start": start, "end": end}, "created_at"):
        events.append(_learning_event(row))
    for row in _period_rows(_sqlite_rows(db_path, "FOUNDER_OPERATIONAL_REPORTS", "created_at", 200), {"start": start, "end": end}, "created_at"):
        events.append(_report_event(row, "FOUNDER_OPERATIONAL_REPORTS"))
    for row in _period_rows(_sqlite_rows(db_path, "TRADING_REPORTS", "created_at", 200), {"start": start, "end": end}, "created_at"):
        events.append(_report_event(row, "TRADING_REPORTS"))
    for row in _period_rows(_sqlite_rows(db_path, "INCIDENT_LIFECYCLE", "last_observed_at", 200), {"start": start, "end": end}, "last_observed_at"):
        events.append(_incident_event(row))
    events = [event for event in events if event.get("timestamp")]
    events.sort(key=lambda item: (item["timestamp"], item["activity_id"]), reverse=True)
    return events


def _base_event(
    *,
    activity_id: str,
    event_type: str,
    category: str,
    source_table: str,
    source_record_id: Any,
    timestamp: Any,
    title: str,
    summary: str,
    outcome: str,
    severity: str,
    component: str,
    detailed_reason: str | None = None,
    broker: str | None = None,
    symbol: str | None = None,
    strategy: str | None = None,
    recommendation_id: str | None = None,
    order_id: str | None = None,
    trade_id: str | None = None,
    incident_id: str | None = None,
    founder_action_required: bool = False,
    raw_evidence_available: bool = True,
) -> dict[str, Any]:
    return {
        "activity_id": activity_id,
        "event_type": event_type,
        "event_category": category,
        "source_table": source_table,
        "source_record_id": source_record_id,
        "timestamp": _iso(timestamp),
        "title": title,
        "summary": summary,
        "detailed_reason": detailed_reason or summary,
        "outcome": outcome,
        "severity": severity,
        "component": component,
        "asset_or_symbol": symbol,
        "broker": broker,
        "strategy": strategy,
        "recommendation_id": recommendation_id,
        "order_id": order_id,
        "trade_id": trade_id,
        "incident_id": incident_id,
        "founder_action_required": bool(founder_action_required),
        "navigation_target": {
            "screen": "Operational Truth",
            "source_table": source_table,
            "source_record_id": source_record_id,
        },
        "raw_evidence_available": raw_evidence_available,
    }


def _job_event(row: dict[str, Any]) -> dict[str, Any]:
    status = _lower(row.get("status"))
    category = _job_category(row.get("job_name"))
    severity = "success" if status.startswith("completed") else "blocked" if status.startswith("blocked") else "failure" if status in {"failed", "timed_out"} else "information"
    processed = _as_int(row.get("assets_processed"))
    recs = _as_int(row.get("recommendations_created"))
    submitted = _as_int(row.get("paper_orders_submitted"))
    fills = _as_int(row.get("paper_orders_filled"))
    summary = _job_summary(row.get("job_name"), processed, recs, submitted, fills, row.get("failure_reason"))
    return _base_event(
        activity_id=f"job:{row.get('job_run_id')}",
        event_type=str(row.get("job_name") or "scheduled-job"),
        category=category,
        source_table="SCHEDULED_JOB_RUNS",
        source_record_id=row.get("job_run_id"),
        timestamp=row.get("completed_at") or row.get("started_at") or row.get("scheduled_for"),
        title=f"{_title(row.get('job_name'))} {row.get('status')}",
        summary=summary,
        detailed_reason=row.get("failure_reason") or summary,
        outcome=str(row.get("status") or "unknown"),
        severity=severity,
        component="Scheduler",
        founder_action_required=severity in {"blocked", "failure"},
    )


def _research_funnel_event(row: dict[str, Any]) -> dict[str, Any]:
    submitted = _as_int(row.get("submitted"))
    eligible = _as_int(row.get("eligible_for_paper_execution"))
    rejected = _as_int(row.get("rejected"))
    severity = "success" if submitted else "blocked" if eligible and not submitted else "information"
    summary = (
        f"{_as_int(row.get('symbols_examined'))} assets analysed; "
        f"{_as_int(row.get('interesting_ideas'))} candidate(s); "
        f"{eligible} execution-eligible; {submitted} submitted."
    )
    if rejected and row.get("primary_reason"):
        summary += f" Main rejection reason: {row.get('primary_reason')}."
    return _base_event(
        activity_id=f"research-funnel:{row.get('funnel_id')}",
        event_type="research_funnel",
        category="Research",
        source_table="RESEARCH_FUNNELS",
        source_record_id=row.get("funnel_id"),
        timestamp=row.get("created_at"),
        title=f"{_title(row.get('broker'))} research funnel recorded",
        summary=summary,
        detailed_reason=row.get("primary_reason") or summary,
        outcome="submitted" if submitted else "eligible_not_submitted" if eligible else "no_submission",
        severity=severity,
        component="Research",
        broker=row.get("broker"),
    )


def _operational_event(row: dict[str, Any]) -> dict[str, Any]:
    severity = _normal_severity(row.get("severity"), row.get("success"))
    return _base_event(
        activity_id=f"operational-event:{row.get('event_id')}",
        event_type=str(row.get("event_type") or "operational_event"),
        category=_category_for_component(row.get("component"), row.get("event_type")),
        source_table="OPERATIONAL_EVENTS",
        source_record_id=row.get("event_id"),
        timestamp=row.get("created_at"),
        title=row.get("summary") or _title(row.get("event_type")),
        summary=row.get("summary") or "Operational event recorded.",
        detailed_reason=_json_reason(row.get("details_json")) or row.get("summary"),
        outcome="success" if row.get("success") else "failure",
        severity=severity,
        component=row.get("component") or "System",
        broker=row.get("broker"),
        recommendation_id=row.get("proposal_id"),
        trade_id=row.get("logical_trade_id"),
        founder_action_required=severity in {"warning", "blocked", "failure"},
    )


def _decision_event(row: dict[str, Any]) -> dict[str, Any]:
    decision = _lower(row.get("final_decision"))
    severity = "success" if decision in {"approved", "approve"} else "blocked" if decision else "information"
    summary = f"{row.get('symbol')} decision: {row.get('final_decision')}. Execution eligibility: {row.get('execution_eligibility')}."
    return _base_event(
        activity_id=f"decision:{row.get('decision_id')}",
        event_type="decision_journal",
        category="Decisions",
        source_table="DECISION_JOURNAL",
        source_record_id=row.get("decision_id"),
        timestamp=row.get("created_at"),
        title=f"{row.get('symbol')} governance decision",
        summary=summary,
        detailed_reason=row.get("evidence_against") if severity == "blocked" else row.get("evidence_for"),
        outcome=row.get("final_decision") or "unknown",
        severity=severity,
        component="Decision Journal",
        broker=row.get("broker"),
        symbol=row.get("symbol"),
        strategy=row.get("strategy_id"),
        recommendation_id=row.get("proposal_id"),
    )


def _portfolio_event(row: dict[str, Any]) -> dict[str, Any]:
    decision = _lower(row.get("decision"))
    severity = "success" if decision in {"approve", "approved", "approve_smaller"} else "blocked"
    return _base_event(
        activity_id=f"portfolio-manager:{row.get('portfolio_decision_id')}",
        event_type="portfolio_manager_decision",
        category="Decisions",
        source_table="PORTFOLIO_MANAGER_DECISIONS",
        source_record_id=row.get("portfolio_decision_id"),
        timestamp=row.get("created_at"),
        title=f"{row.get('symbol')} Portfolio Manager {row.get('decision')}",
        summary=row.get("reason") or "Portfolio Manager decision recorded.",
        outcome=row.get("decision") or "unknown",
        severity=severity,
        component="Portfolio Manager",
        broker=row.get("broker"),
        symbol=row.get("symbol"),
        recommendation_id=row.get("proposal_id"),
    )


def _broker_trade_event(row: dict[str, Any]) -> dict[str, Any]:
    status = _lower(row.get("status"))
    side = _lower(row.get("side")) or "trade"
    severity = "success" if "filled" in status or status == "closed" else "blocked" if "reject" in status or "cancel" in status else "information"
    price = row.get("price")
    qty = row.get("quantity")
    symbol = row.get("symbol")
    title = f"{_title(row.get('broker'))} {side.upper()} {symbol or 'unknown'} {row.get('status')}"
    summary = f"{side.upper()} {qty or 'unknown quantity'} {symbol or 'unknown symbol'}"
    if price not in {None, ""}:
        summary += f" at {price}"
    return _base_event(
        activity_id=f"broker-trade:{row.get('trade_history_id')}",
        event_type="broker_trade",
        category="Execution" if "filled" in status or status in {"submitted", "accepted", "new"} else "Brokers",
        source_table="BROKER_TRADE_HISTORY",
        source_record_id=row.get("trade_history_id"),
        timestamp=row.get("updated_at") or row.get("closed_at") or row.get("opened_at"),
        title=title,
        summary=summary,
        outcome=row.get("status") or "unknown",
        severity=severity,
        component="Broker",
        broker=row.get("broker"),
        symbol=symbol,
        order_id=row.get("external_id"),
        trade_id=row.get("external_id"),
    )


def _reconciliation_event(row: dict[str, Any]) -> dict[str, Any]:
    severity = "success" if not row.get("manual_review_required") else "warning"
    return _base_event(
        activity_id=f"reconciliation:{row.get('case_id')}",
        event_type="trade_reconciliation",
        category="Reconciliation",
        source_table="CANONICAL_RECONCILIATION_CASES",
        source_record_id=row.get("case_id"),
        timestamp=row.get("created_at"),
        title=f"{row.get('broker')} trade reconciled",
        summary=row.get("explanation") or "Reconciliation case recorded.",
        outcome=row.get("status") or "unknown",
        severity=severity,
        component="Reconciliation",
        broker=row.get("broker"),
        symbol=row.get("symbol"),
        trade_id=row.get("logical_trade_id"),
        founder_action_required=bool(row.get("manual_review_required")),
    )


def _learning_event(row: dict[str, Any]) -> dict[str, Any]:
    status = _lower(row.get("status"))
    return _base_event(
        activity_id=f"learning:{row.get('learning_run_id')}",
        event_type="closed_loop_learning",
        category="Learning",
        source_table="CLOSED_LOOP_LEARNING_RUNS",
        source_record_id=row.get("learning_run_id"),
        timestamp=row.get("created_at"),
        title=f"Learning review {row.get('status')}",
        summary=row.get("explanation") or "Closed-loop learning run recorded.",
        outcome=row.get("status") or "unknown",
        severity="success" if status.startswith("completed") else "warning",
        component="Learning",
        broker=row.get("broker"),
        symbol=row.get("symbol"),
        trade_id=row.get("logical_trade_id"),
    )


def _report_event(row: dict[str, Any], table: str) -> dict[str, Any]:
    report_id = row.get("report_id")
    report_type = row.get("report_type") or row.get("type") or "report"
    summary = row.get("summary") or row.get("report_markdown") or "Report generated."
    return _base_event(
        activity_id=f"report:{table}:{report_id}",
        event_type="report_generated",
        category="Reports",
        source_table=table,
        source_record_id=report_id,
        timestamp=row.get("created_at"),
        title=f"{_title(report_type)} report generated",
        summary=str(summary)[:220],
        outcome="generated",
        severity="success",
        component="Reporting",
    )


def _incident_event(row: dict[str, Any]) -> dict[str, Any]:
    resolved = _lower(row.get("status")) in {"resolved", "closed"}
    return _base_event(
        activity_id=f"incident:{row.get('incident_key')}",
        event_type="incident",
        category="Incidents",
        source_table="INCIDENT_LIFECYCLE",
        source_record_id=row.get("incident_key"),
        timestamp=row.get("last_observed_at") or row.get("first_detected_at"),
        title=f"Incident {'resolved' if resolved else 'open'}: {row.get('component')}",
        summary=row.get("explanation") or "Operational incident recorded.",
        detailed_reason=row.get("recommended_action") or row.get("explanation"),
        outcome=row.get("status") or "unknown",
        severity="recovered" if resolved else row.get("severity") or "warning",
        component=row.get("component") or "System",
        incident_id=row.get("incident_key"),
        founder_action_required=not resolved,
    )


def latest_completed_actions(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    wanted = {
        "Research": "Latest research completed",
        "Decisions": "Latest recommendation reviewed",
        "Brokers": "Latest broker poll completed",
        "Execution": "Latest order or fill",
        "Reconciliation": "Latest trade reconciled",
        "Learning": "Latest learning review",
        "Reports": "Latest report generated",
        "Incidents": "Latest incident activity",
    }
    for event in sorted(events, key=lambda item: (item.get("timestamp") or "", item.get("activity_id") or ""), reverse=True):
        category = event.get("event_category")
        if category in wanted and category not in latest:
            latest[category] = {
                "label": wanted[category],
                "timestamp": event.get("timestamp"),
                "title": event.get("title"),
                "outcome": event.get("outcome"),
                "source_table": event.get("source_table"),
                "source_record_id": event.get("source_record_id"),
            }
    return list(latest.values())


def _sqlite_rows(db_path: Path, table: str, order_column: str, limit: int) -> list[dict[str, Any]]:
    if not db_path.exists() or not _table_exists(db_path, table):
        return []
    try:
        with closing(connect(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"SELECT * FROM {table} ORDER BY {order_column} DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
            return [dict(row) for row in rows]
    except sqlite3.Error:
        return []


def _table_exists(db_path: Path, table: str) -> bool:
    try:
        with closing(connect(db_path)) as conn:
            row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name = ?", (table,)).fetchone()
            return bool(row)
    except sqlite3.Error:
        return False


def _period_rows(rows: list[dict[str, Any]], window: dict[str, datetime], key: str, *, fallback_key: str | None = None) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        ts = _timestamp(row.get(key) or (row.get(fallback_key) if fallback_key else None))
        if ts and window["start"] <= ts <= window["end"]:
            result.append(row)
    return result


def _matches_filters(event: dict[str, Any], *, category: str, severity: str, important_only: bool, founder_action_required: bool) -> bool:
    if category and category.lower() != "all" and _lower(event.get("event_category")) != category.lower():
        return False
    if severity and severity.lower() != "all" and _lower(event.get("severity")) != severity.lower():
        return False
    if important_only and _lower(event.get("severity")) not in IMPORTANT_SEVERITIES and not event.get("founder_action_required"):
        return False
    if founder_action_required and not event.get("founder_action_required"):
        return False
    return True


def _timeline_empty_state(all_events: list[dict[str, Any]], filtered: list[dict[str, Any]], period: str) -> str:
    if filtered:
        return ""
    if all_events:
        return "Activity exists in this period, but none matches the selected filters."
    return f"No autonomous activity has been recorded in the last {period}."


def _latest_meaningful_activity(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    for event in sorted(events, key=lambda item: item.get("timestamp") or "", reverse=True):
        if event.get("event_category") in {"Research", "Decisions", "Execution", "Brokers", "Reconciliation", "Learning", "Reports", "Incidents"}:
            return {
                "timestamp": event.get("timestamp"),
                "title": event.get("title"),
                "summary": event.get("summary"),
                "category": event.get("event_category"),
            }
    return None


def _latest_event_time(events: list[dict[str, Any]], categories: set[str]) -> str | None:
    for event in sorted(events, key=lambda item: item.get("timestamp") or "", reverse=True):
        if event.get("event_category") in categories:
            return event.get("timestamp")
    return None


def _latest_job_time(jobs: list[dict[str, Any]], job_name: str) -> str | None:
    for row in jobs:
        if _lower(row.get("job_name")) == job_name:
            return _iso(row.get("completed_at") or row.get("started_at") or row.get("scheduled_for"))
    return None


def _latest_completed_job_time(jobs: list[dict[str, Any]]) -> str | None:
    for row in sorted(jobs, key=lambda item: item.get("completed_at") or item.get("started_at") or item.get("scheduled_for") or "", reverse=True):
        if _lower(row.get("status")).startswith("completed"):
            return _iso(row.get("completed_at") or row.get("started_at") or row.get("scheduled_for"))
    return None


def _latest_trade_time(rows: list[dict[str, Any]], statuses: set[str] | None = None) -> str | None:
    for row in sorted(rows, key=lambda item: item.get("updated_at") or item.get("closed_at") or item.get("opened_at") or "", reverse=True):
        if statuses is None or _lower(row.get("status")) in statuses or any(token in _lower(row.get("status")) for token in statuses):
            return _iso(row.get("updated_at") or row.get("closed_at") or row.get("opened_at"))
    return None


def _latest_error_for_broker(rows: list[dict[str, Any]], jobs: list[dict[str, Any]], broker: str) -> str:
    for row in rows:
        if "reject" in _lower(row.get("status")) or "error" in _lower(row.get("status")):
            return str(row.get("status"))
    for job in jobs:
        if job.get("failure_reason"):
            return str(job.get("failure_reason"))
    return "No broker error recorded in the selected period."


def _latest_no_trade_reason(db_path: Path, broker: str) -> str:
    rows = list_research_funnels(db_path, broker=broker, limit=10)
    for row in rows:
        if row.get("primary_reason"):
            return str(row.get("primary_reason"))
    return "No no-trade reason recorded for this broker yet."


def _broker_mode(broker: str, panel: dict[str, Any]) -> str:
    if broker == "alpaca":
        return "PAPER" if "paper" in _lower(panel.get("trading_status")) or panel.get("paper_only") else "Unknown - Alpaca mode was not returned."
    if broker == "kraken":
        return panel.get("trading_permissions", {}).get("trading_status") or "Kraken permission mode not returned."
    return "Unknown"


def _broker_blocker(broker: str, panel: dict[str, Any], latest_error: str) -> str:
    if "connected" not in _lower(panel.get("connection_status")):
        return f"{broker.title()} is not connected."
    if not panel.get("auto_trading_enabled"):
        return f"{broker.title()} autonomous execution is disabled."
    if latest_error and not latest_error.startswith("No broker error"):
        return latest_error
    return "No current blocker recorded."


def _attention(title: str, impact: str, action: str, component: str, severity: str, *, broker: str | None = None) -> dict[str, Any]:
    return {
        "title": title,
        "impact": impact,
        "began_at": None,
        "recommended_action": action,
        "component": component,
        "severity": severity,
        "broker": broker,
        "navigation_target": {"screen": "Activity", "source_table": "derived_attention", "source_record_id": title},
    }


def _job_category(job_name: Any) -> str:
    name = _lower(job_name)
    if "research" in name or "equity" in name or "crypto" in name:
        return "Research"
    if "auto-execution" in name or "managed-exits" in name:
        return "Execution"
    if "broker-poll" in name:
        return "Brokers"
    if "learning" in name:
        return "Learning"
    if "report" in name:
        return "Reports"
    return "System"


def _category_for_component(component: Any, event_type: Any) -> str:
    text = f"{component or ''} {event_type or ''}".lower()
    if "research" in text:
        return "Research"
    if "portfolio" in text or "committee" in text or "decision" in text:
        return "Decisions"
    if "risk" in text or "guardrail" in text or "sentinel" in text:
        return "Risk"
    if "broker" in text:
        return "Brokers"
    if "execution" in text or "order" in text or "fill" in text:
        return "Execution"
    if "reconcil" in text:
        return "Reconciliation"
    if "learning" in text:
        return "Learning"
    if "report" in text:
        return "Reports"
    if "incident" in text:
        return "Incidents"
    return "System"


def _normal_severity(severity: Any, success: Any) -> str:
    text = _lower(severity)
    if text in {"success", "information", "info", "warning", "blocked", "failure", "failed", "error", "recovered"}:
        return "information" if text == "info" else "failure" if text in {"failed", "error"} else text
    return "success" if success else "failure"


def _job_summary(job_name: Any, processed: int, recs: int, submitted: int, fills: int, failure: Any) -> str:
    if failure:
        return str(failure)
    name = _lower(job_name)
    if "research" in name or "equity" in name or "crypto" in name:
        return f"Research job processed {processed} asset(s) and created {recs} recommendation(s)."
    if name == "auto-execution":
        return f"Auto-execution reviewed eligibility and submitted {submitted} order(s)."
    if name == "broker-poll":
        return f"Broker polling completed and recorded {fills} fill(s)."
    if "learning" in name:
        return "Learning job completed or recorded no action."
    if "report" in name:
        return "Report job completed or recorded no action."
    return f"Scheduled job completed with status evidence: processed {processed}, recommendations {recs}, submitted {submitted}."


def _count_event_types(events: list[dict[str, Any]], names: set[str]) -> int:
    return len([row for row in events if _lower(row.get("event_type")) in names])


def _count_decisions(rows: list[dict[str, Any]], keyword: str, states: set[str]) -> int:
    return len([row for row in rows if keyword in _lower(row.get("payload_json")) and _lower(row.get("final_decision")) in states])


def _count_portfolio(rows: list[dict[str, Any]], states: set[str]) -> int:
    return len([row for row in rows if _lower(row.get("decision")) in states])


def _sum_int(rows: list[dict[str, Any]], key: str) -> int:
    return sum(_as_int(row.get(key)) for row in rows)


def _as_int(value: Any) -> int:
    if value in {None, ""}:
        return 0
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _json_list(value: Any) -> list[Any]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


def _json_reason(value: Any) -> str | None:
    if not value:
        return None
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return None
    if isinstance(parsed, dict):
        for key in ["reason", "message", "plain_english", "summary"]:
            if parsed.get(key):
                return str(parsed[key])
    return None


def _freshness_label(timestamp: str | None, *, minutes: int) -> str:
    ts = _timestamp(timestamp)
    if not ts:
        return "Not available - no successful poll was recorded."
    age = datetime.now(timezone.utc) - ts
    if age <= timedelta(minutes=minutes):
        return "Fresh"
    return f"Stale - last successful evidence is {round(age.total_seconds() / 60)} minutes old."


def _timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        try:
            return datetime.fromtimestamp(float(text), tz=timezone.utc)
        except (TypeError, ValueError, OSError):
            return None


def _iso(value: Any) -> str | None:
    ts = _timestamp(value)
    return ts.isoformat() if ts else None


def _lower(value: Any) -> str:
    return str(value or "").strip().lower()


def _title(value: Any) -> str:
    return str(value or "Unknown").replace("_", " ").replace("-", " ").title()
