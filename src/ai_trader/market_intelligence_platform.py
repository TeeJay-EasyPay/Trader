from __future__ import annotations

import json
import sqlite3
from .database import connect
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .models import utc_now_iso


MARKET_INTELLIGENCE_SCHEMA = """
CREATE TABLE IF NOT EXISTS MARKET_DATA_OBSERVATIONS (
    observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    provider TEXT NOT NULL,
    original_symbol TEXT NOT NULL,
    normalized_symbol TEXT NOT NULL,
    exchange TEXT,
    asset_type TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    observation_time TEXT NOT NULL,
    retrieval_time TEXT NOT NULL,
    freshness TEXT NOT NULL,
    completeness TEXT NOT NULL,
    adjusted_status TEXT NOT NULL,
    source_quality_status TEXT NOT NULL,
    payload_provenance TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume REAL,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS MARKET_DATA_QUALITY_EVENTS (
    quality_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    provider TEXT,
    normalized_symbol TEXT,
    timeframe TEXT,
    severity TEXT NOT NULL,
    issue_type TEXT NOT NULL,
    explanation TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS MULTI_TIMEFRAME_INTELLIGENCE (
    intelligence_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    normalized_symbol TEXT NOT NULL,
    asset_type TEXT NOT NULL,
    conclusion TEXT NOT NULL,
    supporting_evidence_json TEXT NOT NULL,
    contradictory_evidence_json TEXT NOT NULL,
    data_quality_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS FUNDAMENTAL_EVIDENCE (
    evidence_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    normalized_symbol TEXT NOT NULL,
    source TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    metric_value TEXT,
    source_timestamp TEXT,
    confidence TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS MACRO_EVENT_EVIDENCE (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    event_type TEXT NOT NULL,
    affected_asset TEXT,
    event_time TEXT,
    time_until_event TEXT,
    potential_impact TEXT NOT NULL,
    uncertainty_level TEXT NOT NULL,
    source TEXT,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS NEWS_CATALYST_EVIDENCE (
    catalyst_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    normalized_symbol TEXT,
    source TEXT NOT NULL,
    source_timestamp TEXT,
    credibility_level TEXT NOT NULL,
    catalyst_type TEXT NOT NULL,
    relevance TEXT NOT NULL,
    expected_duration TEXT,
    confirmed_fact TEXT,
    market_commentary TEXT,
    analyst_opinion TEXT,
    rumour TEXT,
    opposing_interpretation TEXT,
    cluster_key TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    UNIQUE(normalized_symbol, cluster_key, source_timestamp)
);

CREATE TABLE IF NOT EXISTS MARKET_REGIME_EVIDENCE (
    regime_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    scope TEXT NOT NULL,
    primary_regime TEXT NOT NULL,
    confidence TEXT NOT NULL,
    supporting_evidence_json TEXT NOT NULL,
    contradictory_evidence_json TEXT NOT NULL,
    data_quality_json TEXT NOT NULL,
    plain_english TEXT NOT NULL
);
"""


