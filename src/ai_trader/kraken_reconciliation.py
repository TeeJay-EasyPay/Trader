from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .canonical_trades import (
    _connection,
    canonical_trade,
    initialize_canonical_trade_schema,
    reconcile_canonical_broker_event,
)
from .database import connect, selected_backend
from .models import utc_now_iso
from .symbol_track_record import normalize_symbol
from . import trade_reasons
from .multi_broker import initialize_multi_broker_schema, record_managed_trade_exit
from .sprint6 import enqueue_learning_workflow, initialize_sprint6_schema


KRAKEN_RECONCILIATION_SCHEMA = """
CREATE TABLE IF NOT EXISTS KRAKEN_RECONCILIATION_CONTROL (
    id INTEGER PRIMARY KEY,
    hold_new_entries INTEGER NOT NULL,
    hold_reason TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_replay_at TEXT,
    last_verified_at TEXT,
    unresolved_count INTEGER NOT NULL DEFAULT 0,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS KRAKEN_AI_ORDER_OWNERSHIP (
    broker_order_id TEXT PRIMARY KEY,
    logical_trade_id TEXT NOT NULL,
    proposal_id TEXT,
    managed_exit_id INTEGER,
    order_role TEXT NOT NULL,
    symbol TEXT,
    side TEXT,
    source TEXT NOT NULL,
    confidence REAL NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS KRAKEN_AI_CAPITAL_LEDGER (
    ledger_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    event_time TEXT NOT NULL,
    logical_trade_id TEXT,
    broker_order_id TEXT,
    broker_fill_id TEXT,
    entry_type TEXT NOT NULL,
    amount_gbp REAL NOT NULL,
    quantity REAL,
    price REAL,
    fee_gbp REAL NOT NULL DEFAULT 0,
    idempotency_key TEXT NOT NULL UNIQUE,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS KRAKEN_RECONCILIATION_CASES (
    case_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    raw_event_hash TEXT NOT NULL UNIQUE,
    broker_order_id TEXT,
    broker_fill_id TEXT,
    logical_trade_id TEXT,
    classification TEXT NOT NULL,
    reason TEXT NOT NULL,
    confidence REAL NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS KRAKEN_RECONCILED_RESULTS (
    logical_trade_id TEXT PRIMARY KEY,
    proposal_id TEXT,
    symbol TEXT,
    side TEXT,
    status TEXT NOT NULL,
    entry_time TEXT,
    exit_time TEXT,
    holding_seconds REAL,
    quantity REAL,
    intended_entry REAL,
    actual_entry REAL,
    original_stop REAL,
    target_price REAL,
    actual_exit REAL,
    broker_fee REAL NOT NULL DEFAULT 0,
    exchange_fee REAL NOT NULL DEFAULT 0,
    gross_pnl REAL,
    net_pnl REAL,
    initial_risk REAL,
    planned_r REAL,
    gross_r REAL,
    net_r REAL,
    entry_slippage REAL,
    exit_slippage REAL,
    reconciliation_confidence REAL NOT NULL,
    updated_at TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_kraken_ownership_trade
ON KRAKEN_AI_ORDER_OWNERSHIP(logical_trade_id, order_role);
CREATE INDEX IF NOT EXISTS idx_kraken_ledger_trade
ON KRAKEN_AI_CAPITAL_LEDGER(logical_trade_id, event_time);
CREATE INDEX IF NOT EXISTS idx_kraken_cases_classification
ON KRAKEN_RECONCILIATION_CASES(classification, updated_at);
CREATE INDEX IF NOT EXISTS idx_kraken_results_status
ON KRAKEN_RECONCILED_RESULTS(status, updated_at);
"""


def initialize_kraken_reconciliation_schema(db_path: Path, *, allocation_gbp: float = 100.0) -> None:
    """Create schema and seed the two fixed control/ledger rows exactly once.

    The seed rows (control id=1, ledger idempotency_key below) are checked for
    existence before inserting. Every job runs in its own fresh process, so the
    per-process _INITIALIZED_SCHEMA_KEYS cache in _ensure_schema never prevents
    concurrent processes from reaching this function at the same time -- and an
    unconditional INSERT on every call meant every pair of concurrently-started
    jobs contended for the same two rows, producing both explicit Postgres
    deadlocks and (via lock-wait rather than deadlock) the evidence-snapshot
    180s timeout when it blocked on a concurrent job's still-open transaction.
    Skipping the INSERT once the row already exists (true for every call after
    the database's first-ever bootstrap) removes that contention entirely.
    """

    now = utc_now_iso()
    with closing(connect(db_path)) as conn:
        with conn:
            conn.executescript(KRAKEN_RECONCILIATION_SCHEMA)
            control_exists = conn.execute(
                "SELECT 1 FROM KRAKEN_RECONCILIATION_CONTROL WHERE id = 1"
            ).fetchone()
            if not control_exists:
                conn.execute(
                    """
                    INSERT INTO KRAKEN_RECONCILIATION_CONTROL (
                        id, hold_new_entries, hold_reason, status, started_at,
                        updated_at, unresolved_count, payload_json
                    ) VALUES (1, 1, ?, 'verification_required', ?, ?, 0, '{}')
                    ON CONFLICT(id) DO NOTHING
                    """,
                    (
                        "Kraken entry reconciliation and the AI-managed capital ledger require verification.",
                        now,
                        now,
                    ),
                )
            ledger_idempotency_key = "kraken-founder-allocation-v1"
            ledger_exists = conn.execute(
                "SELECT 1 FROM KRAKEN_AI_CAPITAL_LEDGER WHERE idempotency_key = ?",
                (ledger_idempotency_key,),
            ).fetchone()
            if not ledger_exists:
                conn.execute(
                    """
                    INSERT INTO KRAKEN_AI_CAPITAL_LEDGER (
                        created_at, event_time, logical_trade_id, broker_order_id,
                        broker_fill_id, entry_type, amount_gbp, quantity, price,
                        fee_gbp, idempotency_key, payload_json
                    ) VALUES (?, ?, NULL, NULL, NULL, 'founder_allocation', ?, NULL, NULL, 0, ?, ?)
                    ON CONFLICT(idempotency_key) DO NOTHING
                    """,
                    (
                        now,
                        now,
                        float(allocation_gbp),
                        ledger_idempotency_key,
                        json.dumps({"allocation_gbp": float(allocation_gbp)}, sort_keys=True),
                    ),
                )


