"""Close positions the app thinks it holds but the exchange says it does not.

2026-08-30, Founder-directed: "how do we ensure no phantom positions open up again... why
can't the app tell the positions are not real. shouldn't it have a check for that?"

He was right that no such check existed. Nothing anywhere compared what the app believes it
holds against what the broker actually reports, so a position could sit "open" indefinitely
while the exchange balance was zero. Found live: a BCH managed exit open for 8 days at
0.0126 BCH, against a real Kraken balance of 0.00000005 -- sold long before, never closed.

How they arise, both confirmed:

  * canonical_trades.py defines finished as "entered and then exited"
    (terminal = entry_qty > 0 and exit_qty >= entry_qty). An order that never fills has
    entry_qty = 0, so it can NEVER become terminal. A patient limit entry that expires
    unfilled leaves a record with no state to move to.
  * A position that genuinely sells can leave its managed exit un-closed if the exit
    confirmation is missed.

The check is deliberately one-directional. It closes records the exchange does not support;
it never opens a position the app did not know about. An unexpected balance is the Founder's
own holding far more often than it is a missed fill -- Kraken is his personal account -- and
inventing a managed position over his own coins would be a much worse failure than leaving a
stale row. See kraken_capital_ledger for the same separation applied to valuation.
"""

from __future__ import annotations

from contextlib import closing
from pathlib import Path
from typing import Any

from .database import connect
from .models import utc_now_iso
from .multi_broker import close_managed_exit, initialize_multi_broker_schema, open_managed_exits

# Below this, a balance is dust left over from a sale rather than a position. Kraken leaves
# residue like 5e-8 BCH after a full exit; treating that as "still holding" is what kept the
# record open. Expressed as a fraction of the quantity the app believes it holds, so it
# scales across assets priced from 0.00001 to 100000.
_DUST_FRACTION = 0.01


def _kraken_balances(adapter: Any) -> dict[str, float] | None:
    """Live balances keyed by plain symbol, or None if they cannot be read.

    None means "unknown", and every caller below treats unknown as "change nothing". A
    failed balance read must never be able to close a real position.
    """
    try:
        account = adapter.get_account()
    except Exception:  # noqa: BLE001 - an unreadable broker must not mutate any record
        return None
    balances = account.get("balances") if isinstance(account, dict) else None
    if not isinstance(balances, dict):
        return None
    from .broker_adapters import _kraken_asset_symbol

    out: dict[str, float] = {}
    for key, value in balances.items():
        try:
            amount = float(value)
        except (TypeError, ValueError):
            continue
        symbol = _kraken_asset_symbol(key)
        if not symbol:
            continue
        out[symbol.upper()] = out.get(symbol.upper(), 0.0) + amount
    return out


def reconcile_open_positions(
    db_path: Path, adapter: Any, *, broker: str = "kraken", dry_run: bool = False,
) -> dict[str, Any]:
    """Compare open managed exits against real balances and close the ones that are gone."""
    initialize_multi_broker_schema(db_path)
    open_rows = open_managed_exits(db_path, broker)
    result: dict[str, Any] = {
        "broker": broker,
        "checked": len(open_rows),
        "closed": [],
        "kept": [],
        "status": "ok",
    }
    if not open_rows:
        result["message"] = "No open positions to check."
        return result

    balances = _kraken_balances(adapter)
    if balances is None:
        # Unknown is not zero. This is the same principle the scoring work settled on, and
        # it matters far more here: acting on an unreadable balance would close real
        # positions and abandon their trailing stops.
        result["status"] = "skipped"
        result["message"] = "Could not read balances from the broker, so nothing was changed."
        return result

    for row in open_rows:
        symbol = str(row.get("symbol") or "").upper()
        try:
            expected = abs(float(row.get("quantity") or 0.0))
        except (TypeError, ValueError):
            expected = 0.0
        held = float(balances.get(symbol, 0.0))
        threshold = expected * _DUST_FRACTION
        if expected <= 0 or held > threshold:
            result["kept"].append({"symbol": symbol, "expected": expected, "held": held})
            continue
        entry = {
            "symbol": symbol,
            "managed_exit_id": row.get("managed_exit_id"),
            "expected_quantity": expected,
            "actual_balance": held,
        }
        if not dry_run:
            close_managed_exit(
                db_path,
                int(row["managed_exit_id"]),
                exit_order_id=None,
                exit_reason="reconciled_not_held_at_broker",
                payload={
                    "reconciliation": {
                        "checked_at": utc_now_iso(),
                        "expected_quantity": expected,
                        "actual_balance": held,
                        "note": (
                            f"{broker} reports {held:.10f} {symbol} against an expected "
                            f"{expected:.10f}. The position is not held, so this record was "
                            "closed rather than left occupying a position slot."
                        ),
                    }
                },
            )
        result["closed"].append(entry)
    result["message"] = (
        f"{len(result['closed'])} position(s) closed as not held at {broker}; "
        f"{len(result['kept'])} confirmed still held."
    )
    return result


def stale_execution_intents(db_path: Path, *, broker: str = "kraken", older_than_hours: int = 24) -> int:
    """Count logical trades stuck before any fill, for reporting only.

    Deliberately counts rather than deletes. These rows do not occupy a position slot (the
    cap reads MANAGED_TRADE_EXITS), they are the audit trail of what the app intended, and
    deleting audit history to tidy a number is not a trade this codebase should make. The
    count exists so the debris is visible instead of silently accumulating -- 275 of them
    had built up since 23 July before anyone looked.
    """
    from datetime import datetime, timedelta, timezone

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=older_than_hours)).isoformat()
    try:
        with closing(connect(db_path)) as conn:
            row = conn.execute(
                """SELECT COUNT(*) FROM LOGICAL_TRADES
                   WHERE broker = ? AND terminal = 0 AND state = 'execution_intent'
                     AND created_at < ?""",
                (broker, cutoff),
            ).fetchone()
        return int(row[0]) if row else 0
    except Exception:  # noqa: BLE001 - a reporting count must never break a cycle
        return 0
