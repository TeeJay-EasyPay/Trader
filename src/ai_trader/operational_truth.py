from __future__ import annotations

import hashlib
import json
import sqlite3
from .database import connect
from contextlib import closing
from pathlib import Path
from typing import Any

from .models import utc_now_iso


CANONICAL_STAGES = {
    "idea_discovered",
    "research_started",
    "research_completed",
    "candidate",
    "insufficient_evidence",
    "no_valid_strategy",
    "committee_wait",
    "committee_rejected",
    "approved",
    "risk_rejected",
    "submitted",
    "broker_acknowledged",
    "partially_filled",
    "fully_filled",
    "open",
    "managing",
    "stop_updated",
    "partial_exit",
    "target_exit",
    "stop_exit",
    "manual_exit",
    "cancelled",
    "expired",
    "closed",
    "attributed",
    "learning_completed",
}

TERMINAL_STAGES = {
    "insufficient_evidence",
    "no_valid_strategy",
    "committee_rejected",
    "risk_rejected",
    "cancelled",
    "expired",
    "closed",
    "learning_completed",
}

LEGAL_TRANSITIONS: dict[str, set[str]] = {
    "idea_discovered": {"research_started", "candidate", "insufficient_evidence", "expired"},
    "research_started": {"research_completed", "insufficient_evidence", "expired"},
    "research_completed": {"candidate", "insufficient_evidence", "no_valid_strategy"},
    "candidate": {"committee_wait", "committee_rejected", "approved", "risk_rejected", "expired"},
    "committee_wait": {"approved", "committee_rejected", "expired"},
    "approved": {"submitted", "risk_rejected", "expired"},
    "submitted": {"broker_acknowledged", "partially_filled", "fully_filled", "cancelled"},
    "broker_acknowledged": {"partially_filled", "fully_filled", "cancelled"},
    "partially_filled": {"partially_filled", "fully_filled", "partial_exit", "cancelled"},
    "fully_filled": {"open", "managing", "partial_exit", "target_exit", "stop_exit", "manual_exit"},
    "open": {"managing", "stop_updated", "partial_exit", "target_exit", "stop_exit", "manual_exit", "closed"},
    "managing": {"stop_updated", "partial_exit", "target_exit", "stop_exit", "manual_exit", "closed"},
    "stop_updated": {"managing", "partial_exit", "target_exit", "stop_exit", "manual_exit", "closed"},
    "partial_exit": {"managing", "target_exit", "stop_exit", "manual_exit", "closed"},
    "target_exit": {"closed", "attributed"},
    "stop_exit": {"closed", "attributed"},
    "manual_exit": {"closed", "attributed"},
    "closed": {"attributed", "learning_completed"},
    "attributed": {"learning_completed"},
}

