from __future__ import annotations

import json
import os
from typing import Any

from ..operational import safe_float

"""Phase 9 (architecture/AI_TRADER_MODULARISATION_ARCHITECTURE_2026-08-02.md): the seven
small, pure, side-effect-free helpers that Phases 3-6a each independently duplicated
verbatim into their own application/*.py file to avoid a circular import (every service
file imports at module load time, before api/__init__.py's own later-defined functions
exist yet). Consolidated here into one dependency-free leaf module every application/*.py
file can import from directly -- this file imports nothing from any application/* module
and nothing application/* files don't already depend on, so it introduces no cycle.

Verified byte-for-byte identical across every prior duplicate before consolidating -- no
behaviour change, no formatting change, this is a pure move.
"""


def _broker_label(broker: str) -> str:
    labels = {
        "alpaca": "Alpaca",
        "kraken": "Kraken",
        "coinbase": "Coinbase",
        "binance": "Binance",
        "interactive_brokers": "Interactive Brokers",
    }
    return labels.get(broker.lower(), broker.replace("_", " ").title())


def _money_text(value: Any) -> str:
    number = safe_float(value)
    if number is None:
        return "Not available"
    return f"{number:,.2f}"


def _estimated_in_positions(portfolio_value: Any, cash: Any) -> float | None:
    portfolio_number = safe_float(portfolio_value)
    cash_number = safe_float(cash)
    if portfolio_number is None or cash_number is None:
        return None
    return portfolio_number - cash_number


def _broker_trade_payload(row: dict[str, Any]) -> dict[str, Any]:
    payload = row.get("payload_json")
    if not payload:
        return {}
    try:
        parsed = json.loads(payload)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


def _broker_trade_symbol(row: dict[str, Any]) -> str | None:
    payload = _broker_trade_payload(row)
    value = row.get("symbol") or payload.get("symbol") or payload.get("pair")
    return str(value).upper() if value else None


def _int_or_default(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _csv_env(key: str, default: str) -> list[str]:
    value = os.getenv(key, default)
    return [item.strip().upper() for item in value.split(",") if item.strip()]
