"""Settle order-intent locks against what the broker actually did.

2026-08-26 audit finding: 16 locks sat in a non-terminal state, the oldest from 10 August.
A lock is taken immediately before an order is submitted and is only cleared on a definite,
synchronous rejection -- deliberately, because an unknown outcome might mean the order WAS
placed, and clearing it blind risks resubmitting a live position with real money. So any run
that dies mid-submission leaves a lock behind forever, and that proposal can never be retried.

Checking the brokers showed the 16 were not one problem but three:

  NUE, MLM, VMC, FSLR, NEE   filled at Alpaca -- the order succeeded and the lock was simply
                             never advanced past pending_new
  3 Kraken locks (13 Aug)    locked before submission, process died, no order at the broker
  the remainder              genuinely still working

Blanket-clearing would have been wrong for the first group and dangerous in general. This
asks the broker instead, and applies the only rule that is safe:

  order exists and is finished   -> settle the lock with the real order id
  order exists and is live       -> leave it alone, it is doing its job
  broker says no such order      -> release; the submission provably never happened
  broker cannot be asked         -> leave it alone

The last line is the important one. Silence is not evidence of absence, and a lock that
cannot be checked stays exactly where it is.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .multi_broker import complete_order_intent_lock, initialize_multi_broker_schema, release_order_intent_lock
from .database import connect
from contextlib import closing

logger = logging.getLogger("ai_trader.api")

# States a lock can sit in while the order's real fate is still unrecorded.
UNSETTLED = ("locked", "pending_new", "submitted")

# Broker order states that mean the order is finished, one way or the other.
FINISHED = {"filled", "closed", "canceled", "cancelled", "expired", "rejected", "done"}


def _broker_orders(adapter: Any) -> list[dict[str, Any]] | None:
    """Every order the broker knows about, or None if it could not be asked.

    None and [] mean very different things here: [] is "the broker answered and has no
    orders", None is "we do not know". Only the first is grounds for releasing a lock.
    """
    reader = getattr(adapter, "get_orders", None)
    if not callable(reader):
        return None
    try:
        orders = reader()
    except Exception:  # noqa: BLE001 - an unreachable broker must not release anything
        return None
    return list(orders) if isinstance(orders, (list, tuple)) else None


def _matches(order: dict[str, Any], client_order_id: str, userref: str | None) -> bool:
    """Whether this broker order is the one a lock was taken for.

    Alpaca echoes client_order_id back verbatim. Kraken has no such field and carries a
    numeric userref derived from it instead (broker_adapters._userref), so both are checked.
    """
    if not isinstance(order, dict):
        return False
    for key in ("client_order_id", "clientOrderId"):
        if str(order.get(key) or "") == client_order_id:
            return True
    if userref and str(order.get("userref") or "") == str(userref):
        return True
    descr = order.get("descr")
    if isinstance(descr, dict) and userref and str(descr.get("userref") or "") == str(userref):
        return True
    return False


def _order_state(order: dict[str, Any]) -> str:
    return str(order.get("status") or order.get("state") or "").lower()


def _order_id(order: dict[str, Any]) -> str | None:
    for key in ("id", "order_id", "txid", "ordertxid"):
        value = order.get(key)
        if isinstance(value, list) and value:
            return str(value[0])
        if value:
            return str(value)
    return None


def unsettled_locks(db_path: Path, *, broker: str | None = None) -> list[dict[str, Any]]:
    initialize_multi_broker_schema(db_path)
    sql = (
        "SELECT lock_id, created_at, broker, client_order_id, symbol, side, status "
        "FROM ORDER_INTENT_LOCKS WHERE status IN (" + ",".join(["?"] * len(UNSETTLED)) + ")"
    )
    params: list[Any] = list(UNSETTLED)
    if broker:
        sql += " AND broker = ?"
        params.append(broker.lower())
    sql += " ORDER BY lock_id ASC"
    with closing(connect(db_path)) as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
    return [
        {
            "lock_id": row[0], "created_at": row[1], "broker": row[2],
            "client_order_id": row[3], "symbol": row[4], "side": row[5], "status": row[6],
        }
        for row in rows
    ]


def reconcile_order_intent_locks(db_path: Path, adapters: dict[str, Any]) -> dict[str, Any]:
    """Settle every unsettled lock against its broker. Never releases on doubt."""
    from .broker_adapters import _userref

    outcome = {"checked": 0, "settled": 0, "released": 0, "still_working": 0, "unreachable": 0, "details": []}
    locks = unsettled_locks(db_path)
    if not locks:
        return outcome

    # One order fetch per broker, not per lock.
    orders_by_broker: dict[str, list[dict[str, Any]] | None] = {}
    for broker in {lock["broker"] for lock in locks}:
        adapter = adapters.get(broker)
        orders_by_broker[broker] = _broker_orders(adapter) if adapter is not None else None

    for lock in locks:
        outcome["checked"] += 1
        broker = lock["broker"]
        orders = orders_by_broker.get(broker)
        if orders is None:
            outcome["unreachable"] += 1
            outcome["details"].append({**lock, "action": "left_alone_broker_unreachable"})
            continue

        userref = _userref(lock["client_order_id"])
        match = next((order for order in orders if _matches(order, lock["client_order_id"], userref)), None)

        if match is None:
            # The broker answered and has no such order: the submission provably never
            # happened, so this proposal can safely be tried again.
            release_order_intent_lock(db_path, broker=broker, client_order_id=lock["client_order_id"])
            outcome["released"] += 1
            outcome["details"].append({**lock, "action": "released_no_order_at_broker"})
            continue

        state = _order_state(match)
        if state in FINISHED:
            complete_order_intent_lock(
                db_path, broker=broker, client_order_id=lock["client_order_id"],
                status="accepted" if state in {"filled", "closed", "done"} else "rejected",
                result_order_id=_order_id(match),
                notes=f"Reconciled against the broker: order {state}.",
            )
            outcome["settled"] += 1
            outcome["details"].append({**lock, "action": f"settled_{state}"})
        else:
            outcome["still_working"] += 1
            outcome["details"].append({**lock, "action": f"left_alone_order_{state or 'live'}"})
    return outcome