OPERATIONAL_TRUTH_SCHEMA = """
CREATE TABLE IF NOT EXISTS CANONICAL_TRADE_LIFECYCLE (
    lifecycle_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    proposal_id TEXT,
    recommendation_id TEXT,
    strategy_id TEXT,
    regime_id TEXT,
    broker TEXT,
    broker_order_id TEXT,
    broker_trade_id TEXT,
    broker_fill_id TEXT,
    symbol TEXT,
    asset_type TEXT,
    side TEXT,
    stage TEXT NOT NULL,
    event_source TEXT NOT NULL,
    event_reason TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS LIFECYCLE_TRANSITION_REJECTIONS (
    rejection_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    proposal_id TEXT,
    broker TEXT,
    symbol TEXT,
    attempted_stage TEXT NOT NULL,
    previous_stage TEXT,
    rejection_reason TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    idempotency_key TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS TRADE_EXECUTION_COSTS (
    cost_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    proposal_id TEXT,
    broker TEXT,
    symbol TEXT,
    intended_entry_price REAL,
    actual_average_entry_price REAL,
    entry_slippage REAL,
    intended_exit_price REAL,
    actual_average_exit_price REAL,
    exit_slippage REAL,
    spread_cost REAL,
    broker_fee REAL,
    exchange_fee REAL,
    total_trading_cost REAL,
    cost_currency TEXT,
    cost_pct REAL,
    cost_bps REAL,
    cost_r REAL,
    fee_status TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS TRADE_R_MULTIPLES (
    r_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    proposal_id TEXT,
    broker TEXT,
    symbol TEXT,
    original_stop REAL,
    intended_entry_price REAL,
    filled_quantity REAL,
    initial_monetary_risk REAL,
    planned_r REAL,
    gross_r REAL,
    net_r REAL,
    fee_impact_r REAL,
    slippage_impact_r REAL,
    expected_r REAL,
    actual_r REAL,
    prediction_error REAL,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS TRADE_EXCURSIONS (
    excursion_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    proposal_id TEXT,
    broker TEXT,
    symbol TEXT,
    side TEXT,
    entry_price REAL,
    quantity REAL,
    initial_monetary_risk REAL,
    mae_currency REAL,
    mae_pct REAL,
    mae_r REAL,
    mae_at TEXT,
    mfe_currency REAL,
    mfe_pct REAL,
    mfe_r REAL,
    mfe_at TEXT,
    data_granularity TEXT NOT NULL,
    monitoring_gaps TEXT NOT NULL,
    confidence TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS BROKER_RECONCILIATION_RUNS (
    reconciliation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    broker TEXT NOT NULL,
    status TEXT NOT NULL,
    rows_seen INTEGER NOT NULL,
    lifecycle_events_created INTEGER NOT NULL,
    duplicate_events INTEGER NOT NULL,
    manual_review_required INTEGER NOT NULL,
    summary TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
"""


