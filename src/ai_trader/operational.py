from __future__ import annotations

import json
import sqlite3
from .database import connect
from contextlib import closing
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from .models import utc_now_iso


OPERATIONAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS PORTFOLIO_SNAPSHOTS (
    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    broker TEXT NOT NULL,
    exchange TEXT NOT NULL,
    account_currency TEXT,
    cash REAL,
    portfolio_value REAL,
    buying_power REAL,
    open_positions_count INTEGER,
    day_pnl REAL,
    week_pnl REAL,
    month_pnl REAL,
    month_start_value REAL,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS RESEARCH_RUNS (
    research_run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL,
    trigger_type TEXT NOT NULL,
    markets_reviewed TEXT,
    companies_reviewed INTEGER,
    crypto_assets_reviewed INTEGER,
    benchmark_traders_reviewed INTEGER,
    recommendations_created INTEGER,
    trades_executed INTEGER,
    trades_rejected INTEGER,
    errors TEXT,
    next_scheduled_run TEXT,
    summary TEXT
);

CREATE TABLE IF NOT EXISTS CRYPTO_ASSET_MASTER (
    asset_id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    market_cap_rank INTEGER,
    source TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    notes TEXT,
    last_updated TEXT NOT NULL
);
"""


QUALITATIVE_SCORES = {
    "excellent": 0.95,
    "very high": 0.9,
    "high": 0.85,
    "good": 0.75,
    "positive": 0.75,
    "medium": 0.5,
    "moderate": 0.5,
    "neutral": 0.5,
    "cautious": 0.35,
    "low": 0.25,
    "poor": 0.15,
    "negative": 0.15,
    "unknown": None,
    "not available": None,
}


def initialize_operational_schema(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect(db_path)) as conn:
        with conn:
            conn.executescript(OPERATIONAL_SCHEMA)


def safe_score(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number / 100 if number > 1 else number
    text = str(value).strip()
    if not text:
        return None
    lowered = text.lower()
    if lowered in QUALITATIVE_SCORES:
        return QUALITATIVE_SCORES[lowered]
    try:
        cleaned = lowered.replace("%", "")
        number = float(cleaned)
    except ValueError:
        return None
    return number / 100 if number > 1 else number


def safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", "").replace("$", "").strip())
    except ValueError:
        return None


def display_value(value: Any, reason: str) -> Any:
    return value if value not in (None, "") else f"Not available - {reason}"


def record_portfolio_snapshot(
    db_path: Path,
    *,
    broker: str,
    exchange: str,
    account: dict[str, Any] | None,
    positions: list[dict[str, Any]],
    notes: str,
) -> dict[str, Any]:
    initialize_operational_schema(db_path)
    account = account or {}
    now = utc_now_iso()
    cash = safe_float(account.get("cash"))
    portfolio_value = safe_float(account.get("portfolio_value") or account.get("equity"))
    buying_power = safe_float(account.get("buying_power"))
    currency = account.get("currency")
    month_start_value = _month_start_value(db_path, broker, exchange, now) or portfolio_value
    day_pnl = _pnl_since(db_path, broker, exchange, portfolio_value, days=1)
    week_pnl = _pnl_since(db_path, broker, exchange, portfolio_value, days=7)
    month_pnl = None if month_start_value is None or portfolio_value is None else portfolio_value - month_start_value
    with closing(connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO PORTFOLIO_SNAPSHOTS (
                    created_at, broker, exchange, account_currency, cash, portfolio_value,
                    buying_power, open_positions_count, day_pnl, week_pnl, month_pnl,
                    month_start_value, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now,
                    broker,
                    exchange,
                    currency,
                    cash,
                    portfolio_value,
                    buying_power,
                    len(positions),
                    day_pnl,
                    week_pnl,
                    month_pnl,
                    month_start_value,
                    notes,
                ),
            )
    return {
        "created_at": now,
        "broker": broker,
        "exchange": exchange,
        "account_currency": currency,
        "cash": cash,
        "portfolio_value": portfolio_value,
        "buying_power": buying_power,
        "open_positions_count": len(positions),
        "day_pnl": day_pnl,
        "week_pnl": week_pnl,
        "month_pnl": month_pnl,
        "month_start_value": month_start_value,
        "notes": notes,
    }


def record_research_run(
    db_path: Path,
    *,
    started_at: str,
    completed_at: str | None,
    status: str,
    trigger_type: str,
    markets_reviewed: list[str],
    companies_reviewed: int,
    crypto_assets_reviewed: int,
    benchmark_traders_reviewed: int,
    recommendations_created: int,
    trades_executed: int,
    trades_rejected: int,
    errors: list[str],
    next_scheduled_run: str | None,
    summary: str,
) -> None:
    initialize_operational_schema(db_path)
    with closing(connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO RESEARCH_RUNS (
                    started_at, completed_at, status, trigger_type, markets_reviewed,
                    companies_reviewed, crypto_assets_reviewed, benchmark_traders_reviewed,
                    recommendations_created, trades_executed, trades_rejected, errors,
                    next_scheduled_run, summary
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    started_at,
                    completed_at,
                    status,
                    trigger_type,
                    json.dumps(markets_reviewed),
                    companies_reviewed,
                    crypto_assets_reviewed,
                    benchmark_traders_reviewed,
                    recommendations_created,
                    trades_executed,
                    trades_rejected,
                    json.dumps(errors),
                    next_scheduled_run,
                    summary,
                ),
            )


def latest_pnl_snapshot(db_path: Path, broker: str) -> dict[str, Any]:
    initialize_operational_schema(db_path)
    with closing(connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT day_pnl, week_pnl, month_pnl, portfolio_value
            FROM PORTFOLIO_SNAPSHOTS WHERE broker = ?
            ORDER BY snapshot_id DESC LIMIT 1
            """,
            (broker.lower(),),
        ).fetchone()
        peak = conn.execute(
            "SELECT MAX(portfolio_value) FROM PORTFOLIO_SNAPSHOTS WHERE broker = ?",
            (broker.lower(),),
        ).fetchone()
    return {
        "day_pnl": row["day_pnl"] if row else None,
        "week_pnl": row["week_pnl"] if row else None,
        "month_pnl": row["month_pnl"] if row else None,
        "portfolio_value": row["portfolio_value"] if row else None,
        "peak_equity": peak[0] if peak and peak[0] is not None else None,
    }


