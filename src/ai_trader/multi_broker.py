from __future__ import annotations

import json
import sqlite3
import threading
from .database import connect, selected_backend
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib import request

from .models import utc_now_iso
from .operational import safe_float, safe_score


MULTI_BROKER_SCHEMA = """
CREATE TABLE IF NOT EXISTS BROKER_AUTO_TRADING_SETTINGS (
    broker TEXT PRIMARY KEY,
    auto_trading_enabled INTEGER NOT NULL DEFAULT 0,
    mode TEXT NOT NULL DEFAULT 'paper_or_sandbox',
    updated_at TEXT NOT NULL,
    updated_by TEXT NOT NULL,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS BROKER_RUNTIME_STATE (
    broker TEXT PRIMARY KEY,
    connection_status TEXT NOT NULL,
    research_status TEXT NOT NULL,
    due_diligence_status TEXT NOT NULL,
    current_asset TEXT,
    current_stage TEXT,
    research_queue_json TEXT NOT NULL,
    assets_reviewed_today INTEGER NOT NULL DEFAULT 0,
    research_cycles_today INTEGER NOT NULL DEFAULT 0,
    last_scan TEXT,
    next_scan TEXT,
    research_freshness TEXT,
    last_recommendation TEXT,
    last_trade_submitted TEXT,
    updated_at TEXT NOT NULL,
    details_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS BROKER_TRADE_HISTORY (
    trade_history_id INTEGER PRIMARY KEY AUTOINCREMENT,
    broker TEXT NOT NULL,
    external_id TEXT,
    symbol TEXT,
    asset_type TEXT,
    side TEXT,
    quantity REAL,
    price REAL,
    notional REAL,
    status TEXT NOT NULL,
    opened_at TEXT,
    closed_at TEXT,
    updated_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    UNIQUE(broker, external_id, status, updated_at)
);

CREATE TABLE IF NOT EXISTS NOTIFICATION_EVENTS (
    notification_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    event_type TEXT NOT NULL,
    broker TEXT,
    symbol TEXT,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    delivery_status TEXT NOT NULL DEFAULT 'queued',
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS RECOMMENDATION_SETS (
    set_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    trigger_type TEXT NOT NULL,
    broker TEXT,
    symbols_json TEXT NOT NULL,
    proposal_ids_json TEXT NOT NULL,
    status TEXT NOT NULL,
    summary TEXT
);

CREATE TABLE IF NOT EXISTS CRYPTO_RESEARCH_SCORES (
    score_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    symbol TEXT NOT NULL,
    category TEXT,
    technical_trend_score REAL,
    momentum_score REAL,
    rsi REAL,
    moving_average_position REAL,
    macd REAL,
    volume_trend REAL,
    volatility REAL,
    liquidity REAL,
    market_structure REAL,
    sentiment REAL,
    news_score REAL,
    onchain_activity REAL,
    risk_score REAL,
    overall_due_diligence_score REAL,
    confidence_score REAL,
    reasoning_json TEXT NOT NULL,
    source TEXT
);

CREATE TABLE IF NOT EXISTS ORDER_INTENT_LOCKS (
    lock_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    broker TEXT NOT NULL,
    client_order_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    notional REAL,
    status TEXT NOT NULL,
    result_order_id TEXT,
    notes TEXT,
    UNIQUE(broker, client_order_id)
);

CREATE TABLE IF NOT EXISTS MANAGED_TRADE_EXITS (
    managed_exit_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    broker TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity REAL NOT NULL,
    entry_order_id TEXT,
    entry_price REAL NOT NULL,
    stop_loss REAL NOT NULL,
    take_profit REAL NOT NULL,
    status TEXT NOT NULL,
    exit_order_id TEXT,
    exit_reason TEXT,
    last_checked_at TEXT,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS PUSH_TOKENS (
    token_id INTEGER PRIMARY KEY AUTOINCREMENT,
    push_token TEXT NOT NULL UNIQUE,
    platform TEXT,
    registered_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS PERFORMANCE_ATTRIBUTION (
    attribution_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    proposal_id TEXT,
    broker TEXT NOT NULL,
    symbol TEXT NOT NULL,
    asset_type TEXT,
    side TEXT NOT NULL,
    entry_price REAL NOT NULL,
    exit_price REAL NOT NULL,
    quantity REAL NOT NULL,
    profit_loss REAL NOT NULL,
    opened_at TEXT,
    closed_at TEXT NOT NULL,
    holding_period_seconds REAL,
    entry_reason TEXT,
    exit_reason TEXT,
    primary_factors_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS MECHANICAL_SEATBELT_EVENTS (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    broker TEXT NOT NULL,
    symbol TEXT,
    event_type TEXT NOT NULL,
    result TEXT NOT NULL,
    message TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
"""


DEFAULT_BROKERS = ["alpaca", "kraken", "coinbase", "binance", "interactive_brokers"]


@dataclass(frozen=True)
class BrokerRuntime:
    broker: str
    connection_status: str
    research_status: str
    due_diligence_status: str
    current_asset: str | None
    current_stage: str | None
    research_queue: list[str]
    assets_reviewed_today: int
    research_cycles_today: int
    last_scan: str | None
    next_scan: str | None
    research_freshness: str | None
    last_recommendation: str | None
    last_trade_submitted: str | None
    updated_at: str
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _ensure_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    for column, ddl_type in columns.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}")


_SCHEMA_LOCK = threading.Lock()
_INITIALIZED_SCHEMA_KEYS: set[str] = set()


def _schema_key(db_path: Path) -> str:
    if selected_backend() == "postgres":
        return "postgres"
    return f"sqlite:{Path(db_path).resolve()}"


