"""Real, CIO-level market forecasting -- Phase 3 of the forecasting build
(2026-08-20, Founder-directed).

The Founder rejected the previous "Forecast Centre" outright: it averaged the AI's own
past closed trades and projected that forward. In his words -- "that's not forecasting...
forecasting is about planning, looking at market trends, looking at whether there is a
bull run coming or not."

This module assembles genuine market evidence (multi-timeframe technical analysis over
real price history, detected regime, macro/news context, curated reference material) and
asks an LLM to reason over it like a Chief Investment Officer would.

ANTI-CIRCULARITY RULE (the Founder explicitly accepted this framing when approving the
build): a forecast must NEVER be derived from, or even shown, the AI's own trade P&L or
win rate. Feeding a model its own past results and calling the output a market forecast
is self-referential -- it reinforces whatever pattern it already had on no new
information. Every field build_forecast_evidence() emits traces back to real market data.
tests/test_forecasting.py has a permanent regression test asserting no
performance/P&L-derived key can reach the prompt.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .database import connect
from .knowledge_base import relevant_excerpts
from .market_intelligence_platform import (
    initialize_market_intelligence_schema,
    load_recent_observations,
)
from .models import utc_now_iso
from .trading_intelligence import analyze_price_series, load_recent_candles

# Any evidence key containing one of these is a trade-performance signal, never a market
# signal -- see the anti-circularity rule in this module's docstring. Enforced by
# _assert_no_performance_data() below, which runs on every real forecast call.
_FORBIDDEN_EVIDENCE_MARKERS = (
    "pnl",
    "profit",
    "win_rate",
    "winrate",
    "realized",
    "realised",
    "expectancy",
    "closed_trade",
    "trade_history",
    "performance",
    "attribution",
)


def _float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result


def resample_weekly(candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate daily candles into weekly OHLC, oldest-first.

    A single 20-day window can only ever describe the last month; judging whether a
    genuine multi-week trend (a "bull run", in the Founder's words) is underway needs a
    second, slower timeframe. Computed in memory from the daily history already stored --
    deliberately no new table, no second data fetch.
    """
    buckets: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    for candle in candles:
        stamp = str(candle.get("observation_time") or candle.get("observed_at") or "")
        parsed = _parse_dt(stamp)
        if parsed is None:
            continue
        # ISO week is the natural bucket and handles year boundaries correctly, unlike
        # naive day-index arithmetic.
        iso_year, iso_week, _ = parsed.isocalendar()
        key = f"{iso_year}-W{iso_week:02d}"
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(candle)
    weekly: list[dict[str, Any]] = []
    for key in order:
        group = buckets[key]
        opens = [_float(item.get("open")) for item in group]
        highs = [value for value in (_float(item.get("high")) for item in group) if value is not None]
        lows = [value for value in (_float(item.get("low")) for item in group) if value is not None]
        closes = [_float(item.get("close")) for item in group]
        volumes = [value for value in (_float(item.get("volume")) for item in group) if value is not None]
        first_open = next((value for value in opens if value is not None), None)
        last_close = next((value for value in reversed(closes) if value is not None), None)
        if last_close is None:
            continue
        weekly.append(
            {
                "observation_time": key,
                "open": first_open,
                "high": max(highs) if highs else None,
                "low": min(lows) if lows else None,
                "close": last_close,
                "volume": sum(volumes) if volumes else None,
            }
        )
    return weekly


