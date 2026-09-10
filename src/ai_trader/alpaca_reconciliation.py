"""Turning finished Alpaca trades into results the system can learn from.

2026-09-08. The Founder asked the trading AI how it thought it was doing on Alpaca. It said,
honestly, that it could not tell. Working out why turned up something worse than "we can't tell":

    PERFORMANCE_ATTRIBUTION -- the closed-trade table the learning loop reads -- holds 27 rows,
    every one of them Kraken. Not one Alpaca row has ever existed.

Alpaca has been trading the whole time. The paper account has run since 2 July, holds nine
positions today, and has bought and sold across 21 different shares. Every one of those finished
round trips was thrown away.

WHY IT HAPPENED, precisely. Kraken has a reconciliation step that links each exit fill back to
the entry it closed. Alpaca never got one, because its exits are bracket legs resting on
Alpaca's own book rather than in our exit loop -- so nothing here ever had to pair them. The
result is visible in the ledger: an Alpaca sell is filed as its own brand-new trade with
fill_role 'entry', sitting alongside the buy it actually closed, and neither ever reaches a
profit or loss. 48 trades stuck at "open", 40 at "cancelled", while the broker shows nine
positions.

Alpaca will not compute the profit for you -- a code note from 17 August records that every
Alpaca exit ever seen, 38 for 38, came back with realised P&L missing. So it has to be worked
out from the two fill prices, which is what this module does.

WHICH RECORD TO BELIEVE, and this decided the whole job. The obvious source is our own ledger,
LOGICAL_TRADE_FILLS. It is wrong for this: it holds 48 Alpaca orders, and pairing them produced
16 finished trades and TWELVE sells with no purchase behind them. The identity check below then
failed by $493 against an account that had moved $45 -- the missing buys were simply never
written to our ledger. MDT is the clearest case: bought 27 on 1 September, sold 27 on the 2nd, a
complete round trip our ledger knew nothing about.

BROKER_TRADE_HISTORY is Alpaca's own activity feed and it is complete. Each row is one fill
event carrying an INCREMENT, not a running total, and the real Alpaca order id lives in the
payload. So an order is the sum of its increments with a volume-weighted average price -- AAPL
on 2 July reads 4+152+107+53+9+6+1+1 = 333 shares at 299.328, which is exactly what the ledger's
own cumulative row says. The two agree where they overlap; only one of them is complete.

HOW TO KNOW THE OUTPUT IS RIGHT, which matters more than the pairing itself. The trading AI
insisted on the correct check and it was right to:

    "Can you reconcile the account-value change to realised P&L PLUS the change in unrealised
     P&L, net cash flows, dividends and costs -- not realised P&L alone?"

Realised alone would have failed on perfectly good work: today the nine open positions carry
+$60 of unrealised against a whole-month account change of about -$45. verify_against_account
computes the full identity, so a pairing bug shows up as a number that does not add up rather
than as a plausible-looking table nobody checks.
"""

from __future__ import annotations

import json
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import trade_reasons
from .database import connect, uses_postgres
from .models import utc_now_iso

# Everything here is long-only stock: a "buy" opens and a "sell" closes. Short selling is
# switched off (ALLOW_SHORT_SELLING), so a sell with no buy behind it is a fault to report, not
# a position to model.
OPENING_SIDE = "buy"
CLOSING_SIDE = "sell"

# Quantities are floats coming out of a broker API. Comparing them exactly would leave
# microscopic slivers of a position open for ever and never close a trade.
QUANTITY_EPSILON = 1e-9


@dataclass(frozen=True)
class Order:
    """One Alpaca order, collapsed from however many fill rows described it."""

    order_id: str
    symbol: str
    side: str
    quantity: float
    price: float
    filled_at: str
    proposal_id: str | None = None
    logical_trade_id: str | None = None
    # True when no terminal record was found and the quantity is the sum of whatever partial
    # fills happened to be captured. Carried through so a caller can exclude these rather than
    # treat a possibly-incomplete quantity as fact.
    incomplete: bool = False


