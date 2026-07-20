from __future__ import annotations

import json
import math
import sqlite3
from .database import connect
from collections import defaultdict
from contextlib import closing
from pathlib import Path
from typing import Any

from .models import utc_now_iso


PORTFOLIO_INTELLIGENCE_SCHEMA = """
CREATE TABLE IF NOT EXISTS ASSET_METADATA (
    metadata_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    symbol TEXT NOT NULL,
    asset_class TEXT,
    sector TEXT,
    industry TEXT,
    investment_theme TEXT,
    country TEXT,
    region TEXT,
    trading_currency TEXT,
    economic_currency_exposure TEXT,
    liquidity_class TEXT,
    market_cap_class TEXT,
    crypto_category TEXT,
    underlying_risk_factors_json TEXT NOT NULL,
    source TEXT NOT NULL,
    source_timestamp TEXT,
    confidence TEXT NOT NULL,
    UNIQUE(symbol, source)
);

CREATE TABLE IF NOT EXISTS PORTFOLIO_EXPOSURE_SNAPSHOTS (
    exposure_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    broker TEXT,
    total_value REAL,
    exposure_json TEXT NOT NULL,
    warnings_json TEXT NOT NULL,
    plain_english TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS PORTFOLIO_CORRELATION_WARNINGS (
    warning_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    symbols_json TEXT NOT NULL,
    correlation REAL,
    sample_size INTEGER NOT NULL,
    warning TEXT NOT NULL,
    confidence TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS PORTFOLIO_RISK_CONTRIBUTIONS (
    contribution_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    symbol TEXT NOT NULL,
    broker TEXT,
    position_value REAL,
    stop_based_risk REAL,
    portfolio_risk_contribution REAL,
    marginal_risk_change REAL,
    risk_label TEXT NOT NULL,
    explanation TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS PORTFOLIO_STRESS_TESTS (
    stress_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    scenario_name TEXT NOT NULL,
    estimated_impact REAL,
    vulnerable_positions_json TEXT NOT NULL,
    uncertainty TEXT NOT NULL,
    assumptions_json TEXT NOT NULL,
    explanation TEXT NOT NULL
);
"""


def initialize_portfolio_intelligence_schema(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect(db_path)) as conn:
        with conn:
            conn.executescript(PORTFOLIO_INTELLIGENCE_SCHEMA)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_asset_metadata_symbol ON ASSET_METADATA(symbol)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_exposure_broker ON PORTFOLIO_EXPOSURE_SNAPSHOTS(broker, created_at)")