def _parse_dt(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _load_candles(db_path: Path, *, symbol: str, asset_type: str, limit: int = 200) -> list[dict[str, Any]]:
    """Real stored price history for either asset class, normalized to one shape.

    Equities and crypto have genuinely separate stores (HISTORICAL_CANDLES vs
    MARKET_DATA_OBSERVATIONS, populated by different providers) -- this is the one place
    that difference is resolved, so nothing downstream needs to know which broker a
    symbol belongs to.
    """
    if asset_type.lower() == "crypto":
        return load_recent_observations(db_path, symbol, timeframe="1d", limit=limit)
    return load_recent_candles(db_path, symbol=symbol, asset_type="stock", timeframe="1d", limit=limit)


def _macro_and_news_context(db_path: Path, *, symbol: str | None) -> list[str]:
    """Best-effort macro/news/regime context. Any query failure degrades to fewer lines,
    never raises -- external intelligence being unavailable must never block a forecast
    (same convention as proposal_context.py's _serialize_external_intelligence)."""
    lines: list[str] = []
    queries: list[tuple[str, tuple[Any, ...]]] = [
        (
            "SELECT primary_regime, confidence, plain_english FROM MARKET_REGIME_EVIDENCE "
            "WHERE scope = 'global' ORDER BY regime_id DESC LIMIT 1",
            (),
        ),
        (
            "SELECT event_type, potential_impact, uncertainty_level FROM MACRO_EVENT_EVIDENCE "
            "ORDER BY event_id DESC LIMIT 3",
            (),
        ),
    ]
    if symbol:
        queries.append(
            (
                "SELECT market_commentary, source_timestamp FROM NEWS_CATALYST_EVIDENCE "
                "WHERE normalized_symbol = ? ORDER BY created_at DESC LIMIT 3",
                (symbol.upper(),),
            )
        )
    for sql, params in queries:
        try:
            with closing(connect(db_path)) as conn:
                conn.row_factory = sqlite3.Row
                for row in conn.execute(sql, params).fetchall():
                    lines.append("; ".join(f"{key}={row[key]}" for key in row.keys() if row[key] is not None))
        except Exception:  # noqa: BLE001 - context is additive; its absence must never block a forecast
            continue
    return [line for line in lines if line]


def _assert_no_performance_data(evidence: dict[str, Any]) -> None:
    """Hard guard for this module's anti-circularity rule (see module docstring).

    Checks structural KEYS only, recursively -- never free text. Curated reference
    material legitimately discusses profit-taking (knowledge/stop_loss_and_take_profit_
    mechanics.md is literally about it), and news commentary routinely mentions earnings
    or performance; scanning serialized values would false-positive on all of that while
    catching nothing a key check misses. The actual risk being guarded against is
    someone wiring a real trade-results field (realized_pnl, win_rate, closed_trade_
    history...) into this payload, and such data always arrives under a named key.

    Raises rather than silently stripping: that would mean trade results had been wired
    into the forecast path, exactly the failure the Founder flagged when approving this
    build. It should fail loudly in tests and development, not be quietly papered over.
    """

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                key_text = str(key).lower()
                for marker in _FORBIDDEN_EVIDENCE_MARKERS:
                    if marker in key_text:
                        raise ValueError(
                            f"Forecast evidence key {path + '.' + str(key)!r} contains a trade-performance marker "
                            f"({marker!r}). A market forecast must never be derived from the AI's own trade results "
                            "-- see forecasting.py's anti-circularity rule."
                        )
                walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for index, item in enumerate(node):
                walk(item, f"{path}[{index}]")

    walk(evidence, "evidence")


def build_forecast_evidence(db_path: Path, *, symbol: str | None, asset_type: str) -> dict[str, Any]:
    """Assemble real market evidence for one symbol (or the portfolio-wide view).

    Everything here is market data or curated reference text. Nothing about the AI's own
    trading results is loaded, by design -- _assert_no_performance_data enforces it.
    """
    daily = _load_candles(db_path, symbol=symbol, asset_type=asset_type) if symbol else []
    weekly = resample_weekly(daily)
    daily_metrics = analyze_price_series(daily) if daily else {}
    weekly_metrics = analyze_price_series(weekly) if weekly else {}
    excerpts = relevant_excerpts(asset_type=asset_type, topics=["trend", "momentum", "risk"], limit=2)
    evidence = {
        "symbol": symbol,
        "asset_type": asset_type,
        "daily": {
            "candles_available": len(daily),
            "latest_close": (_float(daily[-1].get("close")) if daily else None),
            "metrics": daily_metrics,
        },
        "weekly": {
            "periods_available": len(weekly),
            "metrics": weekly_metrics,
        },
        "macro_and_news": _macro_and_news_context(db_path, symbol=symbol),
        # Trimmed to 600 chars: this is a reminder of the relevant principle, not the
        # whole document, and a live 2026-08-20 verification run timed out against the
        # model with larger excerpts. The full text stays available via the knowledge
        # base itself for anything that needs it.
        "reference_material": [
            {"title": item.get("title"), "excerpt": str(item.get("excerpt") or "")[:600]}
            for item in excerpts
        ],
    }
    _assert_no_performance_data(evidence)
    return evidence


def record_forecast(
    db_path: Path,
    *,
    scope: str,
    symbol: str | None,
    asset_type: str,
    forecast: dict[str, Any],
    evidence: dict[str, Any],
    generated_by: str,
) -> int:
    initialize_market_intelligence_schema(db_path)
    horizon_days = int(forecast["horizon_days"])
    expires_at = (datetime.now(timezone.utc) + timedelta(days=horizon_days)).isoformat()
    payload = {
        "evidence": evidence,
        "supporting_evidence": forecast.get("supporting_evidence") or [],
        "contradictory_evidence": forecast.get("contradictory_evidence") or [],
        "key_risks": forecast.get("key_risks") or [],
    }
    with closing(connect(db_path)) as conn:
        with conn:
            cursor = conn.execute(
                """
                INSERT INTO FORECAST_RECORDS (
                    created_at, scope, symbol, asset_type, direction, horizon_days,
                    confidence, reasoning, invalidation, evidence_json, generated_by, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    utc_now_iso(),
                    scope,
                    symbol.upper() if symbol else None,
                    asset_type,
                    forecast["direction"],
                    horizon_days,
                    float(forecast["confidence"]),
                    forecast["reasoning"],
                    forecast.get("invalidation") or None,
                    json.dumps(payload, sort_keys=True, default=str),
                    generated_by,
                    expires_at,
                ),
            )
            return int(cursor.lastrowid or 0)


def latest_forecast(db_path: Path, *, symbol: str | None = None, scope: str = "symbol") -> dict[str, Any] | None:
    """Most recent forecast for this symbol/scope, or None when there isn't one.

    Deliberately does not filter on expires_at: an expired forecast is still real
    evidence of what was believed and when, and callers that care about staleness can
    compare created_at/expires_at themselves rather than silently getting nothing back.
    """
    initialize_market_intelligence_schema(db_path)
    with closing(connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        if symbol:
            row = conn.execute(
                "SELECT * FROM FORECAST_RECORDS WHERE scope = ? AND symbol = ? ORDER BY forecast_id DESC LIMIT 1",
                (scope, symbol.upper()),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM FORECAST_RECORDS WHERE scope = ? ORDER BY forecast_id DESC LIMIT 1",
                (scope,),
            ).fetchone()
    return dict(row) if row else None


def recent_forecasts(db_path: Path, *, limit: int = 25) -> list[dict[str, Any]]:
    initialize_market_intelligence_schema(db_path)
    with closing(connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM FORECAST_RECORDS ORDER BY forecast_id DESC LIMIT ?",
            (max(1, int(limit)),),
        ).fetchall()
    return [dict(row) for row in rows]


def generate_market_forecast(
    db_path: Path,
    *,
    analyzer: Any,
    symbol: str | None,
    asset_type: str,
    scope: str = "symbol",
    minimum_candles: int = 20,
) -> dict[str, Any]:
    """Build real evidence, ask the analyzer for a CIO-style view, and persist it.

    Returns an honest status dict rather than raising. `insufficient_evidence` when there
    genuinely isn't enough price history to say anything real -- reporting that is the
    correct answer, not a reason to manufacture a low-confidence guess (this codebase's
    established standard, see forecastEngine.js's MIN_SAMPLE_SIZE handling for the same
    principle applied on the mobile side).
    """
    evidence = build_forecast_evidence(db_path, symbol=symbol, asset_type=asset_type)
    candles_available = int(evidence["daily"]["candles_available"])
    if candles_available < minimum_candles:
        return {
            "status": "insufficient_evidence",
            "symbol": symbol,
            "reason": f"Only {candles_available} daily candle(s) of real price history are stored; at least {minimum_candles} are needed for a genuine technical read.",
        }
    if analyzer is None:
        return {"status": "not_available", "symbol": symbol, "reason": "No forecast analyzer is configured (OPENAI_API_KEY is required)."}
    try:
        forecast = analyzer.forecast(scope=scope, symbol=symbol, asset_type=asset_type, evidence=evidence)
    except Exception as exc:  # noqa: BLE001 - one symbol's model/network failure must never abort a batch
        return {"status": "failed", "symbol": symbol, "reason": str(exc)}
    if not forecast:
        return {"status": "no_usable_forecast", "symbol": symbol, "reason": "The model did not return a usable, in-range forecast."}
    forecast_id = record_forecast(
        db_path,
        scope=scope,
        symbol=symbol,
        asset_type=asset_type,
        forecast=forecast,
        evidence=evidence,
        generated_by=getattr(analyzer, "model", "unknown"),
    )
    return {"status": "completed", "symbol": symbol, "forecast_id": forecast_id, **forecast}
