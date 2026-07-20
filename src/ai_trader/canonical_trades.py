from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from .database import connect
from .models import TradeProposal, utc_now_iso


CANONICAL_TRADE_SCHEMA = """
CREATE TABLE IF NOT EXISTS LOGICAL_TRADES (
    logical_trade_id TEXT PRIMARY KEY,
    proposal_id TEXT UNIQUE,
    recommendation_id TEXT,
    broker TEXT NOT NULL,
    symbol TEXT NOT NULL,
    asset_type TEXT,
    side TEXT NOT NULL,
    state TEXT NOT NULL,
    intended_quantity REAL,
    original_stop REAL,
    intended_target REAL,
    intended_entry_price REAL,
    average_entry_price REAL,
    average_exit_price REAL,
    entry_filled_quantity REAL NOT NULL DEFAULT 0,
    exit_filled_quantity REAL NOT NULL DEFAULT 0,
    remaining_quantity REAL,
    broker_fee REAL NOT NULL DEFAULT 0,
    exchange_fee REAL NOT NULL DEFAULT 0,
    gross_pnl REAL,
    net_pnl REAL,
    reconciliation_confidence REAL NOT NULL DEFAULT 0,
    terminal INTEGER NOT NULL DEFAULT 0,
    decision_context_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    closed_at TEXT
);

CREATE TABLE IF NOT EXISTS LOGICAL_TRADE_EVENTS (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    logical_trade_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    event_source TEXT NOT NULL,
    event_time TEXT NOT NULL,
    broker_order_id TEXT,
    broker_trade_id TEXT,
    broker_fill_id TEXT,
    reason TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS LOGICAL_TRADE_FILLS (
    fill_id INTEGER PRIMARY KEY AUTOINCREMENT,
    logical_trade_id TEXT NOT NULL,
    broker TEXT NOT NULL,
    broker_fill_id TEXT NOT NULL,
    broker_order_id TEXT,
    fill_role TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity REAL NOT NULL,
    price REAL NOT NULL,
    broker_fee REAL,
    exchange_fee REAL,
    filled_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    UNIQUE(broker, broker_fill_id)
);

CREATE INDEX IF NOT EXISTS idx_logical_trade_broker_order
ON LOGICAL_TRADE_EVENTS(broker_order_id);
CREATE INDEX IF NOT EXISTS idx_logical_trade_state
ON LOGICAL_TRADES(state, terminal);
"""


def initialize_canonical_trade_schema(db_path: Path) -> None:
    with closing(connect(db_path)) as conn:
        with conn:
            conn.executescript(CANONICAL_TRADE_SCHEMA)


