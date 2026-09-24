"""Point-in-time market-rule opportunities for historical development screening.

These are deliberately labelled synthetic research opportunities.  They do not recreate
an AI opinion, another trader, news, fundamentals or permission that did not exist.  Each
decision uses only bars available at that timestamp, and every candidate must still pass a
fresh prospective shadow experiment before it can be recommended.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any


RULE_VERSION = "frozen-price-trend-opportunity-v1"
LOOKBACK = 20
MOMENTUM_DAYS = 5
ATR_DAYS = 14
MAX_PER_SYMBOL = 96


def generate(bars: list[dict[str, Any]], broker: str, *, limit: int = 480) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for bar in bars:
        if bar.get("quality") == "verified_unadjusted" and bar.get("symbol"):
            grouped[str(bar["symbol"]).upper()].append(bar)
    signals: list[dict[str, Any]] = []
    for symbol, series in sorted(grouped.items()):
        ordered = sorted(series, key=lambda item: item["start"])
        own: list[dict[str, Any]] = []
        for index in range(LOOKBACK, len(ordered) - 1):
            current = ordered[index]
            history = ordered[: index + 1]
            try:
                close = float(current["close"])
                prior_closes = [float(item["close"]) for item in history[-LOOKBACK:]]
                sma = sum(prior_closes) / len(prior_closes)
                momentum_reference = float(history[-(MOMENTUM_DAYS + 1)]["close"])
                atr = _atr(history[-(ATR_DAYS + 1):])
            except (KeyError, TypeError, ValueError, ZeroDivisionError):
                continue
            if close <= 0 or momentum_reference <= 0 or atr is None:
                continue
            # This is the frozen, market-only opportunity rule: positive 20-bar trend and
            # positive five-bar momentum. It is intentionally simpler than Trader's live
            # decision and is never presented as a reconstructed AI recommendation.
            eligible = close > sma and close > momentum_reference
            minimum = 0.015 if broker == "kraken" else 0.01
            stop_pct = max(minimum, min(0.05, 0.6 * atr / close))
            stop = close * (1 - stop_pct)
            target = close * (1 + 2 * stop_pct)
            own.append({
                "source_id": f"{RULE_VERSION}:{broker}:{symbol}:{current['start'][:10]}",
                "symbol": symbol,
                "time": current["end"],
                "entry": close,
                "stop": stop,
                "target": target,
                "eligible": eligible,
                "rejection_reasons": [] if eligible else ["frozen_price_trend_not_positive"],
                "evidence_kind": "synthetic_point_in_time_market_rule",
                "rule_version": RULE_VERSION,
            })
        # Preserve broad time coverage rather than retaining only the newest cluster.
        if len(own) > MAX_PER_SYMBOL:
            step = (len(own) - 1) / (MAX_PER_SYMBOL - 1)
            own = [own[round(i * step)] for i in range(MAX_PER_SYMBOL)]
        signals.extend(own)
    return sorted(signals, key=lambda item: (item["time"], item["symbol"]))[:limit]


def _atr(series: list[dict[str, Any]]) -> float | None:
    if len(series) < ATR_DAYS + 1:
        return None
    ranges = []
    for previous, current in zip(series[-(ATR_DAYS + 1):-1], series[-ATR_DAYS:]):
        prior_close = float(previous["close"])
        high, low = float(current["high"]), float(current["low"])
        ranges.append(max(high - low, abs(high - prior_close), abs(low - prior_close)))
    return sum(ranges) / len(ranges) if ranges else None
