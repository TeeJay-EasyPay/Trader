from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .always_on import (
    list_job_runs,
    list_worker_heartbeats,
    record_operations_incident,
)
from .experience_engine import (
    create_learning_proposal,
    find_historical_analogues,
    generate_post_trade_review,
    record_experience,
)
from .market_intelligence_platform import validate_candles
from .models import utc_now_iso
from .operational_truth import (
    calculate_execution_costs,
    calculate_mae_mfe,
    calculate_r_multiple,
    record_lifecycle_event,
)
from .portfolio_intelligence import (
    calculate_portfolio_exposure,
    correlation_warning,
    proposed_trade_portfolio_impact,
)


PHASE5_SCHEMA = """
CREATE TABLE IF NOT EXISTS PRODUCTION_SPINE_SNAPSHOTS (
    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    database_backend TEXT NOT NULL,
    readiness_status TEXT NOT NULL,
    migrated_families_json TEXT NOT NULL,
    unmigrated_families_json TEXT NOT NULL,
    explanation TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS WORKER_SUPERVISION_RUNS (
    supervision_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL,
    health_score REAL NOT NULL,
    stale_workers INTEGER NOT NULL,
    duplicate_worker_types INTEGER NOT NULL,
    late_jobs INTEGER NOT NULL,
    backlog_count INTEGER NOT NULL,
    incidents_created INTEGER NOT NULL,
    explanation TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS CANONICAL_RECONCILIATION_CASES (
    case_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    broker TEXT NOT NULL,
    logical_trade_id TEXT NOT NULL,
    symbol TEXT,
    status TEXT NOT NULL,
    confidence_score REAL NOT NULL,
    events_seen INTEGER NOT NULL,
    lifecycle_events_recorded INTEGER NOT NULL,
    duplicate_events INTEGER NOT NULL,
    manual_review_required INTEGER NOT NULL,
    explanation TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    UNIQUE(broker, logical_trade_id)
);

CREATE TABLE IF NOT EXISTS CLOSED_LOOP_LEARNING_RUNS (
    learning_run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    logical_trade_id TEXT NOT NULL UNIQUE,
    broker TEXT,
    symbol TEXT,
    status TEXT NOT NULL,
    lifecycle_marked INTEGER NOT NULL,
    experience_id INTEGER,
    review_id INTEGER,
    learning_proposal_id INTEGER,
    explanation TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS PORTFOLIO_MANAGER_DECISIONS (
    portfolio_decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    proposal_id TEXT,
    broker TEXT,
    symbol TEXT NOT NULL,
    decision TEXT NOT NULL,
    approved_notional REAL,
    reason TEXT NOT NULL,
    evidence_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS MARKET_DATA_GATEWAY_RUNS (
    gateway_run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    provider TEXT NOT NULL,
    normalized_symbol TEXT NOT NULL,
    asset_type TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    status TEXT NOT NULL,
    quality_score REAL NOT NULL,
    latency_ms REAL,
    observations_seen INTEGER NOT NULL,
    issues_json TEXT NOT NULL,
    provenance_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS STRATEGY_PROMOTION_DECISIONS (
    promotion_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    current_stage TEXT NOT NULL,
    proposed_stage TEXT NOT NULL,
    decision TEXT NOT NULL,
    evidence_gate_status TEXT NOT NULL,
    reason TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
"""


CRITICAL_RUNTIME_FAMILIES = {
    "always_on": ["SCHEDULED_JOB_RUNS", "WORKER_HEARTBEATS", "RESEARCH_FUNNELS", "SHADOW_TRADES", "OPERATIONS_INCIDENTS"],
    "recommendations": ["RECOMMENDATION_SETS", "trade_audit"],
    "broker_runtime": ["BROKER_RUNTIME", "BROKER_TRADE_HISTORY", "ORDER_INTENT_LOCKS", "MANAGED_TRADE_EXITS"],
    "canonical_lifecycle": ["CANONICAL_TRADE_LIFECYCLE", "TRADE_EXECUTION_COSTS", "TRADE_R_MULTIPLES", "TRADE_EXCURSIONS"],
    "portfolio_intelligence": ["PORTFOLIO_EXPOSURE_SNAPSHOTS", "PORTFOLIO_RISK_CONTRIBUTIONS"],
    "market_intelligence": ["MARKET_DATA_OBSERVATIONS", "MARKET_DATA_QUALITY_EVENTS", "MARKET_REGIME_EVIDENCE"],
    "experience_learning": ["EXPERIENCE_RECORDS", "POST_TRADE_REVIEWS", "LEARNING_PROPOSALS"],
    "reports": ["TRADING_REPORTS", "daily_briefings"],
}