def initialize_multi_broker_schema(db_path: Path) -> None:
    """Create schema and seed default broker rows once per process.

    This is called unconditionally (CREATE TABLE/ALTER/seed round trips) from nearly
    every function in this module -- update_broker_runtime, broker_auto_trading_enabled,
    broker_runtime, set_broker_auto_trading, etc. -- so every candidate evaluated by
    auto_execute_recommendations and every symbol evaluated by propose_crypto_trades'
    on_symbol_complete callback paid this cost repeatedly. Same "repeated schema setup
    mistaken for slow work" bug already fixed for kraken_reconciliation and
    trading_intelligence; caching per-process is safe for the same reason (every
    statement here is idempotent, every job run is its own fresh process).
    """

    key = _schema_key(db_path)
    if key in _INITIALIZED_SCHEMA_KEYS:
        return
    with _SCHEMA_LOCK:
        if key in _INITIALIZED_SCHEMA_KEYS:
            return
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(connect(db_path)) as conn:
            with conn:
                conn.executescript(MULTI_BROKER_SCHEMA)
                _ensure_columns(
                    conn,
                    "MANAGED_TRADE_EXITS",
                    {
                        "trailing_stop_pct": "REAL",
                        "high_water_mark": "REAL",
                        "low_water_mark": "REAL",
                        "native_stop_order_id": "TEXT",
                    },
                )
                _ensure_columns(conn, "NOTIFICATION_EVENTS", {"push_sent_at": "TEXT"})
                _backfill_epoch_timestamps(conn)
                now = utc_now_iso()
                for broker in DEFAULT_BROKERS:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO BROKER_AUTO_TRADING_SETTINGS (
                            broker, auto_trading_enabled, mode, updated_at, updated_by, notes
                        ) VALUES (?, 0, 'paper_or_sandbox', ?, 'system', 'Disabled by default.')
                        """,
                        (broker, now),
                    )
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO BROKER_RUNTIME_STATE (
                            broker, connection_status, research_status, due_diligence_status,
                            current_asset, current_stage, research_queue_json,
                            assets_reviewed_today, research_cycles_today, last_scan,
                            next_scan, research_freshness, last_recommendation,
                            last_trade_submitted, updated_at, details_json
                        ) VALUES (?, 'Not checked', 'idle', 'idle', NULL, NULL, '[]', 0, 0, NULL, NULL, 'Not available', NULL, NULL, ?, '{}')
                        """,
                        (broker, now),
                    )
        _INITIALIZED_SCHEMA_KEYS.add(key)


def broker_auto_trading_enabled(db_path: Path, broker: str, env_default: bool = False) -> bool:
    initialize_multi_broker_schema(db_path)
    with closing(connect(db_path)) as conn:
        row = conn.execute(
            "SELECT auto_trading_enabled FROM BROKER_AUTO_TRADING_SETTINGS WHERE broker = ?",
            (broker.lower(),),
        ).fetchone()
    if row is None:
        return env_default
    return bool(row[0])


def set_broker_auto_trading(db_path: Path, broker: str, enabled: bool, *, updated_by: str = "founder") -> dict[str, Any]:
    """Set (and durably record) whether a broker's autonomous entries are enabled.

    LocalApiService.__init__ calls _apply_env_broker_auto_defaults /
    _apply_founder_kraken_live_authorization unconditionally on every process --
    and every scheduled job runs in its own fresh process -- so without this
    early-exit, every single job launch (every few minutes, for every job type)
    re-wrote this row and re-fired a "auto trading enabled" notification even
    when nothing had changed. Confirmed via hosted evidence 2026-08-01: dozens
    of duplicate broker_auto_trading_enabled notifications roughly 10-15s apart,
    matching job cadence, plus concurrent auto-execution-alpaca/auto-execution-
    kraken pairs both racing to write the same row on every launch -- the same
    "concurrent processes contending for the same seed row" class of bug already
    found and fixed for kraken_reconciliation's schema seeding.
    """

    initialize_multi_broker_schema(db_path)
    broker_key = broker.lower()
    if broker_auto_trading_enabled(db_path, broker_key) == bool(enabled):
        return {"broker": broker_key, "auto_trading_enabled": bool(enabled), "updated_at": None, "unchanged": True}
    now = utc_now_iso()
    with closing(connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO BROKER_AUTO_TRADING_SETTINGS (
                    broker, auto_trading_enabled, mode, updated_at, updated_by, notes
                ) VALUES (?, ?, 'paper_or_sandbox', ?, ?, ?)
                ON CONFLICT(broker) DO UPDATE SET
                    auto_trading_enabled = excluded.auto_trading_enabled,
                    updated_at = excluded.updated_at,
                    updated_by = excluded.updated_by,
                    notes = excluded.notes
                """,
                (
                    broker_key,
                    int(enabled),
                    now,
                    updated_by,
                    "Auto trading enabled for this broker only." if enabled else "New autonomous entries disabled for this broker.",
                ),
            )
    record_notification(
        db_path,
        event_type="broker_auto_trading_enabled" if enabled else "broker_auto_trading_disabled",
        broker=broker_key,
        symbol=None,
        title=f"{broker_key.title()} auto trading {'enabled' if enabled else 'disabled'}",
        message=f"{broker_key.title()} will {'start autonomous entries' if enabled else 'stop creating new autonomous entries'}. Existing positions remain managed.",
        payload={"broker": broker_key, "enabled": enabled},
    )
    return {"broker": broker_key, "auto_trading_enabled": enabled, "updated_at": now}


def broker_auto_settings(db_path: Path) -> dict[str, bool]:
    initialize_multi_broker_schema(db_path)
    with closing(connect(db_path)) as conn:
        return {
            row[0]: bool(row[1])
            for row in conn.execute("SELECT broker, auto_trading_enabled FROM BROKER_AUTO_TRADING_SETTINGS")
        }


def update_broker_runtime(
    db_path: Path,
    broker: str,
    *,
    connection_status: str | None = None,
    research_status: str | None = None,
    due_diligence_status: str | None = None,
    current_asset: str | None = None,
    current_stage: str | None = None,
    research_queue: list[str] | None = None,
    assets_reviewed_today: int | None = None,
    research_cycles_today: int | None = None,
    last_scan: str | None = None,
    next_scan: str | None = None,
    research_freshness: str | None = None,
    last_recommendation: str | None = None,
    last_trade_submitted: str | None = None,
    details: dict[str, Any] | None = None,
) -> BrokerRuntime:
    initialize_multi_broker_schema(db_path)
    broker_key = broker.lower()
    current = broker_runtime(db_path, broker_key)
    now = utc_now_iso()
    merged = BrokerRuntime(
        broker=broker_key,
        connection_status=connection_status or current.connection_status,
        research_status=research_status or current.research_status,
        due_diligence_status=due_diligence_status or current.due_diligence_status,
        current_asset=current_asset if current_asset is not None else current.current_asset,
        current_stage=current_stage if current_stage is not None else current.current_stage,
        research_queue=research_queue if research_queue is not None else current.research_queue,
        assets_reviewed_today=assets_reviewed_today if assets_reviewed_today is not None else current.assets_reviewed_today,
        research_cycles_today=research_cycles_today if research_cycles_today is not None else current.research_cycles_today,
        last_scan=last_scan if last_scan is not None else current.last_scan,
        next_scan=next_scan if next_scan is not None else current.next_scan,
        research_freshness=research_freshness if research_freshness is not None else current.research_freshness,
        last_recommendation=last_recommendation if last_recommendation is not None else current.last_recommendation,
        last_trade_submitted=last_trade_submitted if last_trade_submitted is not None else current.last_trade_submitted,
        updated_at=now,
        details={**current.details, **(details or {})},
    )
    with closing(connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO BROKER_RUNTIME_STATE (
                    broker, connection_status, research_status, due_diligence_status,
                    current_asset, current_stage, research_queue_json,
                    assets_reviewed_today, research_cycles_today, last_scan, next_scan,
                    research_freshness, last_recommendation, last_trade_submitted,
                    updated_at, details_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(broker) DO UPDATE SET
                    connection_status = excluded.connection_status,
                    research_status = excluded.research_status,
                    due_diligence_status = excluded.due_diligence_status,
                    current_asset = excluded.current_asset,
                    current_stage = excluded.current_stage,
                    research_queue_json = excluded.research_queue_json,
                    assets_reviewed_today = excluded.assets_reviewed_today,
                    research_cycles_today = excluded.research_cycles_today,
                    last_scan = excluded.last_scan,
                    next_scan = excluded.next_scan,
                    research_freshness = excluded.research_freshness,
                    last_recommendation = excluded.last_recommendation,
                    last_trade_submitted = excluded.last_trade_submitted,
                    updated_at = excluded.updated_at,
                    details_json = excluded.details_json
                """,
                (
                    merged.broker,
                    merged.connection_status,
                    merged.research_status,
                    merged.due_diligence_status,
                    merged.current_asset,
                    merged.current_stage,
                    json.dumps(merged.research_queue),
                    merged.assets_reviewed_today,
                    merged.research_cycles_today,
                    merged.last_scan,
                    merged.next_scan,
                    merged.research_freshness,
                    merged.last_recommendation,
                    merged.last_trade_submitted,
                    merged.updated_at,
                    json.dumps(merged.details, sort_keys=True),
                ),
            )
    return merged


