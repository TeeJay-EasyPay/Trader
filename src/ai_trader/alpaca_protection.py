"""Change-only evidence that AI-managed Alpaca positions retain broker-side stops."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from contextlib import closing
from pathlib import Path
from typing import Any

from .database import connect, selected_backend
from .models import utc_now_iso


SCHEMA = """
CREATE TABLE IF NOT EXISTS ALPACA_PROTECTION_STATE (
    logical_trade_id TEXT PRIMARY KEY,
    observed_at TEXT NOT NULL,
    protection_status TEXT NOT NULL,
    expected_quantity REAL NOT NULL,
    protected_quantity REAL NOT NULL,
    expected_stop REAL,
    observed_stop REAL,
    stop_order_id TEXT,
    evidence_digest TEXT NOT NULL,
    evidence_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ALPACA_PROTECTION_EVENTS (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    logical_trade_id TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    protection_status TEXT NOT NULL,
    evidence_digest TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    UNIQUE(logical_trade_id, evidence_digest)
);
CREATE INDEX IF NOT EXISTS idx_alpaca_protection_events_trade
ON ALPACA_PROTECTION_EVENTS(logical_trade_id, observed_at);
"""

ACTIVE = {"new", "accepted", "pending_new", "accepted_for_bidding", "partially_filled", "held", "pending_replace"}
STOP_TYPES = {"stop", "stop_limit", "trailing_stop"}
_SCHEMA_LOCK = threading.Lock()
_SCHEMA_KEYS: set[str] = set()


def initialize_alpaca_protection_schema(db_path: Path) -> None:
    key = "postgres" if selected_backend() == "postgres" else f"sqlite:{Path(db_path).resolve()}"
    if key in _SCHEMA_KEYS:
        return
    with _SCHEMA_LOCK:
        if key in _SCHEMA_KEYS:
            return
        with closing(connect(db_path)) as conn:
            with conn:
                conn.executescript(SCHEMA)
        _SCHEMA_KEYS.add(key)


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def verify_alpaca_protection(db_path: Path, orders: list[dict[str, Any]]) -> dict[str, Any]:
    """Compare canonical open exposure with stops in the already-fetched order response."""
    initialize_alpaca_protection_schema(db_path)
    with closing(connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        trades = conn.execute(
            "SELECT logical_trade_id,symbol,original_stop,entry_filled_quantity,"
            "exit_filled_quantity,remaining_quantity FROM LOGICAL_TRADES "
            "WHERE broker='alpaca' AND terminal=0 AND entry_filled_quantity>exit_filled_quantity"
        ).fetchall()
        if not trades:
            return {"checked": 0, "changed": 0, "protected": 0, "gaps": 0, "unknown": 0}
        ids = [str(row["logical_trade_id"]) for row in trades]
        marks = ",".join("?" for _ in ids)
        links = conn.execute(
            "SELECT logical_trade_id,broker_order_id,stage FROM LOGICAL_TRADE_EVENTS "
            f"WHERE logical_trade_id IN ({marks}) AND broker_order_id IS NOT NULL",
            tuple(ids),
        ).fetchall()
        try:
            managed_stops = conn.execute(
                "SELECT entry_order_id,native_stop_order_id FROM MANAGED_TRADE_EXITS "
                "WHERE broker='alpaca' AND status='open' AND native_stop_order_id IS NOT NULL"
            ).fetchall()
        except Exception:
            managed_stops = []
        current = {
            str(row["logical_trade_id"]): str(row["evidence_digest"])
            for row in conn.execute(
                f"SELECT logical_trade_id,evidence_digest FROM ALPACA_PROTECTION_STATE WHERE logical_trade_id IN ({marks})",
                tuple(ids),
            ).fetchall()
        }

    linked: dict[str, set[str]] = {trade_id: set() for trade_id in ids}
    entries: dict[str, set[str]] = {trade_id: set() for trade_id in ids}
    for row in links:
        target = entries if "entry" in str(row["stage"]).lower() else linked
        target[str(row["logical_trade_id"])].add(str(row["broker_order_id"]))
    # Alpaca trailing stops are standalone orders, so they have no broker parent id.
    # The managed-exit ledger is their durable identity bridge back to the entry.
    for row in managed_stops:
        entry_id = str(row["entry_order_id"] or "")
        for trade_id, entry_ids in entries.items():
            if entry_id and entry_id in entry_ids:
                linked[trade_id].add(str(row["native_stop_order_id"]))

    observations: list[dict[str, Any]] = []
    for trade in trades:
        trade_id = str(trade["logical_trade_id"])
        expected_qty = max(0.0, float(trade["remaining_quantity"] or (float(trade["entry_filled_quantity"] or 0) - float(trade["exit_filled_quantity"] or 0))))
        candidates = []
        for order in orders:
            oid = str(order.get("id") or order.get("order_id") or "")
            parent = str(order.get("parent_order_id") or "")
            kind = str(order.get("type") or order.get("order_type") or "").lower()
            if kind in STOP_TYPES and (oid in linked[trade_id] or parent in entries[trade_id]):
                candidates.append(order)
        active = [order for order in candidates if str(order.get("status") or "").lower() in ACTIVE]
        best = max(active, key=lambda order: _float(order.get("qty") or order.get("quantity")) or 0, default=None)
        protected_qty = _float((best or {}).get("qty") or (best or {}).get("quantity")) or 0.0
        expected_stop = _float(trade["original_stop"])
        observed_stop = _float((best or {}).get("stop_price"))
        if best is None:
            status = "unprotected" if candidates else "unknown"
        elif protected_qty + 1e-9 < expected_qty:
            status = "undersized"
        elif expected_stop is not None and observed_stop is not None and abs(expected_stop - observed_stop) > max(0.01, abs(expected_stop) * 0.001):
            status = "stop_price_mismatch"
        else:
            status = "protected"
        evidence = {
            "symbol": trade["symbol"], "status": status,
            "expected_quantity": round(expected_qty, 8), "protected_quantity": round(protected_qty, 8),
            "expected_stop": expected_stop, "observed_stop": observed_stop,
            "stop_order_id": str((best or {}).get("id") or (best or {}).get("order_id") or "") or None,
            "candidate_stop_orders": len(candidates),
        }
        digest = hashlib.sha256(json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        evidence["digest"] = digest
        evidence["logical_trade_id"] = trade_id
        observations.append(evidence)

    changed = [item for item in observations if current.get(item["logical_trade_id"]) != item["digest"]]
    if changed:
        observed_at = utc_now_iso()
        with closing(connect(db_path)) as conn:
            with conn:
                for item in changed:
                    payload = json.dumps(item, sort_keys=True)
                    values = (
                        item["logical_trade_id"], observed_at, item["status"], item["expected_quantity"],
                        item["protected_quantity"], item["expected_stop"], item["observed_stop"],
                        item["stop_order_id"], item["digest"], payload,
                    )
                    conn.execute(
                        "INSERT INTO ALPACA_PROTECTION_STATE "
                        "(logical_trade_id,observed_at,protection_status,expected_quantity,protected_quantity,expected_stop,observed_stop,stop_order_id,evidence_digest,evidence_json) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(logical_trade_id) DO UPDATE SET "
                        "observed_at=excluded.observed_at,protection_status=excluded.protection_status,expected_quantity=excluded.expected_quantity,"
                        "protected_quantity=excluded.protected_quantity,expected_stop=excluded.expected_stop,observed_stop=excluded.observed_stop,"
                        "stop_order_id=excluded.stop_order_id,evidence_digest=excluded.evidence_digest,evidence_json=excluded.evidence_json",
                        values,
                    )
                    conn.execute(
                        "INSERT INTO ALPACA_PROTECTION_EVENTS (logical_trade_id,observed_at,protection_status,evidence_digest,evidence_json) "
                        "VALUES (?,?,?,?,?) ON CONFLICT(logical_trade_id,evidence_digest) DO NOTHING",
                        (item["logical_trade_id"], observed_at, item["status"], item["digest"], payload),
                    )
    return {
        "checked": len(observations), "changed": len(changed),
        "protected": sum(item["status"] == "protected" for item in observations),
        "gaps": sum(item["status"] in {"unprotected", "undersized", "stop_price_mismatch"} for item in observations),
        "unknown": sum(item["status"] == "unknown" for item in observations),
        "changes": changed,
    }


def resolve_alpaca_protection_incident(db_path: Path, logical_trade_id: str) -> None:
    """Close a previously reported gap only after the broker evidence is protected."""
    now = utc_now_iso()
    try:
        with closing(connect(db_path)) as conn:
            with conn:
                conn.execute(
                    "UPDATE INCIDENT_LIFECYCLE SET status='resolved',resolution_timestamp=?,last_observed_at=?,"
                    "explanation=? WHERE incident_key=? AND status='open'",
                    (now, now, "Broker-side stop protection is present again.",
                     f"alpaca-protection:{logical_trade_id}"),
                )
    except Exception:
        # No incident table also means there is no prior incident to resolve (minimal tests
        # and fresh local databases); protection evidence itself remains valid.
        return