STRATEGY_STAGES = ["Research", "Backtest", "Walk Forward", "Shadow", "Paper", "Micro Live", "Production", "Retired"]


def initialize_production_spine_schema(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db_path)) as conn:
        with conn:
            conn.executescript(PHASE5_SCHEMA)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_pm_decisions_symbol ON PORTFOLIO_MANAGER_DECISIONS(symbol, created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_gateway_symbol ON MARKET_DATA_GATEWAY_RUNS(normalized_symbol, created_at)")


def production_database_spine_status(db_path: Path, *, database_backend: str = "sqlite") -> dict[str, Any]:
    initialize_production_spine_schema(db_path)
    tables = _sqlite_tables(db_path)
    backend_ready = database_backend in {"postgres", "postgresql", "supabase"}
    migrated = {"always_on": backend_ready}
    for family in CRITICAL_RUNTIME_FAMILIES:
        if family != "always_on":
            migrated[family] = False
    missing_tables = {
        family: [table for table in names if table not in tables]
        for family, names in CRITICAL_RUNTIME_FAMILIES.items()
    }
    unmigrated = [family for family, done in migrated.items() if not done]
    status = "production_ready" if not unmigrated else ("operational_with_hardening_backlog" if backend_ready else "partial_spine")
    explanation = (
        "All critical runtime families share the production database."
        if status == "production_ready"
        else (
            "Supabase/Postgres is active for always-on operational evidence. "
            "Remaining runtime families are hardening backlog items; they do not stop the current worker, broker-poll, "
            "auto-execution, and learning cycles from operating."
            if backend_ready
            else "SQLite is active; acceptable for local/test/offline use but not enough for multi-process production truth."
        )
    )
    payload = {
        "critical_runtime_families": CRITICAL_RUNTIME_FAMILIES,
        "missing_local_tables": missing_tables,
        "migration_status_by_family": migrated,
    }
    with closing(sqlite3.connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO PRODUCTION_SPINE_SNAPSHOTS (
                    created_at, database_backend, readiness_status, migrated_families_json,
                    unmigrated_families_json, explanation, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    utc_now_iso(),
                    database_backend,
                    status,
                    json.dumps([key for key, value in migrated.items() if value], sort_keys=True),
                    json.dumps(unmigrated, sort_keys=True),
                    explanation,
                    json.dumps(payload, sort_keys=True, default=str),
                ),
            )
    return {
        "status": status,
        "database_backend": database_backend,
        "migrated_families": [key for key, value in migrated.items() if value],
        "unmigrated_families": unmigrated,
        "missing_local_tables": missing_tables,
        "plain_english": explanation,
    }


def supervise_workers(
    db_path: Path,
    *,
    expected_worker_interval_seconds: int = 120,
    expected_jobs: dict[str, int] | None = None,
) -> dict[str, Any]:
    initialize_production_spine_schema(db_path)
    now = datetime.now(timezone.utc)
    workers = list_worker_heartbeats(db_path)
    jobs = list_job_runs(db_path, limit=200)
    stale_workers = [
        worker for worker in workers
        if (_age_seconds(worker.get("last_heartbeat_at"), now) or 999999) > expected_worker_interval_seconds * 2
    ]
    by_type: dict[str, int] = {}
    for worker in workers:
        by_type[str(worker.get("worker_type") or "unknown")] = by_type.get(str(worker.get("worker_type") or "unknown"), 0) + 1
    duplicate_worker_types = {kind: count for kind, count in by_type.items() if kind == "background-worker" and count > 1}
    late_jobs = _late_jobs(jobs, expected_jobs or {}, now)
    backlog = [job for job in jobs if job.get("status") in {"scheduled", "started"}]
    deductions = len(stale_workers) * 45 + len(duplicate_worker_types) * 20 + len(late_jobs) * 15 + len(backlog) * 5
    score = max(0.0, 100.0 - deductions)
    status = "healthy" if score >= 85 else "degraded" if score >= 60 else "incident"
    incidents = 0
    for worker in stale_workers:
        record_operations_incident(
            db_path,
            severity="error",
            component="worker-supervision",
            title="Worker heartbeat stale",
            message=f"{worker.get('worker_id')} has not heartbeated within the expected window.",
            payload=worker,
        )
        incidents += 1
    for job in late_jobs:
        record_operations_incident(
            db_path,
            severity="warning",
            component="scheduler",
            title="Scheduled job late or missing",
            message=f"{job['job_name']} has not completed within {job['expected_minutes']} minutes.",
            payload=job,
        )
        incidents += 1
    explanation = _worker_supervision_explanation(status, stale_workers, late_jobs, backlog)
    payload = {
        "workers": workers,
        "recent_jobs": jobs,
        "stale_workers": stale_workers,
        "duplicate_worker_types": duplicate_worker_types,
        "late_jobs": late_jobs,
        "backlog": backlog,
    }
    with closing(sqlite3.connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO WORKER_SUPERVISION_RUNS (
                    created_at, status, health_score, stale_workers, duplicate_worker_types,
                    late_jobs, backlog_count, incidents_created, explanation, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    utc_now_iso(),
                    status,
                    score,
                    len(stale_workers),
                    len(duplicate_worker_types),
                    len(late_jobs),
                    len(backlog),
                    incidents,
                    explanation,
                    json.dumps(payload, sort_keys=True, default=str),
                ),
            )
    return {
        "status": status,
        "health_score": score,
        "stale_workers": len(stale_workers),
        "duplicate_worker_types": duplicate_worker_types,
        "late_jobs": late_jobs,
        "backlog_count": len(backlog),
        "incidents_created": incidents,
        "plain_english": explanation,
    }


def reconcile_logical_trade(db_path: Path, *, broker: str, events: list[dict[str, Any]]) -> dict[str, Any]:
    initialize_production_spine_schema(db_path)
    grouped = _group_broker_events(broker, events)
    results: list[dict[str, Any]] = []
    for logical_trade_id, rows in grouped.items():
        lifecycle_recorded = 0
        duplicates = 0
        manual_review = 0
        symbol = None
        for row in sorted(rows, key=lambda item: str(item.get("timestamp") or item.get("time") or "")):
            symbol = symbol or row.get("symbol") or row.get("pair")
            result = record_lifecycle_event(
                db_path,
                stage=_stage_from_event(row),
                proposal_id=row.get("proposal_id"),
                broker=broker,
                broker_order_id=str(row.get("order_id") or row.get("ordertxid") or row.get("id") or ""),
                broker_trade_id=str(row.get("trade_id") or row.get("tradeid") or ""),
                broker_fill_id=str(row.get("fill_id") or row.get("trade_id") or row.get("id") or ""),
                symbol=symbol,
                asset_type=row.get("asset_type") or ("crypto" if broker.lower() == "kraken" else "stock"),
                side=row.get("side") or row.get("type"),
                event_source="phase5_reconciliation",
                event_reason="Broker event reconciled into a logical trade.",
                payload=row,
                idempotency_key=f"{broker}:{logical_trade_id}:{row.get('id') or row.get('trade_id') or row.get('timestamp') or row.get('time')}",
            )
            if result["status"] == "recorded":
                lifecycle_recorded += 1
            elif result["status"] == "duplicate":
                duplicates += 1
            else:
                manual_review += 1
        confidence = _reconciliation_confidence(rows, manual_review)
        status = "reconciled" if confidence >= 0.80 and manual_review == 0 else "manual_review_required"
        explanation = (
            "Broker events reconciled deterministically into one logical trade."
            if status == "reconciled"
            else "Deterministic reconciliation is incomplete; manual review is required."
        )
        with closing(sqlite3.connect(db_path)) as conn:
            with conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO CANONICAL_RECONCILIATION_CASES (
                        case_id, created_at, broker, logical_trade_id, symbol, status,
                        confidence_score, events_seen, lifecycle_events_recorded,
                        duplicate_events, manual_review_required, explanation, payload_json
                    ) VALUES (
                        (SELECT case_id FROM CANONICAL_RECONCILIATION_CASES WHERE broker = ? AND logical_trade_id = ?),
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        broker.lower(),
                        logical_trade_id,
                        utc_now_iso(),
                        broker.lower(),
                        logical_trade_id,
                        symbol,
                        status,
                        confidence,
                        len(rows),
                        lifecycle_recorded,
                        duplicates,
                        1 if manual_review else 0,
                        explanation,
                        json.dumps({"events": rows}, sort_keys=True, default=str),
                    ),
                )
        results.append({
            "logical_trade_id": logical_trade_id,
            "symbol": symbol,
            "status": status,
            "confidence_score": confidence,
            "events_seen": len(rows),
            "lifecycle_events_recorded": lifecycle_recorded,
            "duplicate_events": duplicates,
            "manual_review_required": bool(manual_review),
            "plain_english": explanation,
        })
    return {"broker": broker.lower(), "logical_trades": results, "count": len(results)}