def broker_runtime(db_path: Path, broker: str) -> BrokerRuntime:
    initialize_multi_broker_schema(db_path)
    broker_key = broker.lower()
    with closing(connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM BROKER_RUNTIME_STATE WHERE broker = ?", (broker_key,)).fetchone()
    if row is None:
        now = utc_now_iso()
        return BrokerRuntime(broker_key, "Not checked", "idle", "idle", None, None, [], 0, 0, None, None, "Not available", None, None, now, {})
    return BrokerRuntime(
        broker=row["broker"],
        connection_status=row["connection_status"],
        research_status=row["research_status"],
        due_diligence_status=row["due_diligence_status"],
        current_asset=row["current_asset"],
        current_stage=row["current_stage"],
        research_queue=_json_list(row["research_queue_json"]),
        assets_reviewed_today=int(row["assets_reviewed_today"] or 0),
        research_cycles_today=int(row["research_cycles_today"] or 0),
        last_scan=row["last_scan"],
        next_scan=row["next_scan"],
        research_freshness=row["research_freshness"],
        last_recommendation=row["last_recommendation"],
        last_trade_submitted=row["last_trade_submitted"],
        updated_at=row["updated_at"],
        details=_json_dict(row["details_json"]),
    )


def all_broker_runtime(db_path: Path) -> list[dict[str, Any]]:
    initialize_multi_broker_schema(db_path)
    settings = broker_auto_settings(db_path)
    return [
        {**broker_runtime(db_path, broker).to_dict(), "auto_trading_enabled": settings.get(broker, False)}
        for broker in settings
    ]


_BROKER_HISTORY_INSERT_CHUNK = 500


def _backfill_epoch_timestamps(conn: Any) -> int:
    """Convert the epoch-number timestamps already stored by earlier Kraken writes.

    One-time and idempotent, in the same place and for the same reason as audit.py's
    _backfill_missing_broker: rows written before _iso_timestamp existed still hold Unix
    epoch numbers, so they stay invisible to every date-filtered query until converted.
    Measured on production 2026-08-26: 270 Kraken rows across updated_at, opened_at and
    closed_at.

    Runs inside the existing once-per-process schema init, so it costs nothing after the
    first call, and never raises: a failed backfill must not stop the app from starting.
    """
    converted = 0
    try:
        for column in ("updated_at", "opened_at", "closed_at"):
            rows = conn.execute(
                f"SELECT trade_history_id, {column} FROM BROKER_TRADE_HISTORY "
                f"WHERE {column} IS NOT NULL AND {column} != ''"
            ).fetchall()
            for row in rows:
                row_id, raw = row[0], row[1]
                text = str(raw).strip()
                # Only touch values that are bare numbers; anything already ISO is left alone.
                if not text or text[0] not in "0123456789" or "-" in text or ":" in text:
                    continue
                converted_value = _iso_timestamp(text)
                if converted_value != text:
                    conn.execute(
                        f"UPDATE BROKER_TRADE_HISTORY SET {column} = ? WHERE trade_history_id = ?",
                        (converted_value, row_id),
                    )
                    converted += 1
    except Exception:  # noqa: BLE001 - a backfill must never stop the app starting
        return converted
    return converted


def _iso_timestamp(value: Any) -> str:
    """One timestamp format for every broker.

    2026-08-26 audit finding, measured on the production database: BROKER_TRADE_HISTORY
    held two incompatible formats in the same columns --

        kraken: 270 rows, 100% Unix epoch numbers ("1787702509.30039")
        alpaca: 118 rows, 100% ISO dates    ("2026-08-26T16:08:18")

    -- across updated_at, opened_at and closed_at alike, because Kraken reports opentm/
    closetm as epoch floats and Alpaca reports ISO strings, and both were simply stringified.
    The column is text, so "1787..." sorts before "2026...", and EVERY date-filtered query on
    this table silently returned Alpaca-only results. Nothing errored; Kraken activity just
    quietly vanished from any period-scoped view, which is why a "Kraken trades since 25 Aug"
    query returned nothing while the trades plainly existed.

    Epoch values are converted; anything already ISO is left exactly as it is; anything
    unrecognisable is passed through unchanged rather than discarded, since a preserved odd
    value can be investigated and a dropped one cannot.
    """
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    try:
        epoch = float(text)
    except (TypeError, ValueError):
        return text
    # Anything this large is milliseconds, not seconds; below the floor it is not a
    # timestamp at all (a quantity or a price that reached the wrong field).
    if epoch > 1e12:
        epoch /= 1000.0
    if epoch < 1e8:
        return text
    try:
        return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return text


def _descr(item: dict[str, Any]) -> dict[str, Any]:
    """Kraken's nested order-description block, or an empty dict.

    2026-08-27, found by reading the Trade History table on the phone: 149 of 391 rows --
    every Kraken order, 38% of the table -- showed no symbol and no buy/sell direction.
    Kraken's /0/private/OpenOrders and /0/private/ClosedOrders do not put `pair` and `type`
    at the top level of an order the way its trades endpoint does; they sit one level down
    in `descr`:

        {"descr": {"pair": "LTCGBP", "type": "sell", "order": "sell 0.673 LTCGBP @ ..."}}

    The reader looked only at the top level, so both columns came back empty and the table
    rendered "Not available - source data has not been recorded yet." in place of the coin
    name on every Kraken row. The data was always there and always stored in payload_json.
    """
    descr = item.get("descr")
    return descr if isinstance(descr, dict) else {}


def record_broker_trade_history(db_path: Path, broker: str, trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Persist broker orders/fills, in batches.

    2026-08-24: /timing-diagnostics measured this at 39.09s for Kraken and 21.2s for
    Alpaca in production -- by far the largest cost in either account path, and the
    reason /portfolio, /status and Ask AI Trader all hit Render's hard 60s proxy
    limit. Every broker call feeding it was under half a second; the brokers were
    never the problem.

    The cause was one conn.execute() per trade. Against a local SQLite file that is
    free, but the hosted database is a network hop away, so each row cost a full
    round trip and a few hundred rows cost most of a minute. The work is now a
    single lookup of what already exists plus one multi-row INSERT per chunk --
    two round trips instead of hundreds.
    """
    initialize_multi_broker_schema(db_path)
    if not trades:
        return []

    broker_key = broker.lower()
    prepared: list[tuple[tuple[Any, ...], dict[str, Any], str, tuple[Any, ...]]] = []
    seen: set[tuple[Any, ...]] = set()
    for item in trades:
        external_id = str(item.get("id") or item.get("order_id") or item.get("txid") or item.get("trade_id") or "")
        status = str(item.get("status") or item.get("type") or "unknown")
        event_timestamp = (
            item.get("updated_at")
            or item.get("transaction_time")
            or item.get("filled_at")
            or item.get("closed_at")
            or item.get("closetm")
            or item.get("created_at")
            or item.get("opentm")
            or item.get("time")
            or "broker-event-without-timestamp"
        )
        # Kraken reports times as epoch floats (opentm/closetm), Alpaca as ISO strings.
        # updated_at is a text column, and Postgres has no text = double precision
        # operator -- passing a float through the batch's IN (...) lookup fails the
        # whole write. Row-at-a-time inserts never hit this: an INSERT parameter gets
        # an assignment cast to the column type, a WHERE comparison does not.
        event_timestamp = _iso_timestamp(event_timestamp)
        identity = (external_id or None, status, event_timestamp)
        # A single broker payload can carry the same event twice (an order and its
        # own fill record). Row-at-a-time inserts let the second one be rejected by
        # the unique index; a batch has to drop it here instead.
        if identity in seen:
            continue
        seen.add(identity)
        prepared.append((
            identity,
            item,
            status,
            (
                broker_key,
                external_id or None,
                item.get("symbol") or item.get("pair") or _descr(item).get("pair"),
                item.get("asset_type"),
                item.get("side") or item.get("type") or _descr(item).get("type"),
                safe_float(item.get("qty") or item.get("vol") or item.get("quantity")),
                safe_float(item.get("price")),
                safe_float(item.get("notional")),
                status,
                item.get("created_at") or item.get("transaction_time") or item.get("opentm") or item.get("time"),
                item.get("closed_at") or item.get("closetm"),
                event_timestamp,
                json.dumps(item, sort_keys=True, default=str),
            ),
        ))

    if not prepared:
        return []

    columns = (
        "broker, external_id, symbol, asset_type, side, quantity, "
        "price, notional, status, opened_at, closed_at, updated_at, payload_json"
    )
    row_placeholder = "(" + ", ".join(["?"] * 13) + ")"

    with closing(connect(db_path)) as conn:
        with conn:
            existing = _existing_broker_history_keys(conn, broker_key, [row[0] for row in prepared])
            new_rows = [row for row in prepared if row[0] not in existing]
            for start in range(0, len(new_rows), _BROKER_HISTORY_INSERT_CHUNK):
                chunk = new_rows[start:start + _BROKER_HISTORY_INSERT_CHUNK]
                params: list[Any] = []
                for _, _, _, values in chunk:
                    params.extend(values)
                conn.execute(
                    f"INSERT INTO BROKER_TRADE_HISTORY ({columns}) VALUES "
                    + ", ".join([row_placeholder] * len(chunk))
                    + " ON CONFLICT(broker, external_id, status, updated_at) DO NOTHING",
                    params,
                )

    # Reported from what the pre-insert lookup found rather than from rowcount. A row
    # inserted by another process in between is counted as new here; that is a
    # duplicate notification at worst, where the old code could equally miss one.
    return [{**item, "status": status} for _, item, status, _ in new_rows]


def _existing_broker_history_keys(conn: Any, broker: str, identities: list[tuple[Any, ...]]) -> set[tuple[Any, ...]]:
    """Which of these (external_id, status, updated_at) keys this broker already has.

    Narrowed by the batch's own timestamps so the read stays small on a table that
    grows forever, then matched exactly in Python -- which also sidesteps SQL's
    three-valued NULL comparison for events that arrive without an id.
    """
    timestamps = sorted({identity[2] for identity in identities if identity[2] is not None})
    if not timestamps:
        return set()
    existing: set[tuple[Any, ...]] = set()
    for start in range(0, len(timestamps), _BROKER_HISTORY_INSERT_CHUNK):
        chunk = timestamps[start:start + _BROKER_HISTORY_INSERT_CHUNK]
        rows = conn.execute(
            "SELECT external_id, status, updated_at FROM BROKER_TRADE_HISTORY "
            f"WHERE broker = ? AND updated_at IN ({', '.join(['?'] * len(chunk))})",
            (broker, *chunk),
        ).fetchall()
        for row in rows:
            existing.add((row[0], row[1], row[2]))
    return existing


def latest_broker_trades(db_path: Path, broker: str, limit: int = 20) -> list[dict[str, Any]]:
    initialize_multi_broker_schema(db_path)
    with closing(connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM BROKER_TRADE_HISTORY WHERE broker = ? ORDER BY trade_history_id DESC LIMIT ?",
            (broker.lower(), limit),
        ).fetchall()
    return [dict(row) for row in rows]


def record_recommendation_set(
    db_path: Path,
    *,
    trigger_type: str,
    broker: str | None,
    symbols: list[str],
    proposal_ids: list[str],
    status: str,
    summary: str | None,
) -> None:
    initialize_multi_broker_schema(db_path)
    with closing(connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO RECOMMENDATION_SETS (
                    created_at, trigger_type, broker, symbols_json,
                    proposal_ids_json, status, summary
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (utc_now_iso(), trigger_type, broker, json.dumps(symbols), json.dumps(proposal_ids), status, summary),
            )
    if proposal_ids:
        record_notification(
            db_path,
            event_type="new_recommendation",
            broker=broker,
            symbol=None,
            title="New recommendation set",
            message=f"{len(proposal_ids)} recommendation(s) generated.",
            payload={"proposal_ids": proposal_ids, "symbols": symbols},
        )


def latest_recommendation_set(db_path: Path) -> dict[str, Any] | None:
    initialize_multi_broker_schema(db_path)
    with closing(connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM RECOMMENDATION_SETS ORDER BY set_id DESC LIMIT 1").fetchone()
    if not row:
        return None
    payload = dict(row)
    payload["symbols"] = _json_list(payload.pop("symbols_json"))
    payload["proposal_ids"] = _json_list(payload.pop("proposal_ids_json"))
    return payload


def record_notification(
    db_path: Path,
    *,
    event_type: str,
    broker: str | None,
    symbol: str | None,
    title: str,
    message: str,
    payload: dict[str, Any] | None = None,
) -> int:
    initialize_multi_broker_schema(db_path)
    with closing(connect(db_path)) as conn:
        with conn:
            cursor = conn.execute(
                """
                INSERT INTO NOTIFICATION_EVENTS (
                    created_at, event_type, broker, symbol, title, message,
                    delivery_status, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, 'queued', ?)
                """,
                (utc_now_iso(), event_type, broker, symbol, title, message, json.dumps(payload or {}, sort_keys=True, default=str)),
            )
            return int(cursor.lastrowid)


def list_notifications(db_path: Path, *, unread_only: bool = False, limit: int = 50) -> list[dict[str, Any]]:
    initialize_multi_broker_schema(db_path)
    sql = "SELECT * FROM NOTIFICATION_EVENTS"
    if unread_only:
        sql += " WHERE delivery_status = 'queued'"
    sql += " ORDER BY notification_id DESC LIMIT ?"
    with closing(connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, (limit,)).fetchall()
    return [dict(row) for row in rows]


def register_push_token(db_path: Path, push_token: str, *, platform: str | None = None) -> dict[str, Any]:
    initialize_multi_broker_schema(db_path)
    now = utc_now_iso()
    with closing(connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO PUSH_TOKENS (push_token, platform, registered_at, last_seen_at, active)
                VALUES (?, ?, ?, ?, 1)
                ON CONFLICT(push_token) DO UPDATE SET last_seen_at = excluded.last_seen_at, active = 1, platform = excluded.platform
                """,
                (push_token, platform, now, now),
            )
    return {"push_token": push_token, "registered_at": now}


def active_push_tokens(db_path: Path) -> list[str]:
    initialize_multi_broker_schema(db_path)
    with closing(connect(db_path)) as conn:
        rows = conn.execute("SELECT push_token FROM PUSH_TOKENS WHERE active = 1").fetchall()
    return [row[0] for row in rows]


# High-priority events worth an immediate push, as opposed to quieter events (research
# completed, new recommendation) that are fine to surface only in the in-app notification
# center. Kept as a set here so the send-decision lives with the delivery mechanism, not
# scattered across every call site that records a notification.
PUSH_NOTIFIED_EVENT_TYPES = {
    "stop_loss_triggered",
    "take_profit_triggered",
    "trade_exited",
    "broker_failure",
    "research_failure",
}


def pending_push_notifications(db_path: Path, limit: int = 20) -> list[dict[str, Any]]:
    initialize_multi_broker_schema(db_path)
    placeholders = ",".join("?" for _ in PUSH_NOTIFIED_EVENT_TYPES)
    with closing(connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"""
            SELECT * FROM NOTIFICATION_EVENTS
            WHERE push_sent_at IS NULL AND event_type IN ({placeholders})
            ORDER BY notification_id ASC LIMIT ?
            """,
            (*PUSH_NOTIFIED_EVENT_TYPES, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def mark_push_sent(db_path: Path, notification_ids: list[int]) -> None:
    initialize_multi_broker_schema(db_path)
    if not notification_ids:
        return
    now = utc_now_iso()
    placeholders = ",".join("?" for _ in notification_ids)
    with closing(connect(db_path)) as conn:
        with conn:
            conn.execute(
                f"UPDATE NOTIFICATION_EVENTS SET push_sent_at = ? WHERE notification_id IN ({placeholders})",
                (now, *notification_ids),
            )


def send_expo_push(tokens: list[str], *, title: str, body: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    if not tokens:
        return {"sent": 0, "reason": "no_registered_devices"}
    messages = [{"to": token, "title": title, "body": body, "data": data or {}} for token in tokens]
    try:
        payload = json.dumps(messages).encode("utf-8")
        req = request.Request(
            "https://exp.host/--/api/v2/push/send",
            data=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        with request.urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode("utf-8"))
        return {"sent": len(tokens), "result": result}
    except Exception as exc:
        return {"sent": 0, "error": str(exc)}


def mark_notifications_read(db_path: Path, notification_ids: list[int]) -> int:
    initialize_multi_broker_schema(db_path)
    if not notification_ids:
        return 0
    placeholders = ",".join("?" for _ in notification_ids)
    with closing(connect(db_path)) as conn:
        with conn:
            cursor = conn.execute(
                f"UPDATE NOTIFICATION_EVENTS SET delivery_status = 'read' WHERE notification_id IN ({placeholders})",
                tuple(notification_ids),
            )
            return cursor.rowcount


def acquire_order_intent_lock(
    db_path: Path,
    *,
    broker: str,
    client_order_id: str,
    symbol: str,
    side: str,
    notional: float | None,
) -> bool:
    initialize_multi_broker_schema(db_path)
    try:
        with closing(connect(db_path)) as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO ORDER_INTENT_LOCKS (
                        created_at, broker, client_order_id, symbol, side,
                        notional, status, result_order_id, notes
                    ) VALUES (?, ?, ?, ?, ?, ?, 'locked', NULL, 'Order intent locked before broker submission.')
                    """,
                    (utc_now_iso(), broker.lower(), client_order_id, symbol.upper(), side.lower(), notional),
                )
        return True
    except sqlite3.IntegrityError:
        return False


def complete_order_intent_lock(
    db_path: Path,
    *,
    broker: str,
    client_order_id: str,
    status: str,
    result_order_id: str | None,
    notes: str | None,
) -> None:
    initialize_multi_broker_schema(db_path)
    with closing(connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                UPDATE ORDER_INTENT_LOCKS
                SET status = ?, result_order_id = ?, notes = ?
                WHERE broker = ? AND client_order_id = ?
                """,
                (status, result_order_id, notes, broker.lower(), client_order_id),
            )


def release_order_intent_lock(
    db_path: Path,
    *,
    broker: str,
    client_order_id: str,
) -> None:
    """Free a lock after a definite, non-ambiguous broker rejection.

    Must only be called when the broker synchronously returned a clear
    "no order was placed" result. If the outcome is unknown (network loss,
    process termination, an exception before this point), the lock must
    stay in place so the position is never resubmitted blind.
    """

    initialize_multi_broker_schema(db_path)
    with closing(connect(db_path)) as conn:
        with conn:
            conn.execute(
                "DELETE FROM ORDER_INTENT_LOCKS WHERE broker = ? AND client_order_id = ?",
                (broker.lower(), client_order_id),
            )


def record_managed_trade_exit(
    db_path: Path,
    *,
    broker: str,
    symbol: str,
    side: str,
    quantity: float,
    entry_order_id: str | None,
    entry_price: float,
    stop_loss: float,
    take_profit: float,
    payload: dict[str, Any],
    trailing_stop_pct: float | None = None,
) -> dict[str, Any]:
    initialize_multi_broker_schema(db_path)
    now = utc_now_iso()
    with closing(connect(db_path)) as conn:
        with conn:
            cursor = conn.execute(
                """
                INSERT INTO MANAGED_TRADE_EXITS (
                    created_at, updated_at, broker, symbol, side, quantity,
                    entry_order_id, entry_price, stop_loss, take_profit,
                    status, exit_order_id, exit_reason, last_checked_at, payload_json,
                    trailing_stop_pct, high_water_mark, low_water_mark
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', NULL, NULL, NULL, ?, ?, ?, ?)
                """,
                (
                    now,
                    now,
                    broker.lower(),
                    symbol.upper(),
                    side.lower(),
                    quantity,
                    entry_order_id,
                    entry_price,
                    stop_loss,
                    take_profit,
                    json.dumps(payload, sort_keys=True, default=str),
                    trailing_stop_pct,
                    entry_price if trailing_stop_pct else None,
                    entry_price if trailing_stop_pct else None,
                ),
            )
            managed_exit_id = cursor.lastrowid
    return {"managed_exit_id": managed_exit_id, "status": "open", "created_at": now, "trailing_stop_pct": trailing_stop_pct}


def update_trailing_water_marks(db_path: Path, managed_exit_id: int, *, high_water_mark: float | None, low_water_mark: float | None) -> None:
    initialize_multi_broker_schema(db_path)
    with closing(connect(db_path)) as conn:
        with conn:
            conn.execute(
                "UPDATE MANAGED_TRADE_EXITS SET high_water_mark = ?, low_water_mark = ?, last_checked_at = ? WHERE managed_exit_id = ?",
                (high_water_mark, low_water_mark, utc_now_iso(), managed_exit_id),
            )


def record_native_stop_order_id(db_path: Path, managed_exit_id: int, order_id: str) -> None:
    """Attach a native (broker-side) stop order's ID to an already-open managed exit.

    monitor_managed_exits treats a non-null native_stop_order_id as "Kraken owns the
    stop-loss leg for this position" -- it stops evaluating its own stop trigger for that
    row and only watches take-profit, cancelling this order first if take-profit fires.
    """
    initialize_multi_broker_schema(db_path)
    with closing(connect(db_path)) as conn:
        with conn:
            conn.execute(
                "UPDATE MANAGED_TRADE_EXITS SET native_stop_order_id = ?, last_checked_at = ? WHERE managed_exit_id = ?",
                (order_id, utc_now_iso(), managed_exit_id),
            )


def open_managed_exits(db_path: Path, broker: str | None = None) -> list[dict[str, Any]]:
    initialize_multi_broker_schema(db_path)
    sql = "SELECT * FROM MANAGED_TRADE_EXITS WHERE status = 'open'"
    params: tuple[Any, ...] = ()
    if broker:
        sql += " AND broker = ?"
        params = (broker.lower(),)
    sql += " ORDER BY managed_exit_id ASC"
    with closing(connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def _merge_managed_exit_payload(conn: Any, managed_exit_id: int, new_fields: dict[str, Any] | None) -> str:
    """Merge new fields into a managed exit's existing payload_json instead of replacing it.

    2026-08-19 hosted finding: close_managed_exit/mark_managed_exit_submitted/
    close_managed_exit_and_record all overwrote payload_json wholesale with only their own
    exit-time fields (price/order/reason) -- silently discarding the entry-time payload,
    which is the only place proposal_id (and entry_reason) lives for a managed exit.
    bootstrap_kraken_order_ownership re-derives each order's logical_trade_id from this same
    payload every reconciliation cycle; once proposal_id disappeared from it, the exit order
    got re-registered under a synthetic "kraken-managed-exit:N" logical_trade_id while its
    proposal_id column (preserved separately via ON CONFLICT ... COALESCE) still pointed at
    the real UUID -- two different logical_trade_id rows then collided on LOGICAL_TRADES'
    proposal_id UNIQUE constraint the next time that trade's evidence was reconciled,
    confirmed live via /kraken-reconciliation/replay ("duplicate key value violates unique
    constraint \"logical_trades_proposal_id_key\""). That crash aborted reconciliation before
    ever reaching enqueue_learning_workflow for real closed trades. Merging keeps proposal_id
    (and any other entry-time context) intact across every exit-time payload update.
    """
    row = conn.execute("SELECT payload_json FROM MANAGED_TRADE_EXITS WHERE managed_exit_id = ?", (managed_exit_id,)).fetchone()
    existing = _json_dict(row[0]) if row else {}
    existing.update(new_fields or {})
    return json.dumps(existing, sort_keys=True, default=str)


def close_managed_exit(
    db_path: Path,
    managed_exit_id: int,
    *,
    exit_order_id: str | None,
    exit_reason: str,
    payload: dict[str, Any] | None = None,
) -> None:
    initialize_multi_broker_schema(db_path)
    with closing(connect(db_path)) as conn:
        with conn:
            merged_payload = _merge_managed_exit_payload(conn, managed_exit_id, payload)
            conn.execute(
                """
                UPDATE MANAGED_TRADE_EXITS
                SET updated_at = ?, status = 'closed', exit_order_id = ?,
                    exit_reason = ?, last_checked_at = ?, payload_json = ?
                WHERE managed_exit_id = ?
                """,
                (
                    utc_now_iso(),
                    exit_order_id,
                    exit_reason,
                    utc_now_iso(),
                    merged_payload,
                    managed_exit_id,
                ),
            )


def mark_managed_exit_submitted(
    db_path: Path,
    managed_exit_id: int,
    *,
    exit_order_id: str,
    exit_reason: str,
    payload: dict[str, Any] | None = None,
) -> None:
    """Record an accepted exit order without falsely declaring the position closed."""

    initialize_multi_broker_schema(db_path)
    now = utc_now_iso()
    with closing(connect(db_path)) as conn:
        with conn:
            merged_payload = _merge_managed_exit_payload(conn, managed_exit_id, payload)
            conn.execute(
                """
                UPDATE MANAGED_TRADE_EXITS
                SET updated_at = ?, status = 'exit_submitted', exit_order_id = ?,
                    exit_reason = ?, last_checked_at = ?, payload_json = ?
                WHERE managed_exit_id = ?
                """,
                (
                    now,
                    exit_order_id,
                    exit_reason,
                    now,
                    merged_payload,
                    managed_exit_id,
                ),
            )


def close_managed_exit_and_record(
    db_path: Path,
    managed_exit_id: int,
    *,
    broker: str,
    symbol: str,
    asset_type: str,
    side: str,
    quantity: float,
    price: float | None,
    exit_order_id: str | None,
    exit_reason: str,
    order_payload: dict[str, Any] | None = None,
    entry_price: float | None = None,
    entry_side: str | None = None,
    opened_at: str | None = None,
    proposal_id: str | None = None,
    entry_reason: str | None = None,
    primary_factors: dict[str, Any] | None = None,
) -> None:
    initialize_multi_broker_schema(db_path)
    now = utc_now_iso()
    trade_payload = {"managed_exit_id": managed_exit_id, "reason": exit_reason, "order": order_payload or {}}
    profit_loss = None
    if entry_price is not None and price is not None:
        # P&L sign must follow the ORIGINAL position direction, not the closing order's
        # side (a "sell" exit closes a "buy" position, and inverting on the wrong side
        # would label a stop-loss loss as a profit).
        multiplier = 1 if (entry_side or side).lower() == "buy" else -1
        profit_loss = (price - entry_price) * quantity * multiplier
    holding_period_seconds = None
    opened_dt = _parse_iso(opened_at) if opened_at else None
    closed_dt = _parse_iso(now)
    if opened_dt and closed_dt:
        holding_period_seconds = (closed_dt - opened_dt).total_seconds()
    with closing(connect(db_path)) as conn:
        with conn:
            merged_payload = _merge_managed_exit_payload(conn, managed_exit_id, order_payload)
            conn.execute(
                """
                UPDATE MANAGED_TRADE_EXITS
                SET updated_at = ?, status = 'closed', exit_order_id = ?,
                    exit_reason = ?, last_checked_at = ?, payload_json = ?
                WHERE managed_exit_id = ?
                """,
                (now, exit_order_id, exit_reason, now, merged_payload, managed_exit_id),
            )
            conn.execute(
                """
                INSERT INTO BROKER_TRADE_HISTORY (
                    broker, external_id, symbol, asset_type, side, quantity,
                    price, notional, status, opened_at, closed_at, updated_at,
                    payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'closed', ?, ?, ?, ?)
                ON CONFLICT(broker, external_id, status, updated_at) DO NOTHING
                """,
                (
                    broker.lower(),
                    exit_order_id,
                    symbol.upper(),
                    asset_type,
                    side.lower(),
                    quantity,
                    price,
                    (price or 0.0) * quantity,
                    now,
                    now,
                    now,
                    json.dumps(trade_payload, sort_keys=True, default=str),
                ),
            )
            if entry_price is not None and price is not None:
                conn.execute(
                    """
                    INSERT INTO PERFORMANCE_ATTRIBUTION (
                        created_at, proposal_id, broker, symbol, asset_type, side,
                        entry_price, exit_price, quantity, profit_loss, opened_at,
                        closed_at, holding_period_seconds, entry_reason, exit_reason,
                        primary_factors_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        now,
                        proposal_id,
                        broker.lower(),
                        symbol.upper(),
                        asset_type,
                        side.lower(),
                        entry_price,
                        price,
                        quantity,
                        profit_loss,
                        opened_at,
                        now,
                        holding_period_seconds,
                        entry_reason,
                        exit_reason,
                        json.dumps(primary_factors or {}, sort_keys=True, default=str),
                    ),
                )


def _parse_iso(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def list_performance_attribution(db_path: Path, limit: int = 50) -> list[dict[str, Any]]:
    initialize_multi_broker_schema(db_path)
    with closing(connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM PERFORMANCE_ATTRIBUTION ORDER BY attribution_id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def record_seatbelt_event(
    db_path: Path,
    *,
    broker: str,
    symbol: str | None,
    event_type: str,
    result: str,
    message: str,
    payload: dict[str, Any] | None = None,
) -> None:
    initialize_multi_broker_schema(db_path)
    with closing(connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO MECHANICAL_SEATBELT_EVENTS (
                    created_at, broker, symbol, event_type, result, message, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (utc_now_iso(), broker.lower(), symbol, event_type, result, message, json.dumps(payload or {}, sort_keys=True, default=str)),
            )


def record_crypto_research_score(db_path: Path, *, symbol: str, category: str | None, metrics: dict[str, Any], source: str) -> dict[str, Any]:
    initialize_multi_broker_schema(db_path)
    technical = safe_score(metrics.get("technical_trend_score")) or 0.0
    momentum = safe_score(metrics.get("momentum_score")) or 0.0
    risk = safe_score(metrics.get("risk_score")) or 0.0
    sentiment = safe_score(metrics.get("sentiment")) or 0.0
    liquidity = safe_score(metrics.get("liquidity")) or 0.0
    overall = safe_score(metrics.get("overall_due_diligence_score"))
    if overall is None:
        overall = round((technical + momentum + risk + sentiment + liquidity) / 5, 4)
    confidence = safe_score(metrics.get("confidence_score")) or overall
    payload = {
        "symbol": symbol.upper(),
        "category": category,
        "technical_trend_score": technical,
        "momentum_score": momentum,
        "rsi": safe_float(metrics.get("rsi")),
        "moving_average_position": safe_float(metrics.get("moving_average_position")),
        "macd": safe_float(metrics.get("macd")),
        "volume_trend": safe_score(metrics.get("volume_trend")),
        "volatility": safe_float(metrics.get("volatility")),
        "liquidity": liquidity,
        "market_structure": safe_score(metrics.get("market_structure")),
        "sentiment": sentiment,
        "news_score": safe_score(metrics.get("news_score")),
        "onchain_activity": safe_score(metrics.get("onchain_activity")),
        "risk_score": risk,
        "overall_due_diligence_score": overall,
        "confidence_score": confidence,
        "reasoning": metrics.get("reasoning") or {"source": source},
        "source": source,
    }
    with closing(connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO CRYPTO_RESEARCH_SCORES (
                    created_at, symbol, category, technical_trend_score, momentum_score,
                    rsi, moving_average_position, macd, volume_trend, volatility,
                    liquidity, market_structure, sentiment, news_score, onchain_activity,
                    risk_score, overall_due_diligence_score, confidence_score,
                    reasoning_json, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    utc_now_iso(),
                    payload["symbol"],
                    category,
                    payload["technical_trend_score"],
                    payload["momentum_score"],
                    payload["rsi"],
                    payload["moving_average_position"],
                    payload["macd"],
                    payload["volume_trend"],
                    payload["volatility"],
                    payload["liquidity"],
                    payload["market_structure"],
                    payload["sentiment"],
                    payload["news_score"],
                    payload["onchain_activity"],
                    payload["risk_score"],
                    payload["overall_due_diligence_score"],
                    payload["confidence_score"],
                    json.dumps(payload["reasoning"], sort_keys=True, default=str),
                    source,
                ),
            )
    return payload


def research_freshness(last_scan: str | None, *, max_age_minutes: int = 90) -> str:
    if not last_scan:
        return "Not available - no scan recorded yet"
    try:
        parsed = datetime.fromisoformat(last_scan.replace("Z", "+00:00"))
    except ValueError:
        return "Unknown - last scan timestamp could not be parsed"
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)
    if age <= timedelta(minutes=max_age_minutes):
        return "Fresh"
    return f"Stale - last scan was {int(age.total_seconds() // 60)} minutes ago"


def today_runtime_counts(db_path: Path, broker: str) -> dict[str, int]:
    today = date.today().isoformat()
    initialize_multi_broker_schema(db_path)
    with closing(connect(db_path)) as conn:
        reviewed = conn.execute(
            "SELECT COUNT(*) FROM CRYPTO_RESEARCH_SCORES WHERE created_at LIKE ?",
            (f"{today}%",),
        ).fetchone()[0]
        trades = conn.execute(
            "SELECT COUNT(*) FROM BROKER_TRADE_HISTORY WHERE broker = ? AND updated_at LIKE ?",
            (broker.lower(), f"{today}%"),
        ).fetchone()[0]
    return {"assets_reviewed_today": int(reviewed or 0), "trades_today": int(trades or 0)}


def _json_list(value: Any) -> list[str]:
    try:
        data = json.loads(value or "[]")
    except (TypeError, json.JSONDecodeError):
        return []
    if isinstance(data, list):
        return [str(item) for item in data]
    return []


def _json_dict(value: Any) -> dict[str, Any]:
    try:
        data = json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def backfill_broker_history_symbols(db_path: Path, *, broker: str = "kraken") -> dict[str, Any]:
    """Recover symbol and side on rows stored before _descr was read.

    The values were never lost -- the whole broker payload is kept in payload_json -- so this
    reads them back out rather than re-fetching anything from the broker. Idempotent: rows
    that already carry a symbol are left alone.
    """
    initialize_multi_broker_schema(db_path)
    outcome = {"examined": 0, "symbols_set": 0, "sides_set": 0}
    with closing(connect(db_path)) as conn:
        rows = conn.execute(
            "SELECT trade_history_id, payload_json, symbol, side FROM BROKER_TRADE_HISTORY "
            "WHERE broker = ? AND (symbol IS NULL OR symbol = '' OR side IS NULL OR side = '')",
            (broker.lower(),),
        ).fetchall()
        updates: list[tuple[Any, ...]] = []
        for row in rows:
            outcome["examined"] += 1
            try:
                payload = json.loads(row[1]) if isinstance(row[1], str) else (row[1] or {})
            except (TypeError, ValueError):
                continue
            if not isinstance(payload, dict):
                continue
            descr = _descr(payload)
            symbol = row[2] or payload.get("symbol") or payload.get("pair") or descr.get("pair")
            side = row[3] or payload.get("side") or payload.get("type") or descr.get("type")
            if (symbol and symbol != row[2]) or (side and side != row[3]):
                outcome["symbols_set"] += int(bool(symbol) and symbol != row[2])
                outcome["sides_set"] += int(bool(side) and side != row[3])
                updates.append((symbol, side, row[0]))
        if updates:
            with conn:
                conn.executemany(
                    "UPDATE BROKER_TRADE_HISTORY SET symbol = ?, side = ? WHERE trade_history_id = ?",
                    updates,
                )
    return outcome