def latest_research_run(db_path: Path) -> dict[str, Any] | None:
    initialize_operational_schema(db_path)
    with closing(connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM RESEARCH_RUNS ORDER BY research_run_id DESC LIMIT 1").fetchone()
        return dict(row) if row else None


CRYPTO_CATEGORY_ENDPOINTS: dict[str, str] = {
    "Top 20 by market cap": (
        "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc"
        "&per_page=20&page=1&price_change_percentage=24h,7d,30d"
    ),
    "Top 20 AI coins": (
        "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&category=artificial-intelligence"
        "&order=market_cap_desc&per_page=20&page=1&price_change_percentage=24h,7d,30d"
    ),
    "Top 20 security/privacy coins": (
        "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&category=privacy-coins"
        "&order=market_cap_desc&per_page=20&page=1&price_change_percentage=24h,7d,30d"
    ),
}


def seed_crypto_universe(db_path: Path, *, fetch_live: bool = False) -> dict[str, Any]:
    initialize_operational_schema(db_path)
    assets: list[dict[str, Any]] = []
    market_rows: list[dict[str, Any]] = []
    source = "Unavailable"
    notes = "Live public ranking fetch was not requested."
    if fetch_live:
        try:
            for category_label, url in CRYPTO_CATEGORY_ENDPOINTS.items():
                with urlopen(url, timeout=20) as response:
                    raw = json.loads(response.read().decode("utf-8"))
                for row in raw:
                    assets.append(_crypto_row(row, category_label, "CoinGecko public markets API"))
                    market_rows.append(row)
            source = "CoinGecko public markets API"
            notes = "Fetched live public market data across market-cap, AI, and privacy/security categories."
        except Exception as exc:
            notes = f"Rankings unavailable: {exc}"
    with closing(connect(db_path)) as conn:
        with conn:
            if assets:
                for asset in assets:
                    conn.execute(
                        """
                        INSERT INTO CRYPTO_ASSET_MASTER (
                            symbol, name, category, market_cap_rank, source, active, notes, last_updated
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            asset["symbol"],
                            asset["name"],
                            asset["category"],
                            asset["market_cap_rank"],
                            asset["source"],
                            1,
                            asset["notes"],
                            utc_now_iso(),
                        ),
                    )
    if assets:
        _populate_crypto_master_and_scores(db_path, assets, market_rows)
    return {"inserted": len(assets), "source": source, "notes": notes}


def _populate_crypto_master_and_scores(db_path: Path, assets: list[dict[str, Any]], market_rows: list[dict[str, Any]]) -> None:
    # Deferred imports: foundation.py and multi_broker.py both import this module, so importing
    # them at module load time here would be circular. By call time (runtime, not import time)
    # both modules are already fully loaded, so this is safe.
    from .foundation import initialize_foundation_schema
    from .multi_broker import record_crypto_research_score

    initialize_foundation_schema(db_path)
    now = utc_now_iso()
    with closing(connect(db_path)) as conn:
        with conn:
            for asset, raw_row in zip(assets, market_rows):
                conn.execute(
                    """
                    INSERT INTO CRYPTO_MASTER (symbol, name, category, source, active, created_at, updated_at)
                    VALUES (?, ?, ?, ?, 1, ?, ?)
                    ON CONFLICT(symbol, category) DO UPDATE SET
                        active = 1, name = excluded.name, updated_at = excluded.updated_at
                    """,
                    (asset["symbol"], asset["name"], asset["category"], asset["source"], now, now),
                )
                conn.execute(
                    """
                    INSERT INTO CRYPTO_MARKET_DATA (
                        symbol, observed_at, price_usd, market_cap_usd, volume_24h_usd, source, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        asset["symbol"],
                        now,
                        safe_float(raw_row.get("current_price")),
                        safe_float(raw_row.get("market_cap")),
                        safe_float(raw_row.get("total_volume")),
                        asset["source"],
                        json.dumps(raw_row, default=str),
                    ),
                )
    for asset, raw_row in zip(assets, market_rows):
        record_crypto_research_score(
            db_path,
            symbol=asset["symbol"],
            category=asset["category"],
            metrics=_crypto_metrics_from_market_row(raw_row),
            source=asset["source"],
        )


def _crypto_metrics_from_market_row(row: dict[str, Any]) -> dict[str, Any]:
    change_24h = safe_float(row.get("price_change_percentage_24h_in_currency") or row.get("price_change_percentage_24h"))
    change_7d = safe_float(row.get("price_change_percentage_7d_in_currency"))
    change_30d = safe_float(row.get("price_change_percentage_30d_in_currency"))
    market_cap = safe_float(row.get("market_cap"))
    volume = safe_float(row.get("total_volume"))
    liquidity = min(1.0, volume / market_cap) if market_cap and volume and market_cap > 0 else None
    volatility = min(1.0, abs(change_30d) / 100) if change_30d is not None else None
    risk_score = round(1.0 - volatility, 4) if volatility is not None else None
    return {
        "technical_trend_score": _pct_to_unit_score(change_7d),
        "momentum_score": _pct_to_unit_score(change_24h),
        "volatility": volatility,
        "liquidity": liquidity,
        "risk_score": risk_score,
        # No free reliable on-chain/sentiment/news feed is wired up yet - these are left
        # unset (None) rather than fabricated, so due diligence correctly treats them as
        # insufficient_data instead of silently passing.
        "sentiment": None,
        "news_score": None,
        "onchain_activity": None,
        "reasoning": {
            "source": "CoinGecko public markets API",
            "note": "technical/momentum/volatility/liquidity are computed from live price, volume, and market-cap data. "
            "on-chain activity, sentiment, and news are not available without a paid data provider and are left blank.",
            "price_change_pct_24h": change_24h,
            "price_change_pct_7d": change_7d,
            "price_change_pct_30d": change_30d,
        },
    }


def _pct_to_unit_score(pct: float | None) -> float | None:
    if pct is None:
        return None
    return round(max(0.0, min(1.0, 0.5 + (pct / 100.0))), 4)


def _crypto_row(row: dict[str, Any], category: str, source: str) -> dict[str, Any]:
    return {
        "symbol": str(row.get("symbol", "")).upper(),
        "name": str(row.get("name", "")),
        "category": category,
        "market_cap_rank": row.get("market_cap_rank"),
        "source": source,
        "notes": "Public market ranking.",
    }


def _pnl_since(db_path: Path, broker: str, exchange: str, current_value: float | None, *, days: int) -> float | None:
    if current_value is None:
        return None
    cutoff = (datetime.now(timezone.utc).timestamp() - days * 86400)
    with closing(connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT created_at, portfolio_value FROM PORTFOLIO_SNAPSHOTS
            WHERE broker = ? AND exchange = ? AND portfolio_value IS NOT NULL
            ORDER BY snapshot_id ASC
            """,
            (broker, exchange),
        ).fetchall()
    candidate = None
    for row in rows:
        parsed = _parse_dt(row["created_at"])
        if parsed and parsed.timestamp() <= cutoff:
            candidate = row
    if not candidate:
        return None
    return current_value - float(candidate["portfolio_value"])


def _month_start_value(db_path: Path, broker: str, exchange: str, now_iso: str) -> float | None:
    parsed = _parse_dt(now_iso)
    if parsed is None:
        return None
    month_start = parsed.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
    with closing(connect(db_path)) as conn:
        row = conn.execute(
            """
            SELECT portfolio_value FROM PORTFOLIO_SNAPSHOTS
            WHERE broker = ? AND exchange = ? AND created_at >= ? AND portfolio_value IS NOT NULL
            ORDER BY snapshot_id ASC LIMIT 1
            """,
            (broker, exchange, month_start),
        ).fetchone()
    return None if row is None else float(row[0])


def _parse_dt(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