def run_closed_loop_learning(
    db_path: Path,
    *,
    logical_trade_id: str,
    broker: str,
    symbol: str,
    attribution: dict[str, Any],
    decision_context: dict[str, Any],
    observations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    initialize_production_spine_schema(db_path)
    existing = _row(
        db_path,
        "SELECT * FROM CLOSED_LOOP_LEARNING_RUNS WHERE logical_trade_id = ?",
        (logical_trade_id,),
    )
    if existing:
        return {**existing, "status": "duplicate", "plain_english": "Closed-loop learning already ran for this logical trade."}
    costs = calculate_execution_costs(
        db_path,
        proposal_id=attribution.get("proposal_id"),
        broker=broker,
        symbol=symbol,
        intended_entry_price=_float(decision_context.get("intended_entry_price") or decision_context.get("entry_price")),
        actual_average_entry_price=_float(attribution.get("actual_average_entry_price") or attribution.get("entry_price")),
        intended_exit_price=_float(decision_context.get("intended_exit_price") or decision_context.get("take_profit")),
        actual_average_exit_price=_float(attribution.get("actual_average_exit_price") or attribution.get("exit_price")),
        quantity=_float(attribution.get("quantity")),
        broker_fee=_float(attribution.get("broker_fee")),
        exchange_fee=_float(attribution.get("exchange_fee")),
        spread_cost=_float(attribution.get("spread_cost")),
        payload=attribution,
    )
    r_multiple = calculate_r_multiple(
        db_path,
        proposal_id=attribution.get("proposal_id"),
        broker=broker,
        symbol=symbol,
        intended_entry_price=_required_float(decision_context, "intended_entry_price", "entry_price"),
        original_stop=_required_float(decision_context, "original_stop", "stop_loss"),
        filled_quantity=_required_float(attribution, "quantity", "filled_quantity"),
        gross_realized_pnl=_float(attribution.get("profit_loss") or attribution.get("gross_realized_pnl")) or 0.0,
        total_cost=costs.get("total_trading_cost"),
        expected_r=_float(decision_context.get("expected_r")),
        planned_take_profit=_float(decision_context.get("take_profit")),
        payload={"logical_trade_id": logical_trade_id},
    )
    excursions = calculate_mae_mfe(
        db_path,
        proposal_id=attribution.get("proposal_id"),
        broker=broker,
        symbol=symbol,
        side=str(attribution.get("side") or decision_context.get("side") or "buy"),
        entry_price=_required_float(decision_context, "intended_entry_price", "entry_price"),
        quantity=_required_float(attribution, "quantity", "filled_quantity"),
        original_stop=_required_float(decision_context, "original_stop", "stop_loss"),
        observations=observations or [],
        data_granularity=str(decision_context.get("data_granularity") or "unknown"),
        payload={"logical_trade_id": logical_trade_id},
    )
    experience = record_experience(
        db_path,
        symbol=symbol,
        proposal_id=attribution.get("proposal_id"),
        broker=broker,
        asset_type=decision_context.get("asset_type"),
        strategy_id=decision_context.get("strategy_id"),
        regime_id=decision_context.get("regime_id"),
        decision_context=decision_context,
        execution_context={"costs": costs, "r_multiple": r_multiple, "excursions": excursions},
        result_context=attribution,
    )
    review = generate_post_trade_review(
        db_path,
        {**attribution, "net_r": r_multiple.get("net_r"), "actual_r": r_multiple.get("actual_r"), "experience_id": experience.get("experience_id")},
        decision_context,
    )
    analogues = find_historical_analogues(
        db_path,
        {"symbol": symbol, "strategy_id": decision_context.get("strategy_id"), "regime_id": decision_context.get("regime_id")},
    )
    learning_proposal = create_learning_proposal(
        db_path,
        proposal_type="post_trade_review",
        current_value="production unchanged",
        proposed_value="review evidence before changing thresholds",
        evidence={"review": review, "r_multiple": r_multiple, "analogues": analogues},
        sample_size=int(analogues.get("comparable_cases") or 0),
        expected_impact="Improves governance visibility without changing production parameters.",
        risks="Small samples can mislead learning.",
        rollback_plan="Reject proposal; no production settings were changed.",
    )
    learning_proposal = {
        **learning_proposal,
        "proposal_type": "post_trade_review",
        "current_value": "production unchanged",
        "proposed_value": "review evidence before changing thresholds",
        "no_silent_production_change": True,
    }
    lifecycle = record_lifecycle_event(
        db_path,
        stage="learning_completed",
        proposal_id=attribution.get("proposal_id"),
        broker=broker,
        symbol=symbol,
        event_source="closed_loop_learning",
        event_reason="Closed-loop learning completed idempotently.",
        payload={"logical_trade_id": logical_trade_id, "review_id": review.get("review_id")},
        idempotency_key=f"learning_completed:{logical_trade_id}",
    )
    status = "completed" if lifecycle["status"] in {"recorded", "duplicate"} else "manual_review_required"
    explanation = "Closed-loop learning completed without changing production parameters."
    with closing(sqlite3.connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO CLOSED_LOOP_LEARNING_RUNS (
                    created_at, logical_trade_id, broker, symbol, status,
                    lifecycle_marked, experience_id, review_id, learning_proposal_id,
                    explanation, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    utc_now_iso(),
                    logical_trade_id,
                    broker.lower(),
                    symbol.upper(),
                    status,
                    1 if lifecycle["status"] in {"recorded", "duplicate"} else 0,
                    experience.get("experience_id"),
                    review.get("review_id"),
                    learning_proposal.get("proposal_id"),
                    explanation,
                    json.dumps(
                        {
                            "costs": costs,
                            "r_multiple": r_multiple,
                            "excursions": excursions,
                            "experience": experience,
                            "review": review,
                            "analogues": analogues,
                            "learning_proposal": learning_proposal,
                            "lifecycle": lifecycle,
                        },
                        sort_keys=True,
                        default=str,
                    ),
                ),
            )
    return {
        "status": status,
        "logical_trade_id": logical_trade_id,
        "costs": costs,
        "r_multiple": r_multiple,
        "excursions": excursions,
        "experience": experience,
        "review": review,
        "analogues": analogues,
        "learning_proposal": learning_proposal,
        "plain_english": explanation,
    }


def portfolio_manager_decision(
    db_path: Path,
    *,
    proposal: dict[str, Any],
    positions: list[dict[str, Any]],
    return_series: dict[str, list[float]] | None = None,
) -> dict[str, Any]:
    initialize_production_spine_schema(db_path)
    symbol = str(proposal.get("symbol") or "").upper()
    proposed_notional = _float(proposal.get("position_size") or proposal.get("notional") or proposal.get("approved_notional")) or 0.0
    asset_class = str(proposal.get("asset_class") or proposal.get("asset_type") or "Unknown")
    exposure = calculate_portfolio_exposure(db_path, positions, broker=proposal.get("broker"))
    impact = proposed_trade_portfolio_impact(
        exposure,
        symbol=symbol,
        proposed_notional=proposed_notional,
        proposed_asset_class=asset_class,
    )
    corr = correlation_warning([item.get("symbol") for item in positions if item.get("symbol")] + [symbol], return_series or {})
    existing_open_risk = sum(_float(item.get("stop_based_risk") or item.get("risk_amount")) or 0.0 for item in positions)
    proposed_risk = abs((_float(proposal.get("entry_price")) or 0.0) - (_float(proposal.get("stop_loss")) or 0.0)) * (_float(proposal.get("quantity") or proposal.get("position_size")) or 0.0)
    risk_ratio = (existing_open_risk + proposed_risk) / exposure["total_value"] if exposure["total_value"] else None
    decision = "approve"
    reason = impact["plain_english"]
    approved_notional = proposed_notional
    if exposure["warnings"]:
        decision = "manual_review"
        reason = exposure["warnings"][0]
    if impact["decision"] == "Reject due to concentration":
        decision = "reject"
        approved_notional = None
        reason = impact["plain_english"]
    elif impact["decision"] == "Buy smaller":
        decision = "approve_smaller"
        approved_notional = proposed_notional * 0.5
        reason = "Portfolio concentration is elevated; smaller size required."
    if risk_ratio is not None and risk_ratio > 0.08:
        decision = "wait" if decision == "approve" else decision
        reason = "Existing and proposed open risk are high relative to measured portfolio value."
    evidence = {
        "exposure": exposure,
        "impact": impact,
        "correlation": corr,
        "existing_open_risk": existing_open_risk,
        "proposed_risk_contribution": proposed_risk,
        "portfolio_var_approximation": risk_ratio,
        "liquidity_impact": proposal.get("liquidity_impact") or "Unknown - liquidity provider not configured.",
        "capital_efficiency": "Unknown - requires strategy expectancy and cost history.",
    }
    with closing(sqlite3.connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO PORTFOLIO_MANAGER_DECISIONS (
                    created_at, proposal_id, broker, symbol, decision,
                    approved_notional, reason, evidence_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    utc_now_iso(),
                    proposal.get("proposal_id"),
                    proposal.get("broker"),
                    symbol,
                    decision,
                    approved_notional,
                    reason,
                    json.dumps(evidence, sort_keys=True, default=str),
                ),
            )
    return {
        "decision": decision,
        "approved_notional": approved_notional,
        "reason": reason,
        "evidence": evidence,
        "plain_english": f"Portfolio Manager decision for {symbol}: {decision}. {reason}",
    }


def market_data_gateway_validate(
    db_path: Path,
    *,
    provider: str,
    symbol: str,
    asset_type: str,
    timeframe: str,
    observations: list[dict[str, Any]],
    latency_ms: float | None = None,
    provider_status: str = "available",
) -> dict[str, Any]:
    initialize_production_spine_schema(db_path)
    quality = validate_candles(observations)
    score = _market_quality_score(quality, provider_status, latency_ms)
    status = "approved" if quality["severity"] == "pass" and score >= 0.80 else "blocked"
    provenance = {
        "provider": provider,
        "provider_status": provider_status,
        "latency_ms": latency_ms,
        "normalization": {"original_symbol": symbol, "normalized_symbol": symbol.upper()},
        "quality": quality,
    }
    with closing(sqlite3.connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO MARKET_DATA_GATEWAY_RUNS (
                    created_at, provider, normalized_symbol, asset_type, timeframe,
                    status, quality_score, latency_ms, observations_seen, issues_json,
                    provenance_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    utc_now_iso(),
                    provider,
                    symbol.upper(),
                    asset_type,
                    timeframe,
                    status,
                    score,
                    latency_ms,
                    len(observations),
                    json.dumps(quality["issues"], sort_keys=True, default=str),
                    json.dumps(provenance, sort_keys=True, default=str),
                ),
            )
    return {
        "status": status,
        "quality_score": score,
        "quality": quality,
        "provenance": provenance,
        "plain_english": "Market data passed the execution gate." if status == "approved" else f"Market data blocked execution: {quality['plain_english']}",
    }


def strategy_promotion_decision(
    db_path: Path,
    *,
    strategy_id: str,
    current_stage: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    initialize_production_spine_schema(db_path)
    current = _normal_stage(current_stage)
    proposed = _next_stage(current)
    gates = _strategy_evidence_gates(evidence, proposed)
    decision = "promote" if all(item["passed"] for item in gates) else "hold"
    if _float(evidence.get("recent_drawdown")) is not None and (_float(evidence.get("recent_drawdown")) or 0.0) > 0.12:
        proposed = "Retired" if current in {"Production", "Micro Live"} else current
        decision = "demote" if proposed != current else "hold"
    reason = "All evidence gates passed." if decision == "promote" else "; ".join(item["reason"] for item in gates if not item["passed"]) or "Performance deterioration detected."
    with closing(sqlite3.connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO STRATEGY_PROMOTION_DECISIONS (
                    created_at, strategy_id, current_stage, proposed_stage, decision,
                    evidence_gate_status, reason, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    utc_now_iso(),
                    strategy_id,
                    current,
                    proposed,
                    decision,
                    "passed" if decision == "promote" else "failed",
                    reason,
                    json.dumps({"evidence": evidence, "gates": gates}, sort_keys=True, default=str),
                ),
            )
    return {
        "strategy_id": strategy_id,
        "current_stage": current,
        "proposed_stage": proposed,
        "decision": decision,
        "gates": gates,
        "reason": reason,
        "plain_english": f"Strategy {strategy_id} decision: {decision}. {reason}",
    }


def phase5_status(db_path: Path, *, database_backend: str = "sqlite") -> dict[str, Any]:
    spine = production_database_spine_status(db_path, database_backend=database_backend)
    supervision = supervise_workers(db_path)
    worker_healthy = supervision["status"] == "healthy"
    backend_ready = database_backend in {"postgres", "postgresql", "supabase"}
    operational = backend_ready and worker_healthy
    if spine["status"] == "production_ready" and operational:
        overall = "production_ready"
        plain = "AI Trader is operating from shared Supabase/Postgres truth with a healthy background worker."
    elif operational:
        overall = "operational_with_hardening_backlog"
        plain = (
            "AI Trader is alive: Supabase/Postgres is active and the background worker is healthy. "
            "The listed backlog is future hardening, not a blocker to controlled autonomous operation."
        )
    else:
        overall = "attention_needed"
        plain = "AI Trader needs attention: shared database or background worker evidence is not healthy yet."
    return {
        "generated_at": utc_now_iso(),
        "database_spine": spine,
        "worker_supervision": supervision,
        "overall": overall,
        "plain_english": plain,
    }


def _sqlite_tables(db_path: Path) -> set[str]:
    if not db_path.exists():
        return set()
    with closing(sqlite3.connect(db_path)) as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {row[0] for row in rows}


def _row(db_path: Path, sql: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(sql, params).fetchone()
    return dict(row) if row else None


def _age_seconds(value: Any, now: datetime) -> float | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return max(0.0, (now - parsed).total_seconds())


def _late_jobs(jobs: list[dict[str, Any]], expected_jobs: dict[str, int], now: datetime) -> list[dict[str, Any]]:
    latest_by_name: dict[str, dict[str, Any]] = {}
    for job in jobs:
        name = str(job.get("job_name") or "")
        if name and name not in latest_by_name:
            latest_by_name[name] = job
    late = []
    for name, expected_minutes in expected_jobs.items():
        job = latest_by_name.get(name)
        if not job:
            late.append({"job_name": name, "expected_minutes": expected_minutes, "reason": "no job run found"})
            continue
        completed_at = job.get("completed_at") or job.get("started_at") or job.get("scheduled_for")
        age = _age_seconds(completed_at, now)
        if age is None or age > expected_minutes * 60:
            late.append({"job_name": name, "expected_minutes": expected_minutes, "last_seen": completed_at, "reason": "job is late"})
    return late


def _worker_supervision_explanation(status: str, stale_workers: list[dict[str, Any]], late_jobs: list[dict[str, Any]], backlog: list[dict[str, Any]]) -> str:
    if status == "healthy":
        return "Workers and scheduled jobs are within expected operating limits."
    if stale_workers:
        return "One or more workers have stale heartbeats; autonomous operations may not be running."
    if late_jobs:
        return "One or more scheduled jobs are late or missing."
    if backlog:
        return "Some jobs are still scheduled or started; monitor for completion."
    return "Operations are degraded and require review."


def _group_broker_events(broker: str, events: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        key = str(
            event.get("logical_trade_id")
            or event.get("order_id")
            or event.get("ordertxid")
            or event.get("trade_id")
            or event.get("tradeid")
            or f"{broker}:{event.get('symbol') or event.get('pair')}:{event.get('side') or event.get('type')}"
        )
        grouped.setdefault(key, []).append(event)
    return grouped


def _stage_from_event(event: dict[str, Any]) -> str:
    status = str(event.get("status") or event.get("event") or event.get("type") or "").lower()
    remaining = _float(event.get("remaining_quantity") or event.get("remaining"))
    filled = _float(event.get("filled_quantity") or event.get("filled_qty") or event.get("vol_exec") or event.get("vol"))
    if status in {"submitted", "new"}:
        return "submitted"
    if status in {"accepted", "acknowledged", "open", "pending"}:
        return "broker_acknowledged"
    if status in {"partial", "partially_filled"} or (remaining and filled):
        return "partially_filled"
    if status in {"filled", "complete", "closed"} or filled:
        return "fully_filled"
    if status in {"cancelled", "canceled"}:
        return "cancelled"
    if status in {"target_exit", "stop_exit", "manual_exit", "closed"}:
        return status
    return "broker_acknowledged"


def _reconciliation_confidence(rows: list[dict[str, Any]], manual_review: int) -> float:
    score = 1.0
    if manual_review:
        score -= 0.35
    if not rows:
        return 0.0
    missing_ids = sum(1 for row in rows if not (row.get("order_id") or row.get("ordertxid") or row.get("trade_id") or row.get("tradeid") or row.get("id")))
    missing_symbols = sum(1 for row in rows if not (row.get("symbol") or row.get("pair")))
    score -= min(0.30, missing_ids * 0.10)
    score -= min(0.30, missing_symbols * 0.10)
    return max(0.0, min(1.0, score))


def _required_float(payload: dict[str, Any], *keys: str) -> float:
    for key in keys:
        value = _float(payload.get(key))
        if value is not None:
            return value
    raise ValueError(f"Required numeric value missing: {'/'.join(keys)}")


def _float(value: Any) -> float | None:
    try:
        if value in {None, ""}:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _market_quality_score(quality: dict[str, Any], provider_status: str, latency_ms: float | None) -> float:
    score = 1.0
    if provider_status != "available":
        score -= 0.4
    if quality.get("severity") == "warn":
        score -= 0.25
    elif quality.get("severity") == "reject":
        score -= 0.60
    if latency_ms is not None and latency_ms > 2500:
        score -= 0.10
    return max(0.0, min(1.0, score))


def _normal_stage(stage: str) -> str:
    for item in STRATEGY_STAGES:
        if item.lower() == stage.lower():
            return item
    return "Research"


def _next_stage(stage: str) -> str:
    index = STRATEGY_STAGES.index(stage)
    return STRATEGY_STAGES[min(index + 1, len(STRATEGY_STAGES) - 1)]


def _strategy_evidence_gates(evidence: dict[str, Any], proposed_stage: str) -> list[dict[str, Any]]:
    sample_size = int(_float(evidence.get("sample_size")) or 0)
    expectancy = _float(evidence.get("expectancy"))
    profit_factor = _float(evidence.get("profit_factor"))
    max_drawdown = _float(evidence.get("max_drawdown"))
    calibration_error = _float(evidence.get("calibration_error"))
    min_sample = 30 if proposed_stage in {"Shadow", "Paper"} else 100 if proposed_stage in {"Micro Live", "Production"} else 10
    return [
        {"gate": "minimum_sample_size", "passed": sample_size >= min_sample, "reason": f"{min_sample} samples required for {proposed_stage}; observed {sample_size}."},
        {"gate": "positive_expectancy", "passed": expectancy is not None and expectancy > 0, "reason": "Expectancy must be positive."},
        {"gate": "profit_factor", "passed": profit_factor is not None and profit_factor >= 1.2, "reason": "Profit factor must be at least 1.2."},
        {"gate": "drawdown", "passed": max_drawdown is not None and max_drawdown <= 0.15, "reason": "Maximum drawdown must be 15% or lower."},
        {"gate": "calibration", "passed": calibration_error is not None and calibration_error <= 0.10, "reason": "Calibration error must be 10% or lower."},
    ]
