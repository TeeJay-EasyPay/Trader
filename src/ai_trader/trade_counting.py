"""One definition of "a trade", so every screen reports the same number.

2026-08-27, Founder-reported from the live app. On one day, four surfaces described the same
activity with four different numbers:

    Executive Briefing   "13 share trades placed today"
    Executive Briefing   "submitted 5 orders"          (since your last visit)
    Executive Briefing   "24 orders were actually submitted"
    Portfolio            "Completed today (since midnight)  19"

The true answer was **6**. The whole day was four symbols: SCCO, VMC, NEE and MLM.

Every one of those figures was counting something real, just not the thing its label claimed:

  * Brokers record one row per order EVENT, so a single bracketed buy produces `new`, `held`,
    `partial_fill` (often several), `fill` and `filled` -- up to seven rows for one decision.
    Counting rows counts paperwork.
  * BROKER_TRADE_HISTORY.external_id is unique per EVENT, not per order, so the existing
    "distinct orders" helper counted 22 where there were 12. The broker's own order id lives
    inside payload_json.
  * A bracket order attaches protective stop-loss and take-profit legs the moment the entry
    fills. They are recorded as `new`/`held` sell orders. Counting them as trades reports
    decisions the app never made -- on this day, 6 of the 12 orders were unfired protective
    legs.

So a trade, as a Founder means it, is: **one distinct broker order that actually got a fill.**
Not an event. Not a resting protective leg. That definition lives here, once, and every
surface reads it rather than re-deriving its own.
"""

from __future__ import annotations

import json
from typing import Any, Iterable

# Statuses that mean the broker actually traded some of this order.
FILLED_STATUSES = {"fill", "filled", "partial_fill", "partially_filled", "closed", "done"}

# Where a broker's real order id hides, in preference order. The last two are the row's own
# columns, used only when the payload carries nothing better.
_ORDER_ID_KEYS = (
    "broker_order_id", "order_id", "orderId", "id", "txid", "ordertxid",
    "client_order_id", "clientOrderId",
)


def _payload(row: dict[str, Any]) -> dict[str, Any]:
    for key in ("payload_json", "payload", "raw"):
        value = row.get(key)
        if isinstance(value, dict):
            return value
        if isinstance(value, str) and value:
            try:
                parsed = json.loads(value)
            except (TypeError, ValueError):
                continue
            if isinstance(parsed, dict):
                return parsed
    return {}


def broker_order_key(row: dict[str, Any]) -> str:
    """The broker's own order id for this event row.

    Falls back to external_id and then to the row's identity, so a row carrying no usable id
    is counted once on its own rather than silently merged with unrelated rows -- under-counting
    real activity would be a worse failure than over-counting by one.
    """
    payload = _payload(row)
    for source in (payload, row):
        for key in _ORDER_ID_KEYS:
            value = source.get(key)
            if isinstance(value, list) and value:
                value = value[0]
            if value not in (None, ""):
                return str(value)
    external = row.get("external_id")
    if external not in (None, ""):
        return str(external)
    return f"row:{id(row)}"


def _status(row: dict[str, Any]) -> str:
    return str(row.get("status") or _payload(row).get("status") or "").lower()


def _side(row: dict[str, Any]) -> str:
    payload = _payload(row)
    descr = payload.get("descr") if isinstance(payload.get("descr"), dict) else {}
    return str(row.get("side") or payload.get("side") or payload.get("type") or descr.get("type") or "").lower()


def group_orders(rows: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Collapse event rows into one entry per real broker order."""
    orders: dict[str, dict[str, Any]] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        key = broker_order_key(row)
        order = orders.setdefault(key, {"symbol": None, "side": "", "statuses": set(), "rows": 0})
        order["rows"] += 1
        order["statuses"].add(_status(row))
        if not order["symbol"]:
            order["symbol"] = row.get("symbol") or _payload(row).get("symbol")
        if not order["side"]:
            order["side"] = _side(row)
    return orders


def count_trades(rows: Iterable[dict[str, Any]], *, side: str | None = None) -> int:
    """Distinct broker orders that actually got a fill -- the Founder-facing "trades" figure.

    `side` narrows to entries ("buy") or exits ("sell") when a caller genuinely means one of
    them; leaving it None counts both, which is what "trades placed today" means.
    """
    total = 0
    for order in group_orders(rows).values():
        if not (order["statuses"] & FILLED_STATUSES):
            continue
        if side is not None and order["side"] != side.lower():
            continue
        total += 1
    return total


def count_orders_submitted(rows: Iterable[dict[str, Any]]) -> int:
    """Distinct broker orders submitted, filled or not, excluding nothing.

    Deliberately separate from count_trades. "Submitted" legitimately includes a resting
    protective leg; "traded" does not. Two honest numbers that measure different things beat
    one number used for both, which is how the four contradictory figures arose.
    """
    return len(group_orders(rows))


def count_events(rows: Iterable[dict[str, Any]]) -> int:
    """Raw event rows. Only ever label this "events", never "trades" or "orders"."""
    return sum(1 for row in rows or [] if isinstance(row, dict))


def trade_count_breakdown(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Every figure at once, so a caller cannot accidentally mix definitions."""
    orders = group_orders(rows)
    filled = [o for o in orders.values() if o["statuses"] & FILLED_STATUSES]
    return {
        "trades": len(filled),
        "entries": len([o for o in filled if o["side"] == "buy"]),
        "exits": len([o for o in filled if o["side"] == "sell"]),
        "orders_submitted": len(orders),
        "resting_orders": len(orders) - len(filled),
        "events": count_events(rows),
        "symbols": sorted({str(o["symbol"]) for o in filled if o["symbol"]}),
    }