def record_founder_allocation(
    db_path: Path,
    *,
    amount_gbp: float,
    reference: str,
    note: str | None = None,
) -> dict[str, Any]:
    """Append a founder capital top-up to the Kraken AI capital ledger.

    2026-08-20, found live and confirmed: the ledger's opening balance is written exactly
    once by initialize_kraken_reconciliation_schema, guarded by `if not ledger_exists` plus
    ON CONFLICT DO NOTHING. It was seeded while KRAKEN_TRADING_ALLOCATION_GBP was still its
    GBP 100 default. The env var was later raised to GBP 500, but that seeded row was never
    revisited -- so `/broker-decisions` reported `trading_allocation_gbp: 500.0` (read live
    from the env) next to `ai_capital_ledger.allocation_gbp: 100.0` (the stale row), and
    every sizing decision used the GBP 100 figure. Per-trade size is a percentage of that
    number, so the Founder's trades were being sized off a fifth of the real capital.

    This is the third instance of this exact bug class in this codebase (see
    set_risk_policy_value's docstring for the RISK_POLICIES one, and the four disagreeing
    MAX_OPEN_POSITIONS values before it): a seed-once default that silently outlives the
    configuration change meant to replace it.

    The ledger is append-only and `allocation_gbp` is the SUM of every `founder_allocation`
    row, so a top-up is recorded as a new entry rather than by rewriting history -- which
    is both how a capital ledger is supposed to work and what keeps the original deposit
    auditable. `available_cash_gbp` sums ALL ledger rows, so a top-up correctly raises both
    the allocation and the free cash.

    Deliberately positive-only: this exists to add approved capital. Reducing the AI's
    allocation is a materially different, higher-risk operation (it can strand capital
    already deployed in open positions) and should not share a code path with topping up.
    """
    amount = float(amount_gbp)
    if amount <= 0:
        return {"status": "rejected", "reason": "amount_must_be_positive", "amount_gbp": amount}
    reference_key = str(reference or "").strip()
    if not reference_key:
        return {"status": "rejected", "reason": "reference_required"}
    _ensure_schema(db_path)
    before = kraken_capital_ledger_summary(db_path)
    idempotency_key = f"kraken-founder-allocation-topup:{reference_key}"
    now = utc_now_iso()
    with closing(connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        existing = conn.execute(
            "SELECT 1 FROM KRAKEN_AI_CAPITAL_LEDGER WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        if existing:
            return {
                "status": "already_recorded",
                "reference": reference_key,
                "allocation_gbp": before["allocation_gbp"],
                "available_cash_gbp": before["available_cash_gbp"],
            }
        with conn:
            conn.execute(
                """
                INSERT INTO KRAKEN_AI_CAPITAL_LEDGER (
                    created_at, event_time, logical_trade_id, broker_order_id,
                    broker_fill_id, entry_type, amount_gbp, quantity, price,
                    fee_gbp, idempotency_key, payload_json
                ) VALUES (?, ?, NULL, NULL, NULL, 'founder_allocation', ?, NULL, NULL, 0, ?, ?)
                """,
                (
                    now,
                    now,
                    amount,
                    idempotency_key,
                    json.dumps(
                        {"allocation_gbp": amount, "reference": reference_key, "note": note},
                        sort_keys=True,
                    ),
                ),
            )
    after = kraken_capital_ledger_summary(db_path)
    return {
        "status": "recorded",
        "reference": reference_key,
        "amount_gbp": amount,
        "previous_allocation_gbp": before["allocation_gbp"],
        "allocation_gbp": after["allocation_gbp"],
        "previous_available_cash_gbp": before["available_cash_gbp"],
        "available_cash_gbp": after["available_cash_gbp"],
        "note": note,
    }


_SCHEMA_LOCK = threading.Lock()
_INITIALIZED_SCHEMA_KEYS: set[str] = set()


def _schema_key(db_path: Path) -> str:
    if selected_backend() == "postgres":
        return "postgres"
    return f"sqlite:{Path(db_path).resolve()}"


def _ensure_schema(db_path: Path) -> None:
    """Create every schema this module depends on, once per process.

    Unconditional on both backends (this module previously skipped all four
    calls entirely on Postgres, which is the root cause of the LOGICAL_TRADES
    schema never existing there -- see CRITICAL_REMEDIATION_PLAN.md P0-1).
    Cached so the many call sites in this module that defensively call this
    before every operation do not each reopen four database connections once
    the schema is known to exist for this process (see P0-4).
    """

    key = _schema_key(db_path)
    if key in _INITIALIZED_SCHEMA_KEYS:
        return
    with _SCHEMA_LOCK:
        if key in _INITIALIZED_SCHEMA_KEYS:
            return
        initialize_canonical_trade_schema(db_path)
        initialize_multi_broker_schema(db_path)
        initialize_sprint6_schema(db_path)
        initialize_kraken_reconciliation_schema(db_path)
        _INITIALIZED_SCHEMA_KEYS.add(key)


def reconciliation_control(db_path: Path) -> dict[str, Any]:
    _ensure_schema(db_path)
    with closing(connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM KRAKEN_RECONCILIATION_CONTROL WHERE id = 1").fetchone()
    if not row:
        return {
            "hold_new_entries": True,
            "status": "verification_required",
            "hold_reason": "Kraken reconciliation control has not been initialized.",
        }
    result = dict(row)
    result["hold_new_entries"] = bool(result["hold_new_entries"])
    result["payload"] = _json(result.pop("payload_json", "{}"))
    return result


def set_reconciliation_hold(
    db_path: Path,
    *,
    active: bool,
    reason: str,
    status: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _ensure_schema(db_path)
    now = utc_now_iso()
    with closing(connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                UPDATE KRAKEN_RECONCILIATION_CONTROL
                SET hold_new_entries = ?, hold_reason = ?, status = ?,
                    updated_at = ?, payload_json = ?
                WHERE id = 1
                """,
                (int(active), reason, status, now, json.dumps(payload or {}, sort_keys=True, default=str)),
            )
    return reconciliation_control(db_path)


def register_kraken_order_ownership(
    db_path: Path,
    *,
    broker_order_id: str,
    logical_trade_id: str,
    order_role: str,
    proposal_id: str | None = None,
    managed_exit_id: int | None = None,
    symbol: str | None = None,
    side: str | None = None,
    source: str = "investment_orchestrator",
    confidence: float = 1.0,
    conn: Any = None,
) -> dict[str, Any]:
    _ensure_schema(db_path)
    if not broker_order_id:
        return {"status": "ignored", "reason": "broker_order_id_missing"}
    if order_role not in {"entry", "exit"}:
        raise ValueError("Kraken order ownership role must be entry or exit.")
    now = utc_now_iso()
    with _connection(db_path, conn) as active:
        with active:
            active.execute(
                """
                INSERT INTO KRAKEN_AI_ORDER_OWNERSHIP (
                    broker_order_id, logical_trade_id, proposal_id, managed_exit_id,
                    order_role, symbol, side, source, confidence, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(broker_order_id) DO UPDATE SET
                    logical_trade_id = excluded.logical_trade_id,
                    proposal_id = COALESCE(excluded.proposal_id, KRAKEN_AI_ORDER_OWNERSHIP.proposal_id),
                    managed_exit_id = COALESCE(excluded.managed_exit_id, KRAKEN_AI_ORDER_OWNERSHIP.managed_exit_id),
                    order_role = excluded.order_role,
                    symbol = COALESCE(excluded.symbol, KRAKEN_AI_ORDER_OWNERSHIP.symbol),
                    side = COALESCE(excluded.side, KRAKEN_AI_ORDER_OWNERSHIP.side),
                    source = excluded.source,
                    confidence = excluded.confidence,
                    updated_at = excluded.updated_at
                """,
                (
                    broker_order_id,
                    logical_trade_id,
                    proposal_id,
                    managed_exit_id,
                    order_role,
                    symbol,
                    side,
                    source,
                    float(confidence),
                    now,
                    now,
                ),
            )
    return {"status": "registered", "broker_order_id": broker_order_id, "logical_trade_id": logical_trade_id}


def bootstrap_kraken_order_ownership(db_path: Path, *, conn: Any = None) -> dict[str, int]:
    """Recover explicit order ownership from durable IDs, never from symbol similarity."""

    _ensure_schema(db_path)
    inserted = 0
    with _connection(db_path, conn) as active:
        active.row_factory = sqlite3.Row
        try:
            intents = active.execute(
                """
                SELECT result_order_id, client_order_id, symbol, side
                FROM ORDER_INTENT_LOCKS
                WHERE broker = 'kraken' AND result_order_id IS NOT NULL AND result_order_id <> ''
                """
            ).fetchall()
        except Exception:
            intents = []
        try:
            exits = active.execute(
                """
                SELECT managed_exit_id, entry_order_id, exit_order_id, symbol, side, payload_json
                FROM MANAGED_TRADE_EXITS
                WHERE broker = 'kraken'
                """
            ).fetchall()
        except Exception:
            exits = []
        for row in intents:
            result = register_kraken_order_ownership(
                db_path,
                broker_order_id=str(row["result_order_id"]),
                logical_trade_id=str(row["client_order_id"]),
                proposal_id=str(row["client_order_id"]),
                order_role="entry",
                symbol=row["symbol"],
                side=row["side"],
                source="order_intent_lock",
                conn=active,
            )
            inserted += int(result["status"] == "registered")
        for row in exits:
            payload = _json(row["payload_json"])
            proposal_id = str(payload.get("proposal_id") or "")
            logical_trade_id = proposal_id or f"kraken-managed-exit:{row['managed_exit_id']}"
            if row["entry_order_id"]:
                register_kraken_order_ownership(
                    db_path,
                    broker_order_id=str(row["entry_order_id"]),
                    logical_trade_id=logical_trade_id,
                    proposal_id=proposal_id or None,
                    managed_exit_id=int(row["managed_exit_id"]),
                    order_role="entry",
                    symbol=row["symbol"],
                    side=row["side"],
                    source="managed_exit_entry_id",
                    conn=active,
                )
            if row["exit_order_id"]:
                register_kraken_order_ownership(
                    db_path,
                    broker_order_id=str(row["exit_order_id"]),
                    logical_trade_id=logical_trade_id,
                    proposal_id=proposal_id or None,
                    managed_exit_id=int(row["managed_exit_id"]),
                    order_role="exit",
                    symbol=row["symbol"],
                    side="sell" if str(row["side"]).lower() == "buy" else "buy",
                    source="managed_exit_exit_id",
                    conn=active,
                )
    return {"records_seen": len(intents) + len(exits), "registrations": inserted}


def backfill_missing_managed_exits(db_path: Path, *, conn: Any = None) -> dict[str, int]:
    """Create MANAGED_TRADE_EXITS rows for Kraken positions reconciliation knows are open
    but that were never registered for active exit monitoring.

    2026-08-13 hosted incident: two real Kraken positions (BCH, XRP) were confirmed open --
    KRAKEN_RECONCILED_RESULTS had status='holding' with real original_stop/target_price for
    both -- but neither had a MANAGED_TRADE_EXITS row. Two consequences, both silent: (1)
    monitor_managed_exits only ever reads open_managed_exits(), so neither position's
    stop-loss/take-profit was being watched at all -- the recorded stop/target were inert
    metadata, not an active order, the same failure class as the CSL incident on Alpaca; (2)
    _ai_managed_open_trade_count (also sourced from MANAGED_TRADE_EXITS) under-counted Kraken's
    real open exposure as 0, so the KRAKEN_MAX_OPEN_TRADES capacity gate let every new candidate
    through to evaluation instead of cleanly blocking -- and with BCH at 50% of measured
    portfolio value, every candidate then dead-ended at the portfolio-manager concentration
    check with no way out, since diluting that concentration required a new trade and every new
    trade was blocked by the same check (confirmed live: 28 consecutive Kraken rejections, one
    identical reason, spanning BTC/ETH/SOL/XLM proposals).

    Root cause: both entries went through the live order path (a KRAKEN_AI_ORDER_OWNERSHIP
    entry-role row with a real broker_order_id exists for each, recovered by
    bootstrap_kraken_order_ownership from ORDER_INTENT_LOCKS), but the process evidently did not
    reach the record_managed_trade_exit call that normally follows a submitted order in the same
    breath (orchestrator.py) -- almost certainly a crash/timeout mid-flow, the same failure class
    already documented in architecture/PRODUCTION_TIMEOUT_ROOT_CAUSE_ANALYSIS.md. Reconciliation
    already recovers ownership of the raw fills after the fact; nothing recreated the
    managed-exit record itself until now.

    Additive and idempotent: only acts on a 'holding' position that has zero linked managed-exit
    ownership row, so it never re-registers (or duplicates) a position that already has one.
    Never guesses a stop/target or an order ID -- skips anything without a real recorded value
    for either, matching this codebase's standing rule of failing honestly rather than inventing
    a number a live order would be placed against.
    """
    _ensure_schema(db_path)
    checked = 0
    backfilled = 0
    with _connection(db_path, conn) as active:
        active.row_factory = sqlite3.Row
        holding = active.execute(
            "SELECT * FROM KRAKEN_RECONCILED_RESULTS WHERE status = 'holding'"
        ).fetchall()
        for row in holding:
            checked += 1
            logical_trade_id = row["logical_trade_id"]
            stop = row["original_stop"]
            target = row["target_price"]
            entry_price = row["actual_entry"]
            quantity = row["quantity"]
            if not (logical_trade_id and stop and target and entry_price and quantity):
                continue
            already_linked = active.execute(
                """
                SELECT 1 FROM KRAKEN_AI_ORDER_OWNERSHIP
                WHERE logical_trade_id = ? AND order_role = 'entry' AND managed_exit_id IS NOT NULL
                """,
                (logical_trade_id,),
            ).fetchone()
            if already_linked:
                continue
            entry_order = active.execute(
                """
                SELECT broker_order_id FROM KRAKEN_AI_ORDER_OWNERSHIP
                WHERE logical_trade_id = ? AND order_role = 'entry'
                ORDER BY created_at ASC LIMIT 1
                """,
                (logical_trade_id,),
            ).fetchone()
            entry_broker_order_id = entry_order["broker_order_id"] if entry_order else None
            if not entry_broker_order_id:
                # 2026-08-22 recurrence: BCH/XRP/ETH positions genuinely reconciled to
                # 'holding' (real fills, real logical_trade_id/proposal_id from
                # LOGICAL_TRADE_FILLS) still had no KRAKEN_AI_ORDER_OWNERSHIP entry-role row
                # -- the same "crash/timeout mid-flow" failure class described above, just
                # missing the ownership registration this time instead of the managed-exit
                # record. LOGICAL_TRADE_FILLS.broker_order_id is populated directly from the
                # fill itself, not a separate registration step, and a 'holding' status is
                # only possible when a real entry fill row already exists for this exact
                # logical_trade_id -- so it is available whenever the earlier lookup is not.
                fallback_entry_fill = active.execute(
                    """
                    SELECT broker_order_id FROM LOGICAL_TRADE_FILLS
                    WHERE logical_trade_id = ? AND fill_role = 'entry' AND broker_order_id IS NOT NULL
                    ORDER BY filled_at ASC LIMIT 1
                    """,
                    (logical_trade_id,),
                ).fetchone()
                entry_broker_order_id = fallback_entry_fill["broker_order_id"] if fallback_entry_fill else None
            if not entry_broker_order_id:
                continue
            managed = record_managed_trade_exit(
                db_path,
                broker="kraken",
                symbol=row["symbol"],
                side=row["side"] or "buy",
                quantity=float(quantity),
                entry_order_id=str(entry_broker_order_id),
                entry_price=float(entry_price),
                stop_loss=float(stop),
                take_profit=float(target),
                payload={
                    "proposal_id": row["proposal_id"],
                    "logical_trade_id": logical_trade_id,
                    "backfilled_from": "kraken_reconciliation",
                    "backfilled_at": utc_now_iso(),
                },
            )
            register_kraken_order_ownership(
                db_path,
                broker_order_id=str(entry_broker_order_id),
                logical_trade_id=logical_trade_id,
                proposal_id=row["proposal_id"],
                managed_exit_id=int(managed["managed_exit_id"]),
                order_role="entry",
                symbol=row["symbol"],
                side=row["side"],
                source="reconciliation_backfill",
                conn=active,
            )
            backfilled += 1
    return {"positions_checked": checked, "backfilled": backfilled}


def replay_kraken_evidence(
    db_path: Path,
    *,
    events: list[dict[str, Any]],
    source: str = "kraken_evidence_replay",
    conn: Any = None,
) -> dict[str, Any]:
    """Reconcile persisted Kraken evidence. This function has no broker client or order path.

    Opens exactly one database connection for the whole replay batch (or
    reuses a caller-supplied one) and threads it through every helper call
    below instead of letting each helper open its own connection per row.
    Previously this was the confirmed dominant cost of the Kraken startup
    reconciliation timeout (see PRODUCTION_TIMEOUT_ROOT_CAUSE_ANALYSIS.md):
    up to ~1,000 historical events x ~5-8 fresh Postgres connections each.
    This makes no broker calls at all -- see the docstring above -- so
    connection overhead was the entire cost.
    """

    _ensure_schema(db_path)
    with _connection(db_path, conn) as conn:
        bootstrap_kraken_order_ownership(db_path, conn=conn)
        counts = {
            "owned_reconciled": 0,
            "unmanaged_excluded": 0,
            "ambiguous": 0,
            "duplicates": 0,
            "terminal_trades": 0,
            "learning_queued": 0,
            "reconciliation_errors": 0,
        }
        terminals: set[str] = set()
        for raw in events:
            event = normalize_kraken_evidence(raw)
            raw_hash = _stable_hash(raw)
            owner = _ownership(db_path, event["order_id"], conn=conn)
            if owner is None:
                _record_case(
                    db_path,
                    raw_hash=raw_hash,
                    event=event,
                    classification="unmanaged_excluded",
                    reason="No explicit AI Trader order ownership record matched this Kraken order ID; personal/manual evidence was excluded.",
                    confidence=1.0,
                    conn=conn,
                )
                counts["unmanaged_excluded"] += 1
                continue
            if not event["symbol"] or event["record_type"] == "unknown":
                _record_case(
                    db_path,
                    raw_hash=raw_hash,
                    event=event,
                    owner=owner,
                    classification="ambiguous",
                    reason="The owned Kraken event lacked deterministic symbol or record-type evidence.",
                    confidence=0.3,
                    conn=conn,
                )
                counts["ambiguous"] += 1
                continue
            event.update(
                {
                    "logical_trade_id": owner["logical_trade_id"],
                    "proposal_id": owner.get("proposal_id"),
                    "fill_role": owner["order_role"],
                }
            )
            try:
                reconciled = reconcile_canonical_broker_event(
                    db_path,
                    broker="kraken",
                    event=event,
                    source=source,
                    conn=conn,
                )
            except sqlite3.IntegrityError as exc:
                # 2026-08-19 hosted finding: one Kraken order whose logical_trade_id and
                # proposal_id had drifted apart (see _merge_managed_exit_payload's docstring
                # in multi_broker.py for how that happens) hit LOGICAL_TRADES' proposal_id
                # UNIQUE constraint on every single replay -- confirmed live via
                # /kraken-reconciliation/replay. Uncaught, this aborted the whole batch before
                # ever reaching the terminals loop below, so enqueue_learning_workflow never
                # ran for ANY trade in that cycle, not just the poisoned one -- the entire
                # reason learning_queued stayed 0 across every broker-poll-kraken run despite
                # 7 real trades closing the same day. The PostgresConnection.__exit__ that
                # raised this already rolled back just this statement's own transaction scope
                # (see database.py), so the connection is safe to keep using for the
                # remaining events -- one bad order must never block every other trade's
                # learning from ever being recorded again.
                _record_case(
                    db_path,
                    raw_hash=raw_hash,
                    event=event,
                    owner=owner,
                    classification="reconciliation_error",
                    reason=f"Reconciling this event raised {exc.__class__.__name__}: {exc}",
                    confidence=0.0,
                    conn=conn,
                )
                counts["reconciliation_errors"] += 1
                continue
            duplicate = reconciled["event"].get("status") == "duplicate"
            counts["duplicates"] += int(duplicate)
            counts["owned_reconciled"] += int(not duplicate)
            if event["record_type"] == "trade_fill":
                _record_ledger_fill(db_path, event=event, owner=owner, conn=conn)
            _record_case(
                db_path,
                raw_hash=raw_hash,
                event=event,
                owner=owner,
                classification="owned_reconciled",
                reason="Kraken evidence matched an explicit AI Trader broker order ID.",
                confidence=float(owner["confidence"]),
                conn=conn,
            )
            if reconciled.get("terminal"):
                terminals.add(str(reconciled["logical_trade_id"]))
            _refresh_reconciled_result(db_path, str(reconciled["logical_trade_id"]), conn=conn)
        for logical_trade_id in terminals:
            trade = canonical_trade(db_path, logical_trade_id, conn=conn) or {}
            result = _refresh_reconciled_result(db_path, logical_trade_id, conn=conn)
            _mark_managed_exit_reconciled(db_path, logical_trade_id=logical_trade_id, result=result, conn=conn)
            learning = enqueue_learning_workflow(
                db_path,
                logical_trade_id=logical_trade_id,
                broker="kraken",
                payload=_learning_payload(trade, result),
            )
            counts["terminal_trades"] += 1
            counts["learning_queued"] += int(learning["status"] == "queued")
        managed_exit_backfill = backfill_missing_managed_exits(db_path, conn=conn)
        counts["managed_exits_backfilled"] = managed_exit_backfill["backfilled"]
        now = utc_now_iso()
        with conn:
            conn.execute(
                """
                UPDATE KRAKEN_RECONCILIATION_CONTROL
                SET last_replay_at = ?, updated_at = ?, unresolved_count = ?,
                    status = ?, payload_json = ?
                WHERE id = 1
                """,
                (
                    now,
                    now,
                    counts["ambiguous"],
                    "manual_review_required" if counts["ambiguous"] else "replayed_awaiting_verification",
                    json.dumps(counts, sort_keys=True),
                ),
            )
    return {"status": "completed", **counts, "ledger": kraken_capital_ledger_summary(db_path)}


def replay_persisted_kraken_evidence(db_path: Path, *, limit: int = 1000) -> dict[str, Any]:
    """Replay durable broker evidence without contacting Kraken or submitting orders."""

    _ensure_schema(db_path)
    with _connection(db_path, None) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT payload_json, external_id, symbol, side, quantity, price,
                   status, opened_at, closed_at, updated_at
            FROM BROKER_TRADE_HISTORY
            WHERE broker = 'kraken'
            ORDER BY trade_history_id
            LIMIT ?
            """,
            (max(1, int(limit)),),
        ).fetchall()
        events: list[dict[str, Any]] = []
        for row in rows:
            payload = _json(row["payload_json"])
            payload.setdefault("id", row["external_id"])
            payload.setdefault("symbol", row["symbol"])
            payload.setdefault("side", row["side"])
            payload.setdefault("quantity", row["quantity"])
            payload.setdefault("price", row["price"])
            payload.setdefault("status", row["status"])
            payload.setdefault("updated_at", row["updated_at"] or row["closed_at"] or row["opened_at"])
            events.append(payload)
        result = replay_kraken_evidence(db_path, events=events, source="persisted_kraken_evidence_replay", conn=conn)
    return {**result, "persisted_rows_read": len(rows), "broker_orders_submitted": 0}


def kraken_reconciliation_status(db_path: Path) -> dict[str, Any]:
    _ensure_schema(db_path)
    control = reconciliation_control(db_path)
    ledger = kraken_capital_ledger_summary(db_path)
    with closing(connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        ownership = int(conn.execute("SELECT COUNT(*) FROM KRAKEN_AI_ORDER_OWNERSHIP").fetchone()[0])
        cases = [
            dict(row)
            for row in conn.execute(
                """
                SELECT classification, reason, COUNT(*) AS count, MAX(updated_at) AS latest_at
                FROM KRAKEN_RECONCILIATION_CASES
                GROUP BY classification, reason
                ORDER BY count DESC, latest_at DESC
                """
            ).fetchall()
        ]
        results = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM KRAKEN_RECONCILED_RESULTS ORDER BY updated_at DESC LIMIT 100"
            ).fetchall()
        ]
    return {
        "control": control,
        "capital_ledger": ledger,
        "explicit_order_ownership_count": ownership,
        "case_summary": cases,
        "reconciled_trades": results,
        "personal_holdings_included": False,
        "replay_can_submit_orders": False,
    }


def normalize_kraken_evidence(raw: dict[str, Any]) -> dict[str, Any]:
    descr = raw.get("descr") if isinstance(raw.get("descr"), dict) else {}
    record_type = str(raw.get("kraken_record_type") or "")
    if not record_type:
        record_type = "trade_fill" if raw.get("ordertxid") or raw.get("trade_id") else "closed_order" if descr else "unknown"
    order_id = str(
        raw.get("order_id")
        or raw.get("ordertxid")
        or (raw.get("id") if record_type == "closed_order" else "")
        or ""
    )
    fill_id = str(raw.get("fill_id") or raw.get("trade_id") or (raw.get("id") if record_type == "trade_fill" else "") or "")
    symbol = str(raw.get("symbol") or raw.get("pair") or descr.get("pair") or "").upper()
    side = str(raw.get("side") or raw.get("type") or descr.get("type") or "").lower()
    status = str(raw.get("status") or ("filled" if record_type == "trade_fill" else "unknown")).lower()
    stage = _kraken_stage(record_type, status)
    quantity = _number(raw.get("quantity") or raw.get("qty") or raw.get("vol_exec") or raw.get("vol"))
    price = _number(raw.get("average_fill_price") or raw.get("avg_price") or raw.get("price"))
    timestamp = raw.get("transaction_time") or raw.get("time") or raw.get("closetm") or raw.get("updated_at") or utc_now_iso()
    return {
        "kraken_record_type": record_type,
        "record_type": record_type,
        "order_id": order_id,
        "ordertxid": order_id,
        "trade_id": fill_id or None,
        "fill_id": fill_id or None,
        "status": status,
        "stage": stage,
        "symbol": symbol,
        "pair": symbol,
        "side": side,
        "asset_type": "crypto",
        "quantity": quantity if record_type == "trade_fill" else None,
        "filled_quantity": quantity if record_type == "trade_fill" else None,
        "average_fill_price": price if record_type == "trade_fill" else None,
        "price": price if record_type == "trade_fill" else None,
        "exchange_fee": _number(raw.get("fee")) if record_type == "trade_fill" else None,
        "timestamp": str(timestamp),
        "raw": raw,
    }


def kraken_capital_ledger_summary(
    db_path: Path,
    *,
    current_prices: dict[str, float] | None = None,
) -> dict[str, Any]:
    _ensure_schema(db_path)
    normalized_prices = {
        str(symbol).upper(): float(price)
        for symbol, price in (current_prices or {}).items()
        if _number(price) is not None and float(price) > 0
    }
    with closing(connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT entry_type, amount_gbp, fee_gbp FROM KRAKEN_AI_CAPITAL_LEDGER ORDER BY ledger_id"
        ).fetchall()
        trades = conn.execute(
            """
            SELECT gross_pnl, net_pnl, remaining_quantity, terminal
            FROM LOGICAL_TRADES WHERE broker = 'kraken'
              AND logical_trade_id IN (SELECT DISTINCT logical_trade_id FROM KRAKEN_AI_ORDER_OWNERSHIP)
            """
        ).fetchall()
        results = conn.execute(
            """
            SELECT * FROM KRAKEN_RECONCILED_RESULTS
            ORDER BY updated_at DESC
            """
        ).fetchall()
        open_trades = conn.execute(
            """
            SELECT logical_trade_id, symbol, side, average_entry_price,
                   remaining_quantity, exchange_fee, broker_fee
            FROM LOGICAL_TRADES
            WHERE broker = 'kraken' AND terminal = 0
              AND remaining_quantity > 0
              AND logical_trade_id IN (
                  SELECT DISTINCT logical_trade_id FROM KRAKEN_AI_ORDER_OWNERSHIP
              )
            ORDER BY updated_at DESC
            """
        ).fetchall()
    allocation = sum(float(row["amount_gbp"]) for row in rows if row["entry_type"] == "founder_allocation")
    cash = sum(float(row["amount_gbp"]) for row in rows)
    realized_gross = sum(float(row["gross_pnl"] or 0) for row in trades if row["terminal"])
    realized_net = sum(float(row["net_pnl"] or 0) for row in trades if row["terminal"])
    deployed = max(0.0, allocation + realized_net - cash)
    unrealized = 0.0
    marked_positions: list[dict[str, Any]] = []
    unpriced_symbols: list[str] = []
    for row in open_trades:
        symbol = str(row["symbol"] or "").upper()
        entry_price = _number(row["average_entry_price"])
        quantity = _number(row["remaining_quantity"])
        current_price = normalized_prices.get(symbol)
        if not symbol or entry_price is None or quantity is None or current_price is None:
            if symbol:
                unpriced_symbols.append(symbol)
            continue
        multiplier = 1 if str(row["side"] or "buy").lower() == "buy" else -1
        position_pnl = (current_price - entry_price) * quantity * multiplier
        unrealized += position_pnl
        marked_positions.append(
            {
                "logical_trade_id": row["logical_trade_id"],
                "symbol": symbol,
                "quantity": quantity,
                "entry_price": entry_price,
                "current_price": current_price,
                "unrealized_pnl_gbp": round(position_pnl, 8),
            }
        )
    all_open_positions_marked = len(marked_positions) == len(open_trades)
    return {
        "allocation_gbp": round(allocation, 8),
        "available_cash_gbp": round(cash, 8),
        "deployed_capital_gbp": round(deployed, 8),
        "realized_gross_pnl_gbp": round(realized_gross, 8),
        "realized_net_pnl_gbp": round(realized_net, 8),
        "unrealized_pnl_gbp": round(unrealized, 8) if all_open_positions_marked else None,
        "unrealized_pnl_status": (
            "Calculated from current Kraken prices for every AI-managed open position."
            if all_open_positions_marked
            else "Unavailable because current Kraken prices were not captured for: "
            + ", ".join(sorted(set(unpriced_symbols)))
        ),
        "marked_open_positions": marked_positions,
        "unpriced_open_symbols": sorted(set(unpriced_symbols)),
        "personal_holdings_included": False,
        "reconciled_results": [dict(row) for row in results],
    }


def verify_kraken_reconciliation(db_path: Path) -> dict[str, Any]:
    _ensure_schema(db_path)
    ledger = kraken_capital_ledger_summary(db_path)
    with closing(connect(db_path)) as conn:
        unresolved = int(
            conn.execute(
                "SELECT COUNT(*) FROM KRAKEN_RECONCILIATION_CASES WHERE classification = 'ambiguous'"
            ).fetchone()[0]
        )
        owned = int(conn.execute("SELECT COUNT(*) FROM KRAKEN_AI_ORDER_OWNERSHIP").fetchone()[0])
        terminal = int(
            conn.execute(
                """
                SELECT COUNT(*) FROM LOGICAL_TRADES
                WHERE broker = 'kraken' AND terminal = 1
                  AND logical_trade_id IN (SELECT DISTINCT logical_trade_id FROM KRAKEN_AI_ORDER_OWNERSHIP)
                """
            ).fetchone()[0]
        )
        learning = int(
            conn.execute(
                "SELECT COUNT(*) FROM SPRINT6_WORKFLOW_OUTBOX WHERE workflow_type = 'closed_loop_learning' AND entity_id IN (SELECT DISTINCT logical_trade_id FROM KRAKEN_AI_ORDER_OWNERSHIP)"
            ).fetchone()[0]
        )
        results = int(
            conn.execute(
                "SELECT COUNT(*) FROM KRAKEN_RECONCILED_RESULTS WHERE status = 'closed'"
            ).fetchone()[0]
        )
    checks = {
        "explicit_order_ownership_exists": owned > 0,
        "no_ambiguous_owned_evidence": unresolved == 0,
        "personal_holdings_excluded": ledger["personal_holdings_included"] is False,
        "realized_and_unrealized_separated": "realized_net_pnl_gbp" in ledger and "unrealized_pnl_gbp" in ledger,
        "terminal_learning_idempotent": learning == terminal,
        "terminal_results_complete": results == terminal,
        "allocation_is_finite": ledger["allocation_gbp"] > 0 and ledger["available_cash_gbp"] <= ledger["allocation_gbp"] + max(0.0, ledger["realized_net_pnl_gbp"]) + 1e-6,
    }
    passed = all(checks.values())
    now = utc_now_iso()
    with closing(connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                UPDATE KRAKEN_RECONCILIATION_CONTROL
                SET last_verified_at = ?, updated_at = ?, unresolved_count = ?,
                    status = ?, payload_json = ?
                WHERE id = 1
                """,
                (
                    now,
                    now,
                    unresolved,
                    "verified_hold_active" if passed else "verification_failed",
                    json.dumps({"checks": checks, "ledger": ledger}, sort_keys=True, default=str),
                ),
            )
    return {"status": "verified" if passed else "failed", "passed": passed, "checks": checks, "ledger": ledger}


def founder_override_kraken_hold(db_path: Path, *, reason: str) -> dict[str, Any]:
    """Release the Kraken entry hold on explicit Founder authorization, bypassing verification.

    verify_kraken_reconciliation's explicit_order_ownership_exists check can never pass for
    Kraken evidence that predates this reconciliation system's 2026-07-27 bootstrap -- there is
    no way to retroactively prove an order was AI Trader-placed versus pre-existing personal
    Kraken activity from before ownership records existed. This lets the Founder release the
    hold based on manual review (2026-08-01: confirmed via hosted /kraken-reconciliation that
    all 864 unmatched Kraken events are pre-existing personal/manual activity, not an AI Trader
    accounting gap) instead of waiting on a check that can never pass. The independent
    KRAKEN_MAX_ORDER_GBP / KRAKEN_MIN_ORDER_GBP / KRAKEN_MAX_OPEN_TRADES /
    KRAKEN_TRADING_ALLOCATION_GBP guardrails in broker_adapters.KrakenAdapter are unaffected --
    this only releases the entry hold, it does not change spend limits.
    """

    verification_snapshot = verify_kraken_reconciliation(db_path)
    control = set_reconciliation_hold(
        db_path,
        active=False,
        status="founder_override",
        reason=reason,
        payload={"override": True, "verification_at_override": verification_snapshot},
    )
    return {"status": "resumed", "control": control, "verification_at_override": verification_snapshot}


def resume_kraken_entries_after_verification(db_path: Path) -> dict[str, Any]:
    verification = verify_kraken_reconciliation(db_path)
    if not verification["passed"]:
        return {
            "status": "rejected",
            "message": "Kraken entries remain paused because reconciliation verification failed.",
            "verification": verification,
        }
    control = set_reconciliation_hold(
        db_path,
        active=False,
        status="verified",
        reason="Founder-authorized reconciliation verification passed; new Kraken entries may resume.",
        payload={"verification": verification},
    )
    return {"status": "resumed", "control": control, "verification": verification}


def _ownership(db_path: Path, order_id: str, *, conn: Any = None) -> dict[str, Any] | None:
    if not order_id:
        return None
    with _connection(db_path, conn) as active:
        active.row_factory = sqlite3.Row
        row = active.execute(
            "SELECT * FROM KRAKEN_AI_ORDER_OWNERSHIP WHERE broker_order_id = ?",
            (order_id,),
        ).fetchone()
    return dict(row) if row else None


def _record_ledger_fill(db_path: Path, *, event: dict[str, Any], owner: dict[str, Any], conn: Any = None) -> None:
    quantity = _number(event.get("filled_quantity"))
    price = _number(event.get("average_fill_price"))
    if not quantity or not price:
        return
    fee = _number(event.get("exchange_fee")) or 0.0
    role = str(owner["order_role"])
    amount = -(quantity * price + fee) if role == "entry" else quantity * price - fee
    fill_id = str(event.get("fill_id") or "")
    key = f"kraken-fill:{fill_id}:{role}"
    with _connection(db_path, conn) as active:
        with active:
            active.execute(
                """
                INSERT INTO KRAKEN_AI_CAPITAL_LEDGER (
                    created_at, event_time, logical_trade_id, broker_order_id,
                    broker_fill_id, entry_type, amount_gbp, quantity, price,
                    fee_gbp, idempotency_key, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(idempotency_key) DO NOTHING
                """,
                (
                    utc_now_iso(),
                    event["timestamp"],
                    owner["logical_trade_id"],
                    event["order_id"],
                    fill_id,
                    f"{role}_fill",
                    amount,
                    quantity,
                    price,
                    fee,
                    key,
                    json.dumps(event, sort_keys=True, default=str),
                ),
            )


def _record_case(
    db_path: Path,
    *,
    raw_hash: str,
    event: dict[str, Any],
    classification: str,
    reason: str,
    confidence: float,
    owner: dict[str, Any] | None = None,
    conn: Any = None,
) -> None:
    now = utc_now_iso()
    with _connection(db_path, conn) as active:
        with active:
            active.execute(
                """
                INSERT INTO KRAKEN_RECONCILIATION_CASES (
                    created_at, updated_at, raw_event_hash, broker_order_id,
                    broker_fill_id, logical_trade_id, classification, reason,
                    confidence, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(raw_event_hash) DO UPDATE SET
                    updated_at = excluded.updated_at,
                    classification = excluded.classification,
                    reason = excluded.reason,
                    confidence = excluded.confidence,
                    payload_json = excluded.payload_json
                """,
                (
                    now,
                    now,
                    raw_hash,
                    event.get("order_id"),
                    event.get("fill_id"),
                    owner.get("logical_trade_id") if owner else None,
                    classification,
                    reason,
                    confidence,
                    json.dumps(event, sort_keys=True, default=str),
                ),
            )


def _refresh_reconciled_result(db_path: Path, logical_trade_id: str, *, conn: Any = None) -> dict[str, Any]:
    trade = canonical_trade(db_path, logical_trade_id, conn=conn) or {}
    with _connection(db_path, conn) as active:
        active.row_factory = sqlite3.Row
        fills = active.execute(
            """
            SELECT fill_role, side, quantity, price, broker_fee, exchange_fee, filled_at
            FROM LOGICAL_TRADE_FILLS
            WHERE logical_trade_id = ?
            ORDER BY filled_at, fill_id
            """,
            (logical_trade_id,),
        ).fetchall()
    entries = [row for row in fills if row["fill_role"] == "entry"]
    exits = [row for row in fills if row["fill_role"] == "exit"]
    entry_time = entries[0]["filled_at"] if entries else None
    exit_time = exits[-1]["filled_at"] if exits else None
    entry_price = _number(trade.get("average_entry_price"))
    exit_price = _number(trade.get("average_exit_price"))
    intended_entry = _number(trade.get("intended_entry_price"))
    stop = _number(trade.get("original_stop"))
    target = _number(trade.get("intended_target"))
    quantity = _number(trade.get("entry_filled_quantity"))
    initial_risk = abs((intended_entry or entry_price or 0) - (stop or 0)) * (quantity or 0) if stop else None
    gross = _number(trade.get("gross_pnl"))
    net = _number(trade.get("net_pnl"))
    holding_seconds = _elapsed_seconds(entry_time, exit_time)
    planned_r = (
        abs(target - (intended_entry or entry_price)) / abs((intended_entry or entry_price) - stop)
        if target is not None and stop is not None and (intended_entry or entry_price) is not None
        and abs((intended_entry or entry_price) - stop) > 0
        else None
    )
    side_factor = 1 if str(trade.get("side") or "buy").lower() == "buy" else -1
    result = {
        "logical_trade_id": logical_trade_id,
        "proposal_id": trade.get("proposal_id"),
        "symbol": trade.get("symbol"),
        "side": trade.get("side"),
        "status": "closed" if trade.get("terminal") else "holding" if entries else "awaiting_fill",
        "entry_time": entry_time,
        "exit_time": exit_time,
        "holding_seconds": holding_seconds,
        "quantity": quantity,
        "intended_entry": intended_entry,
        "actual_entry": entry_price,
        "original_stop": stop,
        "target_price": target,
        "actual_exit": exit_price,
        "broker_fee": _number(trade.get("broker_fee")) or 0.0,
        "exchange_fee": _number(trade.get("exchange_fee")) or 0.0,
        "gross_pnl": gross,
        "net_pnl": net,
        "initial_risk": initial_risk,
        "planned_r": planned_r,
        "gross_r": gross / initial_risk if gross is not None and initial_risk else None,
        "net_r": net / initial_risk if net is not None and initial_risk else None,
        "entry_slippage": (
            (entry_price - intended_entry) * side_factor
            if entry_price is not None and intended_entry is not None
            else None
        ),
        "exit_slippage": (
            (target - exit_price) * side_factor
            if exit_price is not None and target is not None
            else None
        ),
        "reconciliation_confidence": _number(trade.get("reconciliation_confidence")) or 0.0,
    }
    now = utc_now_iso()
    with _connection(db_path, conn) as active:
        with active:
            active.execute(
                """
                INSERT INTO KRAKEN_RECONCILED_RESULTS (
                    logical_trade_id, proposal_id, symbol, side, status,
                    entry_time, exit_time, holding_seconds, quantity,
                    intended_entry, actual_entry, original_stop, target_price,
                    actual_exit, broker_fee, exchange_fee, gross_pnl, net_pnl,
                    initial_risk, planned_r, gross_r, net_r, entry_slippage,
                    exit_slippage, reconciliation_confidence, updated_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(logical_trade_id) DO UPDATE SET
                    proposal_id = excluded.proposal_id,
                    symbol = excluded.symbol,
                    side = excluded.side,
                    status = excluded.status,
                    entry_time = excluded.entry_time,
                    exit_time = excluded.exit_time,
                    holding_seconds = excluded.holding_seconds,
                    quantity = excluded.quantity,
                    intended_entry = excluded.intended_entry,
                    actual_entry = excluded.actual_entry,
                    original_stop = excluded.original_stop,
                    target_price = excluded.target_price,
                    actual_exit = excluded.actual_exit,
                    broker_fee = excluded.broker_fee,
                    exchange_fee = excluded.exchange_fee,
                    gross_pnl = excluded.gross_pnl,
                    net_pnl = excluded.net_pnl,
                    initial_risk = excluded.initial_risk,
                    planned_r = excluded.planned_r,
                    gross_r = excluded.gross_r,
                    net_r = excluded.net_r,
                    entry_slippage = excluded.entry_slippage,
                    exit_slippage = excluded.exit_slippage,
                    reconciliation_confidence = excluded.reconciliation_confidence,
                    updated_at = excluded.updated_at,
                    payload_json = excluded.payload_json
                """,
                (
                    result["logical_trade_id"],
                    result["proposal_id"],
                    result["symbol"],
                    result["side"],
                    result["status"],
                    result["entry_time"],
                    result["exit_time"],
                    result["holding_seconds"],
                    result["quantity"],
                    result["intended_entry"],
                    result["actual_entry"],
                    result["original_stop"],
                    result["target_price"],
                    result["actual_exit"],
                    result["broker_fee"],
                    result["exchange_fee"],
                    result["gross_pnl"],
                    result["net_pnl"],
                    result["initial_risk"],
                    result["planned_r"],
                    result["gross_r"],
                    result["net_r"],
                    result["entry_slippage"],
                    result["exit_slippage"],
                    result["reconciliation_confidence"],
                    now,
                    json.dumps(result, sort_keys=True, default=str),
                ),
            )
    return result



def _record_attribution_for_reconciled_trade(conn: Any, *, result: dict[str, Any], now: str) -> None:
    """One PERFORMANCE_ATTRIBUTION row per completed round trip, from reconciled fills only.

    Skips anything without a real entry price, exit price and quantity: an attribution row
    with a guessed price would corrupt both the Founder's P&L view and every strategy
    statistic computed from it. ON CONFLICT DO NOTHING keeps repeated replays idempotent --
    replay_kraken_evidence re-processes the same terminal trades on later cycles.
    """
    entry = _number(result.get("actual_entry"))
    exit_price = _number(result.get("actual_exit"))
    quantity = _number(result.get("quantity"))
    if entry is None or exit_price is None or not quantity:
        return
    # 2026-08-26 audit finding: PERFORMANCE_ATTRIBUTION held both XRP and XRPGBP, and both
    # SOL and SOLGBP, for the same coin -- Kraken reports the traded PAIR here while other
    # writers use the bare coin. Anything grouping by symbol therefore split one coin's
    # record in two: SOL's real 0-from-5 read as 0-from-4 and 0-from-1, which is exactly the
    # per-coin history the entry gates now consult. Normalised on the way in so the stored
    # record is right, not merely corrected by whichever reader remembers to.
    symbol = normalize_symbol(result.get("symbol"))
    closed_at = result.get("exit_time") or now
    # 2026-08-27 audit finding: both of these were the constant "Reconciled from Kraken
    # fills." on all 38 production rows. reporting_service groups wins by entry_reason and
    # losses by exit_reason to build its lessons, so that constant meant the learning loop
    # was grouping every trade into a single bucket and learning nothing. The real
    # rationale was already stored against the proposal; it was simply never joined.
    entry_reason = (
        trade_reasons.entry_reasons_for_proposals(conn, [result.get("proposal_id")]).get(
            str(result.get("proposal_id") or "")
        )
        or trade_reasons.UNRECORDED_ENTRY
    )
    exit_reason = (
        trade_reasons.nearest_exit_reason(
            trade_reasons.exit_reasons_by_symbol(conn, broker="kraken"), symbol, closed_at
        )
        or trade_reasons.UNRECORDED_EXIT
    )
    try:
        # PERFORMANCE_ATTRIBUTION's only key is its autoincrement id, so ON CONFLICT cannot
        # dedupe here -- an explicit check is required. Without it every replay cycle would
        # add another copy of the same round trip, inflating both the Founder's realised P&L
        # and every strategy win rate computed from this table.
        # Deliberately does NOT compare quantity. Postgres stores it as REAL (4-byte) while
        # the bound parameter is an 8-byte float, so 0.1 = 0.1 is FALSE and the guard never
        # matched -- confirmed live, LTC/XLM/LINK each recorded twice an hour apart with
        # byte-identical symbol, closed_at and quantity. broker + symbol + exit timestamp is
        # already unique for a round trip: the same coin cannot close twice at the same
        # instant on the same broker.
        existing = conn.execute(
            """
            SELECT 1 FROM PERFORMANCE_ATTRIBUTION
            WHERE broker = 'kraken' AND symbol = ? AND closed_at = ?
            LIMIT 1
            """,
            (symbol, closed_at),
        ).fetchone()
        if existing:
            return
        conn.execute(
            """
            INSERT INTO PERFORMANCE_ATTRIBUTION (
                created_at, proposal_id, broker, symbol, asset_type, side,
                entry_price, exit_price, quantity, profit_loss, opened_at,
                closed_at, holding_period_seconds, entry_reason, exit_reason,
                primary_factors_json
            ) VALUES (?, ?, 'kraken', ?, 'crypto', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now,
                result.get("proposal_id"),
                symbol,
                str(result.get("side") or "buy").lower(),
                entry,
                exit_price,
                quantity,
                _number(result.get("net_pnl")),
                result.get("entry_time"),
                closed_at,
                # holding_seconds arrives NULL on every production row, so this recomputes
                # from the two timestamps that are reliably present rather than trusting a
                # field that demonstrably was not populated.
                _number(result.get("holding_seconds"))
                or trade_reasons.holding_seconds(result.get("entry_time"), closed_at),
                entry_reason,
                exit_reason,
                json.dumps({"logical_trade_id": result.get("logical_trade_id")}, sort_keys=True, default=str),
            ),
        )
    except Exception:  # noqa: BLE001 - reporting must never break reconciliation itself
        return


def _mark_managed_exit_reconciled(
    db_path: Path,
    *,
    logical_trade_id: str,
    result: dict[str, Any],
    conn: Any = None,
) -> None:
    """Close only explicitly linked managed exits after the canonical exit fill is terminal.

    Also writes the PERFORMANCE_ATTRIBUTION row for the completed round trip.

    2026-08-23 finding: PERFORMANCE_ATTRIBUTION was EMPTY in production -- 0 rows, ever.
    Its only writer, multi_broker.close_managed_exit_and_record, is called from nowhere, and
    real Kraken trades close down this path instead. Three consequences, all silent:

      1. "Completed Trades Today" read 0 on a day with three completed round trips.
      2. Per-trade realised P&L never appeared in Trade History.
      3. Worse, PERFORMANCE_ATTRIBUTION is the ONLY source calculate_performance_metrics and
         _strategy_history read, so strategy win rates and expectancy had no input at all --
         which is why live strategy rankings returned 0 rows. The learning loop had nothing
         to learn from.

    Everything written here comes from the reconciled result (real fills), never estimated.
    A round trip with no exit price is skipped rather than recorded with a guessed one.
    """

    now = utc_now_iso()
    with _connection(db_path, conn) as active:
        with active:
            active.execute(
                """
                UPDATE MANAGED_TRADE_EXITS
                SET status = 'closed',
                    updated_at = ?,
                    last_checked_at = ?
                WHERE broker = 'kraken'
                  AND status IN ('open', 'exit_submitted')
                  AND managed_exit_id IN (
                      SELECT managed_exit_id
                      FROM KRAKEN_AI_ORDER_OWNERSHIP
                      WHERE logical_trade_id = ?
                        AND order_role = 'exit'
                        AND managed_exit_id IS NOT NULL
                  )
                """,
                (
                    now,
                    now,
                    logical_trade_id,
                ),
            )
            _record_attribution_for_reconciled_trade(active, result=result, now=now)


def _learning_payload(trade: dict[str, Any], result: dict[str, Any] | None = None) -> dict[str, Any]:
    result = result or {}
    return {
        "symbol": trade.get("symbol"),
        "attribution": {
            "proposal_id": trade.get("proposal_id"),
            "symbol": trade.get("symbol"),
            "side": trade.get("side"),
            "quantity": trade.get("entry_filled_quantity"),
            "entry_price": trade.get("average_entry_price"),
            "exit_price": trade.get("average_exit_price"),
            "broker_fee": trade.get("broker_fee"),
            "exchange_fee": trade.get("exchange_fee"),
            "gross_realized_pnl": trade.get("gross_pnl"),
            "profit_loss": trade.get("gross_pnl"),
            "net_realized_pnl": trade.get("net_pnl"),
            "entry_time": result.get("entry_time"),
            "exit_time": result.get("exit_time"),
            "holding_seconds": result.get("holding_seconds"),
            "initial_risk": result.get("initial_risk"),
            "planned_r": result.get("planned_r"),
            "gross_r": result.get("gross_r"),
            "net_r": result.get("net_r"),
            "entry_slippage": result.get("entry_slippage"),
            "exit_slippage": result.get("exit_slippage"),
            "original_stop": result.get("original_stop"),
            "target_price": result.get("target_price"),
        },
        "decision_context": _json(trade.get("decision_context_json")),
    }


def _kraken_stage(record_type: str, status: str) -> str:
    if record_type == "trade_fill":
        return "fully_filled"
    if status in {"canceled", "cancelled"}:
        return "cancelled"
    if status in {"rejected", "expired"}:
        return status
    if record_type == "closed_order":
        # Kraken ClosedOrders describes an order that is no longer open. It does
        # not prove that an investment position has been exited.
        return "broker_acknowledged"
    return "broker_acknowledged"


def _stable_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def _number(value: Any) -> float | None:
    try:
        return None if value in {None, ""} else float(value)
    except (TypeError, ValueError):
        return None


def _elapsed_seconds(start: Any, end: Any) -> float | None:
    if not start or not end:
        return None
    try:
        start_dt = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=timezone.utc)
        return max(0.0, (end_dt - start_dt).total_seconds())
    except (TypeError, ValueError):
        return None
