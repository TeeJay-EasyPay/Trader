"""Bounded provider-to-Render daily-bar cache for historical research.

The cache deliberately lives on the application host, not in Supabase.  An initial
backfill is followed by a short overlap refresh; compact screening summaries remain the
only database output.  This module has no broker-order capability.
"""
from __future__ import annotations

from datetime import timedelta
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from . import experiments as e
from .kraken_market_data import fetch_kraken_ohlc

CACHE_VERSION = "provider-daily-bars-v1"
INITIAL_DAYS = 1825
OVERLAP_DAYS = 7
MAX_SYMBOLS = {"alpaca": 20, "kraken": 10}
MAX_BARS_PER_SYMBOL = 2000
MAX_CACHE_BYTES = 64 * 1024 * 1024


def _root(db) -> Path:
    configured = os.getenv("AI_TRADER_RESEARCH_CACHE_DIR")
    if configured:
        base = Path(configured)
    elif os.getenv("RENDER") and Path("/data").is_dir():
        # Use a service's persistent Render disk when it is mounted.  The cache is not
        # database authority and remains safe to rebuild if a service has no disk.
        base = Path("/data/ai-trader-research-cache")
    else:
        base = Path(db).parent / "research-cache"
    return base / CACHE_VERSION


def _path(db, broker: str, symbol: str) -> Path:
    safe = re.sub(r"[^A-Z0-9._-]", "_", symbol.upper())
    return _root(db) / broker / f"{safe}.json"


def _read(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if value.get("cache_version") == CACHE_VERSION else {}
    except (OSError, ValueError, TypeError):
        return {}


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = e.dump(value).encode("utf-8")
    # Calculate against the actual cache root without following arbitrary paths.
    cache_root = path.parents[1]
    total = sum(p.stat().st_size for p in cache_root.rglob("*.json")) if cache_root.exists() else 0
    replaced = path.stat().st_size if path.exists() else 0
    if total - replaced + len(raw) > MAX_CACHE_BYTES:
        raise ValueError("Historical market cache capacity reached")
    temp = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".tmp", delete=False) as handle:
            temp = Path(handle.name)
            handle.write(raw)
        os.replace(temp, path)
    finally:
        if temp is not None and temp.exists():
            temp.unlink()


def _fetch_alpaca(settings, symbol: str, start: str, end: str) -> list[dict]:
    if not settings.alpaca_api_key or not settings.alpaca_secret_key:
        return []
    result, token = [], None
    for _ in range(3):
        params = dict(timeframe="1Day", start=start, end=end, limit=1000,
                      feed="iex", adjustment="raw")
        if token:
            params["page_token"] = token
        url = settings.alpaca_data_base_url.rstrip("/") + f"/v2/stocks/{symbol}/bars?" + urlencode(params)
        request = Request(url, method="GET", headers={"APCA-API-KEY-ID": settings.alpaca_api_key,
                          "APCA-API-SECRET-KEY": settings.alpaca_secret_key})
        with urlopen(request, timeout=20) as response:
            body = response.read(2_000_001)
        if len(body) > 2_000_000:
            raise ValueError("Alpaca historical response budget exceeded")
        payload = json.loads(body)
        result.extend(payload.get("bars") or [])
        token = payload.get("next_page_token")
        if not token:
            break
    return result


def _normalise_alpaca(symbol: str, rows: list[dict], now: str) -> list[dict]:
    bars = []
    for row in rows:
        try:
            start = e.stamp(row["t"]); end = start + timedelta(days=1)
            if end <= e.stamp(now):
                bars.append(dict(symbol=symbol, start=start.isoformat(), end=end.isoformat(),
                    open=e.number(row["o"], .000001, 1_000_000), high=e.number(row["h"], .000001, 1_000_000),
                    low=e.number(row["l"], .000001, 1_000_000), close=e.number(row["c"], .000001, 1_000_000),
                    quality="verified_unadjusted", source="alpaca_raw_iex_daily"))
        except (KeyError, ValueError, TypeError):
            continue
    return bars


def _normalise_kraken(symbol: str, rows: list[dict], now: str) -> list[dict]:
    bars = []
    for row in rows:
        try:
            start = e.stamp(row["observation_time"]); end = start + timedelta(days=1)
            if end <= e.stamp(now):
                bars.append(dict(symbol=symbol, start=start.isoformat(), end=end.isoformat(),
                    open=e.number(row["open"], .000001, 1_000_000), high=e.number(row["high"], .000001, 1_000_000),
                    low=e.number(row["low"], .000001, 1_000_000), close=e.number(row["close"], .000001, 1_000_000),
                    quality="verified_unadjusted", source="kraken_public_exact_gbp_pair"))
        except (KeyError, ValueError, TypeError):
            continue
    return bars


def refresh(db, settings, broker: str, symbols: list[str], now: str) -> dict:
    """Initial backfill once, then only a seven-day overlap for correction safety."""
    if broker not in MAX_SYMBOLS:
        raise ValueError("Unsupported historical market-data broker")
    chosen = [s for s in sorted(set(str(x).upper() for x in symbols))
              if s.isalnum() and (broker != "kraken" or s.endswith("GBP"))][:MAX_SYMBOLS[broker]]
    all_bars, coverage, errors, downloaded = [], [], [], 0
    for symbol in chosen:
        path = _path(db, broker, symbol)
        saved = _read(path)
        old = saved.get("bars") or []
        if saved.get("refreshed_day") == now[:10]:
            fresh = old
        else:
            latest = max((b.get("start", "") for b in old), default="")
            start = ((e.stamp(latest) - timedelta(days=OVERLAP_DAYS)) if latest
                     else (e.stamp(now) - timedelta(days=INITIAL_DAYS))).date().isoformat()
            try:
                if broker == "alpaca":
                    fetched = _normalise_alpaca(symbol, _fetch_alpaca(settings, symbol, start, e.stamp(now).date().isoformat()), now)
                else:
                    fetched = _normalise_kraken(symbol, fetch_kraken_ohlc(symbol, interval_minutes=1440,
                        since=int(e.stamp(start + "T00:00:00+00:00").timestamp())), now)
                downloaded += len(fetched)
                merged = {(b["symbol"], b["start"]): b for b in old}
                merged.update({(b["symbol"], b["start"]): b for b in fetched})
                fresh = sorted(merged.values(), key=lambda b: b["start"])[-MAX_BARS_PER_SYMBOL:]
                _write(path, dict(cache_version=CACHE_VERSION, broker=broker, symbol=symbol,
                    refreshed_day=now[:10], refreshed_at=now, bars=fresh))
            except Exception as exc:  # one unavailable symbol never blocks the batch
                fresh = old
                errors.append(dict(symbol=symbol, error_type=type(exc).__name__))
        all_bars.extend(fresh)
        coverage.append(dict(symbol=symbol, bars=len(fresh),
            first=fresh[0]["start"] if fresh else None, last=fresh[-1]["start"] if fresh else None))
    return dict(broker=broker, status="partial" if errors else "completed", symbols=len(chosen),
                bars=all_bars, downloaded=downloaded, coverage=coverage, errors=errors,
                storage="render_research_cache", supabase_rows_written=0, cache_version=CACHE_VERSION)