def initialize_market_intelligence_schema(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect(db_path)) as conn:
        with conn:
            conn.executescript(MARKET_INTELLIGENCE_SCHEMA)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_mdo_symbol_time ON MARKET_DATA_OBSERVATIONS(normalized_symbol, timeframe, observation_time)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_mq_symbol ON MARKET_DATA_QUALITY_EVENTS(normalized_symbol, issue_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_news_cluster ON NEWS_CATALYST_EVIDENCE(normalized_symbol, cluster_key)")


def validate_candles(candles: list[dict[str, Any]], *, stale_after_minutes: int = 1440) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    seen_times: set[str] = set()
    last_time: datetime | None = None
    now = datetime.now(timezone.utc)
    valid_count = 0
    for candle in candles:
        observed = str(candle.get("observation_time") or candle.get("time") or candle.get("timestamp") or "")
        opened = _float(candle.get("open"))
        high = _float(candle.get("high"))
        low = _float(candle.get("low"))
        close = _float(candle.get("close"))
        volume = _float(candle.get("volume"))
        parsed_time = _parse_dt(observed)
        if observed in seen_times:
            issues.append({"issue_type": "duplicate_candle", "explanation": f"Duplicate candle at {observed}."})
        seen_times.add(observed)
        if parsed_time and last_time and parsed_time < last_time:
            issues.append({"issue_type": "time_order_error", "explanation": "Candles are not in chronological order."})
        if parsed_time:
            last_time = parsed_time
        if None in {opened, high, low, close}:
            issues.append({"issue_type": "incomplete_ohlc", "explanation": "Open, high, low, or close is missing."})
            continue
        if high < max(opened, low, close) or low > min(opened, high, close):
            issues.append({"issue_type": "impossible_ohlc", "explanation": "OHLC values are internally inconsistent."})
        if volume is not None and volume < 0:
            issues.append({"issue_type": "negative_volume", "explanation": "Volume cannot be negative."})
        valid_count += 1
    if not candles:
        issues.append({"issue_type": "missing_data", "explanation": "No candles were supplied."})
    elif last_time and now - last_time > timedelta(minutes=stale_after_minutes):
        issues.append({"issue_type": "stale_data", "explanation": "Latest candle is older than the freshness threshold."})
    severity = "pass" if not issues else "reject" if any(item["issue_type"] in {"impossible_ohlc", "negative_volume", "missing_data"} for item in issues) else "warn"
    return {
        "severity": severity,
        "valid_candles": valid_count,
        "issues": issues,
        "freshness": "fresh" if severity == "pass" else "requires_review",
        "completeness": "complete" if valid_count == len(candles) and candles else "incomplete",
        "plain_english": "Market data is usable." if severity == "pass" else "; ".join(item["explanation"] for item in issues[:4]),
    }


def record_market_observations(
    db_path: Path,
    *,
    provider: str,
    original_symbol: str,
    normalized_symbol: str,
    exchange: str | None,
    asset_type: str,
    timeframe: str,
    candles: list[dict[str, Any]],
    adjusted_status: str = "unknown",
    payload_provenance: str = "provider_api",
) -> dict[str, Any]:
    initialize_market_intelligence_schema(db_path)
    quality = validate_candles(candles)
    with closing(connect(db_path)) as conn:
        with conn:
            for issue in quality["issues"]:
                conn.execute(
                    """
                    INSERT INTO MARKET_DATA_QUALITY_EVENTS (
                        created_at, provider, normalized_symbol, timeframe, severity,
                        issue_type, explanation, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        utc_now_iso(),
                        provider,
                        normalized_symbol.upper(),
                        timeframe,
                        quality["severity"],
                        issue["issue_type"],
                        issue["explanation"],
                        json.dumps(issue, sort_keys=True),
                    ),
                )
            for candle in candles:
                observation_time = str(candle.get("observation_time") or candle.get("time") or candle.get("timestamp") or utc_now_iso())
                conn.execute(
                    """
                    INSERT INTO MARKET_DATA_OBSERVATIONS (
                        created_at, provider, original_symbol, normalized_symbol, exchange,
                        asset_type, timeframe, observation_time, retrieval_time, freshness,
                        completeness, adjusted_status, source_quality_status, payload_provenance,
                        open, high, low, close, volume, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        utc_now_iso(),
                        provider,
                        original_symbol,
                        normalized_symbol.upper(),
                        exchange,
                        asset_type,
                        timeframe,
                        observation_time,
                        utc_now_iso(),
                        quality["freshness"],
                        quality["completeness"],
                        adjusted_status,
                        quality["severity"],
                        payload_provenance,
                        _float(candle.get("open")),
                        _float(candle.get("high")),
                        _float(candle.get("low")),
                        _float(candle.get("close")),
                        _float(candle.get("volume")),
                        json.dumps(candle, sort_keys=True, default=str),
                    ),
                )
    return quality


def multi_timeframe_conclusion(timeframes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    supporting: list[str] = []
    contradictory: list[str] = []
    quality: dict[str, str] = {}
    trend_labels: dict[str, str] = {}
    for timeframe, evidence in timeframes.items():
        trend = str(evidence.get("trend") or "unknown").lower()
        momentum = str(evidence.get("momentum") or "unknown").lower()
        quality[timeframe] = str(evidence.get("data_quality") or "unknown")
        trend_labels[timeframe] = trend
        if trend in {"up", "positive", "bullish"}:
            supporting.append(f"{timeframe} trend is positive.")
        elif trend in {"down", "negative", "bearish"}:
            contradictory.append(f"{timeframe} trend is negative.")
        if momentum in {"weakening", "negative", "bearish"}:
            contradictory.append(f"{timeframe} momentum is weakening.")
    if not timeframes:
        conclusion = "Insufficient evidence across timeframes."
    elif supporting and contradictory:
        conclusion = "Timeframes disagree: longer or shorter horizons are not pointing the same way."
    elif supporting:
        conclusion = "Multiple timeframes lean positive, subject to data quality."
    elif contradictory:
        conclusion = "Multiple timeframes lean negative or uncertain."
    else:
        conclusion = "Timeframes are mostly neutral or insufficient."
    return {
        "conclusion": conclusion,
        "supporting_evidence": supporting,
        "contradictory_evidence": contradictory,
        "data_quality": quality,
        "plain_english": conclusion,
    }


def infer_regime_2_0(
    *,
    multi_timeframe: dict[str, Any],
    volatility: str = "unknown",
    breadth: str = "unknown",
    liquidity: str = "unknown",
    macro: str = "unknown",
    crypto_risk: str = "unknown",
) -> dict[str, Any]:
    supporting = list(multi_timeframe.get("supporting_evidence") or [])
    contradictory = list(multi_timeframe.get("contradictory_evidence") or [])
    if volatility in {"high", "volatile"}:
        contradictory.append("Volatility is elevated.")
    if liquidity in {"weak", "thin"}:
        contradictory.append("Liquidity is weak.")
    if macro in {"supportive"}:
        supporting.append("Macro backdrop is supportive.")
    elif macro in {"hostile", "risk_off"}:
        contradictory.append("Macro backdrop is hostile.")
    if not supporting and not contradictory:
        regime = "Insufficient evidence"
    elif supporting and not contradictory and volatility not in {"high", "volatile"}:
        regime = "Strong upward trend"
    elif supporting and contradictory:
        regime = "Transition and uncertainty"
    elif contradictory and volatility in {"high", "volatile"}:
        regime = "Sideways and volatile"
    else:
        regime = "Risk-off decline"
    return {
        "primary_regime": regime,
        "confidence": "medium" if supporting or contradictory else "low",
        "supporting_evidence": supporting,
        "contradictory_evidence": contradictory,
        "data_quality": {
            "multi_timeframe": multi_timeframe.get("data_quality") or {},
            "breadth": breadth,
            "liquidity": liquidity,
            "macro": macro,
            "crypto_risk": crypto_risk,
        },
        "plain_english": f"Current regime: {regime}. Supporting and opposing evidence are both shown so the Founder can see uncertainty.",
    }


def _float(value: Any) -> float | None:
    try:
        if value in {None, ""}:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_dt(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed
