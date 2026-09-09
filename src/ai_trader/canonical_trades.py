from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any, Iterator

from .database import connect, selected_backend
from .models import TradeProposal, utc_now_iso


@contextmanager
def _connection(db_path: Path, conn: Any = None) -> Iterator[Any]:
    """Reuse a caller-supplied connection, or open and close a fresh one.

    Every function in this module that touches the database accepts an
    optional ``conn`` so a caller processing many events in one loop (see
    ``kraken_reconciliation.replay_kraken_evidence``) can share a single
    physical connection across the whole batch instead of opening a new one
    per row -- the confirmed dominant cost of that job's production timeouts
    (PRODUCTION_TIMEOUT_ROOT_CAUSE_ANALYSIS.md). Callers that don't pass a
    connection keep the exact previous per-call-connection behaviour.
    """

    if conn is not None:
        yield conn
        return
    with closing(connect(db_path)) as new_conn:
        yield new_conn


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


_SCHEMA_LOCK = threading.Lock()
_INITIALIZED_SCHEMA_KEYS: set[str] = set()


def _schema_key(db_path: Path) -> str:
    if selected_backend() == "postgres":
        return "postgres"
    return f"sqlite:{Path(db_path).resolve()}"


def _ensure_canonical_trade_schema(db_path: Path) -> None:
    """Create the canonical-trade schema on first use, on every backend.

    Unconditional on both SQLite and Postgres -- unlike an earlier version of
    this function, it no longer skips schema creation when Postgres is the
    active backend. It is cached per-process (matching the pattern already
    used by ``always_on.initialize_always_on_schema`` and
    ``production_evidence``) so that the many call sites throughout this
    module that defensively call it before every operation do not each pay
    for a fresh database connection once the schema is known to exist.
    """

    key = _schema_key(db_path)
    if key in _INITIALIZED_SCHEMA_KEYS:
        return
    with _SCHEMA_LOCK:
        if key in _INITIALIZED_SCHEMA_KEYS:
            return
        initialize_canonical_trade_schema(db_path)
        _INITIALIZED_SCHEMA_KEYS.add(key)


def register_execution_intent(
    db_path: Path,
    *,
    proposal: TradeProposal,
    broker: str,
    decision_context: dict[str, Any],
) -> str:
    """Create the immutable logical identity before broker submission."""

    _ensure_canonical_trade_schema(db_path)
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
    conn: Any = None,
) -> dict[str, Any]:
    _ensure_canonical_trade_schema(db_path)
    key = idempotency_key or _event_key(logical_trade_id, stage, payload)
    try:
        with _connection(db_path, conn) as conn:
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
    order_role: str | None = None,
) -> dict[str, Any]:
    result = record_canonical_event(
        db_path,
        logical_trade_id=logical_trade_id,
        stage=f"{order_role}_order_linked" if order_role in {"entry", "exit"} else str(payload.get("status") or "submitted").lower(),
        event_source="broker_submission",
        reason="Broker response linked to the governed execution intent.",
        payload=payload,
        broker_order_id=broker_order_id,
        idempotency_key=f"broker-order:{logical_trade_id}:{broker_order_id}:{payload.get('status')}",
    )
    if order_role == "entry" and payload.get("side") in {"buy", "sell"}:
        # Broker-supplied bracket children only; never pair exits by symbol.
        for leg in payload.get("legs") or []:
            if isinstance(leg, dict) and leg.get("id") and leg.get("side") in {"buy", "sell"} and leg.get("side") != payload.get("side"):
                link_broker_order(db_path, logical_trade_id=logical_trade_id,
                                  broker_order_id=str(leg["id"]), payload=leg, order_role="exit")
    return result


def resolve_logical_trade_id(
    db_path: Path,
    *,
    broker: str,
    event: dict[str, Any],
    conn: Any = None,
) -> str:
    _ensure_canonical_trade_schema(db_path)
    supplied = event.get("logical_trade_id") or event.get("proposal_id")
    if supplied:
        return str(supplied)
    order_id = str(event.get("order_id") or event.get("ordertxid") or event.get("id") or "")
    if order_id:
        parent_link = False
        with _connection(db_path, conn) as conn:
            row = conn.execute(
                """
                SELECT e.logical_trade_id, t.proposal_id FROM LOGICAL_TRADE_EVENTS e
                JOIN LOGICAL_TRADES t ON t.logical_trade_id = e.logical_trade_id
                WHERE e.broker_order_id = ? AND t.broker = ?
                ORDER BY CASE WHEN t.proposal_id IS NOT NULL THEN 0 ELSE 1 END, e.event_id ASC LIMIT 1
                """,
                (order_id, broker.lower()),
            ).fetchone()
            if (not row or row[1] is None) and broker.lower() == "alpaca" and event.get("parent_order_id"):
                parent = conn.execute(
                    """SELECT e.logical_trade_id, t.side FROM LOGICAL_TRADE_EVENTS e
                       JOIN LOGICAL_TRADES t ON t.logical_trade_id = e.logical_trade_id
                       WHERE e.broker_order_id = ? AND t.broker = 'alpaca'
                         AND t.proposal_id IS NOT NULL AND e.event_source = 'broker_submission'
                         AND e.stage != 'exit_order_linked'
                       ORDER BY e.event_id ASC LIMIT 1""",
                    (str(event["parent_order_id"]),),
                ).fetchone()
                if parent and str(event.get("side") or "").lower() in {"buy", "sell"} and str(event["side"]).lower() != parent[1]:
                    row = parent
                    parent_link = True
            if not row and broker.lower() not in {"kraken", "alpaca"}:
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
            if parent_link:
                link_broker_order(db_path, logical_trade_id=str(row[0]), broker_order_id=order_id, payload=event, order_role="exit")
            return str(row[0])
    trade_id = str(event.get("trade_id") or event.get("tradeid") or "")
    stable = order_id or trade_id or _event_key(broker.lower(), str(event.get("symbol") or event.get("pair") or "unknown"), event)
    return f"{broker.lower()}:{stable}"


# Every LOGICAL_TRADES column EXCEPT decision_context_json, which is 45,433 of the row's
# ~50,000 bytes. 2026-09-06 Supabase egress finding: SELECT * on this table ran 42,320 times
# a day during Kraken reconciliation, and most of those callers read a handful of numbers off
# it. Kept as an explicit list rather than "SELECT * minus one" (which SQL cannot express),
# and test_canonical_trade_lean_columns_match_the_schema fails if a column is added to the
# table without a decision about whether lean callers need it -- so a new field cannot go
# silently missing from half the system.
_LEAN_TRADE_COLUMNS = (
    "logical_trade_id, proposal_id, recommendation_id, broker, symbol, asset_type, side, state, "
    "intended_quantity, original_stop, intended_target, intended_entry_price, average_entry_price, "
    "average_exit_price, entry_filled_quantity, exit_filled_quantity, remaining_quantity, broker_fee, "
    "exchange_fee, gross_pnl, net_pnl, reconciliation_confidence, terminal, created_at, updated_at, closed_at"
)


def canonical_trade(
    db_path: Path,
    logical_trade_id: str,
    *,
    conn: Any = None,
    include_decision_context: bool = True,
) -> dict[str, Any] | None:
    """One logical trade.

    include_decision_context defaults to True so every existing caller is unchanged -- the AI's
    own record of why a trade was taken flows from here into _learning_payload and
    _learning_payload_from_canonical_trade, and silently emptying it would corrupt the learning
    loop in production only. Callers that demonstrably read only scalars pass False.
    """

    _ensure_canonical_trade_schema(db_path)
    columns = "*" if include_decision_context else _LEAN_TRADE_COLUMNS
    with _connection(db_path, conn) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            f"SELECT {columns} FROM LOGICAL_TRADES WHERE logical_trade_id = ?", (logical_trade_id,)
        ).fetchone()
    return dict(row) if row else None


