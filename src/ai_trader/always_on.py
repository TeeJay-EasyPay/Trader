from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .models import utc_now_iso
from .operational import latest_research_run, safe_float


ALWAYS_ON_SCHEMA = """
CREATE TABLE IF NOT EXISTS SCHEDULED_JOB_RUNS (
    job_run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_name TEXT NOT NULL,
    scheduled_for TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    status TEXT NOT NULL,
    attempt INTEGER NOT NULL DEFAULT 1,
    worker_id TEXT,
    idempotency_key TEXT NOT NULL UNIQUE,
    assets_requested INTEGER DEFAULT 0,
    assets_processed INTEGER DEFAULT 0,
    recommendations_created INTEGER DEFAULT 0,
    shadow_decisions_created INTEGER DEFAULT 0,
    paper_orders_submitted INTEGER DEFAULT 0,
    paper_orders_filled INTEGER DEFAULT 0,
    rejection_count INTEGER DEFAULT 0,
    failure_count INTEGER DEFAULT 0,
    failure_reason TEXT,
    payload_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_scheduled_job_runs_name_time
ON SCHEDULED_JOB_RUNS(job_name, scheduled_for);

CREATE TABLE IF NOT EXISTS WORKER_HEARTBEATS (
    worker_id TEXT PRIMARY KEY,
    worker_type TEXT NOT NULL,
    started_at TEXT NOT NULL,
    last_heartbeat_at TEXT NOT NULL,
    status TEXT NOT NULL,
    current_job TEXT,
    last_successful_job TEXT,
    last_error TEXT,
    deployment_commit TEXT,
    payload_json TEXT
);

CREATE TABLE IF NOT EXISTS RESEARCH_FUNNELS (
    funnel_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    job_run_id INTEGER,
    broker TEXT NOT NULL,
    asset_type TEXT NOT NULL,
    trigger_type TEXT NOT NULL,
    symbols_examined INTEGER DEFAULT 0,
    symbols_with_adequate_data INTEGER DEFAULT 0,
    interesting_ideas INTEGER DEFAULT 0,
    valid_strategies INTEGER DEFAULT 0,
    committee_approved INTEGER DEFAULT 0,
    portfolio_approved INTEGER DEFAULT 0,
    guardrail_approved INTEGER DEFAULT 0,
    eligible_for_paper_execution INTEGER DEFAULT 0,
    submitted INTEGER DEFAULT 0,
    filled INTEGER DEFAULT 0,
    rejected INTEGER DEFAULT 0,
    expired INTEGER DEFAULT 0,
    primary_reason TEXT,
    secondary_reasons_json TEXT,
    payload_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_research_funnels_broker_time
ON RESEARCH_FUNNELS(broker, created_at);

CREATE TABLE IF NOT EXISTS SHADOW_TRADES (
    shadow_trade_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    symbol TEXT NOT NULL,
    asset_type TEXT NOT NULL,
    intended_broker TEXT NOT NULL,
    strategy TEXT,
    regime TEXT,
    decision_status TEXT NOT NULL,
    intended_entry REAL,
    stop_loss REAL,
    take_profit REAL,
    quantity REAL,
    notional REAL,
    probability REAL,
    expected_r REAL,
    strongest_argument_for TEXT,
    strongest_argument_against TEXT,
    wait_or_rejection_reason TEXT,
    market_evidence_json TEXT,
    portfolio_snapshot_json TEXT,
    data_quality_json TEXT,
    expires_at TEXT,
    simulated_costs_json TEXT,
    outcome_status TEXT NOT NULL DEFAULT 'pending',
    theoretical_fill_price REAL,
    final_price REAL,
    gross_r REAL,
    estimated_net_r REAL,
    mae REAL,
    mfe REAL,
    holding_time_minutes REAL,
    benchmark_outcome TEXT,
    idempotency_key TEXT NOT NULL UNIQUE
);

CREATE INDEX IF NOT EXISTS idx_shadow_trades_broker_status
ON SHADOW_TRADES(intended_broker, decision_status, outcome_status);

CREATE TABLE IF NOT EXISTS OPERATIONS_INCIDENTS (
    incident_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    severity TEXT NOT NULL,
    component TEXT NOT NULL,
    status TEXT NOT NULL,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    payload_json TEXT
);
"""

