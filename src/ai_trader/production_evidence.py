from __future__ import annotations

import json
import sqlite3
from .database import connect
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from .always_on import initialize_always_on_schema, postgres_connection, uses_postgres
from .models import utc_now_iso


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
"""

POSTGRES_SCHEMA = SQLITE_SCHEMA.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY").replace(" REAL", " DOUBLE PRECISION")


def initialize_production_evidence_schema(db_path: Path) -> None:
    if uses_postgres():
        with postgres_connection() as conn:
            with conn.cursor() as cur:
                for statement in POSTGRES_SCHEMA.split(";"):
                    if statement.strip():
                        cur.execute(statement)
            conn.commit()
        return
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect(db_path)) as conn:
        conn.executescript(SQLITE_SCHEMA)


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
    initialize_production_evidence_schema(db_path)
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
    strongest_for = proposal.get("strongest_argument_for") or reasoning or None
    strongest_against = proposal.get("strongest_argument_against") or _risk_argument(proposal)
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


def record_trade_evidence(db_path: Path, *, broker: str, event: dict[str, Any]) -> None:
    broker_order_id = _first(event, "order_id", "ordertxid", "id", "client_order_id")
    broker_trade_id = _first(event, "trade_id", "activity_id", "fill_id", "id")
    status = str(_first(event, "status", "order_status", "type") or "observed").lower()
    observed_at = str(_first(event, "updated_at", "transaction_time", "time", "timestamp", "filled_at", "created_at") or utc_now_iso())
    symbol = _first(event, "symbol", "pair")
    quantity = _number(_first(event, "qty", "quantity", "vol", "filled_qty", "cum_qty"))
    price = _number(_first(event, "price", "filled_avg_price", "average_price", "avg_price"))
    key_parts = [broker, str(broker_order_id or ""), str(broker_trade_id or ""), status, str(quantity or ""), str(price or "")]
    idempotency_key = ":".join(key_parts)
    values = (
        idempotency_key, observed_at, broker.lower(), broker_order_id, broker_trade_id,
        str(symbol).upper() if symbol else None, _first(event, "side", "type"), status, quantity, price,
        _number(_first(event, "filled_avg_price", "average_price", "avg_price")),
        _number(_first(event, "fee", "fees", "commission")), _number(_first(event, "realized_pnl", "pnl", "profit_loss")),
        _first(event, "opened_at", "created_at"), _first(event, "closed_at", "filled_at"),
        event.get("entry_reason"), event.get("exit_reason"), _json(event),
    )
    _upsert(
        db_path,
        """
        INSERT INTO PRODUCTION_TRADE_EVIDENCE (
            idempotency_key, observed_at, broker, broker_order_id, broker_trade_id, symbol, side,
            status, quantity, price, average_fill_price, fee, realized_pnl, opened_at, closed_at,
            entry_reason, exit_reason, payload_json
        ) VALUES ({p}) ON CONFLICT(idempotency_key) DO UPDATE SET
            observed_at=excluded.observed_at, status=excluded.status, quantity=excluded.quantity,
            price=excluded.price, average_fill_price=excluded.average_fill_price, fee=excluded.fee,
            realized_pnl=excluded.realized_pnl, closed_at=excluded.closed_at, payload_json=excluded.payload_json
        """,
        values,
    )


def record_learning_evidence(db_path: Path, result: dict[str, Any], *, worker_id: str) -> None:
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


def founder_evidence_payload(db_path: Path, *, period: str = "24h", trade_limit: int = 100) -> dict[str, Any]:
    # Schema creation belongs to process startup. Re-running DDL here opened two
    # extra hosted database connections and could block every Founder refresh.
    # Local SQLite callers may create isolated demo/test databases without a
    # long-running process, so retain idempotent local schema bootstrapping.
    if not uses_postgres():
        initialize_always_on_schema(db_path)
        initialize_production_evidence_schema(db_path)
    since = _period_start(period)
    research, recommendations, snapshots_all, trades, learning, jobs, funnels, workers = _query_batch(
        db_path,
        [
            ("""SELECT evidence_id, created_at, completed_at, broker, asset_type, trigger_type,
                       provider, symbols_json, assets_analysed, recommendations_created, status,
                       freshness_status, data_quality_status, no_action_reason, summary
                FROM PRODUCTION_RESEARCH_EVIDENCE
                WHERE completed_at >= {x} ORDER BY completed_at DESC LIMIT 100""", (since,)),
            ("SELECT * FROM PRODUCTION_RECOMMENDATION_EVIDENCE ORDER BY created_at DESC LIMIT 100", ()),
            ("""SELECT snapshot_id, captured_at, broker, connection_status, account_mode, currency,
                       portfolio_value, cash, buying_power, deployed_capital, day_pnl, week_pnl,
                       month_pnl, open_positions, positions_json, reconciliation_status, source, error
                FROM PRODUCTION_BROKER_SNAPSHOTS ORDER BY captured_at DESC LIMIT 100""", ()),
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
    )
    snapshots = _latest_per(snapshots_all, "broker")
    realized_pnl = sum(_number(row.get("realized_pnl")) or 0.0 for row in trades)
    fees = sum(_number(row.get("fee")) or 0.0 for row in trades)
    latest_activity = _latest_activity(research, trades, learning, jobs)
    no_trade = _why_no_trade(funnels, jobs, trades)
    broker_payload = [_decode_row(row, {"positions_json", "payload_json"}) for row in snapshots]
    return {
        "generated_at": utc_now_iso(),
        "period": period,
        "status": {
            "state": _operating_state(workers, jobs),
            "plain_english": _operating_sentence(workers, research, jobs, no_trade),
            "last_meaningful_activity": latest_activity,
            "worker_status": "healthy" if _worker_fresh(workers) else "stale_or_missing",
            "scheduler_status": "active" if jobs else "no_recent_jobs",
            "database_status": "postgres" if uses_postgres() else "sqlite",
            "last_successful_research_run": research[0].get("completed_at") if research else None,
            "last_broker_poll": _latest_job_time(jobs, "broker-poll"),
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
                "broker_polls": len([row for row in jobs if row.get("job_name") == "broker-poll"]),
                "learning_reviews_completed": len(learning),
                "reports_generated": len([row for row in jobs if "report" in str(row.get("job_name") or "") and str(row.get("status") or "").startswith("completed")]),
                "incidents_opened": 0,
                "incidents_resolved": 0,
            },
        },
        "why_no_trade": no_trade,
        "portfolio": _portfolio_payload(broker_payload),
        "brokers": broker_payload,
        "trades": [_decode_row(row, {"payload_json"}) for row in trades],
        "performance": {"realized_pnl": realized_pnl, "fees": fees, "net_realized_pnl": realized_pnl - fees},
        "research": [_decode_row(row, {"symbols_json", "payload_json"}) for row in research],
        "recommendations": [_recommendation_payload(row) for row in recommendations],
        "learning": [_decode_row(row, {"payload_json"}) for row in learning],
        "jobs": jobs[:100],
        "timeline": {"items": _timeline(research, trades, learning, jobs), "total": len(research) + len(trades) + len(learning) + len(jobs)},
        "truthfulness": {"source": "shared production evidence projection", "mock_data_used": False, "synthetic_activity_used": False},
    }


def list_production_trade_evidence(db_path: Path, *, broker: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    initialize_production_evidence_schema(db_path)
    if broker and broker.lower() != "all":
        rows = _query(db_path, "SELECT * FROM PRODUCTION_TRADE_EVIDENCE WHERE broker = {x} ORDER BY observed_at DESC LIMIT {n}", (broker.lower(),), limit=limit)
    else:
        rows = _query(db_path, "SELECT * FROM PRODUCTION_TRADE_EVIDENCE ORDER BY observed_at DESC LIMIT {n}", limit=limit)
    return [_decode_row(row, {"payload_json"}) for row in rows]


def _upsert(db_path: Path, sql: str, values: tuple[Any, ...]) -> None:
    initialize_production_evidence_schema(db_path)
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


def _latest_per(rows: Iterable[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for row in rows:
        found.setdefault(str(row.get(key) or "unknown"), row)
    return list(found.values())


def _period_start(period: str) -> str:
    delta = {"1h": timedelta(hours=1), "24h": timedelta(hours=24), "7d": timedelta(days=7), "30d": timedelta(days=30)}.get(period, timedelta(hours=24))
    return (datetime.now(timezone.utc) - delta).isoformat()


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
    return {"portfolio_value": total if brokers else None, "cash_available": cash if brokers else None, "deployed_capital": total - cash if brokers else None, "todays_pnl": sum(day_pnl_known) if day_pnl_known else None, "open_positions": positions, "brokers": brokers, "source": "Shared production broker snapshots"}


def _recommendation_payload(row: dict[str, Any]) -> dict[str, Any]:
    payload = _decode_row(row, {"payload_json"})
    raw = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
    return {**raw, **{key: value for key, value in payload.items() if key not in {"payload_json", "payload"}}, "proposal_id": row.get("recommendation_id"), "confidence_score": row.get("confidence"), "freshness_status": "Fresh" if not row.get("expires_at") or str(row.get("expires_at")) > utc_now_iso() else "Expired", "suggested_broker": row.get("broker")}


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