def reconcile_canonical_broker_event(
    db_path: Path,
    *,
    broker: str,
    event: dict[str, Any],
    source: str,
    conn: Any = None,
) -> dict[str, Any]:
    """Fold one broker event into one logical trade without reconstructing by symbol."""

    _ensure_canonical_trade_schema(db_path)
    logical_trade_id = resolve_logical_trade_id(db_path, broker=broker, event=event, conn=conn)
    symbol = str(event.get("symbol") or event.get("pair") or "unknown").upper()
    side = str(event.get("side") or event.get("type") or "buy").lower()
    stage = str(event.get("stage") or event.get("status") or "broker_acknowledged").lower()
    now = str(event.get("timestamp") or event.get("time") or event.get("updated_at") or utc_now_iso())
    with _connection(db_path, conn) as active:
        with active:
            active.execute(
                """
                INSERT INTO LOGICAL_TRADES (
                    logical_trade_id, proposal_id, recommendation_id, broker, symbol,
                    asset_type, side, state, intended_quantity, original_stop,
                    intended_target, intended_entry_price, remaining_quantity,
                    decision_context_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    _number(event.get("intended_quantity") or event.get("quantity")),
                    _number(event.get("original_stop") or event.get("stop_loss")),
                    _number(event.get("intended_target") or event.get("take_profit")),
                    _number(event.get("intended_entry_price") or event.get("entry_price")),
                    _number(event.get("intended_quantity") or event.get("quantity")),
                    json.dumps(event.get("decision_context") or {}, sort_keys=True, default=str),
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
        conn=conn,
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
        conn=conn,
    )
    aggregate = _refresh_trade_aggregate(db_path, logical_trade_id, conn=conn)
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
    conn: Any = None,
) -> dict[str, Any]:
    if broker.lower() == "kraken" and str(event.get("record_type") or "").lower() != "trade_fill":
        return {"status": "not_a_fill", "reason": "kraken_trade_fill_evidence_required"}
    if broker.lower() == "alpaca" and str(event.get("status") or "").lower() not in {"fill", "partial_fill"}:
        # Order snapshots contain cumulative quantities, not distinct executions.
        return {"status": "not_a_fill", "reason": "alpaca_activity_fill_required"}
    quantity = _number(event.get("filled_quantity") or event.get("filled_qty") or event.get("vol_exec") or event.get("quantity"))
    price = _number(event.get("average_fill_price") or event.get("filled_avg_price") or event.get("avg_price") or event.get("price"))
    if not fill_id or not quantity or quantity <= 0 or not price or price <= 0:
        return {"status": "not_a_fill"}
    fill_role = str(event.get("fill_role") or "").lower()
    if fill_role not in {"entry", "exit"}:
        fill_role = _fill_role_from_order(db_path, broker=broker, order_id=order_id, logical_trade_id=logical_trade_id, conn=conn)
    if fill_role not in {"entry", "exit"}:
        return {"status": "unresolved_fill_role"}
    try:
        with _connection(db_path, conn) as active:
            with active:
                active.execute(
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
                        _number(event.get("exchange_fee") if event.get("exchange_fee") is not None else event.get("fee")),
                        filled_at,
                        json.dumps(event, sort_keys=True, default=str),
                    ),
                )
        return {"status": "recorded", "fill_role": fill_role}
    except sqlite3.IntegrityError:
        return {"status": "duplicate", "fill_role": fill_role}


def _fill_role_from_order(
    db_path: Path, *, broker: str, order_id: str | None, logical_trade_id: str, conn: Any = None
) -> str:
    if order_id:
        with _connection(db_path, conn) as conn:
            if broker.lower() == "alpaca":
                linked = conn.execute(
                    """SELECT stage FROM LOGICAL_TRADE_EVENTS
                       WHERE logical_trade_id = ? AND broker_order_id = ?
                         AND event_source = 'broker_submission'
                       ORDER BY event_id ASC LIMIT 1""",
                    (logical_trade_id, order_id),
                ).fetchone()
                if not linked:
                    return "unknown"
                return "exit" if linked[0] == "exit_order_linked" else "entry"
            if broker.lower() == "kraken":
                try:
                    owned = conn.execute(
                        """
                        SELECT order_role FROM KRAKEN_AI_ORDER_OWNERSHIP
                        WHERE broker_order_id = ? AND logical_trade_id = ?
                        """,
                        (order_id, logical_trade_id),
                    ).fetchone()
                except Exception:
                    owned = None
                return str(owned[0]) if owned and str(owned[0]) in {"entry", "exit"} else "unknown"
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
    # Reads one number; no need to drag 45 KB of decision context across the wire for it.
    trade = canonical_trade(db_path, logical_trade_id, include_decision_context=False) or {}
    return "entry" if not float(trade.get("entry_filled_quantity") or 0) else "exit"


def _refresh_trade_aggregate(db_path: Path, logical_trade_id: str, *, conn: Any = None) -> dict[str, Any] | None:
    with _connection(db_path, conn) as active:
        active.row_factory = sqlite3.Row
        fills = active.execute(
            "SELECT * FROM LOGICAL_TRADE_FILLS WHERE logical_trade_id = ? ORDER BY filled_at, fill_id",
            (logical_trade_id,),
        ).fetchall()
        # 2026-09-05 Supabase egress finding: SELECT * here cost the whole row, and
        # decision_context_json on LOGICAL_TRADES averages 45,433 of its ~50,000 bytes. This
        # function reads exactly two fields off trade_row -- `side` just below and `state` a
        # few lines further down -- so 91% of every fetch was discarded unread. Measured via
        # pg_stat_statements: SELECT * on this table ran 72,487 times for ~63 MB/day, and this
        # call site is half of them (the other half is the canonical_trade() call at the end
        # of this same function).
        #
        # Deliberately NOT narrowed at that second call site or in canonical_trade() itself:
        # its result is public and genuinely carries decision_context_json onward into
        # _learning_payload_from_canonical_trade (sprint6.py) and the Kraken reconciliation
        # payload, both of which read that exact field. Dropping it there would empty the
        # AI's own record of why a trade was taken -- silently, and only in production.
        trade_row = active.execute(
            "SELECT side, state, broker FROM LOGICAL_TRADES WHERE logical_trade_id = ?", (logical_trade_id,)
        ).fetchone()
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
        fees_known = trade_row["broker"] != "alpaca" or bool(fills and all(row["broker_fee"] is not None and row["exchange_fee"] is not None for row in fills))
        # Legacy aggregate fee columns are NOT NULL; net_pnl carries incompleteness.
        net_pnl = gross_pnl - broker_fee - exchange_fee if gross_pnl is not None and fees_known else None
        terminal = bool(entry_qty > 0 and exit_qty >= entry_qty - 1e-9)
        state = "closed" if terminal else "open" if entry_qty > 0 else str(trade_row["state"])
        confidence = 1.0 if terminal and all(row["broker_fill_id"] for row in fills) else 0.85 if fills else 0.5
        with active:
            active.execute(
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
        # 2026-09-06 Supabase egress finding, and the completion of a fix left half-done
        # this morning. This ran on EVERY fill event -- 4,306 times a day measured on
        # production, about 206 MB/day and the single largest remaining source -- and each
        # full row carries decision_context_json, 45,433 of its ~50,000 bytes.
        #
        # Only ONE consumer needs that field: sprint6 hands terminal trades to
        # _learning_payload_from_canonical_trade, which reads the AI's record of why the trade
        # was taken. Terminal trades are rare -- 27 in the system's entire history against
        # 4,306 reads a day -- so that caller now fetches the full row for itself, and this
        # returns the lean one for the thousands of ordinary fill events that never look at it.
        return canonical_trade(db_path, logical_trade_id, conn=active, include_decision_context=False)


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