def initialize_operational_truth_schema(db_path: Path) -> None:
    with closing(connect(db_path)) as conn:
        with conn:
            conn.executescript(OPERATIONAL_TRUTH_SCHEMA)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ctl_proposal ON CANONICAL_TRADE_LIFECYCLE(proposal_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ctl_broker_symbol ON CANONICAL_TRADE_LIFECYCLE(broker, symbol)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ctl_stage ON CANONICAL_TRADE_LIFECYCLE(stage)")


def record_lifecycle_event(
    db_path: Path,
    *,
    stage: str,
    proposal_id: str | None = None,
    recommendation_id: str | None = None,
    strategy_id: str | None = None,
    regime_id: str | None = None,
    broker: str | None = None,
    broker_order_id: str | None = None,
    broker_trade_id: str | None = None,
    broker_fill_id: str | None = None,
    symbol: str | None = None,
    asset_type: str | None = None,
    side: str | None = None,
    event_source: str = "system",
    event_reason: str = "",
    payload: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    initialize_operational_truth_schema(db_path)
    normalized_stage = stage.lower().strip()
    payload = payload or {}
    if normalized_stage not in CANONICAL_STAGES:
        return _reject_transition(
            db_path,
            proposal_id=proposal_id,
            broker=broker,
            symbol=symbol,
            attempted_stage=normalized_stage,
            previous_stage=None,
            reason="unknown_lifecycle_stage",
            payload=payload,
            idempotency_key=idempotency_key or _lifecycle_key(normalized_stage, proposal_id, broker, symbol, payload),
        )
    key = idempotency_key or _lifecycle_key(normalized_stage, proposal_id, broker, symbol, payload)
    with closing(connect(db_path)) as conn:
        existing = conn.execute(
            "SELECT lifecycle_id FROM CANONICAL_TRADE_LIFECYCLE WHERE idempotency_key = ?",
            (key,),
        ).fetchone()
    if existing:
        return {"status": "duplicate", "idempotency_key": key, "lifecycle_id": existing[0]}
    previous = latest_lifecycle_stage(db_path, proposal_id=proposal_id, broker=broker, symbol=symbol)
    if previous and not _is_legal_transition(previous["stage"], normalized_stage):
        return _reject_transition(
            db_path,
            proposal_id=proposal_id,
            broker=broker,
            symbol=symbol,
            attempted_stage=normalized_stage,
            previous_stage=previous["stage"],
            reason="illegal_lifecycle_transition",
            payload=payload,
            idempotency_key=key,
        )
    with closing(connect(db_path)) as conn:
        with conn:
            try:
                cursor = conn.execute(
                    """
                    INSERT INTO CANONICAL_TRADE_LIFECYCLE (
                        created_at, proposal_id, recommendation_id, strategy_id, regime_id,
                        broker, broker_order_id, broker_trade_id, broker_fill_id, symbol,
                        asset_type, side, stage, event_source, event_reason, payload_json,
                        idempotency_key
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        utc_now_iso(),
                        proposal_id,
                        recommendation_id,
                        strategy_id,
                        regime_id,
                        broker.lower() if broker else None,
                        broker_order_id,
                        broker_trade_id,
                        broker_fill_id,
                        symbol,
                        asset_type,
                        side.lower() if side else None,
                        normalized_stage,
                        event_source,
                        event_reason or normalized_stage,
                        json.dumps(payload, sort_keys=True, default=str),
                        key,
                    ),
                )
            except sqlite3.IntegrityError:
                existing = conn.execute(
                    "SELECT * FROM CANONICAL_TRADE_LIFECYCLE WHERE idempotency_key = ?",
                    (key,),
                ).fetchone()
                return {"status": "duplicate", "idempotency_key": key, "lifecycle_id": existing[0] if existing else None}
    return {"status": "recorded", "stage": normalized_stage, "idempotency_key": key, "lifecycle_id": cursor.lastrowid}


def latest_lifecycle_stage(
    db_path: Path,
    *,
    proposal_id: str | None = None,
    broker: str | None = None,
    symbol: str | None = None,
) -> dict[str, Any] | None:
    initialize_operational_truth_schema(db_path)
    filters = []
    params: list[Any] = []
    if proposal_id:
        filters.append("proposal_id = ?")
        params.append(proposal_id)
    if broker:
        filters.append("broker = ?")
        params.append(broker.lower())
    if symbol:
        filters.append("symbol = ?")
        params.append(symbol)
    if not filters:
        return None
    with closing(connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            f"SELECT * FROM CANONICAL_TRADE_LIFECYCLE WHERE {' AND '.join(filters)} ORDER BY lifecycle_id DESC LIMIT 1",
            tuple(params),
        ).fetchone()
    return dict(row) if row else None


def reconcile_broker_trade_rows(db_path: Path, broker: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    initialize_operational_truth_schema(db_path)
    created = 0
    duplicates = 0
    manual_review = 0
    for row in rows:
        parsed = parse_broker_row(broker, row)
        if not parsed["symbol"]:
            manual_review += 1
        result = record_lifecycle_event(
            db_path,
            proposal_id=parsed.get("proposal_id"),
            broker=broker,
            broker_order_id=parsed.get("broker_order_id"),
            broker_trade_id=parsed.get("broker_trade_id"),
            broker_fill_id=parsed.get("broker_fill_id"),
            symbol=parsed.get("symbol"),
            asset_type=parsed.get("asset_type"),
            side=parsed.get("side"),
            stage=parsed["stage"],
            event_source=f"{broker.lower()}_reconciliation",
            event_reason=parsed["reason"],
            payload={"raw": row, "parsed": parsed},
            idempotency_key=parsed["idempotency_key"],
        )
        if result["status"] == "recorded":
            created += 1
        elif result["status"] == "duplicate":
            duplicates += 1
    status = "Fully reconciled" if rows and manual_review == 0 else "Awaiting broker data" if not rows else "Manual review required"
    summary = f"{broker.title()} reconciliation saw {len(rows)} row(s), created {created} lifecycle event(s), skipped {duplicates} duplicate(s)."
    with closing(connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO BROKER_RECONCILIATION_RUNS (
                    created_at, broker, status, rows_seen, lifecycle_events_created,
                    duplicate_events, manual_review_required, summary, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    utc_now_iso(),
                    broker.lower(),
                    status,
                    len(rows),
                    created,
                    duplicates,
                    1 if manual_review else 0,
                    summary,
                    json.dumps({"rows": rows}, sort_keys=True, default=str),
                ),
            )
    return {
        "broker": broker.lower(),
        "status": status,
        "rows_seen": len(rows),
        "lifecycle_events_created": created,
        "duplicate_events": duplicates,
        "manual_review_required": bool(manual_review),
        "summary": summary,
    }


def parse_broker_row(broker: str, row: dict[str, Any]) -> dict[str, Any]:
    payload = _payload(row)
    source = {**payload, **row}
    status = str(source.get("status") or source.get("type") or "").lower()
    order_id = str(source.get("order_id") or source.get("ordertxid") or source.get("id") or source.get("txid") or "")
    trade_id = str(source.get("trade_id") or source.get("tradeid") or source.get("postxid") or "")
    fill_id = str(source.get("fill_id") or source.get("id") or trade_id or order_id or "")
    symbol = source.get("symbol") or source.get("pair")
    side = source.get("side") or source.get("type")
    quantity = _float(source.get("qty") or source.get("filled_qty") or source.get("vol") or source.get("quantity"))
    price = _float(source.get("filled_avg_price") or source.get("avg_price") or source.get("price"))
    stage = _stage_from_broker_status(status=status, quantity=quantity)
    reason = f"Broker row status {status or 'unknown'} mapped to {stage}."
    key = _lifecycle_key(stage, source.get("proposal_id"), broker, symbol, {"order_id": order_id, "trade_id": trade_id, "fill_id": fill_id, "status": status})
    return {
        "proposal_id": source.get("proposal_id"),
        "broker_order_id": order_id or None,
        "broker_trade_id": trade_id or None,
        "broker_fill_id": fill_id or None,
        "symbol": symbol,
        "asset_type": source.get("asset_type") or ("crypto" if broker.lower() == "kraken" else "stock"),
        "side": str(side).lower() if side else None,
        "quantity": quantity,
        "price": price,
        "stage": stage,
        "reason": reason,
        "idempotency_key": key,
    }


def calculate_execution_costs(
    db_path: Path,
    *,
    proposal_id: str | None,
    broker: str,
    symbol: str,
    intended_entry_price: float | None,
    actual_average_entry_price: float | None,
    intended_exit_price: float | None = None,
    actual_average_exit_price: float | None = None,
    quantity: float | None = None,
    broker_fee: float | None = None,
    exchange_fee: float | None = None,
    spread_cost: float | None = None,
    cost_currency: str = "account",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    initialize_operational_truth_schema(db_path)
    entry_slippage = _slippage(actual_average_entry_price, intended_entry_price)
    exit_slippage = _slippage(actual_average_exit_price, intended_exit_price)
    confirmed_costs = [value for value in [broker_fee, exchange_fee, spread_cost] if value is not None]
    total_cost = sum(confirmed_costs) if confirmed_costs else None
    notional = abs((actual_average_entry_price or intended_entry_price or 0.0) * (quantity or 0.0))
    cost_pct = (total_cost / notional) if total_cost is not None and notional else None
    cost_bps = cost_pct * 10_000 if cost_pct is not None else None
    fee_status = "confirmed" if confirmed_costs else "unavailable"
    result = {
        "entry_slippage": entry_slippage,
        "exit_slippage": exit_slippage,
        "total_trading_cost": total_cost,
        "cost_pct": cost_pct,
        "cost_bps": cost_bps,
        "fee_status": fee_status,
    }
    with closing(connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO TRADE_EXECUTION_COSTS (
                    created_at, proposal_id, broker, symbol, intended_entry_price,
                    actual_average_entry_price, entry_slippage, intended_exit_price,
                    actual_average_exit_price, exit_slippage, spread_cost, broker_fee,
                    exchange_fee, total_trading_cost, cost_currency, cost_pct, cost_bps,
                    cost_r, fee_status, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    utc_now_iso(),
                    proposal_id,
                    broker.lower(),
                    symbol,
                    intended_entry_price,
                    actual_average_entry_price,
                    entry_slippage,
                    intended_exit_price,
                    actual_average_exit_price,
                    exit_slippage,
                    spread_cost,
                    broker_fee,
                    exchange_fee,
                    total_cost,
                    cost_currency,
                    cost_pct,
                    cost_bps,
                    None,
                    fee_status,
                    json.dumps(payload or {}, sort_keys=True, default=str),
                ),
            )
    return result


def calculate_r_multiple(
    db_path: Path,
    *,
    proposal_id: str | None,
    broker: str,
    symbol: str,
    intended_entry_price: float,
    original_stop: float,
    filled_quantity: float,
    gross_realized_pnl: float,
    total_cost: float | None = None,
    expected_r: float | None = None,
    planned_take_profit: float | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    initialize_operational_truth_schema(db_path)
    initial_risk = abs(intended_entry_price - original_stop) * abs(filled_quantity)
    net_pnl = gross_realized_pnl - (total_cost or 0.0)
    gross_r = gross_realized_pnl / initial_risk if initial_risk else None
    net_r = net_pnl / initial_risk if initial_risk else None
    planned_r = (abs((planned_take_profit or intended_entry_price) - intended_entry_price) * abs(filled_quantity) / initial_risk) if initial_risk and planned_take_profit is not None else None
    fee_impact_r = (total_cost / initial_risk) if total_cost is not None and initial_risk else None
    prediction_error = (net_r - expected_r) if net_r is not None and expected_r is not None else None
    result = {
        "initial_monetary_risk": initial_risk,
        "planned_r": planned_r,
        "gross_r": gross_r,
        "net_r": net_r,
        "fee_impact_r": fee_impact_r,
        "actual_r": net_r,
        "prediction_error": prediction_error,
    }
    with closing(connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO TRADE_R_MULTIPLES (
                    created_at, proposal_id, broker, symbol, original_stop,
                    intended_entry_price, filled_quantity, initial_monetary_risk,
                    planned_r, gross_r, net_r, fee_impact_r, slippage_impact_r,
                    expected_r, actual_r, prediction_error, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    utc_now_iso(),
                    proposal_id,
                    broker.lower(),
                    symbol,
                    original_stop,
                    intended_entry_price,
                    filled_quantity,
                    initial_risk,
                    planned_r,
                    gross_r,
                    net_r,
                    fee_impact_r,
                    None,
                    expected_r,
                    net_r,
                    prediction_error,
                    json.dumps(payload or {}, sort_keys=True, default=str),
                ),
            )
    return result


def calculate_mae_mfe(
    db_path: Path,
    *,
    proposal_id: str | None,
    broker: str,
    symbol: str,
    side: str,
    entry_price: float,
    quantity: float,
    original_stop: float,
    observations: list[dict[str, Any]],
    data_granularity: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    initialize_operational_truth_schema(db_path)
    initial_risk = abs(entry_price - original_stop) * abs(quantity)
    adverse: tuple[float, str | None] = (0.0, None)
    favourable: tuple[float, str | None] = (0.0, None)
    long_side = side.lower() == "buy"
    for item in observations:
        high = _float(item.get("high") or item.get("price"))
        low = _float(item.get("low") or item.get("price"))
        observed_at = item.get("observed_at") or item.get("time") or item.get("timestamp")
        if high is None or low is None:
            continue
        adverse_price_move = (entry_price - low) if long_side else (high - entry_price)
        favourable_price_move = (high - entry_price) if long_side else (entry_price - low)
        adverse_currency = max(0.0, adverse_price_move * abs(quantity))
        favourable_currency = max(0.0, favourable_price_move * abs(quantity))
        if adverse_currency > adverse[0]:
            adverse = (adverse_currency, observed_at)
        if favourable_currency > favourable[0]:
            favourable = (favourable_currency, observed_at)
    mae_pct = adverse[0] / (entry_price * abs(quantity)) if entry_price and quantity else None
    mfe_pct = favourable[0] / (entry_price * abs(quantity)) if entry_price and quantity else None
    result = {
        "initial_monetary_risk": initial_risk,
        "mae_currency": adverse[0],
        "mae_pct": mae_pct,
        "mae_r": adverse[0] / initial_risk if initial_risk else None,
        "mae_at": adverse[1],
        "mfe_currency": favourable[0],
        "mfe_pct": mfe_pct,
        "mfe_r": favourable[0] / initial_risk if initial_risk else None,
        "mfe_at": favourable[1],
        "data_granularity": data_granularity,
        "monitoring_gaps": "No observations supplied." if not observations else "Calculated from supplied observations; precision depends on granularity.",
        "confidence": "low" if data_granularity in {"daily", "weekly", "monthly"} else "medium",
    }
    with closing(connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO TRADE_EXCURSIONS (
                    created_at, proposal_id, broker, symbol, side, entry_price, quantity,
                    initial_monetary_risk, mae_currency, mae_pct, mae_r, mae_at,
                    mfe_currency, mfe_pct, mfe_r, mfe_at, data_granularity,
                    monitoring_gaps, confidence, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    utc_now_iso(),
                    proposal_id,
                    broker.lower(),
                    symbol,
                    side.lower(),
                    entry_price,
                    quantity,
                    initial_risk,
                    result["mae_currency"],
                    result["mae_pct"],
                    result["mae_r"],
                    result["mae_at"],
                    result["mfe_currency"],
                    result["mfe_pct"],
                    result["mfe_r"],
                    result["mfe_at"],
                    data_granularity,
                    result["monitoring_gaps"],
                    result["confidence"],
                    json.dumps(payload or {"observations": observations}, sort_keys=True, default=str),
                ),
            )
    return result


def reconciliation_health(db_path: Path, broker: str | None = None) -> list[dict[str, Any]]:
    initialize_operational_truth_schema(db_path)
    params: tuple[Any, ...] = ()
    where = ""
    if broker:
        where = "WHERE broker = ?"
        params = (broker.lower(),)
    with closing(connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"""
            SELECT *
            FROM BROKER_RECONCILIATION_RUNS
            {where}
            ORDER BY reconciliation_id DESC
            LIMIT 10
            """,
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def _stage_from_broker_status(*, status: str, quantity: float | None) -> str:
    if status in {"filled", "closed", "complete", "fully_filled"}:
        return "fully_filled" if quantity else "broker_acknowledged"
    if status in {"partially_filled", "partial"}:
        return "partially_filled"
    if status in {"new", "accepted", "open", "pending", "pending_new"}:
        return "broker_acknowledged"
    if status in {"canceled", "cancelled"}:
        return "cancelled"
    if status in {"rejected", "expired"}:
        return status
    return "broker_acknowledged"


def _is_legal_transition(previous_stage: str, next_stage: str) -> bool:
    if previous_stage == next_stage:
        return True
    if previous_stage not in LEGAL_TRANSITIONS:
        return previous_stage not in TERMINAL_STAGES
    return next_stage in LEGAL_TRANSITIONS[previous_stage]


def _reject_transition(
    db_path: Path,
    *,
    proposal_id: str | None,
    broker: str | None,
    symbol: str | None,
    attempted_stage: str,
    previous_stage: str | None,
    reason: str,
    payload: dict[str, Any],
    idempotency_key: str,
) -> dict[str, Any]:
    with closing(connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO LIFECYCLE_TRANSITION_REJECTIONS (
                    created_at, proposal_id, broker, symbol, attempted_stage,
                    previous_stage, rejection_reason, payload_json, idempotency_key
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    utc_now_iso(),
                    proposal_id,
                    broker.lower() if broker else None,
                    symbol,
                    attempted_stage,
                    previous_stage,
                    reason,
                    json.dumps(payload, sort_keys=True, default=str),
                    idempotency_key,
                ),
            )
    return {"status": "rejected", "reason": reason, "previous_stage": previous_stage, "attempted_stage": attempted_stage}


def _lifecycle_key(stage: str, proposal_id: str | None, broker: str | None, symbol: str | None, payload: dict[str, Any]) -> str:
    raw = json.dumps(
        {
            "stage": stage,
            "proposal_id": proposal_id,
            "broker": broker,
            "symbol": symbol,
            "payload": payload,
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _payload(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("payload_json") or row.get("payload")
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}


def _float(value: Any) -> float | None:
    try:
        if value in {None, ""}:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _slippage(actual: float | None, intended: float | None) -> float | None:
    if actual is None or intended is None:
        return None
    return actual - intended