def upsert_asset_metadata(
    db_path: Path,
    *,
    symbol: str,
    source: str,
    confidence: str = "medium",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    initialize_portfolio_intelligence_schema(db_path)
    payload = payload or {}
    with closing(connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO ASSET_METADATA (
                    created_at, symbol, asset_class, sector, industry, investment_theme,
                    country, region, trading_currency, economic_currency_exposure,
                    liquidity_class, market_cap_class, crypto_category,
                    underlying_risk_factors_json, source, source_timestamp, confidence
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, source) DO UPDATE SET
                    created_at = excluded.created_at,
                    asset_class = excluded.asset_class,
                    sector = excluded.sector,
                    industry = excluded.industry,
                    investment_theme = excluded.investment_theme,
                    country = excluded.country,
                    region = excluded.region,
                    trading_currency = excluded.trading_currency,
                    economic_currency_exposure = excluded.economic_currency_exposure,
                    liquidity_class = excluded.liquidity_class,
                    market_cap_class = excluded.market_cap_class,
                    crypto_category = excluded.crypto_category,
                    underlying_risk_factors_json = excluded.underlying_risk_factors_json,
                    source_timestamp = excluded.source_timestamp,
                    confidence = excluded.confidence
                """,
                (
                    utc_now_iso(),
                    symbol.upper(),
                    payload.get("asset_class"),
                    payload.get("sector"),
                    payload.get("industry"),
                    payload.get("investment_theme"),
                    payload.get("country"),
                    payload.get("region"),
                    payload.get("trading_currency"),
                    payload.get("economic_currency_exposure"),
                    payload.get("liquidity_class"),
                    payload.get("market_cap_class"),
                    payload.get("crypto_category"),
                    json.dumps(payload.get("underlying_risk_factors") or [], sort_keys=True),
                    source,
                    payload.get("source_timestamp"),
                    confidence,
                ),
            )
    return {"symbol": symbol.upper(), "source": source, "confidence": confidence}


def calculate_portfolio_exposure(db_path: Path, positions: list[dict[str, Any]], *, broker: str | None = None) -> dict[str, Any]:
    initialize_portfolio_intelligence_schema(db_path)
    metadata = _metadata_by_symbol(db_path)
    total = sum(max(0.0, _float(item.get("market_value") or item.get("notional") or item.get("value")) or 0.0) for item in positions)
    buckets: dict[str, dict[str, float]] = {
        "asset_class": defaultdict(float),
        "sector": defaultdict(float),
        "country": defaultdict(float),
        "currency": defaultdict(float),
        "theme": defaultdict(float),
        "crypto_category": defaultdict(float),
    }
    missing_metadata: list[str] = []
    largest: list[dict[str, Any]] = []
    for item in positions:
        symbol = str(item.get("symbol") or item.get("pair") or "").upper()
        value = max(0.0, _float(item.get("market_value") or item.get("notional") or item.get("value")) or 0.0)
        meta = metadata.get(symbol) or {}
        if not meta:
            missing_metadata.append(symbol)
        buckets["asset_class"][meta.get("asset_class") or item.get("asset_type") or "Unknown"] += value
        buckets["sector"][meta.get("sector") or "Unknown - sector metadata missing"] += value
        buckets["country"][meta.get("country") or "Unknown - country metadata missing"] += value
        buckets["currency"][meta.get("trading_currency") or item.get("currency") or "Unknown"] += value
        buckets["theme"][meta.get("investment_theme") or "Unknown - theme metadata missing"] += value
        buckets["crypto_category"][meta.get("crypto_category") or ("Unknown crypto category" if item.get("asset_type") == "crypto" else "Not crypto")] += value
        largest.append({"symbol": symbol, "value": value, "weight": value / total if total else None})
    largest = sorted(largest, key=lambda row: row["value"], reverse=True)
    exposure = {name: _bucket_percentages(values, total) for name, values in buckets.items()}
    warnings = _exposure_warnings(exposure, largest, missing_metadata)
    plain = _plain_exposure_summary(total, exposure, warnings)
    with closing(connect(db_path)) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO PORTFOLIO_EXPOSURE_SNAPSHOTS (
                    created_at, broker, total_value, exposure_json, warnings_json, plain_english
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    utc_now_iso(),
                    broker.lower() if broker else None,
                    total,
                    json.dumps({"buckets": exposure, "largest_positions": largest}, sort_keys=True, default=str),
                    json.dumps(warnings, sort_keys=True, default=str),
                    plain,
                ),
            )
    return {"total_value": total, "exposure": exposure, "largest_positions": largest, "warnings": warnings, "plain_english": plain}


def correlation_warning(symbols: list[str], return_series: dict[str, list[float]], *, minimum_samples: int = 20) -> dict[str, Any]:
    if len(symbols) < 2:
        return {"status": "insufficient_history", "warning": "At least two assets are required for correlation analysis."}
    pairs: list[dict[str, Any]] = []
    for index, left in enumerate(symbols):
        for right in symbols[index + 1 :]:
            left_series = return_series.get(left, [])
            right_series = return_series.get(right, [])
            sample = min(len(left_series), len(right_series))
            if sample < minimum_samples:
                pairs.append({"symbols": [left, right], "sample_size": sample, "warning": f"Insufficient history for correlation; {minimum_samples} observations required."})
                continue
            corr = _correlation(left_series[-sample:], right_series[-sample:])
            warning = "These assets have recently moved closely together and may provide less diversification than expected." if corr is not None and corr >= 0.75 else "No high-correlation warning."
            pairs.append({"symbols": [left, right], "sample_size": sample, "correlation": corr, "warning": warning})
    return {"status": "complete", "pairs": pairs}


def proposed_trade_portfolio_impact(
    current_exposure: dict[str, Any],
    *,
    symbol: str,
    proposed_notional: float,
    proposed_asset_class: str,
    max_asset_class_weight: float = 0.40,
) -> dict[str, Any]:
    total = _float(current_exposure.get("total_value")) or 0.0
    new_total = total + max(0.0, proposed_notional)
    current_bucket = current_exposure.get("exposure", {}).get("asset_class", {})
    current_value = 0.0
    for label, details in current_bucket.items():
        if label.lower() == proposed_asset_class.lower():
            current_value = _float(details.get("value")) or 0.0
    new_weight = (current_value + proposed_notional) / new_total if new_total else None
    if new_weight is not None and new_weight > max_asset_class_weight:
        decision = "Reject due to concentration"
    elif new_weight is not None and new_weight > max_asset_class_weight * 0.85:
        decision = "Buy smaller"
    else:
        decision = "Acceptable portfolio impact"
    return {
        "symbol": symbol.upper(),
        "decision": decision,
        "new_asset_class_weight": new_weight,
        "plain_english": (
            f"Adding {symbol.upper()} would put {proposed_asset_class} at {_pct(new_weight)} of the measured portfolio."
            if new_weight is not None
            else "Portfolio impact cannot be calculated because total portfolio value is unavailable."
        ),
    }


def _metadata_by_symbol(db_path: Path) -> dict[str, dict[str, Any]]:
    with closing(connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT *
            FROM ASSET_METADATA
            WHERE metadata_id IN (
                SELECT MAX(metadata_id)
                FROM ASSET_METADATA
                GROUP BY symbol
            )
            """
        ).fetchall()
    return {row["symbol"]: dict(row) for row in rows}


def _bucket_percentages(values: dict[str, float], total: float) -> dict[str, dict[str, float | None]]:
    return {
        key: {"value": value, "weight": value / total if total else None}
        for key, value in sorted(values.items(), key=lambda pair: pair[1], reverse=True)
    }


def _exposure_warnings(exposure: dict[str, Any], largest: list[dict[str, Any]], missing: list[str]) -> list[str]:
    warnings: list[str] = []
    for label, details in exposure.get("asset_class", {}).items():
        weight = details.get("weight")
        if weight is not None and weight > 0.40:
            warnings.append(f"{label} represents {_pct(weight)} of measured portfolio value, creating concentration risk.")
    if largest and largest[0].get("weight") is not None and largest[0]["weight"] > 0.25:
        warnings.append(f"{largest[0]['symbol']} is a large position at {_pct(largest[0]['weight'])} of measured portfolio value.")
    if missing:
        warnings.append(f"Metadata is missing for {', '.join(sorted(set(missing))[:5])}; exposure analysis is incomplete.")
    return warnings


def _plain_exposure_summary(total: float, exposure: dict[str, Any], warnings: list[str]) -> str:
    if total <= 0:
        return "Portfolio exposure cannot be calculated because measured position value is unavailable."
    top_asset_class = next(iter(exposure.get("asset_class", {})), "Unknown")
    message = f"Measured portfolio value is {total:.2f}. Largest measured asset-class exposure is {top_asset_class}."
    if warnings:
        message += " Main warning: " + warnings[0]
    return message


def _float(value: Any) -> float | None:
    try:
        if value in {None, ""}:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _correlation(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    numerator = sum((x - left_mean) * (y - right_mean) for x, y in zip(left, right))
    left_var = sum((x - left_mean) ** 2 for x in left)
    right_var = sum((y - right_mean) ** 2 for y in right)
    denominator = math.sqrt(left_var * right_var)
    return numerator / denominator if denominator else None


def _pct(value: float | None) -> str:
    return "unknown" if value is None else f"{value * 100:.1f}%"
