"""Real Kraken OHLC candle history -- Phase 1 of the CIO-level forecasting build
(2026-08-20, Founder-directed). Crypto has never had multi-point price history
anywhere in this codebase before this module; every existing Kraken price read
(KrakenAdapter.current_prices, `/0/public/Ticker`) is a single snapshot. This
is a self-contained new integration against Kraken's real, public, no-auth-
required OHLC endpoint -- not a research problem, a straightforward fetch.

Interval is expressed in minutes, matching Kraken's own `interval` query
parameter (Kraken only accepts specific values: 1, 5, 15, 30, 60, 240, 1440,
10080, 21600 -- anything else is silently rounded down by Kraken's API, so
callers should stick to those).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any
from urllib import parse, request

KRAKEN_OHLC_INTERVALS_MINUTES = (1, 5, 15, 30, 60, 240, 1440, 10080, 21600)


def _iso_from_epoch(value: Any) -> str | None:
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def fetch_kraken_ohlc(pair: str, *, interval_minutes: int = 1440, since: int | None = None) -> list[dict[str, Any]]:
    """Fetch real OHLC candles for one Kraken pair.

    Returns candles oldest-first, each shaped for market_intelligence_platform's
    record_market_observations (`observation_time`/`open`/`high`/`low`/`close`/`volume`
    keys). Kraken's own response includes the still-forming, not-yet-closed current
    candle as its last element -- dropped here (matches this codebase's existing
    Kraken exit/entry code, which never treats an in-progress candle as settled data).
    """
    base_url = os.getenv("KRAKEN_BASE_URL", "https://api.kraken.com")
    params = {"pair": pair, "interval": str(interval_minutes)}
    if since is not None:
        params["since"] = str(since)
    query = parse.urlencode(params)
    with request.urlopen(f"{base_url}/0/public/OHLC?{query}", timeout=20) as response:
        data = json.loads(response.read().decode("utf-8"))
    if data.get("error"):
        raise RuntimeError("; ".join(data["error"]))
    result = data.get("result") or {}
    rows = next((value for key, value in result.items() if key != "last"), None) or []
    # Kraken always includes the still-forming, not-yet-closed current interval as the
    # last row -- drop it unconditionally (matches the codebase's convention elsewhere
    # of never treating an in-progress bar as settled data), not just when len(rows) > 1.
    candles: list[dict[str, Any]] = []
    for row in rows[:-1]:
        if len(row) < 7:
            continue
        observation_time = _iso_from_epoch(row[0])
        if observation_time is None:
            continue
        candles.append(
            {
                "observation_time": observation_time,
                "open": row[1],
                "high": row[2],
                "low": row[3],
                "close": row[4],
                "volume": row[6],
                "vwap": row[5],
                "trade_count": row[7] if len(row) > 7 else None,
            }
        )
    return candles