def register_execution_intent(
    db_path: Path,
    *,
    proposal: TradeProposal,
    broker: str,
    decision_context: dict[str, Any],
) -> str:
    """Create the immutable logical identity before broker submission."""

    initialize_canonical_trade_schema(db_path)
    logical_trade_id = proposal.proposal_id
    now = utc_now_iso()
    with closing(connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO LOGICAL_TRADES (
                    logical_trade_id, proposal_id, recommendation_id, broker, symbol,
                    asset_type, side, state, intended_quantity, original_stop,
                    intended_target, intended_entry_price, remaining_quantity,
                    decision_context_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'execution_intent', ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(logical_trade_id) DO UPDATE SET
                    updated_at = excluded.updated_at,
                    decision_context_json = LOGICAL_TRADES.decision_context_json
                """,
                (
                    logical_trade_id,
                    proposal.proposal_id,
                    proposal.proposal_id,
                    broker.lower(),
                    proposal.symbol,
                    proposal.asset_type,
                    proposal.side,
                    proposal.position_size,
                    proposal.stop_loss,
                    proposal.take_profit,
                    proposal.entry_price,
                    proposal.position_size,
                    json.dumps(decision_context, sort_keys=True, default=str),
                    now,
                    now,
                ),
            )
    record_canonical_event(
        db_path,
        logical_trade_id=logical_trade_id,
        stage="execution_intent",
        event_source="investment_orchestrator",
        reason="Governed execution intent created before broker submission.",
        payload=decision_context,
        idempotency_key=f"execution-intent:{logical_trade_id}",
    )
    return logical_trade_id


def record_canonical_event(
    db_path: Path,
    *,
    logical_trade_id: str,
    stage: str,
    event_source: str,
    reason: str,
    payload: dict[str, Any],
    broker_order_id: str | None = None,
    broker_trade_id: str | None = None,
    broker_fill_id: str | None = None,
    event_time: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    initialize_canonical_trade_schema(db_path)
    key = idempotency_key or _event_key(logical_trade_id, stage, payload)
    try:
        with closing(connect(db_path)) as conn:
            with conn:
                cursor = conn.execute(
                    """
                    INSERT INTO LOGICAL_TRADE_EVENTS (
                        logical_trade_id, stage, event_source, event_time,
                        broker_order_id, broker_trade_id, broker_fill_id,
                        reason, payload_json, idempotency_key
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        logical_trade_id,
                        stage,
                        event_source,
                        event_time or utc_now_iso(),
                        broker_order_id,
                        broker_trade_id,
                        broker_fill_id,
                        reason,
                        json.dumps(payload, sort_keys=True, default=str),
                        key,
                    ),
                )
                conn.execute(
                    "UPDATE LOGICAL_TRADES SET state = ?, updated_at = ? WHERE logical_trade_id = ?",
                    (stage, utc_now_iso(), logical_trade_id),
                )
        return {"status": "recorded", "event_id": cursor.lastrowid, "logical_trade_id": logical_trade_id}
    except sqlite3.IntegrityError:
        return {"status": "duplicate", "logical_trade_id": logical_trade_id, "idempotency_key": key}


def link_broker_order(
    db_path: Path,
    *,
    logical_trade_id: str,
    broker_order_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    return record_canonical_event(
        db_path,
        logical_trade_id=logical_trade_id,
        stage=str(payload.get("status") or "submitted").lower(),
        event_source="broker_submission",
        reason="Broker response linked to the governed execution intent.",
        payload=payload,
        broker_order_id=broker_order_id,
        idempotency_key=f"broker-order:{logical_trade_id}:{broker_order_id}:{payload.get('status')}",
    )


def resolve_logical_trade_id(
    db_path: Path,
    *,
    broker: str,
    event: dict[str, Any],
) -> str:
    initialize_canonical_trade_schema(db_path)
    supplied = event.get("logical_trade_id") or event.get("proposal_id")
    if supplied:
        return str(supplied)
    order_id = str(event.get("order_id") or event.get("ordertxid") or event.get("id") or "")
    if order_id:
        with closing(connect(db_path)) as conn:
            row = conn.execute(
                """
                SELECT logical_trade_id FROM LOGICAL_TRADE_EVENTS
                WHERE broker_order_id = ? ORDER BY event_id ASC LIMIT 1
                """,
                (order_id,),
            ).fetchone()
            if not row:
                try:
                    row = conn.execute(
                        """
                        SELECT lt.logical_trade_id
                        FROM MANAGED_TRADE_EXITS m
                        JOIN LOGICAL_TRADES lt ON lt.broker = m.broker AND lt.symbol = m.symbol
                        WHERE m.broker = ? AND (m.entry_order_id = ? OR m.exit_order_id = ?)
                        ORDER BY lt.created_at DESC LIMIT 1
                        """,
                        (broker.lower(), order_id, order_id),
                    ).fetchone()
                except Exception:
                    row = None
        if row:
            return str(row[0])
    trade_id = str(event.get("trade_id") or event.get("tradeid") or "")
    stable = order_id or trade_id or _event_key(broker.lower(), str(event.get("symbol") or event.get("pair") or "unknown"), event)
    return f"{broker.lower()}:{stable}"


def canonical_trade(db_path: Path, logical_trade_id: str) -> dict[str, Any] | None:
    initialize_canonical_trade_schema(db_path)
    with closing(connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM LOGICAL_TRADES WHERE logical_trade_id = ?", (logical_trade_id,)).fetchone()
    return dict(row) if row else None


def reconcile_canonical_broker_event(
    db_path: Path,
    *,
    broker: str,
    event: dict[str, Any],
    source: str,
) -> dict[str, Any]:
    """Fold one broker event into one logical trade without reconstructing by symbol."""

    initialize_canonical_trade_schema(db_path)
    logical_trade_id = resolve_logical_trade_id(db_path, broker=broker, event=event)
    symbol = str(event.get("symbol") or event.get("pair") or "unknown").upper()
    side = str(event.get("side") or event.get("type") or "buy").lower()
    stage = str(event.get("stage") or event.get("status") or "broker_acknowledged").lower()
    now = str(event.get("timestamp") or event.get("time") or event.get("updated_at") or utc_now_iso())
    with closing(connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO LOGICAL_TRADES (
                    logical_trade_id, proposal_id, recommendation_id, broker, symbol,
                    asset_type, side, state, decision_context_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '{}', ?, ?)
                ON CONFLICT(logical_trade_id) DO NOTHING
                """,
                (
                    logical_trade_id,
                    event.get("proposal_id"),
                    event.get("recommendation_id"),
                    broker.lower(),
                    symbol,
                    event.get("asset_type") or ("crypto" if broker.lower() == "kraken" else "stock"),
                    side,
                    stage,
                    now,
                    now,
                ),
            )
    order_id = str(event.get("order_id") or event.get("ordertxid") or event.get("id") or "") or None
    trade_id = str(event.get("trade_id") or event.get("tradeid") or "") or None
    fill_id = str(event.get("fill_id") or trade_id or event.get("id") or "") or None
    event_result = record_canonical_event(
        db_path,
        logical_trade_id=logical_trade_id,
        stage=stage,
        event_source=source,
        reason="Broker evidence reconciled into the canonical logical trade.",
        payload=event,
        broker_order_id=order_id,
        broker_trade_id=trade_id,
        broker_fill_id=fill_id,
        event_time=now,
        idempotency_key=_event_key(logical_trade_id, stage, event),
    )
    fill_result = _record_fill_if_present(
        db_path,
        logical_trade_id=logical_trade_id,
        broker=broker,
        event=event,
        order_id=order_id,
        fill_id=fill_id,
        side=side,
        filled_at=now,
    )
    aggregate = _refresh_trade_aggregate(db_path, logical_trade_id)
    return {
        "logical_trade_id": logical_trade_id,
        "event": event_result,
        "fill": fill_result,
        "trade": aggregate,
        "terminal": bool(aggregate and aggregate.get("terminal")),
    }


def _record_fill_if_present(
    db_path: Path,
    *,
    logical_trade_id: str,
    broker: str,
    event: dict[str, Any],
    order_id: str | None,
    fill_id: str | None,
    side: str,
    filled_at: str,
) -> dict[str, Any]:
    quantity = _number(event.get("filled_quantity") or event.get("filled_qty") or event.get("vol_exec") or event.get("quantity"))
    price = _number(event.get("average_fill_price") or event.get("filled_avg_price") or event.get("avg_price") or event.get("price"))
    if not fill_id or not quantity or quantity <= 0 or not price or price <= 0:
        return {"status": "not_a_fill"}
    fill_role = str(event.get("fill_role") or "").lower()
    if fill_role not in {"entry", "exit"}:
        fill_role = _fill_role_from_order(db_path, broker=broker, order_id=order_id, logical_trade_id=logical_trade_id)
    try:
        with closing(connect(db_path)) as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO LOGICAL_TRADE_FILLS (
                        logical_trade_id, broker, broker_fill_id, broker_order_id,
                        fill_role, side, quantity, price, broker_fee, exchange_fee,
                        filled_at, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        logical_trade_id,
                        broker.lower(),
                        fill_id,
                        order_id,
                        fill_role,
                        side,
                        quantity,
                        price,
                        _number(event.get("broker_fee")),
                        _number(event.get("exchange_fee") or event.get("fee")),
                        filled_at,
                        json.dumps(event, sort_keys=True, default=str),
                    ),
                )
        return {"status": "recorded", "fill_role": fill_role}
    except sqlite3.IntegrityError:
        return {"status": "duplicate", "fill_role": fill_role}


def _fill_role_from_order(db_path: Path, *, broker: str, order_id: str | None, logical_trade_id: str) -> str:
    if order_id:
        with closing(connect(db_path)) as conn:
            try:
                row = conn.execute(
                    """
                    SELECT entry_order_id, exit_order_id FROM MANAGED_TRADE_EXITS
                    WHERE broker = ? AND (entry_order_id = ? OR exit_order_id = ?)
                    ORDER BY managed_exit_id DESC LIMIT 1
                    """,
                    (broker.lower(), order_id, order_id),
                ).fetchone()
            except Exception:
                row = None
            initial_order = conn.execute(
                """
                SELECT broker_order_id FROM LOGICAL_TRADE_EVENTS
                WHERE logical_trade_id = ? AND broker_order_id IS NOT NULL
                ORDER BY event_id ASC LIMIT 1
                """,
                (logical_trade_id,),
            ).fetchone()
        if row and str(row[1] or "") == order_id:
            return "exit"
        if row and str(row[0] or "") == order_id:
            return "entry"
        if initial_order and str(initial_order[0] or "") == order_id:
            return "entry"
    trade = canonical_trade(db_path, logical_trade_id) or {}
    return "entry" if not float(trade.get("entry_filled_quantity") or 0) else "exit"


def _refresh_trade_aggregate(db_path: Path, logical_trade_id: str) -> dict[str, Any] | None:
    with closing(connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        fills = conn.execute(
            "SELECT * FROM LOGICAL_TRADE_FILLS WHERE logical_trade_id = ? ORDER BY filled_at, fill_id",
            (logical_trade_id,),
        ).fetchall()
        trade_row = conn.execute("SELECT * FROM LOGICAL_TRADES WHERE logical_trade_id = ?", (logical_trade_id,)).fetchone()
    if not trade_row:
        return None
    entries = [row for row in fills if row["fill_role"] == "entry"]
    exits = [row for row in fills if row["fill_role"] == "exit"]
    entry_qty = sum(float(row["quantity"]) for row in entries)
    exit_qty = sum(float(row["quantity"]) for row in exits)
    avg_entry = _weighted_average(entries)
    avg_exit = _weighted_average(exits)
    broker_fee = sum(float(row["broker_fee"] or 0) for row in fills)
    exchange_fee = sum(float(row["exchange_fee"] or 0) for row in fills)
    side = str(trade_row["side"] or "buy").lower()
    gross_pnl = None
    if avg_entry is not None and avg_exit is not None and exit_qty > 0:
        matched = min(entry_qty, exit_qty)
        gross_pnl = (avg_exit - avg_entry) * matched * (1 if side == "buy" else -1)
    net_pnl = gross_pnl - broker_fee - exchange_fee if gross_pnl is not None else None
    terminal = bool(entry_qty > 0 and exit_qty >= entry_qty - 1e-9)
    state = "closed" if terminal else "open" if entry_qty > 0 else str(trade_row["state"])
    confidence = 1.0 if terminal and all(row["broker_fill_id"] for row in fills) else 0.85 if fills else 0.5
    with closing(connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                UPDATE LOGICAL_TRADES SET
                    state = ?, average_entry_price = ?, average_exit_price = ?,
                    entry_filled_quantity = ?, exit_filled_quantity = ?, remaining_quantity = ?,
                    broker_fee = ?, exchange_fee = ?, gross_pnl = ?, net_pnl = ?,
                    reconciliation_confidence = ?, terminal = ?, updated_at = ?, closed_at = ?
                WHERE logical_trade_id = ?
                """,
                (
                    state,
                    avg_entry,
                    avg_exit,
                    entry_qty,
                    exit_qty,
                    max(0.0, entry_qty - exit_qty),
                    broker_fee,
                    exchange_fee,
                    gross_pnl,
                    net_pnl,
                    confidence,
                    1 if terminal else 0,
                    utc_now_iso(),
                    utc_now_iso() if terminal else None,
                    logical_trade_id,
                ),
            )
    return canonical_trade(db_path, logical_trade_id)


def _weighted_average(rows: list[Any]) -> float | None:
    quantity = sum(float(row["quantity"]) for row in rows)
    if quantity <= 0:
        return None
    return sum(float(row["quantity"]) * float(row["price"]) for row in rows) / quantity


def _number(value: Any) -> float | None:
    try:
        return None if value in {None, ""} else float(value)
    except (TypeError, ValueError):
        return None


def _event_key(logical_trade_id: str, stage: str, payload: dict[str, Any]) -> str:
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    return f"{logical_trade_id}:{stage}:{digest}"