POSTGRES_ALWAYS_ON_SCHEMA = """
CREATE TABLE IF NOT EXISTS SCHEDULED_JOB_RUNS (
    job_run_id BIGSERIAL PRIMARY KEY,
    job_name TEXT NOT NULL,
    scheduled_for TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    status TEXT NOT NULL,
    attempt INTEGER NOT NULL DEFAULT 1,
    worker_id TEXT,
    idempotency_key TEXT NOT NULL UNIQUE,
    assets_requested INTEGER DEFAULT 0,
    assets_processed INTEGER DEFAULT 0,
    recommendations_created INTEGER DEFAULT 0,
    shadow_decisions_created INTEGER DEFAULT 0,
    paper_orders_submitted INTEGER DEFAULT 0,
    paper_orders_filled INTEGER DEFAULT 0,
    rejection_count INTEGER DEFAULT 0,
    failure_count INTEGER DEFAULT 0,
    failure_reason TEXT,
    payload_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_scheduled_job_runs_name_time
ON SCHEDULED_JOB_RUNS(job_name, scheduled_for);

CREATE TABLE IF NOT EXISTS WORKER_HEARTBEATS (
    worker_id TEXT PRIMARY KEY,
    worker_type TEXT NOT NULL,
    started_at TEXT NOT NULL,
    last_heartbeat_at TEXT NOT NULL,
    status TEXT NOT NULL,
    current_job TEXT,
    last_successful_job TEXT,
    last_error TEXT,
    deployment_commit TEXT,
    payload_json TEXT
);

CREATE TABLE IF NOT EXISTS RESEARCH_FUNNELS (
    funnel_id BIGSERIAL PRIMARY KEY,
    created_at TEXT NOT NULL,
    job_run_id BIGINT,
    broker TEXT NOT NULL,
    asset_type TEXT NOT NULL,
    trigger_type TEXT NOT NULL,
    symbols_examined INTEGER DEFAULT 0,
    symbols_with_adequate_data INTEGER DEFAULT 0,
    interesting_ideas INTEGER DEFAULT 0,
    valid_strategies INTEGER DEFAULT 0,
    committee_approved INTEGER DEFAULT 0,
    portfolio_approved INTEGER DEFAULT 0,
    guardrail_approved INTEGER DEFAULT 0,
    eligible_for_paper_execution INTEGER DEFAULT 0,
    submitted INTEGER DEFAULT 0,
    filled INTEGER DEFAULT 0,
    rejected INTEGER DEFAULT 0,
    expired INTEGER DEFAULT 0,
    primary_reason TEXT,
    secondary_reasons_json TEXT,
    payload_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_research_funnels_broker_time
ON RESEARCH_FUNNELS(broker, created_at);

CREATE TABLE IF NOT EXISTS SHADOW_TRADES (
    shadow_trade_id BIGSERIAL PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    symbol TEXT NOT NULL,
    asset_type TEXT NOT NULL,
    intended_broker TEXT NOT NULL,
    strategy TEXT,
    regime TEXT,
    decision_status TEXT NOT NULL,
    intended_entry DOUBLE PRECISION,
    stop_loss DOUBLE PRECISION,
    take_profit DOUBLE PRECISION,
    quantity DOUBLE PRECISION,
    notional DOUBLE PRECISION,
    probability DOUBLE PRECISION,
    expected_r DOUBLE PRECISION,
    strongest_argument_for TEXT,
    strongest_argument_against TEXT,
    wait_or_rejection_reason TEXT,
    market_evidence_json TEXT,
    portfolio_snapshot_json TEXT,
    data_quality_json TEXT,
    expires_at TEXT,
    simulated_costs_json TEXT,
    outcome_status TEXT NOT NULL DEFAULT 'pending',
    theoretical_fill_price DOUBLE PRECISION,
    final_price DOUBLE PRECISION,
    gross_r DOUBLE PRECISION,
    estimated_net_r DOUBLE PRECISION,
    mae DOUBLE PRECISION,
    mfe DOUBLE PRECISION,
    holding_time_minutes DOUBLE PRECISION,
    benchmark_outcome TEXT,
    idempotency_key TEXT NOT NULL UNIQUE
);

CREATE INDEX IF NOT EXISTS idx_shadow_trades_broker_status
ON SHADOW_TRADES(intended_broker, decision_status, outcome_status);

CREATE TABLE IF NOT EXISTS OPERATIONS_INCIDENTS (
    incident_id BIGSERIAL PRIMARY KEY,
    created_at TEXT NOT NULL,
    severity TEXT NOT NULL,
    component TEXT NOT NULL,
    status TEXT NOT NULL,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    payload_json TEXT
);
"""


JOB_STATUSES = {
    "scheduled",
    "started",
    "completed",
    "completed_no_action",
    "partially_completed",
    "failed",
    "timed_out",
    "skipped_duplicate",
    "blocked_configuration",
    "blocked_market_closed",
}


def initialize_always_on_schema(db_path: Path) -> None:
    if _use_postgres():
        with _postgres_connection() as conn:
            with conn.cursor() as cur:
                for statement in POSTGRES_ALWAYS_ON_SCHEMA.split(";"):
                    if statement.strip():
                        cur.execute(statement)
            conn.commit()
        return
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db_path)) as conn:
        with conn:
            conn.executescript(ALWAYS_ON_SCHEMA)