@dataclass(frozen=True)
class RoundTrip:
    """A finished trade: shares bought, later sold, with the profit that came of it."""

    symbol: str
    quantity: float
    entry_price: float
    exit_price: float
    profit_loss: float
    opened_at: str
    closed_at: str
    entry_proposal_id: str | None
    exit_proposal_id: str | None
    lots: int = 1
    incomplete: bool = False
    exit_order_id: str | None = None
    entry_proposal_ids: tuple[str, ...] = ()
    mixed_entry_decisions: bool = False


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result


def collapse_fills(rows: list[dict[str, Any]]) -> list[Order]:
    """One Order per Alpaca order, from the several fill events that made it up.

    Every row is an INCREMENT -- Alpaca's activity feed reports "9 filled, 18 to go" and then
    "18 filled, 0 to go" -- so an order is the sum of its parts at the volume-weighted average
    price they were bought at. Getting this backwards is the difference between a 333-share
    trade and a 666-share one, and the fabricated version looks perfectly reasonable in a table.

    `order_id` is Alpaca's own, taken from the activity payload. The stored external id is a
    per-fill identifier and cannot group anything.

    Pure on purpose: this is where a wrong rule produces a page of plausible, entirely fictional
    trades, and it should be provable without a database.
    """

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        order_id = str(row.get("order_id") or "").strip()
        if not order_id:
            # Nothing can be grouped or paired without it. Dropped rather than guessed at: an
            # unattributable fill is not evidence.
            continue
        grouped.setdefault(order_id, []).append(row)

    orders: list[Order] = []
    for order_id, fills in grouped.items():
        quantity = sum(_number(fill.get("quantity")) or 0.0 for fill in fills)
        weighted = sum(
            (_number(fill.get("quantity")) or 0.0) * (_number(fill.get("price")) or 0.0)
            for fill in fills
        )
        if quantity <= 0 or weighted <= 0:
            continue
        newest = max(fills, key=lambda fill: str(fill.get("filled_at") or ""))
        # An order still working has shares left to fill. Its quantity is real but not final,
        # so it is marked rather than trusted as a completed trade.
        incomplete = not any(
            (_number(fill.get("leaves_quantity")) or 0.0) <= 0 for fill in fills
        )
        orders.append(Order(
            order_id=order_id,
            symbol=str(newest.get("symbol") or "").upper(),
            side=str(newest.get("side") or "").lower(),
            quantity=quantity,
            price=weighted / quantity,
            filled_at=str(newest.get("filled_at") or ""),
            proposal_id=(str(newest.get("proposal_id")) if newest.get("proposal_id") else None),
            logical_trade_id=(str(newest.get("logical_trade_id")) if newest.get("logical_trade_id") else None),
            incomplete=incomplete,
        ))
    orders.sort(key=lambda order: (order.filled_at, order.order_id))
    return orders


@dataclass
class _Lot:
    quantity: float
    price: float
    filled_at: str
    proposal_id: str | None


