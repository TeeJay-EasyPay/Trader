"""Alpaca paper-account fee evidence and conservative pre-trade estimates."""
from __future__ import annotations

import math
import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .database import connect, selected_backend
from .models import utc_now_iso


SCHEMA = """
CREATE TABLE IF NOT EXISTS ALPACA_ACCOUNT_FEES (
    activity_id TEXT PRIMARY KEY,
    activity_date TEXT NOT NULL,
    created_at TEXT,
    subtype TEXT,
    net_amount REAL NOT NULL,
    currency TEXT NOT NULL,
    description TEXT,
    status TEXT,
    observed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_alpaca_account_fees_date
ON ALPACA_ACCOUNT_FEES(activity_date);
"""


_SCHEMA_LOCK = threading.Lock()
_SCHEMA_KEYS: set[str] = set()


def initialize_alpaca_cost_schema(db_path: Path) -> None:
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


def record_alpaca_fee_activities(db_path: Path, activities: list[dict[str, Any]]) -> dict[str, Any]:
    """Persist each broker ledger fee once; FEE rows are account-level, not trade-level."""
    initialize_alpaca_cost_schema(db_path)
    observed = utc_now_iso()
    rows: list[tuple[Any, ...]] = []
    for item in activities:
        activity_id = str(item.get("id") or "").strip()
        if not activity_id:
            continue
        activity_date = str(item.get("date") or item.get("created_at") or "")[:10]
        try:
            amount = float(item.get("net_amount") or 0)
        except (TypeError, ValueError):
            continue
        rows.append((
            activity_id, activity_date, item.get("created_at"),
            item.get("activity_sub_type"), amount,
            str(item.get("currency") or "USD"), item.get("description"),
            item.get("status"), observed,
        ))
    if not rows:
        return {"received": len(activities), "inserted": 0, "recorded_cost_usd": 0.0}
    placeholders = ",".join(["(?,?,?,?,?,?,?,?,?)"] * len(rows))
    flat = tuple(value for row in rows for value in row)
    with closing(connect(db_path)) as conn:
        with conn:
            cursor = conn.execute(
                "INSERT INTO ALPACA_ACCOUNT_FEES "
                "(activity_id,activity_date,created_at,subtype,net_amount,currency,description,status,observed_at) "
                f"VALUES {placeholders} ON CONFLICT(activity_id) DO NOTHING",
                flat,
            )
    inserted = max(0, int(cursor.rowcount or 0))
    return {
        "received": len(activities),
        "inserted": inserted,
        "recorded_cost_usd": round(sum(max(0.0, -row[4]) for row in rows), 6),
    }


def alpaca_fee_periods(db_path: Path, *, now_epoch: float | None = None) -> dict[str, dict[str, Any]]:
    """Return account-level paper fees for all reporting windows in one small read."""
    initialize_alpaca_cost_schema(db_path)
    now = datetime.fromtimestamp(now_epoch, timezone.utc) if now_epoch is not None else datetime.now(timezone.utc)
    cutoffs = {
        "day": datetime.fromtimestamp(now.timestamp() - 86400, timezone.utc).date().isoformat(),
        "week": datetime.fromtimestamp(now.timestamp() - 7 * 86400, timezone.utc).date().isoformat(),
        "month": datetime.fromtimestamp(now.timestamp() - 30 * 86400, timezone.utc).date().isoformat(),
    }
    with closing(connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT "
            "SUM(CASE WHEN activity_date>=? AND net_amount<0 THEN -net_amount ELSE 0 END) AS day_cost, "
            "SUM(CASE WHEN activity_date>=? AND net_amount<0 THEN -net_amount ELSE 0 END) AS week_cost, "
            "SUM(CASE WHEN activity_date>=? AND net_amount<0 THEN -net_amount ELSE 0 END) AS month_cost, "
            "MIN(activity_date) AS first_date, MAX(activity_date) AS last_date, COUNT(*) AS ledger_records "
            "FROM ALPACA_ACCOUNT_FEES WHERE activity_date<=?",
            (cutoffs["day"], cutoffs["week"], cutoffs["month"], now.date().isoformat()),
        ).fetchone()
    values = dict(row) if row else {}
    ledger_available = bool(values.get("ledger_records"))
    return {
        name: {
            "recorded_account_fees": (
                round(float(values.get(f"{name}_cost") or 0), 6) if ledger_available else None
            ),
            "currency": "USD",
            "source": "alpaca_paper_account_FEE_ledger",
            "ledger_records": int(values.get("ledger_records") or 0),
            "first_recorded_date": values.get("first_date"),
            "last_recorded_date": values.get("last_date"),
        }
        for name in ("day", "week", "month")
    }


def estimate_alpaca_round_trip_cost(*, sell_notional: float, quantity: float) -> dict[str, Any]:
    """Estimate US regulatory charges using Alpaca's published April 2026 schedule.

    Commission is zero. SEC and TAF amounts are rounded up to the nearest cent, as
    disclosed. Recorded FEE ledger rows replace this estimate in retrospective reports;
    the two are never added together.
    """
    notional = max(0.0, float(sell_notional or 0))
    qty = max(0.0, float(quantity or 0))
    sec = math.ceil((notional * 0.00002060) * 100 - 1e-12) / 100 if notional else 0.0
    taf = min(9.79, math.ceil((qty * 0.000195) * 100 - 1e-12) / 100) if qty else 0.0
    cat = 0.0  # Current Alpaca schedule lists NMS and OTC equity CAT at $0.00.
    total = round(sec + taf + cat, 2)
    return {
        "estimated_round_trip_fee_usd": total,
        "components": {"commission": 0.0, "sec_sell_fee": sec, "taf_sell_fee": taf, "cat_fee": cat},
        "basis": "published_regulatory_formula",
        "schedule": "Alpaca Brokerage Fee Schedule, effective 2026-04-01",
        "source_url": "https://files.alpaca.markets/disclosures/BrokFeeSched.pdf",
        "excludes": ["spread", "slippage"],
    }