def database_backend_status(db_path: Path) -> dict[str, Any]:
    requested = os.getenv("AI_TRADER_DATABASE_BACKEND", "sqlite").strip().lower()
    database_url = _database_url()
    active = "postgres" if _use_postgres() else "sqlite"
    return {
        "requested_backend": requested,
        "active_backend": active,
        "postgres_configured": bool(database_url),
        "sqlite_path": str(db_path),
        "plain_english": (
            "Always-On evidence is using Supabase/Postgres durable storage."
            if active == "postgres"
            else "Always-On evidence is using SQLite. This is fine for local use, but Render worker/API/cron should use Supabase/Postgres before multi-process scheduling is enabled."
        ),
    }


def claim_scheduled_job(
    db_path: Path,
    *,
    job_name: str,
    scheduled_for: str | None = None,
    worker_id: str | None = None,
    assets_requested: int = 0,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    initialize_always_on_schema(db_path)
    scheduled_for = scheduled_for or utc_now_iso()
    worker_id = worker_id or default_worker_id("job")
    idempotency_key = f"{job_name}:{scheduled_for}"
    now = utc_now_iso()
    payload_json = json.dumps(payload or {}, sort_keys=True)
    if _use_postgres():
        with _postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM SCHEDULED_JOB_RUNS WHERE idempotency_key = %s", (idempotency_key,))
                existing = cur.fetchone()
                if existing:
                    return {
                        **dict(existing),
                        "status": "skipped_duplicate",
                        "claimed": False,
                        "message": "This scheduled job was already claimed or completed.",
                    }
                cur.execute(
                    """
                    INSERT INTO SCHEDULED_JOB_RUNS (
                        job_name, scheduled_for, started_at, status, attempt, worker_id,
                        idempotency_key, assets_requested, payload_json
                    ) VALUES (%s, %s, %s, 'started', 1, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (job_name, scheduled_for, now, worker_id, idempotency_key, int(assets_requested or 0), payload_json),
                )
                row = cur.fetchone()
            conn.commit()
        return {**dict(row), "claimed": True, "message": "Scheduled job claimed."}
    with closing(sqlite3.connect(db_path, timeout=30)) as conn:
        conn.row_factory = sqlite3.Row
        with conn:
            existing = conn.execute(
                "SELECT * FROM SCHEDULED_JOB_RUNS WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if existing:
                return {
                    **dict(existing),
                    "status": "skipped_duplicate",
                    "claimed": False,
                    "message": "This scheduled job was already claimed or completed.",
                }
            conn.execute(
                """
                INSERT INTO SCHEDULED_JOB_RUNS (
                    job_name, scheduled_for, started_at, status, attempt, worker_id,
                    idempotency_key, assets_requested, payload_json
                ) VALUES (?, ?, ?, 'started', 1, ?, ?, ?, ?)
                """,
                (job_name, scheduled_for, now, worker_id, idempotency_key, int(assets_requested or 0), payload_json),
            )
            row = conn.execute(
                "SELECT * FROM SCHEDULED_JOB_RUNS WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
    return {**dict(row), "claimed": True, "message": "Scheduled job claimed."}


def complete_scheduled_job(
    db_path: Path,
    job_run_id: int,
    *,
    status: str,
    result: dict[str, Any] | None = None,
    failure_reason: str | None = None,
) -> dict[str, Any]:
    if status not in JOB_STATUSES:
        raise ValueError(f"Unsupported scheduled job status: {status}")
    initialize_always_on_schema(db_path)
    result = result or {}
    if _use_postgres():
        with _postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE SCHEDULED_JOB_RUNS
                    SET completed_at = %s, status = %s, assets_processed = %s,
                        recommendations_created = %s, shadow_decisions_created = %s,
                        paper_orders_submitted = %s, paper_orders_filled = %s,
                        rejection_count = %s, failure_count = %s, failure_reason = %s,
                        payload_json = %s
                    WHERE job_run_id = %s
                    RETURNING *
                    """,
                    (
                        utc_now_iso(),
                        status,
                        _count_result(result, "assets_processed", "symbols", "symbols_examined"),
                        _count_result(result, "recommendations_created", "proposals"),
                        _count_result(result, "shadow_decisions_created", "shadow_decisions"),
                        _count_result(result, "paper_orders_submitted", "submitted", "result"),
                        _count_result(result, "paper_orders_filled", "filled"),
                        _count_result(result, "rejection_count", "skipped", "skipped_symbols"),
                        1 if status == "failed" else 0,
                        failure_reason,
                        json.dumps(result, default=str, sort_keys=True),
                        job_run_id,
                    ),
                )
                row = cur.fetchone()
            conn.commit()
        return dict(row) if row else {"job_run_id": job_run_id, "status": "missing"}
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        with conn:
            conn.execute(
                """
                UPDATE SCHEDULED_JOB_RUNS
                SET completed_at = ?, status = ?, assets_processed = ?,
                    recommendations_created = ?, shadow_decisions_created = ?,
                    paper_orders_submitted = ?, paper_orders_filled = ?,
                    rejection_count = ?, failure_count = ?, failure_reason = ?,
                    payload_json = ?
                WHERE job_run_id = ?
                """,
                (
                    utc_now_iso(),
                    status,
                    _count_result(result, "assets_processed", "symbols", "symbols_examined"),
                    _count_result(result, "recommendations_created", "proposals"),
                    _count_result(result, "shadow_decisions_created", "shadow_decisions"),
                    _count_result(result, "paper_orders_submitted", "submitted", "result"),
                    _count_result(result, "paper_orders_filled", "filled"),
                    _count_result(result, "rejection_count", "skipped", "skipped_symbols"),
                    1 if status == "failed" else 0,
                    failure_reason,
                    json.dumps(result, default=str, sort_keys=True),
                    job_run_id,
                ),
            )
            row = conn.execute("SELECT * FROM SCHEDULED_JOB_RUNS WHERE job_run_id = ?", (job_run_id,)).fetchone()
    return dict(row) if row else {"job_run_id": job_run_id, "status": "missing"}


def record_worker_heartbeat(
    db_path: Path,
    *,
    worker_id: str,
    worker_type: str,
    status: str = "running",
    current_job: str | None = None,
    last_successful_job: str | None = None,
    last_error: str | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    initialize_always_on_schema(db_path)
    now = utc_now_iso()
    deployment_commit = os.getenv("RENDER_GIT_COMMIT") or os.getenv("GIT_COMMIT")
    if _use_postgres():
        with _postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT started_at FROM WORKER_HEARTBEATS WHERE worker_id = %s", (worker_id,))
                existing = cur.fetchone()
                started_at = existing["started_at"] if existing else now
                cur.execute(
                    """
                    INSERT INTO WORKER_HEARTBEATS (
                        worker_id, worker_type, started_at, last_heartbeat_at, status,
                        current_job, last_successful_job, last_error, deployment_commit, payload_json
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(worker_id) DO UPDATE SET
                        worker_type = excluded.worker_type,
                        last_heartbeat_at = excluded.last_heartbeat_at,
                        status = excluded.status,
                        current_job = excluded.current_job,
                        last_successful_job = COALESCE(excluded.last_successful_job, WORKER_HEARTBEATS.last_successful_job),
                        last_error = excluded.last_error,
                        deployment_commit = excluded.deployment_commit,
                        payload_json = excluded.payload_json
                    RETURNING *
                    """,
                    (
                        worker_id,
                        worker_type,
                        started_at,
                        now,
                        status,
                        current_job,
                        last_successful_job,
                        last_error,
                        deployment_commit,
                        json.dumps(payload or {}, default=str, sort_keys=True),
                    ),
                )
                row = cur.fetchone()
            conn.commit()
        return dict(row)
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        with conn:
            existing = conn.execute("SELECT started_at FROM WORKER_HEARTBEATS WHERE worker_id = ?", (worker_id,)).fetchone()
            started_at = existing["started_at"] if existing else now
            conn.execute(
                """
                INSERT INTO WORKER_HEARTBEATS (
                    worker_id, worker_type, started_at, last_heartbeat_at, status,
                    current_job, last_successful_job, last_error, deployment_commit, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(worker_id) DO UPDATE SET
                    worker_type = excluded.worker_type,
                    last_heartbeat_at = excluded.last_heartbeat_at,
                    status = excluded.status,
                    current_job = excluded.current_job,
                    last_successful_job = COALESCE(excluded.last_successful_job, WORKER_HEARTBEATS.last_successful_job),
                    last_error = excluded.last_error,
                    deployment_commit = excluded.deployment_commit,
                    payload_json = excluded.payload_json
                """,
                (
                    worker_id,
                    worker_type,
                    started_at,
                    now,
                    status,
                    current_job,
                    last_successful_job,
                    last_error,
                    deployment_commit,
                    json.dumps(payload or {}, default=str, sort_keys=True),
                ),
            )
            row = conn.execute("SELECT * FROM WORKER_HEARTBEATS WHERE worker_id = ?", (worker_id,)).fetchone()
    return dict(row)


def record_research_funnel(
    db_path: Path,
    *,
    broker: str,
    asset_type: str,
    trigger_type: str,
    symbols_examined: int,
    symbols_with_adequate_data: int,
    interesting_ideas: int,
    valid_strategies: int,
    committee_approved: int,
    portfolio_approved: int,
    guardrail_approved: int,
    eligible_for_paper_execution: int,
    submitted: int,
    filled: int,
    rejected: int,
    expired: int = 0,
    primary_reason: str | None = None,
    secondary_reasons: list[str] | None = None,
    payload: dict[str, Any] | None = None,
    job_run_id: int | None = None,
) -> dict[str, Any]:
    initialize_always_on_schema(db_path)
    values = (
        utc_now_iso(),
        job_run_id,
        broker.lower(),
        asset_type.lower(),
        trigger_type,
        symbols_examined,
        symbols_with_adequate_data,
        interesting_ideas,
        valid_strategies,
        committee_approved,
        portfolio_approved,
        guardrail_approved,
        eligible_for_paper_execution,
        submitted,
        filled,
        rejected,
        expired,
        primary_reason,
        json.dumps(secondary_reasons or []),
        json.dumps(payload or {}, default=str, sort_keys=True),
    )
    if _use_postgres():
        with _postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO RESEARCH_FUNNELS (
                        created_at, job_run_id, broker, asset_type, trigger_type,
                        symbols_examined, symbols_with_adequate_data, interesting_ideas,
                        valid_strategies, committee_approved, portfolio_approved,
                        guardrail_approved, eligible_for_paper_execution, submitted,
                        filled, rejected, expired, primary_reason, secondary_reasons_json,
                        payload_json
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    values,
                )
                row = cur.fetchone()
            conn.commit()
        return dict(row)
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        with conn:
            conn.execute(
                """
                INSERT INTO RESEARCH_FUNNELS (
                    created_at, job_run_id, broker, asset_type, trigger_type,
                    symbols_examined, symbols_with_adequate_data, interesting_ideas,
                    valid_strategies, committee_approved, portfolio_approved,
                    guardrail_approved, eligible_for_paper_execution, submitted,
                    filled, rejected, expired, primary_reason, secondary_reasons_json,
                    payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            row = conn.execute("SELECT * FROM RESEARCH_FUNNELS ORDER BY funnel_id DESC LIMIT 1").fetchone()
    return dict(row)


def record_shadow_trade(
    db_path: Path,
    *,
    symbol: str,
    asset_type: str,
    intended_broker: str,
    decision_status: str,
    strategy: str | None = None,
    regime: str | None = None,
    intended_entry: float | None = None,
    stop_loss: float | None = None,
    take_profit: float | None = None,
    quantity: float | None = None,
    notional: float | None = None,
    probability: float | None = None,
    expected_r: float | None = None,
    strongest_argument_for: str | None = None,
    strongest_argument_against: str | None = None,
    wait_or_rejection_reason: str | None = None,
    market_evidence: dict[str, Any] | None = None,
    portfolio_snapshot: dict[str, Any] | None = None,
    data_quality: dict[str, Any] | None = None,
    expires_at: str | None = None,
    simulated_costs: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    initialize_always_on_schema(db_path)
    now = utc_now_iso()
    idempotency_key = idempotency_key or f"{symbol}:{intended_broker}:{decision_status}:{now[:16]}"
    values = (
        now,
        now,
        symbol.upper(),
        asset_type.lower(),
        intended_broker.lower(),
        strategy,
        regime,
        decision_status,
        intended_entry,
        stop_loss,
        take_profit,
        quantity,
        notional,
        probability,
        expected_r,
        strongest_argument_for,
        strongest_argument_against,
        wait_or_rejection_reason,
        json.dumps(market_evidence or {}, default=str, sort_keys=True),
        json.dumps(portfolio_snapshot or {}, default=str, sort_keys=True),
        json.dumps(data_quality or {}, default=str, sort_keys=True),
        expires_at,
        json.dumps(simulated_costs or {}, default=str, sort_keys=True),
        idempotency_key,
    )
    if _use_postgres():
        with _postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO SHADOW_TRADES (
                        created_at, updated_at, symbol, asset_type, intended_broker, strategy,
                        regime, decision_status, intended_entry, stop_loss, take_profit,
                        quantity, notional, probability, expected_r, strongest_argument_for,
                        strongest_argument_against, wait_or_rejection_reason,
                        market_evidence_json, portfolio_snapshot_json, data_quality_json,
                        expires_at, simulated_costs_json, idempotency_key
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(idempotency_key) DO NOTHING
                    """,
                    values,
                )
                cur.execute("SELECT * FROM SHADOW_TRADES WHERE idempotency_key = %s", (idempotency_key,))
                row = cur.fetchone()
            conn.commit()
        return dict(row)
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        with conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO SHADOW_TRADES (
                    created_at, updated_at, symbol, asset_type, intended_broker, strategy,
                    regime, decision_status, intended_entry, stop_loss, take_profit,
                    quantity, notional, probability, expected_r, strongest_argument_for,
                    strongest_argument_against, wait_or_rejection_reason,
                    market_evidence_json, portfolio_snapshot_json, data_quality_json,
                    expires_at, simulated_costs_json, idempotency_key
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            row = conn.execute("SELECT * FROM SHADOW_TRADES WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
    return dict(row)


def update_shadow_outcome(
    db_path: Path,
    shadow_trade_id: int,
    *,
    outcome_status: str,
    theoretical_fill_price: float | None = None,
    final_price: float | None = None,
    gross_r: float | None = None,
    estimated_net_r: float | None = None,
    mae: float | None = None,
    mfe: float | None = None,
    holding_time_minutes: float | None = None,
    benchmark_outcome: str | None = None,
) -> dict[str, Any]:
    initialize_always_on_schema(db_path)
    values = (
        utc_now_iso(),
        outcome_status,
        theoretical_fill_price,
        final_price,
        gross_r,
        estimated_net_r,
        mae,
        mfe,
        holding_time_minutes,
        benchmark_outcome,
        shadow_trade_id,
    )
    if _use_postgres():
        with _postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE SHADOW_TRADES
                    SET updated_at = %s, outcome_status = %s, theoretical_fill_price = %s,
                        final_price = %s, gross_r = %s, estimated_net_r = %s, mae = %s, mfe = %s,
                        holding_time_minutes = %s, benchmark_outcome = %s
                    WHERE shadow_trade_id = %s
                    RETURNING *
                    """,
                    values,
                )
                row = cur.fetchone()
            conn.commit()
        return dict(row) if row else {"shadow_trade_id": shadow_trade_id, "status": "missing"}
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        with conn:
            conn.execute(
                """
                UPDATE SHADOW_TRADES
                SET updated_at = ?, outcome_status = ?, theoretical_fill_price = ?,
                    final_price = ?, gross_r = ?, estimated_net_r = ?, mae = ?, mfe = ?,
                    holding_time_minutes = ?, benchmark_outcome = ?
                WHERE shadow_trade_id = ?
                """,
                values,
            )
            row = conn.execute("SELECT * FROM SHADOW_TRADES WHERE shadow_trade_id = ?", (shadow_trade_id,)).fetchone()
    return dict(row) if row else {"shadow_trade_id": shadow_trade_id, "status": "missing"}


def record_operations_incident(
    db_path: Path,
    *,
    severity: str,
    component: str,
    title: str,
    message: str,
    status: str = "open",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    initialize_always_on_schema(db_path)
    values = (utc_now_iso(), severity, component, status, title, message, json.dumps(payload or {}, default=str))
    if _use_postgres():
        with _postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO OPERATIONS_INCIDENTS (
                        created_at, severity, component, status, title, message, payload_json
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    values,
                )
                row = cur.fetchone()
            conn.commit()
        return dict(row)
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        with conn:
            conn.execute(
                """
                INSERT INTO OPERATIONS_INCIDENTS (
                    created_at, severity, component, status, title, message, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            row = conn.execute("SELECT * FROM OPERATIONS_INCIDENTS ORDER BY incident_id DESC LIMIT 1").fetchone()
    return dict(row)


def list_job_runs(db_path: Path, *, limit: int = 50, job_name: str | None = None) -> list[dict[str, Any]]:
    initialize_always_on_schema(db_path)
    params: tuple[Any, ...]
    sql = "SELECT * FROM SCHEDULED_JOB_RUNS"
    if job_name:
        sql += " WHERE job_name = %s" if _use_postgres() else " WHERE job_name = ?"
        params = (job_name,)
    else:
        params = ()
    sql += " ORDER BY COALESCE(started_at, scheduled_for) DESC, job_run_id DESC LIMIT "
    sql += "%s" if _use_postgres() else "?"
    params = (*params, int(limit))
    if _use_postgres():
        with _postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return [dict(row) for row in cur.fetchall()]
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(sql, params)]


def list_worker_heartbeats(db_path: Path) -> list[dict[str, Any]]:
    initialize_always_on_schema(db_path)
    if _use_postgres():
        with _postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM WORKER_HEARTBEATS ORDER BY last_heartbeat_at DESC")
                return [dict(row) for row in cur.fetchall()]
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute("SELECT * FROM WORKER_HEARTBEATS ORDER BY last_heartbeat_at DESC")]


def list_shadow_trades(db_path: Path, *, broker: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    initialize_always_on_schema(db_path)
    sql = "SELECT * FROM SHADOW_TRADES"
    params: tuple[Any, ...] = ()
    if broker:
        sql += " WHERE intended_broker = %s" if _use_postgres() else " WHERE intended_broker = ?"
        params = (broker.lower(),)
    sql += " ORDER BY created_at DESC, shadow_trade_id DESC LIMIT "
    sql += "%s" if _use_postgres() else "?"
    params = (*params, int(limit))
    if _use_postgres():
        with _postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return [dict(row) for row in cur.fetchall()]
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(sql, params)]


def list_research_funnels(db_path: Path, *, broker: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    initialize_always_on_schema(db_path)
    sql = "SELECT * FROM RESEARCH_FUNNELS"
    params: tuple[Any, ...] = ()
    if broker:
        sql += " WHERE broker = %s" if _use_postgres() else " WHERE broker = ?"
        params = (broker.lower(),)
    sql += " ORDER BY created_at DESC, funnel_id DESC LIMIT "
    sql += "%s" if _use_postgres() else "?"
    params = (*params, int(limit))
    if _use_postgres():
        with _postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return [dict(row) for row in cur.fetchall()]
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(sql, params)]


def shadow_performance(db_path: Path) -> dict[str, Any]:
    rows = list_shadow_trades(db_path, limit=500)
    completed = [row for row in rows if row.get("outcome_status") not in {None, "pending"}]
    gross_rs = [safe_float(row.get("gross_r")) for row in completed]
    gross_rs = [value for value in gross_rs if value is not None]
    return {
        "shadow_trades_total": len(rows),
        "pending": len(rows) - len(completed),
        "completed": len(completed),
        "average_gross_r": sum(gross_rs) / len(gross_rs) if gross_rs else None,
        "wins": len([value for value in gross_rs if value > 0]),
        "losses": len([value for value in gross_rs if value < 0]),
        "note": "Shadow trades are simulated decisions only. They never submit broker orders.",
    }


def operations_health(db_path: Path, *, expected_worker_interval_seconds: int = 120) -> dict[str, Any]:
    initialize_always_on_schema(db_path)
    now = datetime.now(timezone.utc)
    workers = list_worker_heartbeats(db_path)
    latest_jobs = list_job_runs(db_path, limit=10)
    latest_funnels = list_research_funnels(db_path, limit=5)
    try:
        latest_research = latest_research_run(db_path)
    except sqlite3.Error:
        latest_research = None
    incidents = _open_incidents(db_path)
    worker_states = []
    for row in workers:
        age = _age_seconds(row.get("last_heartbeat_at"), now)
        healthy = age is not None and age <= expected_worker_interval_seconds * 2
        worker_states.append({
            **row,
            "age_seconds": age,
            "healthy": healthy,
            "plain_english": (
                "Worker is heartbeating normally."
                if healthy
                else "Worker heartbeat is stale or missing; background work may not be running."
            ),
        })
    has_worker = any(item.get("healthy") for item in worker_states)
    latest_equity = _latest_funnel_for(latest_funnels, "alpaca")
    latest_crypto = _latest_funnel_for(latest_funnels, "kraken")
    db_path_text = str(db_path)
    durable = db_path.is_absolute() and (db_path_text.startswith("/data") or ":\\data" in db_path_text.lower())
    backend = database_backend_status(db_path)
    return {
        "generated_at": utc_now_iso(),
        "overall": "healthy" if has_worker and not incidents else "attention_needed",
        "api_health": "available",
        "worker_health": "healthy" if has_worker else "not_proven",
        "database_backend": backend,
        "database_durability": (
            "supabase_postgres" if backend["active_backend"] == "postgres"
            else "persistent_disk_path" if durable
            else "not_proven_from_path"
        ),
        "database_path": db_path_text,
        "last_equity_research": latest_equity,
        "last_crypto_research": latest_crypto,
        "last_research_run": latest_research,
        "last_job_runs": latest_jobs,
        "workers": worker_states,
        "incidents": incidents,
        "plain_english": _operations_plain_english(has_worker, latest_equity, latest_crypto, incidents),
    }


def scheduler_status(db_path: Path) -> dict[str, Any]:
    jobs = list_job_runs(db_path, limit=30)
    workers = list_worker_heartbeats(db_path)
    return {
        "status": "active" if any(_age_seconds(row.get("last_heartbeat_at"), datetime.now(timezone.utc)) is not None for row in workers) else "not_proven",
        "workers": workers,
        "recent_jobs": jobs,
        "supported_jobs": [
            "premarket-equity",
            "market-open-equity",
            "midday-equity",
            "market-close-equity",
            "overnight-crypto",
            "daily-learning",
            "daily-report",
            "auto-execution",
            "broker-poll",
            "managed-exits",
        ],
    }


def alpaca_inactivity_diagnosis(db_path: Path) -> dict[str, Any]:
    initialize_always_on_schema(db_path)
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        last_research = conn.execute(
            "SELECT * FROM RESEARCH_RUNS WHERE markets_reviewed LIKE '%Alpaca%' ORDER BY research_run_id DESC LIMIT 1"
        ).fetchone()
        last_proposal = conn.execute(
            "SELECT created_at, proposal_id, symbol, ai_confidence, validation_result FROM trade_audit WHERE event_type = 'agent_proposal' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        last_rejected = conn.execute(
            "SELECT created_at, proposal_id, symbol, execution_result FROM trade_audit WHERE event_type = 'execution_rejected' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        last_order = conn.execute(
            "SELECT * FROM BROKER_TRADE_HISTORY WHERE broker = 'alpaca' ORDER BY trade_history_id DESC LIMIT 1"
        ).fetchone()
        control = conn.execute("SELECT * FROM engine_control WHERE id = 1").fetchone()
        funnel_rows = [dict(row) for row in conn.execute("SELECT * FROM RESEARCH_FUNNELS WHERE broker = 'alpaca' ORDER BY funnel_id DESC LIMIT 20")]
        decision_rows = [dict(row) for row in conn.execute("SELECT * FROM ORCHESTRATOR_DECISIONS ORDER BY decision_id DESC LIMIT 50")]
    reasons = []
    for row in funnel_rows:
        if row.get("primary_reason"):
            reasons.append(row["primary_reason"])
    for row in decision_rows:
        if row.get("decision") != "approved" and row.get("rejection_reason"):
            reasons.append(row["rejection_reason"])
    top_reasons = _top_counts(reasons)
    last_eligible = next((row for row in funnel_rows if int(row.get("eligible_for_paper_execution") or 0) > 0), None)
    fault = not last_research or _age_seconds(dict(last_research).get("completed_at"), datetime.now(timezone.utc)) is None
    return {
        "last_successful_research_cycle": dict(last_research) if last_research else None,
        "last_proposal": dict(last_proposal) if last_proposal else None,
        "last_valid_strategy": _latest_approved(decision_rows),
        "last_eligible_paper_recommendation": last_eligible,
        "last_submitted_paper_order": dict(last_order) if last_order else None,
        "last_filled_paper_order": dict(last_order) if last_order and str(last_order["status"]).lower() == "filled" else None,
        "current_global_trading_state": dict(control) if control else None,
        "current_alpaca_auto_trading_state": _broker_auto_state(db_path, "alpaca"),
        "current_market_state": "unknown - requires live Alpaca clock check during job execution",
        "top_rejection_reasons": {
            "1_day": top_reasons,
            "7_days": top_reasons,
            "30_days": top_reasons,
        },
        "expected_or_fault": "operational_fault" if fault else "explainable_from_recorded_reasons",
        "plain_english": (
            "No Alpaca research records were found, so inactivity is an operational fault until a scheduled cycle proves otherwise."
            if not last_research
            else "Alpaca inactivity can now be traced through persisted research funnels and rejection reasons."
        ),
    }


def default_worker_id(worker_type: str) -> str:
    return f"{worker_type}-{os.getenv('RENDER_INSTANCE_ID') or uuid.uuid4().hex[:8]}"


def _open_incidents(db_path: Path) -> list[dict[str, Any]]:
    if _use_postgres():
        with _postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM OPERATIONS_INCIDENTS WHERE status = 'open' ORDER BY incident_id DESC LIMIT 10"
                )
                return [dict(row) for row in cur.fetchall()]
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        return [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM OPERATIONS_INCIDENTS WHERE status = 'open' ORDER BY incident_id DESC LIMIT 10"
            )
        ]


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


def _latest_funnel_for(rows: list[dict[str, Any]], broker: str) -> dict[str, Any] | None:
    return next((row for row in rows if row.get("broker") == broker), None)


def _operations_plain_english(
    has_worker: bool,
    latest_equity: dict[str, Any] | None,
    latest_crypto: dict[str, Any] | None,
    incidents: list[dict[str, Any]],
) -> str:
    if incidents:
        return f"{len(incidents)} operations incident(s) require attention."
    if not has_worker:
        return "The API is available, but a separate background worker heartbeat has not been proven yet."
    if latest_equity or latest_crypto:
        return "Background operations have persisted research or job evidence independent of the mobile app."
    return "Worker heartbeat exists, but no completed research funnel has been recorded yet."


def _count_result(result: dict[str, Any], *keys: str) -> int:
    for key in keys:
        value = result.get(key)
        if isinstance(value, list):
            return len(value)
        if isinstance(value, dict):
            return len(value)
        if isinstance(value, (int, float)):
            return int(value)
    return 0


def _top_counts(values: list[str]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for value in values:
        if value:
            counts[value] = counts.get(value, 0) + 1
    return [{"reason": key, "count": value} for key, value in sorted(counts.items(), key=lambda item: item[1], reverse=True)[:10]]


def _latest_approved(decisions: list[dict[str, Any]]) -> dict[str, Any] | None:
    return next((row for row in decisions if row.get("decision") == "approved"), None)


def _broker_auto_state(db_path: Path, broker: str) -> dict[str, Any]:
    try:
        with closing(sqlite3.connect(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM BROKER_AUTO_TRADING_SETTINGS WHERE broker = ?",
                (broker,),
            ).fetchone()
            return dict(row) if row else {"broker": broker, "enabled": False, "source": "no persisted broker setting"}
    except sqlite3.OperationalError:
        return {"broker": broker, "enabled": False, "source": "settings table unavailable"}


def _database_url() -> str | None:
    return os.getenv("DATABASE_URL") or os.getenv("SUPABASE_DATABASE_URL")


def _use_postgres() -> bool:
    requested = os.getenv("AI_TRADER_DATABASE_BACKEND", "sqlite").strip().lower()
    return requested in {"postgres", "postgresql", "supabase"} and bool(_database_url())


def uses_postgres() -> bool:
    """Return whether durable production evidence is configured for Postgres."""
    return _use_postgres()


def _postgres_connection():
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:  # pragma: no cover - exercised only when postgres mode is enabled without dependency
        raise RuntimeError(
            "Postgres backend requested but psycopg is not installed. Install ai-trading-assistant with psycopg[binary]."
        ) from exc
    url = _database_url()
    if not url:
        raise RuntimeError("Postgres backend requested but DATABASE_URL/SUPABASE_DATABASE_URL is not configured.")
    return psycopg.connect(url, row_factory=dict_row)


def postgres_connection():
    """Open the shared production connection used by API and worker processes."""
    return _postgres_connection()