def pair_round_trips(orders: list[Order]) -> tuple[list[RoundTrip], list[dict[str, Any]]]:
    """Match sells back to the buys they closed, oldest first, per share.

    First in, first out, which is both the ordinary accounting convention and the only one that
    can be checked against a broker that reports positions rather than lots.

    One row per SELL, not per matched sliver. A sell that consumes three buy lots is one
    finished trade in the Founder's terms -- "I bought this and later sold it" -- and splitting
    it into three would inflate every count of how often the system trades. The entry price is
    the quantity-weighted average of the lots it consumed, and opened_at is the oldest of them,
    so the holding period is the true one.

    Returns the round trips and, separately, everything that could not be paired. The second
    list is not a failure to hide: a sell with no buy behind it means either an unrecorded
    entry or a pairing fault, and both need to be seen rather than averaged away.
    """

    open_lots: dict[str, list[_Lot]] = {}
    round_trips: list[RoundTrip] = []
    unmatched: list[dict[str, Any]] = []

    for order in orders:
        if order.side == OPENING_SIDE:
            open_lots.setdefault(order.symbol, []).append(_Lot(
                quantity=order.quantity, price=order.price,
                filled_at=order.filled_at, proposal_id=order.proposal_id,
            ))
            continue
        if order.side != CLOSING_SIDE:
            continue

        lots = open_lots.get(order.symbol) or []
        remaining = order.quantity
        consumed_quantity = 0.0
        consumed_cost = 0.0
        opened_at: str | None = None
        entry_proposal: str | None = None
        entry_proposals: set[str | None] = set()
        lots_used = 0

        while remaining > QUANTITY_EPSILON and lots:
            lot = lots[0]
            take = min(remaining, lot.quantity)
            consumed_quantity += take
            consumed_cost += take * lot.price
            lots_used += 1
            entry_proposals.add(lot.proposal_id)
            if opened_at is None:
                opened_at, entry_proposal = lot.filled_at, lot.proposal_id
            lot.quantity -= take
            remaining -= take
            if lot.quantity <= QUANTITY_EPSILON:
                lots.pop(0)

        if consumed_quantity <= QUANTITY_EPSILON:
            unmatched.append({
                "symbol": order.symbol, "order_id": order.order_id,
                "quantity": order.quantity, "filled_at": order.filled_at,
                "reason": "sold with no recorded purchase behind it",
            })
            continue

        entry_price = consumed_cost / consumed_quantity
        round_trips.append(RoundTrip(
            symbol=order.symbol,
            quantity=round(consumed_quantity, 10),
            entry_price=entry_price,
            exit_price=order.price,
            # Before fees: absent per-fill fees do not prove there were no account costs.
            profit_loss=round((order.price - entry_price) * consumed_quantity, 6),
            opened_at=opened_at or order.filled_at,
            closed_at=order.filled_at,
            entry_proposal_id=entry_proposal if len(entry_proposals) == 1 else None,
            exit_proposal_id=order.proposal_id,
            lots=lots_used,
            incomplete=order.incomplete or remaining > QUANTITY_EPSILON,
            exit_order_id=order.order_id,
            entry_proposal_ids=tuple(sorted(p for p in entry_proposals if p)),
            mixed_entry_decisions=len(entry_proposals)>1,
        ))

        if remaining > QUANTITY_EPSILON:
            # Sold more than was ever recorded as bought. Half a real trade, so the part that
            # paired is kept and the rest is reported.
            unmatched.append({
                "symbol": order.symbol, "order_id": order.order_id,
                "quantity": round(remaining, 10), "filled_at": order.filled_at,
                "reason": "sold more than was recorded as bought",
            })

    return round_trips, unmatched


def _alpaca_fill_rows(conn: Any) -> list[dict[str, Any]]:
    """Alpaca's own fill events, with our proposal id attached wherever we recorded one.

    The proposal is a LEFT join for a reason: the broker's record is complete and ours is not,
    and a trade whose rationale we failed to store is still a trade that happened. It is
    recorded with its reason marked unknown rather than dropped for being inconvenient.
    """

    # Pairing needs two payload fields, not a full broker response per historical fill.
    def field(name: str) -> str:
        if uses_postgres():
            return f"h.payload_json::jsonb ->> '{name}'"
        return f"json_extract(CASE WHEN json_valid(h.payload_json) THEN h.payload_json ELSE '{{}}' END, '$.{name}')"

    rows = conn.execute(
        f"""
        SELECT h.symbol, h.side, h.quantity, h.price, h.opened_at,
               {field('order_id')} AS broker_order_id, {field('leaves_qty')} AS leaves_quantity,
               COALESCE(t.proposal_id, linked.proposal_id),
               CASE WHEN t.proposal_id IS NOT NULL THEN t.logical_trade_id ELSE linked.logical_trade_id END
        FROM BROKER_TRADE_HISTORY h
        LEFT JOIN LOGICAL_TRADE_FILLS f ON f.broker_fill_id = h.external_id
        LEFT JOIN LOGICAL_TRADES t ON t.logical_trade_id = f.logical_trade_id
        LEFT JOIN (
            SELECT ev.broker_order_id, MIN(original.proposal_id) AS proposal_id,
                   MIN(original.logical_trade_id) AS logical_trade_id
            FROM LOGICAL_TRADE_EVENTS ev
            JOIN LOGICAL_TRADES original ON original.logical_trade_id=ev.logical_trade_id
            WHERE original.broker='alpaca' AND original.proposal_id IS NOT NULL
            GROUP BY ev.broker_order_id
            HAVING COUNT(DISTINCT original.logical_trade_id)=1
        ) linked ON linked.broker_order_id={field('order_id')}
        WHERE LOWER(h.broker) = 'alpaca' AND h.status IN ('fill', 'partial_fill')
        ORDER BY h.opened_at
        """
    ).fetchall()

    fills: list[dict[str, Any]] = []
    for row in rows:
        fills.append({
            # The real Alpaca order id. Only the payload carries it; the stored external id
            # identifies the fill, not the order, so there is no fallback worth having -- a
            # fill that cannot name its order is dropped by collapse_fills rather than guessed.
            "order_id": row[5],
            "symbol": row[0],
            "side": row[1],
            "quantity": row[2],
            "price": row[3],
            "filled_at": row[4],
            "leaves_quantity": row[6],
            "proposal_id": row[7],
            "logical_trade_id": row[8],
        })
    return fills


