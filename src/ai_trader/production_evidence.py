from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from .always_on import classify_worker_presence, initialize_always_on_schema, postgres_connection, uses_postgres
from .daily_plan import daily_trading_plan_status
from .database import connect
from .models import utc_now_iso
from .multi_broker import open_managed_exits


SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS PRODUCTION_RESEARCH_EVIDENCE (
    evidence_id INTEGER PRIMARY KEY AUTOINCREMENT,
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    broker TEXT NOT NULL,
    asset_type TEXT NOT NULL,
    trigger_type TEXT NOT NULL,
    provider TEXT,
    symbols_json TEXT NOT NULL,
    assets_analysed INTEGER NOT NULL DEFAULT 0,
    recommendations_created INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    freshness_status TEXT NOT NULL,
    data_quality_status TEXT NOT NULL,
    no_action_reason TEXT,
    summary TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_production_research_broker_time
ON PRODUCTION_RESEARCH_EVIDENCE(broker, completed_at DESC);

CREATE TABLE IF NOT EXISTS PRODUCTION_RECOMMENDATION_EVIDENCE (
    recommendation_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    expires_at TEXT,
    broker TEXT NOT NULL,
    symbol TEXT NOT NULL,
    asset_type TEXT NOT NULL,
    side TEXT NOT NULL,
    status TEXT NOT NULL,
    confidence REAL,
    entry_price REAL,
    stop_loss REAL,
    take_profit REAL,
    position_size REAL,
    strongest_argument_for TEXT,
    strongest_argument_against TEXT,
    no_action_reason TEXT,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_production_recommendations_time
ON PRODUCTION_RECOMMENDATION_EVIDENCE(created_at DESC);

CREATE TABLE IF NOT EXISTS PRODUCTION_BROKER_SNAPSHOTS (
    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    idempotency_key TEXT NOT NULL UNIQUE,
    captured_at TEXT NOT NULL,
    broker TEXT NOT NULL,
    connection_status TEXT NOT NULL,
    account_mode TEXT,
    currency TEXT,
    portfolio_value REAL,
    cash REAL,
    buying_power REAL,
    deployed_capital REAL,
    day_pnl REAL,
    week_pnl REAL,
    month_pnl REAL,
    open_positions INTEGER NOT NULL DEFAULT 0,
    positions_json TEXT NOT NULL,
    reconciliation_status TEXT,
    source TEXT,
    error TEXT,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_production_broker_snapshots_time
ON PRODUCTION_BROKER_SNAPSHOTS(broker, captured_at DESC);

CREATE TABLE IF NOT EXISTS PRODUCTION_TRADE_EVIDENCE (
    trade_evidence_id INTEGER PRIMARY KEY AUTOINCREMENT,
    idempotency_key TEXT NOT NULL UNIQUE,
    observed_at TEXT NOT NULL,
    broker TEXT NOT NULL,
    broker_order_id TEXT,
    broker_trade_id TEXT,
    symbol TEXT,
    side TEXT,
    status TEXT NOT NULL,
    quantity REAL,
    price REAL,
    average_fill_price REAL,
    fee REAL,
    realized_pnl REAL,
    opened_at TEXT,
    closed_at TEXT,
    entry_reason TEXT,
    exit_reason TEXT,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_production_trade_broker_time
ON PRODUCTION_TRADE_EVIDENCE(broker, observed_at DESC);

CREATE TABLE IF NOT EXISTS PRODUCTION_LEARNING_EVIDENCE (
    learning_id INTEGER PRIMARY KEY AUTOINCREMENT,
    idempotency_key TEXT NOT NULL UNIQUE,
    completed_at TEXT NOT NULL,
    broker TEXT,
    logical_trade_id TEXT,
    status TEXT NOT NULL,
    summary TEXT NOT NULL,
    realized_pnl REAL,
    gross_r REAL,
    net_r REAL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_production_learning_time
ON PRODUCTION_LEARNING_EVIDENCE(completed_at DESC);

CREATE TABLE IF NOT EXISTS PRODUCTION_FOUNDER_EVIDENCE_SNAPSHOTS (
    period TEXT PRIMARY KEY,
    generated_at TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS PRODUCTION_EVIDENCE_MAINTENANCE (
    task_name TEXT PRIMARY KEY,
    last_run_at TEXT NOT NULL
);
"""

POSTGRES_SCHEMA = SQLITE_SCHEMA.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY").replace(" REAL", " DOUBLE PRECISION")

_SCHEMA_LOCK = threading.Lock()
_INITIALIZED_SCHEMA_KEYS: set[str] = set()
FOUNDER_SNAPSHOT_MAX_AGE_SECONDS = 15 * 60
PRODUCTION_EVIDENCE_RETENTION_INTERVAL = timedelta(hours=24)
PRODUCTION_EVIDENCE_RETENTION_DAYS = {
    "PRODUCTION_BROKER_SNAPSHOTS": ("captured_at", 30),
    "PRODUCTION_RESEARCH_EVIDENCE": ("completed_at", 90),
    "PRODUCTION_RECOMMENDATION_EVIDENCE": ("created_at", 90),
    "PRODUCTION_LEARNING_EVIDENCE": ("completed_at", 365),
}

# 2026-08-08 Supabase database-size emergency: /database-diagnostics showed these high-volume
# decision/audit-log tables (one row per governance decision or scheduled job run), not the
# Founder-evidence snapshot tables above, are the real bulk of database size (~339 MB of 428 MB
# total measured that day), and that VACUUM cannot reclaim their space since they hold almost
# no dead rows -- the only way to shrink them is fewer live rows. Founder-directed policy: a
# 90-day cutoff, but never delete a row that is either a rejected/blocked/manual-review
# governance decision (the risk controls actually firing -- worth reviewing regardless of age)
# or linked to a proposal whose eventual trade outcome was a notably large win or loss.
DECISION_AUDIT_RETENTION_DAYS = 90
NOTABLE_R_MULTIPLE_THRESHOLD = 2.0

# Every protect_column/protect_values pair was read directly from the real call sites that
# write it (foundation.py's record_execution_decision/calculate_capital_allocation,
# orchestrator.py's evaluate_recommendation, production_spine.py's portfolio-manager decision,
# sprint6.py's strategy-entitlement/risk-sentinel decisions, always_on.py's job-run status),
# not guessed -- see the commit message / IMPLEMENTATION_LOG entry for the verification.
DECISION_AUDIT_TABLES: dict[str, dict[str, Any]] = {
    "DECISION_JOURNAL": {
        "timestamp_column": "created_at",
        "proposal_id_column": "proposal_id",
        "protect_column": "final_decision",
        "protect_values": ("blocked",),
    },
    "EXECUTION_DECISIONS": {
        "timestamp_column": "created_at",
        "proposal_id_column": "proposal_id",
        "protect_column": "decision",
        "protect_values": ("rejected", "manual_approval_required"),
    },
    "ORCHESTRATOR_DECISIONS": {
        "timestamp_column": "created_at",
        "proposal_id_column": "recommendation_id",  # holds the same value as proposal_id elsewhere
        "protect_column": "decision",
        "protect_values": ("rejected", "manual_approval_required"),
    },
    "PORTFOLIO_MANAGER_DECISIONS": {
        "timestamp_column": "created_at",
        "proposal_id_column": "proposal_id",
        "protect_column": "decision",
        "protect_values": ("reject", "manual_review"),
    },
    "STRATEGY_ENTITLEMENT_DECISIONS": {
        "timestamp_column": "created_at",
        "proposal_id_column": "proposal_id",
        "protect_column": "decision",
        "protect_values": ("blocked",),
    },
    "PRODUCTION_RISK_SENTINEL_DECISIONS": {
        "timestamp_column": "created_at",
        "proposal_id_column": "proposal_id",
        "protect_column": "decision",
        "protect_values": ("blocked",),
    },
    "CAPITAL_ALLOCATION_HISTORY": {
        "timestamp_column": "created_at",
        "proposal_id_column": "proposal_id",
        "protect_column": "result",
        "protect_values": ("rejected",),
    },
    "OPERATIONAL_EVENTS": {
        "timestamp_column": "created_at",
        "proposal_id_column": "proposal_id",
        "protect_column": "severity",
        "protect_values": ("error", "warning"),
    },
    "SCHEDULED_JOB_RUNS": {
        "timestamp_column": "scheduled_for",
        "proposal_id_column": None,
        "protect_column": "status",
        "protect_values": ("failed", "timed_out"),
    },
    # No decision/status field of their own -- protected only via the notable-outcome
    # proposal_id set (TRADE_SIGNALS) or, for PORTFOLIO_EXPOSURE_SNAPSHOTS (no proposal_id at
    # all), a straightforward age cutoff.
    "TRADE_SIGNALS": {
        "timestamp_column": "created_at",
        "proposal_id_column": "proposal_id",
        "protect_column": None,
        "protect_values": (),
    },
    "PORTFOLIO_EXPOSURE_SNAPSHOTS": {
        "timestamp_column": "created_at",
        "proposal_id_column": None,
        "protect_column": None,
        "protect_values": (),
    },
    # BROKER_TRADE_HISTORY is deliberately NOT in this dict. 2026-08-08 incident: its
    # updated_at is populated from whichever of several broker-supplied fields is present
    # first (multi_broker.py's record_broker_trade_history) -- for Kraken specifically this
    # can be closetm/opentm, raw Unix-epoch numbers, not ISO-8601 strings. A string cutoff
    # comparison against an epoch-formatted value is not reliably ordered (e.g. "162..." can
    # sort before "2026-..." purely lexicographically), and a real production run deleted all
    # rows in this table as a result -- confirmed recoverable (this table is a local cache
    # repopulated every ~10 minutes from Alpaca/Kraken's own APIs via the broker-poll jobs,
    # not the canonical trade record), but never add this table back without first normalizing
    # updated_at to a real, consistently-ISO timestamp at write time.
}


def initialize_production_evidence_schema(db_path: Path) -> None:
    schema_key = _schema_key(db_path)
    if schema_key in _INITIALIZED_SCHEMA_KEYS:
        return
    with _SCHEMA_LOCK:
        if schema_key in _INITIALIZED_SCHEMA_KEYS:
            return
        if uses_postgres():
            with postgres_connection() as conn:
                with conn.cursor() as cur:
                    for statement in POSTGRES_SCHEMA.split(";"):
                        if statement.strip():
                            cur.execute(statement)
                conn.commit()
        else:
            db_path.parent.mkdir(parents=True, exist_ok=True)
            with closing(connect(db_path)) as conn:
                conn.executescript(SQLITE_SCHEMA)
        _INITIALIZED_SCHEMA_KEYS.add(schema_key)


def _ensure_local_production_evidence_schema(db_path: Path) -> None:
    """Bootstrap isolated SQLite databases without running hosted DDL in hot paths."""
    if not uses_postgres():
        initialize_production_evidence_schema(db_path)


def record_research_evidence(
    db_path: Path,
    *,
    idempotency_key: str,
    started_at: str,
    broker: str,
    asset_type: str,
    trigger_type: str,
    symbols: list[str],
    result: dict[str, Any],
    provider: str,
) -> dict[str, Any]:
    _ensure_local_production_evidence_schema(db_path)
    completed_at = utc_now_iso()
    proposals = result.get("proposals") if isinstance(result.get("proposals"), list) else []
    status = str(result.get("status") or "unknown")
    quality = "healthy" if status == "completed" else "unavailable"
    freshness = "fresh" if status == "completed" else "not_proven"
    no_action = None
    if not proposals:
        no_action = str(result.get("message") or _no_action_from_result(result) or "No recommendation passed the research and governance gates.")
    summary = (
        f"{broker.title()} research reviewed {len(symbols)} asset(s) and created {len(proposals)} recommendation(s)."
        if status == "completed"
        else f"{broker.title()} research did not complete: {no_action or status}."
    )
    values = (
        idempotency_key, started_at, completed_at, broker.lower(), asset_type.lower(), trigger_type,
        provider, _json(symbols), len(symbols), len(proposals), status, freshness, quality,
        no_action, summary, _json(result),
    )
    _upsert(
        db_path,
        """
        INSERT INTO PRODUCTION_RESEARCH_EVIDENCE (
            idempotency_key, created_at, completed_at, broker, asset_type, trigger_type,
            provider, symbols_json, assets_analysed, recommendations_created, status,
            freshness_status, data_quality_status, no_action_reason, summary, payload_json
        ) VALUES ({p})
        ON CONFLICT(idempotency_key) DO UPDATE SET
            completed_at=excluded.completed_at, status=excluded.status,
            recommendations_created=excluded.recommendations_created,
            freshness_status=excluded.freshness_status, data_quality_status=excluded.data_quality_status,
            no_action_reason=excluded.no_action_reason, summary=excluded.summary, payload_json=excluded.payload_json
        """,
        values,
    )
    for proposal in proposals:
        record_recommendation_evidence(db_path, proposal, broker=broker)
    return {"status": status, "summary": summary, "recommendations_created": len(proposals), "completed_at": completed_at}


def record_recommendation_evidence(db_path: Path, proposal: dict[str, Any], *, broker: str) -> None:
    _ensure_local_production_evidence_schema(db_path)
    recommendation_id = str(proposal.get("proposal_id") or proposal.get("recommendation_id") or "").strip()
    if not recommendation_id:
        return
    created_at = str(proposal.get("created_at") or utc_now_iso())
    expires_at = proposal.get("expires_at")
    if not expires_at:
        try:
            expires_at = (datetime.fromisoformat(created_at.replace("Z", "+00:00")) + timedelta(hours=4)).isoformat()
        except ValueError:
            expires_at = None
    reasoning = str(proposal.get("plain_english_reasoning") or "")
    intelligence = proposal.get("intelligence") if isinstance(proposal.get("intelligence"), dict) else {}
    committee = intelligence.get("committee") if isinstance(intelligence.get("committee"), dict) else {}
    strongest_for = proposal.get("strongest_argument_for") or committee.get("strongest_argument_for") or reasoning or None
    strongest_against = (
        proposal.get("strongest_argument_against")
        or committee.get("strongest_argument_against")
        or _risk_argument(proposal)
    )
    values = (
        recommendation_id, created_at, expires_at, broker.lower(), str(proposal.get("symbol") or "").upper(),
        str(proposal.get("asset_type") or "stock").lower(), str(proposal.get("side") or "buy").lower(),
        "actionable" if proposal.get("ai_guardrails_passed") else "review_required",
        _number(proposal.get("confidence_score") or proposal.get("confidence")), _number(proposal.get("entry_price")),
        _number(proposal.get("stop_loss")), _number(proposal.get("take_profit")), _number(proposal.get("position_size")),
        strongest_for, strongest_against, "; ".join(proposal.get("ai_guardrail_failures") or []) or None, _json(proposal),
    )
    _upsert(
        db_path,
        """
        INSERT INTO PRODUCTION_RECOMMENDATION_EVIDENCE (
            recommendation_id, created_at, expires_at, broker, symbol, asset_type, side, status,
            confidence, entry_price, stop_loss, take_profit, position_size,
            strongest_argument_for, strongest_argument_against, no_action_reason, payload_json
        ) VALUES ({p})
        ON CONFLICT(recommendation_id) DO UPDATE SET
            expires_at=excluded.expires_at, status=excluded.status, confidence=excluded.confidence,
            strongest_argument_for=excluded.strongest_argument_for,
            strongest_argument_against=excluded.strongest_argument_against,
            no_action_reason=excluded.no_action_reason, payload_json=excluded.payload_json
        """,
        values,
    )


def record_broker_snapshot(db_path: Path, panel: dict[str, Any], *, captured_at: str | None = None) -> None:
    _ensure_local_production_evidence_schema(db_path)
    broker = str(panel.get("broker") or "").lower()
    if broker not in {"alpaca", "kraken"}:
        return
    captured_at = captured_at or utc_now_iso()
    portfolio = _number(panel.get("portfolio_value"))
    cash = _number(panel.get("cash_available"))
    deployed = None if portfolio is None or cash is None else portfolio - cash
    positions = panel.get("open_positions_detail") or panel.get("open_positions")
    positions_list = positions if isinstance(positions, list) else panel.get("positions") or []
    open_count = len(positions_list) if positions_list else int(_number(panel.get("open_positions")) or 0)
    key = f"{broker}:{captured_at[:16]}"
    values = (
        key, captured_at, broker, str(panel.get("connection_status") or "unknown"),
        str(panel.get("account_mode") or ("paper" if broker == "alpaca" else "live-controlled")),
        "USD" if broker == "alpaca" else "GBP", portfolio, cash, _number(panel.get("buying_power")), deployed,
        _number(panel.get("todays_pnl")), _number(panel.get("week_pnl")), _number(panel.get("month_pnl")),
        open_count, _json(positions_list), str(panel.get("reconciliation_status") or "awaiting broker reconciliation"),
        str(panel.get("source") or "broker adapter"), panel.get("error"), _json(panel),
    )
    _upsert(
        db_path,
        """
        INSERT INTO PRODUCTION_BROKER_SNAPSHOTS (
            idempotency_key, captured_at, broker, connection_status, account_mode, currency,
            portfolio_value, cash, buying_power, deployed_capital, day_pnl, week_pnl, month_pnl,
            open_positions, positions_json, reconciliation_status, source, error, payload_json
        ) VALUES ({p}) ON CONFLICT(idempotency_key) DO NOTHING
        """,
        values,
    )


_TRADE_EVIDENCE_INSERT_SQL = """
    INSERT INTO PRODUCTION_TRADE_EVIDENCE (
        idempotency_key, observed_at, broker, broker_order_id, broker_trade_id, symbol, side,
        status, quantity, price, average_fill_price, fee, realized_pnl, opened_at, closed_at,
        entry_reason, exit_reason, payload_json
    ) VALUES ({p}) ON CONFLICT(idempotency_key) DO UPDATE SET
        observed_at=excluded.observed_at, status=excluded.status, quantity=excluded.quantity,
        price=excluded.price, average_fill_price=excluded.average_fill_price, fee=excluded.fee,
        realized_pnl=excluded.realized_pnl, closed_at=excluded.closed_at, payload_json=excluded.payload_json
"""


def _normalize_broker_timestamp(value: Any) -> str | None:
    """Convert a raw Kraken-style Unix-epoch timestamp to a real ISO-8601 UTC string.

    2026-08-19 hosted finding: Kraken's own API returns timestamps as raw epoch floats
    (e.g. a TradesHistory trade's "time" field), never ISO-8601 strings the way Alpaca's
    API does -- stored as-is, `new Date("1787154660.049352")` on the mobile side parses to
    Invalid Date, silently dropping every real Kraken exit from the Forecast Centre's
    closed-trade sample even after ai_decided correctly recognised them as AI-decided.
    This exact bug class already caused a real production incident once before (2026-08-08,
    see BROKER_TRADE_HISTORY's exclusion comment above): a plain string comparison against
    an epoch-formatted value does not sort the way a real date would, and a retention pass
    deleted rows it should have kept as a direct result -- that incident was worked around
    by excluding one table from pruning, not by fixing the root cause. This is the actual
    fix, at the one place (_trade_evidence_values) that writes every trade's observed_at/
    opened_at/closed_at. A value that fails to parse as a bare number (any real ISO string,
    which always contains non-numeric characters) passes through unchanged.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        epoch_seconds = float(text)
    except (TypeError, ValueError):
        return text
    return datetime.fromtimestamp(epoch_seconds, tz=timezone.utc).isoformat()


def _trade_evidence_values(broker: str, event: dict[str, Any]) -> tuple[Any, ...]:
    broker_order_id = _first(event, "order_id", "ordertxid", "id", "client_order_id")
    broker_trade_id = _first(event, "trade_id", "activity_id", "fill_id", "id")
    status = str(_first(event, "status", "order_status", "type") or "observed").lower()
    observed_at = _normalize_broker_timestamp(
        _first(event, "updated_at", "transaction_time", "time", "timestamp", "filled_at", "created_at")
    ) or utc_now_iso()
    symbol = _first(event, "symbol", "pair")
    quantity = _number(_first(event, "qty", "quantity", "vol", "filled_qty", "cum_qty"))
    price = _number(_first(event, "price", "filled_avg_price", "average_price", "avg_price"))
    key_parts = [broker, str(broker_order_id or ""), str(broker_trade_id or ""), status, str(quantity or ""), str(price or "")]
    idempotency_key = ":".join(key_parts)
    return (
        idempotency_key, observed_at, broker.lower(), broker_order_id, broker_trade_id,
        str(symbol).upper() if symbol else None, _first(event, "side", "type"), status, quantity, price,
        _number(_first(event, "filled_avg_price", "average_price", "avg_price")),
        _number(_first(event, "fee", "fees", "commission")), _number(_first(event, "realized_pnl", "pnl", "profit_loss")),
        _normalize_broker_timestamp(_first(event, "opened_at", "created_at")),
        _normalize_broker_timestamp(_first(event, "closed_at", "filled_at")),
        event.get("entry_reason"), event.get("exit_reason"), _json(event),
    )


def record_trade_evidence(db_path: Path, *, broker: str, event: dict[str, Any]) -> None:
    # Hosted startup owns additive Postgres migrations. Re-running the complete
    # schema script for every broker event turns a bounded poll into hundreds of
    # DDL round trips and can starve Founder-facing snapshots.
    _ensure_local_production_evidence_schema(db_path)
    _upsert(db_path, _TRADE_EVIDENCE_INSERT_SQL, _trade_evidence_values(broker, event))


def record_trade_evidence_batch(db_path: Path, *, broker: str, events: Iterable[dict[str, Any]]) -> int:
    """Persist every event from one broker-poll cycle over a single connection/transaction.

    record_trade_evidence() opens a fresh connection per call; a poll cycle with
    dozens of new broker events turned that into dozens of round trips and was a
    confirmed contributor to worker-cycle timeouts. Each event still becomes its
    own idempotent row with identical ON CONFLICT semantics -- only the connection
    is shared.
    """
    rows = [_trade_evidence_values(broker, event) for event in events if isinstance(event, dict)]
    if not rows:
        return 0
    _ensure_local_production_evidence_schema(db_path)
    if uses_postgres():
        statement = _TRADE_EVIDENCE_INSERT_SQL.format(p=", ".join(["%s"] * len(rows[0])))
        with postgres_connection() as conn:
            with conn.cursor() as cur:
                for values in rows:
                    cur.execute(statement, values)
            conn.commit()
        return len(rows)
    statement = _TRADE_EVIDENCE_INSERT_SQL.format(p=", ".join(["?"] * len(rows[0])))
    with closing(connect(db_path)) as conn:
        with conn:
            for values in rows:
                conn.execute(statement, values)
    return len(rows)


def record_learning_evidence(db_path: Path, result: dict[str, Any], *, worker_id: str) -> None:
    _ensure_local_production_evidence_schema(db_path)
    completed_at = utc_now_iso()
    key = f"{worker_id}:{completed_at[:16]}:{result.get('processed', 0)}"
    summary = f"Learning processor completed; {int(result.get('processed') or 0)} item(s) processed."
    values = (key, completed_at, None, None, str(result.get("status") or "completed"), summary, None, None, None, _json(result))
    _upsert(
        db_path,
        """INSERT INTO PRODUCTION_LEARNING_EVIDENCE (
            idempotency_key, completed_at, broker, logical_trade_id, status, summary,
            realized_pnl, gross_r, net_r, payload_json
        ) VALUES ({p}) ON CONFLICT(idempotency_key) DO NOTHING""",
        values,
    )


def founder_evidence_payload(
    db_path: Path,
    *,
    period: str = "24h",
    trade_limit: int = 100,
    prefer_snapshot: bool = True,
) -> dict[str, Any]:
    """Return a fast persisted projection with a local-only live fallback.

    Hosted mobile reads should never reconstruct the complete Founder view on
    demand. The worker owns that work and persists one row per supported period.
    """
    if prefer_snapshot:
        snapshot = load_founder_evidence_snapshot(db_path, period=period)
        if snapshot is not None:
            return snapshot
        if uses_postgres():
            return _snapshot_not_ready_payload(period)
    return _build_founder_evidence_payload(db_path, period=period, trade_limit=trade_limit)


def _build_founder_evidence_payload(db_path: Path, *, period: str, trade_limit: int) -> dict[str, Any]:
    # Schema creation belongs to process startup. Re-running DDL here opened two
    # extra hosted database connections and could block every Founder refresh.
    # Local SQLite callers may create isolated demo/test databases without a
    # long-running process, so retain idempotent local schema bootstrapping.
    if not uses_postgres():
        initialize_always_on_schema(db_path)
        initialize_production_evidence_schema(db_path)
    rows = _load_founder_evidence_rows(
        db_path,
        since=_period_start(period),
        trade_limit=trade_limit,
    )
    closed_trade_history = _load_closed_trade_history(db_path)
    return _assemble_founder_evidence_payload(rows, period=period, db_path=db_path, closed_trade_history=closed_trade_history)


def _load_closed_trade_history(db_path: Path, *, limit: int = 200) -> list[dict[str, Any]]:
    """Every terminal ('filled') trade, any broker, not bounded by the Founder-evidence
    `period` window -- 2026-08-17 hosted finding: Current Position's "Realised this month",
    the Forecast Centre, and Learning's "Closed Trades"/win-rate/total P&L all read from the
    same `trades` field this function's caller also builds from the period-scoped query
    (`_load_founder_evidence_rows`, default period=24h). A real ~$639 CSL profit had just
    been correctly computed (see backfill_realized_pnl) but was invisible in the app anyway,
    because the exit itself was 6 days old and the mobile app's default 24h window can never
    include it -- confirmed live, `/founder-evidence?period=24h` returned zero trades outright.
    That period window is legitimately correct for the "N broker order or fill event(s) are
    visible in this period" operational-activity sentence it also feeds; it was never correct
    for "how much has actually been made" or "what has the AI learned from closed trades",
    which need real history, not a rolling day. Bounded by row count (LIMIT), not time, so it
    naturally still favours the most recent closed trades without ever needing a redeploy to
    widen a hardcoded window as more trading accumulates.
    """
    rows = _query(
        db_path,
        """
        SELECT trade_evidence_id, observed_at, broker, broker_order_id, broker_trade_id,
               symbol, side, status, quantity, price, average_fill_price, fee, realized_pnl,
               opened_at, closed_at, entry_reason, exit_reason
        FROM PRODUCTION_TRADE_EVIDENCE
        WHERE status = 'filled'
        ORDER BY COALESCE(closed_at, opened_at, observed_at) DESC
        LIMIT {n}
        """,
        limit=limit,
    )
    ai_order_ids = _ai_decided_broker_order_ids(db_path)
    for row in rows:
        row["ai_decided"] = bool(row.get("broker_order_id")) and str(row["broker_order_id"]) in ai_order_ids
    return rows


def _ai_decided_broker_order_ids(db_path: Path) -> set[str]:
    """Every broker_order_id AI Trader's own production path actually submitted, entry or exit.

    2026-08-18 Founder request: separate the AI's real trading judgment from whatever else
    is sitting in a broker account. orchestrator.py's evaluate_recommendation is the only
    production ENTRY-order path (both brokers) -- it links the broker's resulting order id
    to a real proposal_id via link_broker_order(), the only call site anywhere in this
    codebase using event_source="broker_submission" (canonical_trades.py:259, confirmed via a
    full-codebase grep). That specific event_source is the actual signal, not merely "a
    LOGICAL_TRADE_EVENTS row exists for this order": 2026-08-18 hosted incident, caught
    before ever shipping to the Founder as correct -- poll_broker_activity's own routine
    broker-history reconciliation (normalize_broker_events -> reconcile_canonical_broker_event,
    source_endpoint="poll_broker_activity") ALSO writes a LOGICAL_TRADE_EVENTS row for every
    historical broker order it observes, AI-decided or not, so the query is filtered to that
    literal event_source to exclude the general reconciliation noise.

    2026-08-19 hosted finding: that signal alone still marked real, governed Kraken EXITS
    (and, it turned out, some Kraken entries too) as not AI-decided -- confirmed live, a real
    XRP position the AI had itself entered (documented due-diligence reasoning on record) and
    then exited via its own stop/take-profit management showed ai_decided=false on both legs.
    monitor_managed_exits (execution_service.py) is a SEPARATE production order-placement
    path from evaluate_recommendation -- it places every real Kraken managed exit and never
    calls link_broker_order at all, only register_kraken_order_ownership(). That function
    writes KRAKEN_AI_ORDER_OWNERSHIP unconditionally for both order_role='entry' (called from
    evaluate_recommendation too) and order_role='exit' (called only from
    monitor_managed_exits) -- unioning it in is what actually closes the gap for both legs of
    a real Kraken round trip, not just entries.
    """
    from .canonical_trades import initialize_canonical_trade_schema
    from .kraken_reconciliation import initialize_kraken_reconciliation_schema

    initialize_canonical_trade_schema(db_path)
    initialize_kraken_reconciliation_schema(db_path)
    logical_event_rows = _query(
        db_path,
        "SELECT DISTINCT broker_order_id FROM LOGICAL_TRADE_EVENTS WHERE broker_order_id IS NOT NULL AND event_source = {x}",
        ("broker_submission",),
        limit=500,
    )
    kraken_ownership_rows = _query(
        db_path,
        "SELECT DISTINCT broker_order_id FROM KRAKEN_AI_ORDER_OWNERSHIP WHERE broker_order_id IS NOT NULL",
        limit=500,
    )
    return {str(row["broker_order_id"]) for row in logical_event_rows} | {
        str(row["broker_order_id"]) for row in kraken_ownership_rows
    }


def _load_founder_evidence_rows(
    db_path: Path,
    *,
    since: str,
    trade_limit: int,
) -> tuple[list[dict[str, Any]], ...]:
    return tuple(_query_batch(
        db_path,
        [
            ("""SELECT evidence_id, created_at, completed_at, broker, asset_type, trigger_type,
                       provider, symbols_json, assets_analysed, recommendations_created, status,
                       freshness_status, data_quality_status, no_action_reason, summary
                FROM PRODUCTION_RESEARCH_EVIDENCE
                WHERE completed_at >= {x} ORDER BY completed_at DESC LIMIT 100""", (since,)),
            ("SELECT * FROM PRODUCTION_RECOMMENDATION_EVIDENCE ORDER BY created_at DESC LIMIT 100", ()),
            # 2026-08-10 Supabase egress finding: this result feeds straight into
            # _latest_per(snapshots_all, "broker") a few lines below the call site, which keeps
            # only the single newest row per broker (2 brokers today) and discards the rest --
            # LIMIT 100 was fetching full payload_json/positions_json (real TOAST-backed JSON
            # blobs, confirmed via /database-diagnostics) for ~98 rows that were thrown away
            # immediately after leaving Postgres, every single call. This query runs from the
            # 5-minute worker refresh, not from the mobile app's poll (founder_evidence_payload
            # serves that from the cheap precomputed snapshot -- confirmed via
            # prefer_snapshot=True), but still adds up over hundreds of refreshes per day.
            # LIMIT 20 keeps a wide safety margin (10x today's 2 brokers) while cutting the
            # fetched volume by ~80%.
            ("""SELECT snapshot_id, captured_at, broker, connection_status, account_mode, currency,
                       portfolio_value, cash, buying_power, deployed_capital, day_pnl, week_pnl,
                       month_pnl, open_positions, positions_json, reconciliation_status, source, error,
                       payload_json
                FROM PRODUCTION_BROKER_SNAPSHOTS ORDER BY captured_at DESC LIMIT 20""", ()),
            ("""SELECT trade_evidence_id, observed_at, broker, broker_order_id, broker_trade_id,
                       symbol, side, status, quantity, price, average_fill_price, fee, realized_pnl,
                       opened_at, closed_at, entry_reason, exit_reason
                FROM PRODUCTION_TRADE_EVIDENCE
                WHERE observed_at >= {x} ORDER BY observed_at DESC LIMIT {n}""", (since,)),
            ("""SELECT learning_id, completed_at, broker, logical_trade_id, status, summary,
                       realized_pnl, gross_r, net_r
                FROM PRODUCTION_LEARNING_EVIDENCE
                WHERE completed_at >= {x} ORDER BY completed_at DESC LIMIT 50""", (since,)),
            ("""SELECT job_run_id, job_name, scheduled_for, started_at, completed_at, status,
                       attempt, worker_id, assets_requested, assets_processed,
                       recommendations_created, shadow_decisions_created, paper_orders_submitted,
                       paper_orders_filled, rejection_count, failure_count, failure_reason
                FROM SCHEDULED_JOB_RUNS
                WHERE COALESCE(started_at, scheduled_for) >= {x}
                ORDER BY scheduled_for DESC LIMIT 100""", (since,)),
            ("""SELECT funnel_id, created_at, job_run_id, broker, asset_type, trigger_type,
                       symbols_examined, symbols_with_adequate_data, interesting_ideas,
                       valid_strategies, committee_approved, portfolio_approved,
                       guardrail_approved, eligible_for_paper_execution, submitted, filled,
                       rejected, expired, primary_reason
                FROM RESEARCH_FUNNELS
                WHERE created_at >= {x} ORDER BY created_at DESC LIMIT 100""", (since,)),
            ("""SELECT worker_id, worker_type, started_at, last_heartbeat_at, status,
                       current_job, last_successful_job, last_error, deployment_commit
                FROM WORKER_HEARTBEATS ORDER BY last_heartbeat_at DESC""", ()),
        ],
        limit=trade_limit,
    ))


# (job_key, label, expected_cadence_seconds, broker, matching job_name(s) - old
# combined name kept for continuity across the AT-ED-003 split deploy).
_JOB_HEALTH_SPECS: tuple[tuple[str, str, int, str | None, tuple[str, ...]], ...] = (
    ("broker-poll-alpaca", "Alpaca Broker Poll", 400, "alpaca", ("broker-poll-alpaca", "broker-poll")),
    ("broker-poll-kraken", "Kraken Broker Poll", 400, "kraken", ("broker-poll-kraken", "broker-poll")),
    ("auto-execution-alpaca", "Alpaca Auto-Execution", 180, "alpaca", ("auto-execution-alpaca", "auto-execution")),
    ("auto-execution-kraken", "Kraken Auto-Execution", 180, "kraken", ("auto-execution-kraken", "auto-execution")),
    ("managed-exits", "Managed Exits", 180, None, ("managed-exits",)),
    # 2026-08-19: matches production_snapshot_interval_seconds's new default (600s) --
    # config.py's own comment explains the balance between the app's 900s staleness
    # threshold and this job's known Supabase egress cost per run.
    ("evidence-snapshot", "Evidence Snapshot", 600, None, ("evidence-snapshot",)),
    ("push-dispatch", "Push Notification Dispatch", 90, None, ("push-dispatch",)),
    ("crypto-research", "Crypto Research (24/7)", 4200, None, ("crypto-research",)),
    ("daily-learning", "Daily Learning", 90000, None, ("daily-learning",)),
    ("daily-report", "Daily Report", 90000, None, ("daily-report", "weekly-report", "monthly-report")),
)


def _job_health_summary(jobs: list[dict[str, Any]], broker_payload: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Classify each scheduled job using the Founder-facing status vocabulary AT-ED-003
    Section 2 requires. A job must never read "Healthy" merely because a process
    exists somewhere in history: no recent run, a Founder-disabled broker, or a
    cycle that had nothing eligible to act on must each say so plainly and
    distinctly, not collapse into a generic "OK".
    """
    auto_enabled = {str(row.get("broker") or "").lower(): row.get("auto_trading_enabled") for row in broker_payload}
    results: list[dict[str, Any]] = []
    for job_key, label, expected_seconds, broker, names in _JOB_HEALTH_SPECS:
        broker_enabled = auto_enabled.get(broker) if broker else None
        entry: dict[str, Any] = {
            "job": job_key,
            "label": label,
            "broker": broker,
            "last_run_at": None,
            "status": "Awaiting First Run",
            "detail": "No run has been recorded for this job in the selected period.",
        }
        if broker is not None and broker_enabled is False:
            entry["status"] = "Disabled by Founder"
            entry["detail"] = "Auto trading is disabled by the Founder for this broker; new-entry jobs are not scheduled."
        matches = [row for row in jobs if row.get("job_name") in names]
        if matches:
            latest = matches[0]
            status_raw = str(latest.get("status") or "").lower()
            last_time = latest.get("completed_at") or latest.get("started_at") or latest.get("scheduled_for")
            entry["last_run_at"] = last_time
            age = _timestamp_age_seconds(last_time) if last_time else None
            if entry["status"] != "Disabled by Founder":
                if status_raw == "timed_out":
                    entry["status"] = "Timed Out"
                    entry["detail"] = latest.get("failure_reason") or "The job exceeded its execution time boundary and was terminated."
                elif status_raw == "failed":
                    entry["status"] = "Blocked"
                    entry["detail"] = latest.get("failure_reason") or "The job failed."
                elif age is not None and age > expected_seconds * 3:
                    minutes = int(age // 60)
                    expected_minutes = max(1, expected_seconds // 60)
                    entry["status"] = "Delayed"
                    entry["detail"] = f"Last run was {minutes} minute(s) ago; expected roughly every {expected_minutes} minute(s)."
                elif job_key in {"auto-execution-alpaca", "auto-execution-kraken"} and status_raw == "completed":
                    submitted = int(latest.get("paper_orders_submitted") or 0)
                    rejected = int(latest.get("rejection_count") or 0)
                    if submitted == 0 and rejected == 0:
                        entry["status"] = "No Eligible Action"
                        entry["detail"] = "No candidate recommendations were available for this broker in its last completed cycle."
                    elif submitted == 0 and rejected > 0:
                        entry["status"] = "Enabled but Blocked"
                        entry["detail"] = f"{rejected} candidate(s) were evaluated and blocked by governance or risk checks; none were submitted."
                    else:
                        entry["status"] = "Healthy"
                        entry["detail"] = f"{submitted} order(s) submitted in the last completed cycle."
                else:
                    entry["status"] = "Healthy"
                    entry["detail"] = "Last run completed within the expected schedule."
        results.append(entry)
    return results


def _assemble_founder_evidence_payload(
    rows: tuple[list[dict[str, Any]], ...],
    *,
    period: str,
    db_path: Path | None = None,
    closed_trade_history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    research, recommendations, snapshots_all, trades, learning, jobs, funnels, workers = rows
    # Defaults to the period-scoped `trades` (old behaviour) when no caller supplies the
    # broader history -- callers that matter (_build_founder_evidence_payload,
    # refresh_founder_evidence_snapshots) always do; see _load_closed_trade_history.
    closed_trade_history = trades if closed_trade_history is None else closed_trade_history
    snapshots = _latest_per(snapshots_all, "broker")
    realized_pnl = sum(_number(row.get("realized_pnl")) or 0.0 for row in closed_trade_history)
    fees = sum(_number(row.get("fee")) or 0.0 for row in closed_trade_history)
    latest_activity = _latest_activity(research, trades, learning, jobs)
    no_trade = _why_no_trade(funnels, jobs, trades)
    broker_payload = []
    for row in snapshots:
        broker_row = _lift_broker_payload_fields(_decode_row(row, {"positions_json", "payload_json"}))
        # The decoded objects are authoritative in the API contract. Keeping their original
        # JSON strings beside them doubled each broker row on every snapshot/read.
        broker_row.pop("positions_json", None)
        broker_row.pop("payload_json", None)
        broker_payload.append(broker_row)
    if db_path is not None:
        # Open, AI-tracked positions (MANAGED_TRADE_EXITS) are a distinct, explicitly-owned
        # subset of a broker's raw position list -- the raw list also includes personal/manual
        # holdings the AI never opened. Exposing this here is what lets the mobile Portfolio
        # screen show AI-managed position detail (originating recommendation, managed-exit
        # status) without ever mislabeling a manual Kraken holding as AI-managed.
        for broker_row in broker_payload:
            try:
                broker_row["managed_exits"] = [
                    _decode_row(exit_row, {"payload_json"})
                    for exit_row in open_managed_exits(db_path, broker_row.get("broker"))
                ]
            except Exception:  # noqa: BLE001 - evidence enrichment must never break the payload
                broker_row["managed_exits"] = []
    job_health = _job_health_summary(jobs, broker_payload)
    daily_plan = {}
    if db_path is not None:
        # 2026-08-14: the Founder's stated ask -- a real trader's morning strategy decision,
        # executed (or explicitly declined) for the day, visible on Executive Briefing.
        # Alpaca-only so far (daily_plan.py: crypto research already runs continuously, with
        # no single "morning" to decide against).
        try:
            daily_plan = daily_trading_plan_status(db_path, broker="alpaca")
        except Exception:  # noqa: BLE001 - evidence enrichment must never break the payload
            daily_plan = {}
    return {
        "generated_at": utc_now_iso(),
        "period": period,
        "status": {
            "state": _operating_state(workers, jobs),
            "plain_english": _operating_sentence(workers, research, jobs, no_trade),
            "last_meaningful_activity": latest_activity,
            "worker_status": "healthy" if _worker_fresh(workers) else "stale_or_missing",
            "worker": _live_worker_summary(workers),
            "scheduler_status": "active" if jobs else "no_recent_jobs",
            "database_status": "postgres" if uses_postgres() else "sqlite",
            "last_successful_research_run": research[0].get("completed_at") if research else None,
            "last_broker_poll": _latest_job_time_any(jobs, BROKER_POLL_JOB_NAMES),
            "last_report_generated": _latest_report_time(jobs),
            "unresolved_incident_count": 0,
        },
        "summary": {
            "research": {
                "runs": len(research),
                "assets_analysed": sum(int(row.get("assets_analysed") or 0) for row in research),
                "candidates": sum(int(row.get("recommendations_created") or 0) for row in research),
                "recommendations_created": sum(int(row.get("recommendations_created") or 0) for row in research),
            },
            "decisions": _decision_counts(funnels),
            "execution": {
                "orders_submitted": len([row for row in trades if row.get("status") in {"submitted", "accepted", "new"}]),
                "orders_rejected": len([row for row in trades if row.get("status") in {"rejected", "cancelled", "canceled"}]),
                "orders_filled": len([row for row in trades if "filled" in str(row.get("status") or "")]),
                "trades_closed": len([row for row in trades if row.get("status") in {"closed", "target_exit", "stop_exit", "manual_exit"}]),
            },
            "operations": {
                "broker_polls": len([row for row in jobs if row.get("job_name") in BROKER_POLL_JOB_NAMES]),
                "learning_reviews_completed": len(learning),
                "reports_generated": len([row for row in jobs if "report" in str(row.get("job_name") or "") and str(row.get("status") or "").startswith("completed")]),
                "incidents_opened": 0,
                "incidents_resolved": 0,
                "job_health": job_health,
            },
        },
        "why_no_trade": no_trade,
        "daily_plan": daily_plan,
        "portfolio": _portfolio_payload(broker_payload),
        "brokers": broker_payload,
        "trades": [_decode_row(row, {"payload_json"}) for row in trades],
        # Not bounded by `period` -- see _load_closed_trade_history's docstring. This is
        # what Current Position's "Realised this month", the Forecast Centre, and
        # Learning's closed-trade/win-rate figures read; `trades` above stays period-scoped
        # for the "N event(s) visible in this period" operational-activity sentence.
        "closed_trade_history": [_decode_row(row, {"payload_json"}) for row in closed_trade_history],
        "performance": {"realized_pnl": realized_pnl, "fees": fees, "net_realized_pnl": realized_pnl - fees},
        "research": [_decode_row(row, {"symbols_json", "payload_json"}) for row in research],
        # The frequently-read Founder projection carries bounded summaries only. Full immutable
        # dossiers remain available from the dedicated /recommendations endpoint when the
        # Founder opens that screen. This prevents four persisted period snapshots from each
        # duplicating ~4 MB of nested intelligence every five minutes.
        "recommendations": [_recommendation_summary_payload(row) for row in recommendations],
        "learning": [_decode_row(row, {"payload_json"}) for row in learning],
        "jobs": jobs[:100],
        "timeline": {"items": _timeline(research, trades, learning, jobs), "total": len(research) + len(trades) + len(learning) + len(jobs)},
        "truthfulness": {"source": "shared production evidence projection", "mock_data_used": False, "synthetic_activity_used": False},
    }


def persist_founder_evidence_snapshot(db_path: Path, payload: dict[str, Any], *, period: str) -> None:
    _ensure_local_production_evidence_schema(db_path)
    generated_at = str(payload.get("generated_at") or utc_now_iso())
    values = (period, generated_at, _json(payload))
    _upsert(
        db_path,
        """INSERT INTO PRODUCTION_FOUNDER_EVIDENCE_SNAPSHOTS (period, generated_at, payload_json)
        VALUES ({p}) ON CONFLICT(period) DO UPDATE SET
            generated_at=excluded.generated_at, payload_json=excluded.payload_json""",
        values,
    )


def load_founder_evidence_snapshot(db_path: Path, *, period: str) -> dict[str, Any] | None:
    try:
        rows = _query(
            db_path,
            """SELECT generated_at, payload_json
            FROM PRODUCTION_FOUNDER_EVIDENCE_SNAPSHOTS WHERE period = {x} LIMIT 1""",
            (period,),
            limit=1,
        )
    except Exception:
        # A newly deployed API can briefly precede the worker migration. Hosted
        # callers receive an explicit warm-up payload until the first worker
        # snapshot has been written.
        return None
    if not rows:
        return None
    row = rows[0]
    try:
        payload = json.loads(str(row.get("payload_json") or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    generated_at = str(row.get("generated_at") or payload.get("generated_at") or "")
    age_seconds = _timestamp_age_seconds(generated_at)
    stale = age_seconds is None or age_seconds > FOUNDER_SNAPSHOT_MAX_AGE_SECONDS
    payload["snapshot"] = {
        "served_from": "worker_projection",
        "generated_at": generated_at or None,
        "age_seconds": age_seconds,
        "stale": stale,
        "refresh_expected_seconds": 300,
    }
    if stale:
        status = payload.setdefault("status", {})
        status["state"] = "OPERATING WITH WARNINGS"
        status["plain_english"] = (
            "The last durable Founder snapshot is stale. Historical evidence is shown, "
            "but current worker and broker activity require attention."
        )
    return payload


def refresh_founder_evidence_snapshots(
    db_path: Path,
    *,
    periods: tuple[str, ...] = ("24h", "1h", "7d", "30d"),
    trade_limit: int = 100,
) -> dict[str, Any]:
    """Build and persist worker-owned Founder projections for mobile reads."""
    if not uses_postgres():
        initialize_always_on_schema(db_path)
    _ensure_local_production_evidence_schema(db_path)
    refreshed: list[str] = []
    failures: dict[str, str] = {}
    try:
        retention = prune_production_evidence(db_path)
    except Exception as exc:  # retention must never prevent a current Founder snapshot
        retention = {"status": "failed", "reason": str(exc)}
    try:
        decision_audit_retention = prune_decision_and_audit_history(db_path)
    except Exception as exc:  # retention must never prevent a current Founder snapshot
        decision_audit_retention = {"status": "failed", "reason": str(exc)}
    oldest_since = min((_period_start(period) for period in periods), default=_period_start("24h"))
    try:
        shared_rows = _load_founder_evidence_rows(
            db_path,
            since=oldest_since,
            trade_limit=trade_limit,
        )
        # Same list regardless of period -- not bounded by any of the four periods this
        # loop refreshes, so it only needs fetching once per worker cycle, not once per
        # period. See _load_closed_trade_history's docstring for why this exists.
        closed_trade_history = _load_closed_trade_history(db_path)
    except Exception as exc:  # noqa: BLE001 - expose complete projection failure
        return {
            "status": "failed",
            "refreshed_periods": [],
            "failed_periods": {period: str(exc) for period in periods},
            "retention": retention,
            "decision_audit_retention": decision_audit_retention,
            "generated_at": utc_now_iso(),
        }
    for period in periods:
        try:
            period_rows = _filter_founder_evidence_rows(shared_rows, since=_period_start(period))
            payload = _assemble_founder_evidence_payload(period_rows, period=period, db_path=db_path, closed_trade_history=closed_trade_history)
            persist_founder_evidence_snapshot(db_path, payload, period=period)
            refreshed.append(period)
        except Exception as exc:  # noqa: BLE001 - retain partial snapshots and expose failure evidence
            failures[period] = str(exc)
    return {
        "status": "completed" if not failures else "partially_completed",
        "refreshed_periods": refreshed,
        "failed_periods": failures,
        "retention": retention,
        "decision_audit_retention": decision_audit_retention,
        "generated_at": utc_now_iso(),
    }


def prune_production_evidence(
    db_path: Path,
    *,
    now: datetime | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Bound redundant operational evidence without deleting canonical trade history.

    The five-minute snapshot job calls this function, but the durable maintenance marker
    makes the delete pass run at most once per 24 hours across worker restarts. Trade evidence
    is intentionally excluded: broker/canonical trade history remains the permanent audit
    trail, while replaceable broker snapshots and recommendation projections are bounded.
    """
    _ensure_local_production_evidence_schema(db_path)
    now = now or datetime.now(timezone.utc)
    task_name = "production-evidence-retention"
    with closing(connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        with conn:
            row = conn.execute(
                "SELECT last_run_at FROM PRODUCTION_EVIDENCE_MAINTENANCE WHERE task_name = ?",
                (task_name,),
            ).fetchone()
            last_run_at = _as_utc_datetime(row["last_run_at"]) if row else None
            if not force and last_run_at and now - last_run_at < PRODUCTION_EVIDENCE_RETENTION_INTERVAL:
                return {"status": "skipped_recent", "last_run_at": last_run_at.isoformat()}
            cutoffs: dict[str, str] = {}
            for table, (timestamp_column, days) in PRODUCTION_EVIDENCE_RETENTION_DAYS.items():
                cutoff = (now - timedelta(days=days)).isoformat()
                conn.execute(f"DELETE FROM {table} WHERE {timestamp_column} < ?", (cutoff,))
                cutoffs[table] = cutoff
            conn.execute(
                """INSERT INTO PRODUCTION_EVIDENCE_MAINTENANCE (task_name, last_run_at)
                VALUES (?, ?) ON CONFLICT(task_name) DO UPDATE SET last_run_at=excluded.last_run_at""",
                (task_name, now.isoformat()),
            )
    return {"status": "completed", "last_run_at": now.isoformat(), "cutoffs": cutoffs}


def _notable_proposal_ids(conn: Any, *, threshold: float) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT proposal_id FROM TRADE_LIFECYCLE "
        "WHERE r_multiple IS NOT NULL AND ABS(r_multiple) >= ? AND proposal_id IS NOT NULL",
        (threshold,),
    ).fetchall()
    return [row["proposal_id"] for row in rows]


def decision_audit_retention_enabled() -> bool:
    return os.getenv("DECISION_AUDIT_RETENTION_ENABLED", "").strip().lower() in {"1", "true", "yes"}


def prune_decision_and_audit_history(
    db_path: Path,
    *,
    now: datetime | None = None,
    force: bool = False,
    retention_days: int = DECISION_AUDIT_RETENTION_DAYS,
    notable_r_multiple_threshold: float = NOTABLE_R_MULTIPLE_THRESHOLD,
    explicitly_confirmed: bool = False,
) -> dict[str, Any]:
    """Bound the high-volume decision/audit-log tables in DECISION_AUDIT_TABLES -- see that
    dict's module-level comment for the 2026-08-08 diagnosis and Founder-directed policy this
    implements (90-day cutoff, but never delete a rejected/blocked/manual-review governance
    decision or a row linked to a notably large trade outcome).

    Same once-per-24h durable-marker pattern as prune_production_evidence, sharing the same
    PRODUCTION_EVIDENCE_MAINTENANCE table under a distinct task_name so the two retention
    passes run and are individually skippable/forceable independently of each other. Every
    table's DELETE is isolated in its own try/except so one not-yet-migrated table (e.g. a
    fresh database that hasn't run every schema's init yet) never blocks the rest.

    The *automatic* 5-minute snapshot cycle (refresh_founder_evidence_snapshots) only calls
    this when decision_audit_retention_enabled() is True -- this is a much larger, more
    consequential DELETE (governance/decision history, not just replaceable evidence
    snapshots) than prune_production_evidence's unconditional wiring, running for the first
    time against real production data far larger and messier than any test fixture.
    explicitly_confirmed=True is the deliberate escape hatch for a single, human-confirmed
    manual run (via the admin API's confirmed_by_founder gate) to inspect real
    deleted_row_counts before ever enabling the automatic cycle -- it bypasses the *enablement*
    flag but never the per-row protection logic below, which applies identically either way.
    """
    if not explicitly_confirmed and not decision_audit_retention_enabled():
        return {"status": "disabled", "message": "DECISION_AUDIT_RETENTION_ENABLED is not set; no rows were touched."}
    _ensure_local_production_evidence_schema(db_path)
    now = now or datetime.now(timezone.utc)
    task_name = "decision-audit-retention"
    cutoff = (now - timedelta(days=retention_days)).isoformat()
    deleted: dict[str, int] = {}
    errors: dict[str, str] = {}

    # Each table gets its own connection and its own committed transaction -- deliberately NOT
    # one shared transaction across all 13 DELETEs. A single long-running transaction holds
    # locks on every table for its entire duration, and this app's own worker/API traffic
    # writes to several of these tables (OPERATIONAL_EVENTS especially) continuously in the
    # background; a real production run of an earlier, single-transaction version of this
    # function deadlocked against that live traffic and rolled back with zero rows deleted.
    # Per-table transactions keep each lock's hold time to one DELETE, and mean one table
    # failing (deadlock, lock timeout) never rolls back another table's already-committed work.
    with closing(connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        with conn:
            row = conn.execute(
                "SELECT last_run_at FROM PRODUCTION_EVIDENCE_MAINTENANCE WHERE task_name = ?",
                (task_name,),
            ).fetchone()
            last_run_at = _as_utc_datetime(row["last_run_at"]) if row else None
            if not force and last_run_at and now - last_run_at < PRODUCTION_EVIDENCE_RETENTION_INTERVAL:
                return {"status": "skipped_recent", "last_run_at": last_run_at.isoformat()}
        try:
            notable_ids = _notable_proposal_ids(conn, threshold=notable_r_multiple_threshold)
        except Exception:  # noqa: BLE001 - a read failure here must not block every table's retention
            notable_ids = []
        notable_placeholders = ",".join("?" for _ in notable_ids)

        # TRADE_LIFECYCLE is the source of the notable set itself -- protect its own
        # big-outcome rows the same way every other table protects rows linked to one.
        try:
            with conn:
                cursor = conn.execute(
                    "DELETE FROM TRADE_LIFECYCLE WHERE created_at < ? "
                    "AND NOT (r_multiple IS NOT NULL AND ABS(r_multiple) >= ?)",
                    (cutoff, notable_r_multiple_threshold),
                )
                deleted["TRADE_LIFECYCLE"] = cursor.rowcount
        except Exception as exc:  # noqa: BLE001 - isolate one table's failure (e.g. deadlock) from the rest
            deleted["TRADE_LIFECYCLE"] = 0
            errors["TRADE_LIFECYCLE"] = str(exc)

        for table, config in DECISION_AUDIT_TABLES.items():
            timestamp_column = config["timestamp_column"]
            proposal_id_column = config["proposal_id_column"]
            protect_column = config["protect_column"]
            protect_values = config["protect_values"]
            clauses = [f"{timestamp_column} < ?"]
            params: list[Any] = [cutoff]
            if protect_column and protect_values:
                placeholders = ",".join("?" for _ in protect_values)
                clauses.append(f"{protect_column} NOT IN ({placeholders})")
                params.extend(protect_values)
            if proposal_id_column and notable_ids:
                clauses.append(f"({proposal_id_column} IS NULL OR {proposal_id_column} NOT IN ({notable_placeholders}))")
                params.extend(notable_ids)
            sql = f"DELETE FROM {table} WHERE " + " AND ".join(clauses)
            try:
                with conn:
                    cursor = conn.execute(sql, tuple(params))
                    deleted[table] = cursor.rowcount
            except Exception as exc:  # noqa: BLE001 - isolate one table's failure (e.g. deadlock) from the rest
                deleted[table] = 0
                errors[table] = str(exc)

        with conn:
            conn.execute(
                """INSERT INTO PRODUCTION_EVIDENCE_MAINTENANCE (task_name, last_run_at)
                VALUES (?, ?) ON CONFLICT(task_name) DO UPDATE SET last_run_at=excluded.last_run_at""",
                (task_name, now.isoformat()),
            )
    result = {
        "status": "completed" if not errors else "partially_completed",
        "last_run_at": now.isoformat(),
        "cutoff": cutoff,
        "notable_proposal_count": len(notable_ids),
        "deleted_row_counts": deleted,
    }
    if errors:
        result["table_errors"] = errors
    return result


def _filter_founder_evidence_rows(
    rows: tuple[list[dict[str, Any]], ...],
    *,
    since: str,
) -> tuple[list[dict[str, Any]], ...]:
    research, recommendations, snapshots, trades, learning, jobs, funnels, workers = rows
    return (
        _rows_since(research, since=since, fields=("completed_at", "created_at")),
        recommendations,
        snapshots,
        _rows_since(trades, since=since, fields=("observed_at",)),
        _rows_since(learning, since=since, fields=("completed_at",)),
        _rows_since(jobs, since=since, fields=("started_at", "scheduled_for")),
        _rows_since(funnels, since=since, fields=("created_at",)),
        workers,
    )


def _rows_since(
    rows: list[dict[str, Any]],
    *,
    since: str,
    fields: tuple[str, ...],
) -> list[dict[str, Any]]:
    cutoff = _as_utc_datetime(since)
    if cutoff is None:
        return list(rows)
    selected: list[dict[str, Any]] = []
    for row in rows:
        timestamp = next((row.get(field) for field in fields if row.get(field)), None)
        observed = _as_utc_datetime(timestamp)
        if observed is not None and observed >= cutoff:
            selected.append(row)
    return selected


def _as_utc_datetime(value: Any) -> datetime | None:
    try:
        timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)


def _snapshot_not_ready_payload(period: str) -> dict[str, Any]:
    reason = (
        "The production worker has not written the first Founder evidence snapshot yet. "
        "The API is available, but current autonomous evidence is still warming up."
    )
    return {
        "generated_at": utc_now_iso(),
        "period": period,
        "status": {
            "state": "STATUS UNKNOWN",
            "plain_english": reason,
            "last_meaningful_activity": None,
            "worker_status": "awaiting_snapshot",
            "scheduler_status": "awaiting_snapshot",
            "database_status": "postgres",
            "last_successful_research_run": None,
            "last_broker_poll": None,
            "last_report_generated": None,
            "unresolved_incident_count": 0,
        },
        "summary": {
            "research": {"runs": 0, "assets_analysed": 0, "candidates": 0, "recommendations_created": 0},
            "decisions": {},
            "execution": {"orders_submitted": 0, "orders_rejected": 0, "orders_filled": 0, "trades_closed": 0},
            "operations": {
                "broker_polls": 0,
                "learning_reviews_completed": 0,
                "reports_generated": 0,
                "incidents_opened": 0,
                "incidents_resolved": 0,
            },
        },
        "why_no_trade": {"state": "operational_evidence_pending", "conclusion": reason, "reasons": []},
        "portfolio": {},
        "brokers": [],
        "trades": [],
        "performance": {"realized_pnl": 0.0, "fees": 0.0, "net_realized_pnl": 0.0},
        "research": [],
        "recommendations": [],
        "learning": [],
        "jobs": [],
        "timeline": {"items": [], "total": 0},
        "snapshot": {
            "served_from": "warmup_state",
            "generated_at": None,
            "age_seconds": None,
            "stale": True,
            "refresh_expected_seconds": 300,
        },
        "truthfulness": {"source": "snapshot availability check", "mock_data_used": False, "synthetic_activity_used": False},
    }


def list_production_trade_evidence(db_path: Path, *, broker: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    _ensure_local_production_evidence_schema(db_path)
    if broker and broker.lower() != "all":
        rows = _query(db_path, "SELECT * FROM PRODUCTION_TRADE_EVIDENCE WHERE broker = {x} ORDER BY observed_at DESC LIMIT {n}", (broker.lower(),), limit=limit)
    else:
        rows = _query(db_path, "SELECT * FROM PRODUCTION_TRADE_EVIDENCE ORDER BY observed_at DESC LIMIT {n}", limit=limit)
    return [_decode_row(row, {"payload_json"}) for row in rows]


def _fifo_matched_realized_pnl(fills: list[dict[str, Any]]) -> dict[int, float]:
    """fills: one symbol+broker's terminal ('filled') order rows, oldest first, each with
    trade_evidence_id/side/quantity/price/fee. Returns {trade_evidence_id: realized_pnl} for
    exit rows whose full quantity is matched by prior entry history in this same list.

    A sell only partially covered by known buys (a position that existed before trade-
    evidence tracking began, e.g. AZN/AAPL in the 2026-08-17 hosted finding) is left out of
    the result entirely -- pricing the unmatched portion against an unknown cost basis would
    be a fabricated number, not a real one, and this project does not show those.
    """
    buy_lots: list[list[float]] = []  # mutable [remaining_qty, price] pairs, oldest first
    results: dict[int, float] = {}
    for fill in fills:
        side = str(fill.get("side") or "").lower()
        quantity = float(fill.get("quantity") or 0)
        price = float(fill.get("price") or 0)
        if quantity <= 0 or price <= 0:
            continue
        if side == "buy":
            buy_lots.append([quantity, price])
            continue
        if side != "sell":
            continue
        if sum(lot[0] for lot in buy_lots) + 1e-9 < quantity:
            continue
        remaining = quantity
        pnl = 0.0
        while remaining > 1e-9 and buy_lots:
            lot_quantity, lot_price = buy_lots[0]
            matched = min(lot_quantity, remaining)
            pnl += (price - lot_price) * matched
            buy_lots[0][0] -= matched
            remaining -= matched
            if buy_lots[0][0] <= 1e-9:
                buy_lots.pop(0)
        results[fill["trade_evidence_id"]] = pnl - float(fill.get("fee") or 0)
    return results


def _set_trade_evidence_realized_pnl(db_path: Path, trade_evidence_id: int, realized_pnl: float) -> None:
    if uses_postgres():
        with postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE PRODUCTION_TRADE_EVIDENCE SET realized_pnl = %s WHERE trade_evidence_id = %s",
                    (realized_pnl, trade_evidence_id),
                )
            conn.commit()
        return
    with closing(connect(db_path)) as conn:
        with conn:
            conn.execute(
                "UPDATE PRODUCTION_TRADE_EVIDENCE SET realized_pnl = ? WHERE trade_evidence_id = ?",
                (realized_pnl, trade_evidence_id),
            )


def backfill_realized_pnl(db_path: Path, *, broker: str) -> dict[str, Any]:
    """Fills in realized_pnl for exits Alpaca (and any other broker) never reports it for.

    2026-08-17 hosted finding: every Alpaca exit ever recorded (38 for 38, confirmed live)
    had realized_pnl = NULL -- Alpaca's order/fill API has no such field, and the existing
    LOGICAL_TRADES reconciliation (canonical_trades.py) that DOES compute real gross_pnl/
    net_pnl can only link an entry order to its exit order via a shared proposal_id or a
    MANAGED_TRADE_EXITS row -- and MANAGED_TRADE_EXITS is Kraken-only (see the 2026-08-12
    close-position commit), so every Alpaca entry/exit pair is permanently two separate,
    unlinked logical trades and gross_pnl can never be computed for either. A real
    ~$645 CSL profit was invisible everywhere in the app (Current Position "Realised this
    month", Forecast Centre closed-trade count) as a direct result.

    Computes realized P&L independently of that linkage -- straightforward FIFO matching
    over each symbol's own terminal 'filled' order history already sitting in
    PRODUCTION_TRADE_EVIDENCE. Only ever touches rows where realized_pnl IS NULL, so it is
    safe to call on every broker-poll cycle: it backfills existing history the first time it
    runs and keeps up with new exits going forward, with no separate one-time script needed.
    """
    _ensure_local_production_evidence_schema(db_path)
    rows = _query(
        db_path,
        """
        SELECT trade_evidence_id, symbol, side, quantity, average_fill_price, price, fee,
               COALESCE(closed_at, opened_at, observed_at) AS event_time, realized_pnl
        FROM PRODUCTION_TRADE_EVIDENCE
        WHERE broker = {x} AND status = 'filled' AND symbol IS NOT NULL
        ORDER BY symbol ASC, event_time ASC
        """,
        (broker.lower(),),
        limit=500,
    )
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        row = dict(row)
        row["price"] = row.get("average_fill_price") if row.get("average_fill_price") is not None else row.get("price")
        by_symbol.setdefault(str(row["symbol"]), []).append(row)
    updated = 0
    total_realized_pnl = 0.0
    for fills in by_symbol.values():
        already_known = {row["trade_evidence_id"] for row in fills if row.get("realized_pnl") is not None}
        for trade_evidence_id, realized_pnl in _fifo_matched_realized_pnl(fills).items():
            if trade_evidence_id in already_known:
                continue
            _set_trade_evidence_realized_pnl(db_path, trade_evidence_id, realized_pnl)
            updated += 1
            total_realized_pnl += realized_pnl
    return {"broker": broker.lower(), "updated": updated, "total_realized_pnl": total_realized_pnl}


def _upsert(db_path: Path, sql: str, values: tuple[Any, ...]) -> None:
    if uses_postgres():
        statement = sql.format(p=", ".join(["%s"] * len(values)))
        with postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(statement, values)
            conn.commit()
        return
    statement = sql.format(p=", ".join(["?"] * len(values)))
    with closing(connect(db_path)) as conn:
        with conn:
            conn.execute(statement, values)


def _query(db_path: Path, sql: str, values: tuple[Any, ...] = (), *, limit: int = 100) -> list[dict[str, Any]]:
    if uses_postgres():
        statement = sql.format(x="%s", n=max(1, min(limit, 500)))
        with postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(statement, values)
                return [dict(row) for row in cur.fetchall()]
    statement = sql.format(x="?", n=max(1, min(limit, 500)))
    with closing(connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(statement, values).fetchall()]


def _query_batch(
    db_path: Path,
    queries: list[tuple[str, tuple[Any, ...]]],
    *,
    limit: int,
) -> list[list[dict[str, Any]]]:
    """Read one coherent Founder snapshot using one database connection."""
    bounded_limit = max(1, min(limit, 500))
    if uses_postgres():
        results: list[list[dict[str, Any]]] = []
        with postgres_connection() as conn:
            with conn.cursor() as cur:
                for sql, values in queries:
                    cur.execute(sql.format(x="%s", n=bounded_limit), values)
                    results.append([dict(row) for row in cur.fetchall()])
        return results
    with closing(connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        return [
            [dict(row) for row in conn.execute(sql.format(x="?", n=bounded_limit), values).fetchall()]
            for sql, values in queries
        ]


def _schema_key(db_path: Path) -> str:
    if uses_postgres():
        return "postgres"
    return f"sqlite:{db_path.resolve()}"


def _timestamp_age_seconds(value: str) -> float | None:
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - timestamp.astimezone(timezone.utc)).total_seconds())


def _json(value: Any) -> str:
    return json.dumps(value, default=str, sort_keys=True)


def _number(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, str) and value.lower().startswith("not available"):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _first(row: dict[str, Any], *keys: str) -> Any:
    return next((row.get(key) for key in keys if row.get(key) not in (None, "")), None)


def _decode_row(row: dict[str, Any], keys: set[str]) -> dict[str, Any]:
    item = dict(row)
    for key in keys:
        value = item.get(key)
        if isinstance(value, str):
            try:
                item[key.removesuffix("_json")] = json.loads(value)
            except json.JSONDecodeError:
                item[key.removesuffix("_json")] = value
    return item


_BROKER_PAYLOAD_LIFT_KEYS = ("auto_trading_enabled", "auto_trading_status", "trading_permissions", "block_reason")


def _lift_broker_payload_fields(row: dict[str, Any]) -> dict[str, Any]:
    """Surface the governance fields captured onto the snapshot's payload_json.

    capture_production_broker_snapshots() computes the true DB-backed auto-trading
    setting, env-level trading permission, reconciliation state, and block reason
    for each broker and stores them inside payload_json. Founder-facing consumers
    (Command screen, broker panels) must never see a silent default of False/
    "Disabled" when this data simply has not been captured yet -- absence must
    read as Unknown, not Disabled.
    """
    payload = row.get("payload")
    payload = payload if isinstance(payload, dict) else {}
    for key in _BROKER_PAYLOAD_LIFT_KEYS:
        if key in payload:
            row[key] = payload[key]
    row.setdefault("auto_trading_enabled", None)
    row.setdefault("auto_trading_status", "Unknown")
    row.setdefault("trading_permissions", None)
    row.setdefault("block_reason", None)
    return row


def _latest_per(rows: Iterable[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for row in rows:
        found.setdefault(str(row.get(key) or "unknown"), row)
    return list(found.values())


def _period_start(period: str) -> str:
    delta = {"1h": timedelta(hours=1), "24h": timedelta(hours=24), "7d": timedelta(days=7), "30d": timedelta(days=30)}.get(period, timedelta(hours=24))
    return (datetime.now(timezone.utc) - delta).isoformat()


def _live_worker_summary(workers: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Identify the single currently-live worker by heartbeat freshness, not row presence.

    Render's rolling deploys leave every past deployment generation's heartbeat row in the
    table permanently (never deleted). Returning the freshest row unconditionally would let a
    long-dead worker from a previous deploy be mistaken for "the" current scheduler. This
    exposes exactly what the Command screen needs to show the true live deployment: which
    worker, on which commit, and how stale it is (AT-ED-003 corrective session, Part 3).
    """
    classified = classify_worker_presence(workers)
    if not classified:
        return None
    candidate = classified[0]
    return {
        "presence_status": candidate["presence_status"],
        "worker_id": candidate.get("worker_id"),
        "deployment_commit": candidate.get("deployment_commit"),
        "last_heartbeat_at": candidate.get("last_heartbeat_at"),
        "heartbeat_age_seconds": candidate.get("heartbeat_age_seconds"),
        "current_job": candidate.get("current_job"),
        "last_successful_job": candidate.get("last_successful_job"),
    }


def _worker_fresh(workers: list[dict[str, Any]]) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=4)
    for worker in workers:
        try:
            if datetime.fromisoformat(str(worker.get("last_heartbeat_at")).replace("Z", "+00:00")) >= cutoff:
                return True
        except (TypeError, ValueError):
            pass
    return False


def _operating_state(workers: list[dict[str, Any]], jobs: list[dict[str, Any]]) -> str:
    if not _worker_fresh(workers):
        return "NOT OPERATING"
    if any(str(row.get("status")) == "failed" for row in jobs[:10]):
        return "OPERATING WITH WARNINGS"
    return "OPERATING NORMALLY"


def _operating_sentence(workers: list[dict[str, Any]], research: list[dict[str, Any]], jobs: list[dict[str, Any]], no_trade: dict[str, Any]) -> str:
    if not _worker_fresh(workers):
        return "AI Trader is not operating normally because no recent worker heartbeat is visible."
    if not research:
        return "The worker is operating, but no completed production research evidence exists in this period."
    return f"AI Trader is operating autonomously. {no_trade['conclusion']}"


def _latest_job_time(jobs: list[dict[str, Any]], job_name: str) -> str | None:
    row = next((item for item in jobs if item.get("job_name") == job_name), None)
    return str(row.get("completed_at") or row.get("started_at")) if row else None


# AT-ED-003 split broker-poll/auto-execution into per-broker job names. Evidence
# rows recorded under the old combined names remain valid history, so summaries
# recognize both the retired name and its per-broker replacements.
BROKER_POLL_JOB_NAMES = ("broker-poll", "broker-poll-alpaca", "broker-poll-kraken")
AUTO_EXECUTION_JOB_NAMES = ("auto-execution", "auto-execution-alpaca", "auto-execution-kraken")


def _latest_job_time_any(jobs: list[dict[str, Any]], job_names: tuple[str, ...]) -> str | None:
    times = [_latest_job_time(jobs, name) for name in job_names]
    times = [value for value in times if value]
    return max(times) if times else None


def _latest_report_time(jobs: list[dict[str, Any]]) -> str | None:
    row = next((item for item in jobs if "report" in str(item.get("job_name") or "")), None)
    return str(row.get("completed_at") or row.get("started_at")) if row else None


def _latest_activity(research: list[dict[str, Any]], trades: list[dict[str, Any]], learning: list[dict[str, Any]], jobs: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates: list[tuple[str, str, str]] = []
    candidates += [(str(row.get("completed_at")), "Research completed", str(row.get("summary"))) for row in research]
    candidates += [(str(row.get("observed_at")), "Broker activity recorded", f"{row.get('broker')} {row.get('symbol') or 'order'} is {row.get('status')}.") for row in trades]
    candidates += [(str(row.get("completed_at")), "Learning completed", str(row.get("summary"))) for row in learning]
    candidates += [(str(row.get("completed_at") or row.get("started_at")), f"{row.get('job_name')} {row.get('status')}", "Persisted worker job evidence.") for row in jobs]
    if not candidates:
        return None
    timestamp, title, summary = max(candidates, key=lambda item: item[0])
    return {"timestamp": timestamp, "title": title, "summary": summary}


def _decision_counts(funnels: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "portfolio_manager_approvals": sum(int(row.get("portfolio_approved") or 0) for row in funnels),
        "portfolio_manager_rejections": sum(max(0, int(row.get("valid_strategies") or 0) - int(row.get("portfolio_approved") or 0)) for row in funnels),
        "risk_engine_approvals": sum(int(row.get("guardrail_approved") or 0) for row in funnels),
        "risk_engine_rejections": sum(max(0, int(row.get("portfolio_approved") or 0) - int(row.get("guardrail_approved") or 0)) for row in funnels),
        "sentinel_blocks": 0,
    }


def _why_no_trade(funnels: list[dict[str, Any]], jobs: list[dict[str, Any]], trades: list[dict[str, Any]]) -> dict[str, Any]:
    submitted = len([row for row in trades if row.get("status") in {"submitted", "accepted", "new", "filled", "partially_filled"}])
    assets = sum(int(row.get("symbols_examined") or 0) for row in funnels)
    candidates = sum(int(row.get("interesting_ideas") or 0) for row in funnels)
    eligible = sum(int(row.get("eligible_for_paper_execution") or 0) for row in funnels)
    reasons: dict[str, int] = {}
    for row in funnels:
        reason = row.get("primary_reason")
        if reason:
            reasons[str(reason)] = reasons.get(str(reason), 0) + 1
    if submitted:
        state, conclusion = "order_submitted_or_trade_completed", f"{submitted} broker order or fill event(s) are recorded in this period."
    elif not funnels:
        state, conclusion = "research_did_not_run", "No trade was placed because no research funnel was recorded in this period."
    elif not candidates:
        state, conclusion = "no_opportunity_found", f"AI Trader analysed {assets} asset(s), but no opportunity qualified as a candidate."
    elif not eligible:
        state, conclusion = "opportunity_found_but_rejected", "Opportunities were found, but none passed every portfolio, strategy, and risk gate."
    else:
        state, conclusion = "approved_but_not_submitted", "An opportunity reached execution eligibility, but no broker submission is recorded. This requires attention."
    return {"state": state, "conclusion": conclusion, "counts": {"assets_analysed": assets, "interesting_ideas": candidates, "eligible_for_paper_execution": eligible, "orders_submitted": submitted}, "top_reasons": [{"reason": key, "count": value} for key, value in sorted(reasons.items(), key=lambda item: item[1], reverse=True)[:8]]}


def _portfolio_payload(brokers: list[dict[str, Any]]) -> dict[str, Any]:
    total = sum(_number(row.get("portfolio_value")) or 0.0 for row in brokers)
    cash = sum(_number(row.get("cash")) or 0.0 for row in brokers)
    day_pnl_values = [_number(row.get("day_pnl")) for row in brokers]
    day_pnl_known = [value for value in day_pnl_values if value is not None]
    positions = []
    for row in brokers:
        for position in row.get("positions") or []:
            positions.append({**position, "broker": row.get("broker")})
    # Broker detail already has its own top-level `brokers` field. Repeating that full array
    # inside portfolio was another verbatim copy in every persisted/read projection.
    return {"portfolio_value": total if brokers else None, "cash_available": cash if brokers else None, "deployed_capital": total - cash if brokers else None, "todays_pnl": sum(day_pnl_known) if day_pnl_known else None, "open_positions": positions, "source": "Shared production broker snapshots"}


def _recommendation_payload(row: dict[str, Any]) -> dict[str, Any]:
    payload = _decode_row(row, {"payload_json"})
    raw = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
    result = {
        **raw,
        **{key: value for key, value in payload.items() if key not in {"payload_json", "payload"}},
        "proposal_id": row.get("recommendation_id"),
        "confidence_score": row.get("confidence"),
        "freshness_status": "Fresh" if not row.get("expires_at") or str(row.get("expires_at")) > utc_now_iso() else "Expired",
        "suggested_broker": row.get("broker"),
    }
    intelligence = result.get("intelligence") if isinstance(result.get("intelligence"), dict) else {}
    strategy = intelligence.get("strategy") if isinstance(intelligence.get("strategy"), dict) else {}
    probability = intelligence.get("probability") if isinstance(intelligence.get("probability"), dict) else {}
    committee = intelligence.get("committee") if isinstance(intelligence.get("committee"), dict) else {}
    trade_setup = intelligence.get("trade_setup") if isinstance(intelligence.get("trade_setup"), dict) else {}
    explainability = intelligence.get("explainability") if isinstance(intelligence.get("explainability"), dict) else {}
    regime = intelligence.get("regime") if isinstance(intelligence.get("regime"), dict) else {}

    def set_missing(key: str, value: Any) -> None:
        if result.get(key) is None and value is not None:
            result[key] = value

    # Trading Intelligence is persisted as one immutable evidence packet. The
    # Founder contract deliberately exposes the most important dossier fields
    # as stable top-level aliases while retaining the complete packet for
    # evidence drill-down.
    set_missing("strategy", strategy or None)
    set_missing("strategy_id", strategy.get("strategy_id") or committee.get("strategy_id") or probability.get("strategy_id"))
    set_missing("strategy_name", strategy.get("name"))
    set_missing("probability", probability or None)
    set_missing("probability_of_success", probability.get("probability_of_success"))
    set_missing("expected_return_r", probability.get("expected_return_r"))
    set_missing("expected_r_multiple", trade_setup.get("expected_r_multiple"))
    set_missing("probability_interval_low", probability.get("confidence_interval_low"))
    set_missing("probability_interval_high", probability.get("confidence_interval_high"))
    set_missing("calibration_status", probability.get("calibration_status"))
    set_missing("committee", committee or None)
    set_missing("committee_result", committee.get("committee_result"))
    set_missing("market_regime", regime or None)
    set_missing("trade_setup", trade_setup or None)
    set_missing("signals", intelligence.get("signals") if isinstance(intelligence.get("signals"), list) else [])
    set_missing(
        "invalidation",
        explainability.get("invalidation_conditions") or trade_setup.get("invalidation_conditions") or [],
    )
    set_missing("strongest_argument_for", committee.get("strongest_argument_for"))
    set_missing("strongest_argument_against", committee.get("strongest_argument_against"))
    # Older production rows contain a valid proposal but predate the full
    # Founder dossier handoff. Preserve their truth while giving the app stable
    # aliases instead of blank sections.
    result.setdefault("ticker", result.get("symbol"))
    result.setdefault("reason_for_recommendation", result.get("plain_english_reasoning"))
    result.setdefault("investment_thesis", result.get("plain_english_reasoning"))
    result.setdefault("key_risks", result.get("strongest_argument_against"))
    result.setdefault("suggested_stop_loss", result.get("stop_loss"))
    result.setdefault("suggested_take_profit", result.get("take_profit"))
    result.setdefault("suggested_position_size", result.get("position_size"))
    result.setdefault("recommended_position_size", result.get("position_size"))
    result.setdefault("guardrails_passed", result.get("ai_guardrails_passed"))
    result.setdefault("guardrail_failures", result.get("ai_guardrail_failures") or [])
    return result


_RECOMMENDATION_SUMMARY_FIELDS = (
    "proposal_id",
    "recommendation_id",
    "created_at",
    "expires_at",
    "broker",
    "suggested_broker",
    "symbol",
    "ticker",
    "company",
    "asset_type",
    "side",
    "status",
    "confidence",
    "confidence_score",
    "freshness_status",
    "exchange",
    "strategy_id",
    "strategy_name",
    "probability_of_success",
    "expected_return_r",
    "committee_result",
    "strongest_argument_for",
    "strongest_argument_against",
    "reason_for_recommendation",
    "plain_english_reasoning",
    "key_risks",
    "suggested_stop_loss",
    "suggested_take_profit",
    "suggested_position_size",
    "position_size",
    "guardrails_passed",
    "ai_guardrails_passed",
    "auto_trade_eligible",
    "investment_philosophy_fit",
)


def _recommendation_summary_payload(row: dict[str, Any]) -> dict[str, Any]:
    """Project the small cross-screen fields; omit nested dossier/intelligence packets."""
    full = _recommendation_payload(row)
    return {key: full[key] for key in _RECOMMENDATION_SUMMARY_FIELDS if full.get(key) is not None}


def _timeline(research: list[dict[str, Any]], trades: list[dict[str, Any]], learning: list[dict[str, Any]], jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items = []
    for row in research:
        items.append({"activity_id": f"research:{row.get('evidence_id')}", "timestamp": row.get("completed_at"), "category": "Research", "title": "Research completed" if row.get("status") == "completed" else "Research did not complete", "summary": row.get("summary"), "outcome": row.get("status"), "severity": "success" if row.get("status") == "completed" else "warning", "component": "Research", "broker": row.get("broker")})
    for row in trades:
        items.append({"activity_id": f"trade:{row.get('trade_evidence_id')}", "timestamp": row.get("observed_at"), "category": "Execution", "title": f"{str(row.get('broker')).title()} {row.get('status')}", "summary": f"{str(row.get('side') or '').upper()} {row.get('quantity') or 'unknown quantity'} {row.get('symbol') or 'unknown symbol'} at {row.get('average_fill_price') or row.get('price') or 'price unavailable'}.", "outcome": row.get("status"), "severity": "success" if "filled" in str(row.get("status")) or row.get("status") == "closed" else "information", "component": "Broker", "broker": row.get("broker"), "symbol": row.get("symbol")})
    for row in learning:
        items.append({"activity_id": f"learning:{row.get('learning_id')}", "timestamp": row.get("completed_at"), "category": "Learning", "title": "Learning processor completed", "summary": row.get("summary"), "outcome": row.get("status"), "severity": "success", "component": "Experience Engine"})
    for row in jobs:
        items.append({"activity_id": f"job:{row.get('job_run_id')}", "timestamp": row.get("completed_at") or row.get("started_at"), "category": "System", "title": f"{row.get('job_name')} {row.get('status')}", "summary": row.get("failure_reason") or "Worker job left durable execution evidence.", "outcome": row.get("status"), "severity": "failure" if row.get("status") == "failed" else "information", "component": "Worker"})
    return sorted(items, key=lambda row: str(row.get("timestamp") or ""), reverse=True)[:100]


def _no_action_from_result(result: dict[str, Any]) -> str | None:
    skipped = result.get("skipped_symbols")
    if isinstance(skipped, list) and skipped:
        reasons = [str(row.get("reason")) for row in skipped if isinstance(row, dict) and row.get("reason")]
        if reasons:
            return "; ".join(dict.fromkeys(reasons))
    return None


def _risk_argument(proposal: dict[str, Any]) -> str:
    failures = proposal.get("ai_guardrail_failures") or []
    if failures:
        return "The strongest argument against this trade is that these checks need attention: " + ", ".join(map(str, failures))
    return "The trade can still lose money if the thesis fails or the stop loss is reached; confidence is not certainty."