def recorded_exit_evidence(conn: Any, order_ids: list[str]) -> dict[str, dict[str, str]]:
    """Match actual closing fill order IDs to recorded order types, never P&L signs."""
    result = {}
    unique = sorted(set(order_ids))
    for start in range(0, len(unique), 100):
        batch = unique[start:start + 100]
        marks = ','.join('?' for _ in batch)
        kind = "payload_json::jsonb->>'type'" if uses_postgres() else "json_extract(payload_json, '$.type')"
        rows = conn.execute(f"""SELECT external_id,{kind} FROM BROKER_TRADE_HISTORY
            WHERE broker='alpaca' AND external_id IN ({marks})""", tuple(batch)).fetchall()
        types: dict[str, set[str]] = {}
        for order_id, order_type in (tuple(row[i] for i in range(2)) for row in rows):
            types.setdefault(order_id, set()).add(str(order_type or '').lower())
        for order_id, values in types.items():
            if len(values) != 1:
                continue
            order_type = next(iter(values))
            if order_type in {'stop', 'stop_limit', 'trailing_stop'}:
                result[order_id] = {'order_id': order_id, 'order_type': order_type,
                    'basis': 'closing_fill_order_id_matches_recorded_broker_order_type',
                    'reason': f'Broker {order_type.replace("_", "-")} order filled.'}
    return result


def reconcile_alpaca(db_path: Path) -> dict[str, Any]:
    """Work out every finished Alpaca trade and write the ones that are missing.

    Idempotent on broker + symbol + closed_at, the same key the Kraken side uses: one share
    cannot close twice at the same instant on the same broker. So this can run every cycle and
    only ever adds what is new.
    """

    try:
        from .production_evidence import _ensure_local_production_evidence_schema
        _ensure_local_production_evidence_schema(db_path)
        with closing(connect(db_path)) as conn:
            fills = _alpaca_fill_rows(conn)
            orders = collapse_fills(fills)
            round_trips, unmatched = pair_round_trips(orders)
            exits = recorded_exit_evidence(conn, [trip.exit_order_id for trip in round_trips if trip.exit_order_id])

            entry_reasons = trade_reasons.entry_reasons_for_proposals(
                conn, [trip.entry_proposal_id for trip in round_trips if trip.entry_proposal_id]
            )
            written = 0
            with conn:
                for trip in round_trips:
                    _publish_order_result(conn, trip)
                    existing = conn.execute(
                        """
                        SELECT attribution_id, exit_reason, primary_factors_json, proposal_id FROM PERFORMANCE_ATTRIBUTION
                        WHERE broker = 'alpaca' AND symbol = ? AND closed_at = ?
                        LIMIT 1
                        """,
                        (trip.symbol, trip.closed_at),
                    ).fetchone()
                    if existing:
                        if trip.mixed_entry_decisions:
                            factors = json.loads(existing[2] or '{}')
                            factors.update(entry_proposal_ids=list(trip.entry_proposal_ids),mixed_entry_decisions=True)
                            if existing[3]:
                                factors['previous_single_proposal_id']=existing[3]
                            conn.execute('UPDATE PERFORMANCE_ATTRIBUTION SET proposal_id=NULL, primary_factors_json=? WHERE attribution_id=?',
                                         (json.dumps(factors,sort_keys=True),existing[0]))
                        if not existing[3] and trip.entry_proposal_id:
                            conn.execute('UPDATE PERFORMANCE_ATTRIBUTION SET proposal_id = ?, entry_reason = ? WHERE attribution_id = ? AND proposal_id IS NULL',
                                         (trip.entry_proposal_id, entry_reasons.get(trip.entry_proposal_id) or trade_reasons.UNRECORDED_ENTRY, existing[0]))
                        evidence = exits.get(trip.exit_order_id)
                        if evidence and (not existing[1] or 'not recorded' in existing[1].lower()):
                            factors = json.loads(existing[2] or '{}')
                            factors['exit_evidence'] = evidence
                            conn.execute('UPDATE PERFORMANCE_ATTRIBUTION SET exit_reason = ?, primary_factors_json = ? WHERE attribution_id = ?',
                                         (evidence['reason'], json.dumps(factors, sort_keys=True), existing[0]))
                        continue
                    conn.execute(
                        """
                        INSERT INTO PERFORMANCE_ATTRIBUTION (
                            created_at, proposal_id, broker, symbol, asset_type, side,
                            entry_price, exit_price, quantity, profit_loss, opened_at,
                            closed_at, holding_period_seconds, entry_reason, exit_reason,
                            primary_factors_json
                        ) VALUES (?, ?, 'alpaca', ?, 'stock', 'buy', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            utc_now_iso(),
                            trip.entry_proposal_id,
                            trip.symbol,
                            trip.entry_price,
                            trip.exit_price,
                            trip.quantity,
                            trip.profit_loss,
                            trip.opened_at,
                            trip.closed_at,
                            trade_reasons.holding_seconds(trip.opened_at, trip.closed_at),
                            entry_reasons.get(str(trip.entry_proposal_id or ""))
                            or trade_reasons.UNRECORDED_ENTRY,
                            # Alpaca exits are bracket legs resting on Alpaca's own book, so
                            # there is no local record of what tripped them. Said plainly
                            # rather than invented: a constant string here would send the
                            # learning loop the same false lesson the Kraken side had to have
                            # removed on 2026-08-27.
                            exits.get(trip.exit_order_id, {}).get('reason', trade_reasons.UNRECORDED_EXIT),
                            json.dumps({
                                "reconstructed_from": "alpaca_fill_pairing",
                                "lots_consumed": trip.lots,
                                "exit_proposal_id": trip.exit_proposal_id,
                                "incomplete_fill_record": trip.incomplete,
                                "exit_order_id": trip.exit_order_id,
                                "pnl_basis": "before_unreconciled_fees",
                                "exit_evidence": exits.get(trip.exit_order_id),
                                "entry_proposal_ids": list(trip.entry_proposal_ids),
                                "mixed_entry_decisions": trip.mixed_entry_decisions,
                            }, sort_keys=True, default=str),
                        ),
                    )
                    written += 1
    except Exception as exc:  # noqa: BLE001 - a reconciliation fault must not stop a cycle
        return {"status": "failed", "error": f"{type(exc).__name__}: {exc}", "written": 0}

    # Completed reporting evidence must not disappear merely because original
    # decision links are missing. Keep this distinct from full canonical learning.
    from .alpaca_learning import capture_outcome_evidence, review_linked_outcomes
    try:
        learning_evidence = capture_outcome_evidence(db_path)
        learning_evidence['linked_reviews'] = review_linked_outcomes(db_path)
    except Exception as exc:
        learning_evidence = {'status': 'failed', 'error_type': type(exc).__name__}
    return {
        "status": "completed",
        "learning_evidence": learning_evidence,
        "orders": len(orders),
        "round_trips": len(round_trips),
        "written": written,
        "already_recorded": len(round_trips) - written,
        "unmatched": unmatched,
        "realised_total": round(sum(trip.profit_loss for trip in round_trips), 2),
    }


def _publish_order_result(conn: Any, trip: RoundTrip) -> None:
    """Use full fill-pairing, never the last partial fill, for the order's result.

    Retain all source events but publish P&L on one terminal evidence row only.
    This repairs old FIFO estimates by exact broker order identity. No history is
    downloaded here: the reconciliation already computed this result in memory.
    """
    if trip.incomplete or not trip.exit_order_id:
        return
    key = (trip.exit_order_id,)
    conn.execute("""
        UPDATE PRODUCTION_TRADE_EVIDENCE SET realized_pnl = NULL
        WHERE broker = 'alpaca' AND broker_order_id = ? AND status = 'filled'
          AND realized_pnl IS NOT NULL
          AND trade_evidence_id <> (
            SELECT MIN(trade_evidence_id) FROM PRODUCTION_TRADE_EVIDENCE
            WHERE broker = 'alpaca' AND broker_order_id = ? AND status = 'filled'
          )
    """, key + key)
    conn.execute("""
        UPDATE PRODUCTION_TRADE_EVIDENCE
        SET realized_pnl = ?, quantity = ?, average_fill_price = ?
        WHERE trade_evidence_id = (
            SELECT MIN(trade_evidence_id) FROM PRODUCTION_TRADE_EVIDENCE
            WHERE broker = 'alpaca' AND broker_order_id = ? AND status = 'filled'
        ) AND (realized_pnl IS NULL OR realized_pnl <> ? OR quantity IS NULL
               OR quantity <> ? OR average_fill_price IS NULL OR average_fill_price <> ?)
    """, (trip.profit_loss, trip.quantity, trip.exit_price, trip.exit_order_id,
          trip.profit_loss, trip.quantity, trip.exit_price))


def verify_against_account(db_path: Path, *, since: str | None = None) -> dict[str, Any]:
    """Does the reconstructed profit actually explain what the account did?

    The identity the trading AI insisted on, and it was right to:

        account value change  =  realised P&L  +  change in unrealised P&L  +  cash in or out

    Checking realised alone would fail on perfectly good pairing whenever positions are open --
    today's nine carry +$60 against a monthly change of about -$45, so realised would look
    wrong by more than the whole change it was trying to explain.

    Returns the terms rather than a verdict. A number that does not add up is a finding, and
    what it means depends on which term is off; deciding that here would hide it.
    """

    try:
        with closing(connect(db_path)) as conn:
            snapshots = conn.execute(
                """
                SELECT captured_at, portfolio_value, cash, positions_json
                FROM PRODUCTION_BROKER_SNAPSHOTS
                WHERE LOWER(broker) = 'alpaca'
                ORDER BY captured_at
                """
            ).fetchall()
            if since:
                snapshots = [row for row in snapshots if str(row[0] or "") >= since]
            if len(snapshots) < 2:
                return {"status": "insufficient_snapshots", "snapshots": len(snapshots)}
            first, last = snapshots[0], snapshots[-1]

            realised = conn.execute(
                """
                SELECT COALESCE(SUM(profit_loss), 0) FROM PERFORMANCE_ATTRIBUTION
                WHERE broker = 'alpaca' AND closed_at >= ? AND closed_at <= ?
                """,
                (str(first[0]), str(last[0])),
            ).fetchone()
    except Exception as exc:  # noqa: BLE001
        return {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}

    def _unrealised(raw: Any) -> float:
        try:
            positions = json.loads(raw or "[]") or []
        except (TypeError, ValueError):
            return 0.0
        return sum(_number(p.get("unrealized_pl")) or 0.0 for p in positions)

    account_change = (_number(last[1]) or 0.0) - (_number(first[1]) or 0.0)
    unrealised_change = _unrealised(last[3]) - _unrealised(first[3])
    realised_total = _number(realised[0]) or 0.0
    explained = realised_total + unrealised_change
    return {
        "status": "measured",
        "from": str(first[0]),
        "to": str(last[0]),
        "account_value_change": round(account_change, 2),
        "realised_profit_loss": round(realised_total, 2),
        "unrealised_change": round(unrealised_change, 2),
        "explained": round(explained, 2),
        # What is left over. Dividends, any cash the Founder moved, and anything the pairing got
        # wrong all land here, so a small number is reassuring and a large one is a lead.
        "unexplained": round(account_change - explained, 2),
    }
