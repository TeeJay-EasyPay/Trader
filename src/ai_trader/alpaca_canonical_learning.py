"""Repair only complete, uniquely owned Alpaca round trips from retained activity fills.

No broker requests. No guessing proposal IDs, fees, stop activation or exit triggers.
Mixed-entry decisions and incomplete quantities remain reporting-only evidence.
"""
import json
from . import experiments as e
_INITIALIZED = set()


def reconcile_completed(db, fills, orders, trips, exits, *, limit=10, force=False):
    from .canonical_trades import _refresh_trade_aggregate, canonical_trade
    from .sprint6 import enqueue_learning_workflow, _learning_payload_from_canonical_trade
    groups = {}
    for trip in trips:
        if trip.entry_proposal_id:
            groups.setdefault(trip.entry_proposal_id, []).append(trip)
    if not groups:
        return dict(canonical_queued=[], unresolved=[])
    schema_key = (str(db), e.uses_postgres())
    if schema_key not in _INITIALIZED:
        e.migrate(db)
        _INITIALIZED.add(schema_key)
    with e.transaction(db) as conn:
        progress = e.control(conn, 'alpaca_canonical_repair', {})
        if not force and progress.get('day') == e.now_iso()[:10]:
            return dict(canonical_queued=[], unresolved=progress.get('unresolved', []), status='daily_budget_reached')
        start = int(progress.get('cursor', 0)) % len(groups)
        selected_groups = list(groups.items())[start:start + max(1, min(limit, 10))]
        e.put_control(conn, 'alpaca_canonical_repair', dict(day=e.now_iso()[:10], cursor=start + len(selected_groups), status='reserved'))
    completed, blocked = [], []
    for proposal_id, group in selected_groups:
        entries = [o for o in orders if o.side == 'buy' and o.proposal_id == proposal_id]
        if not entries or any(o.incomplete for o in entries) or any(t.incomplete or t.mixed_entry_decisions for t in group):
            blocked.append(dict(proposal_id=proposal_id, reason='Incomplete or mixed entry evidence'))
            continue
        if abs(sum(o.quantity for o in entries) - sum(t.quantity for t in group)) > 1e-8:
            continue  # still partly open; do not teach a premature completed outcome
        entry_ids = {o.order_id for o in entries}
        exit_ids = {t.exit_order_id for t in group}
        selected = [f for f in fills if f['order_id'] in entry_ids | exit_ids]
        if not selected or any(not f.get('fill_id') for f in selected):
            continue
        complete_orders = True
        for order_id in entry_ids | exit_ids:
            order_fills = [f for f in selected if f['order_id'] == order_id]
            terminal = [f for f in order_fills if f.get('leaves_quantity') is not None and float(f['leaves_quantity']) == 0 and f.get('cumulative_quantity') is not None]
            if not terminal or abs(max(float(f['cumulative_quantity']) for f in terminal) - sum(float(f['quantity']) for f in order_fills)) > 1e-8:
                complete_orders = False
        if not complete_orders:
            blocked.append(dict(proposal_id=proposal_id, reason='Activity increments do not verify terminal cumulative quantity'))
            continue
        # Whole closing orders must belong to this single decision, not split across lots.
        if any(sum(t.exit_order_id == oid for t in group) != 1 for oid in exit_ids):
            continue
        with e.transaction(db) as conn:
            trade = conn.execute("SELECT logical_trade_id,terminal,side FROM LOGICAL_TRADES WHERE broker='alpaca' AND proposal_id=?", (proposal_id,)).fetchone()
            if not trade or trade['side'] != 'buy':
                continue
            logical = trade['logical_trade_id']
            owned = conn.execute("SELECT DISTINCT broker_order_id FROM LOGICAL_TRADE_EVENTS WHERE logical_trade_id=? AND stage='exit_order_linked'", (logical,)).fetchall()
            if not exit_ids.issubset({r[0] for r in owned}):
                blocked.append(dict(proposal_id=proposal_id, reason='Closing order lacks an explicit canonical parent/exit link; FIFO alone is not ownership'))
                continue
            already = conn.execute('SELECT learning_run_id FROM CLOSED_LOOP_LEARNING_RUNS WHERE logical_trade_id=? LIMIT 1', (logical,)).fetchone()
            if already:
                continue
            conflict = False
            existing_fills = conn.execute('SELECT broker_fill_id FROM LOGICAL_TRADE_FILLS WHERE logical_trade_id=?', (logical,)).fetchall()
            if {r[0] for r in existing_fills} - {f['fill_id'] for f in selected}:
                blocked.append(dict(proposal_id=proposal_id, reason='Additional legacy fills require separate reconciliation; not double counted'))
                continue
            if abs(sum(f['quantity'] for f in selected if f['side'] == 'sell') - sum(t.quantity for t in group)) > 1e-8:
                continue
            for f in selected:
                old = conn.execute("SELECT f.logical_trade_id,t.side,t.terminal FROM LOGICAL_TRADE_FILLS f JOIN LOGICAL_TRADES t ON t.logical_trade_id=f.logical_trade_id WHERE f.broker='alpaca' AND f.broker_fill_id=?", (f['fill_id'],)).fetchone()
                if old and old[0] != logical and not (f['side'] == 'sell' and old['side'] == 'sell' and not old['terminal']):
                    conflict = True
            if conflict:
                blocked.append(dict(proposal_id=proposal_id, reason='Fill already owned by another completed or entry decision'))
                continue
            for f in selected:
                role = 'entry' if f['order_id'] in entry_ids else 'exit'
                old_fill = conn.execute("SELECT * FROM LOGICAL_TRADE_FILLS WHERE broker='alpaca' AND broker_fill_id=?", (f['fill_id'],)).fetchone()
                conn.execute('INSERT INTO LOGICAL_TRADE_EVENTS(logical_trade_id,stage,event_source,event_time,broker_order_id,broker_fill_id,reason,payload_json,idempotency_key) '
                    'VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(idempotency_key) DO NOTHING',
                    (logical, 'learning_evidence_repair', 'retained_alpaca_activity', e.now_iso(), f['order_id'], f['fill_id'],
                     'Exact uniquely owned activity fill restored; previous row retained for audit',
                     e.dump({'previous_fill': dict(old_fill) if old_fill else None, 'source_fill_id': f['fill_id']}),
                     'alpaca-learning-repair:' + logical + ':' + f['fill_id']))
                conn.execute('INSERT INTO LOGICAL_TRADE_FILLS(logical_trade_id,broker,broker_fill_id,broker_order_id,fill_role,side,quantity,price,broker_fee,exchange_fee,filled_at,payload_json) '
                    'VALUES (?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(broker,broker_fill_id) DO UPDATE SET '
                    'logical_trade_id=excluded.logical_trade_id,fill_role=excluded.fill_role,quantity=excluded.quantity,price=excluded.price,broker_fee=excluded.broker_fee,exchange_fee=excluded.exchange_fee',
                    (logical, 'alpaca', f['fill_id'], f['order_id'], role, f['side'], f['quantity'], f['price'],
                     f.get('broker_fee'), f.get('exchange_fee'), f['filled_at'], e.dump(dict(source='retained_alpaca_activity_fill', fill_id=f['fill_id'], order_id=f['order_id']))))
            _refresh_trade_aggregate(db, logical, conn=conn)
            closed = max(t.closed_at for t in group)
            conn.execute('UPDATE LOGICAL_TRADES SET closed_at=? WHERE logical_trade_id=? AND terminal=1', (closed, logical))
            trade = canonical_trade(db, logical, conn=conn)
        if not trade or not trade['terminal']:
            continue
        payload = _learning_payload_from_canonical_trade(db, trade)
        opened = min(f['filled_at'] for f in selected if f['order_id'] in entry_ids)
        reason_evidence = [exits[oid] for oid in sorted(exit_ids) if oid in exits]
        payload['attribution'].update(entry_time=opened, exit_time=closed,
            holding_seconds=(e.stamp(closed) - e.stamp(opened)).total_seconds(),
            canonical_closure_verified=True, evidence_basis='complete uniquely linked retained activity fills',
            exit_evidence=reason_evidence,
            exit_reason='; '.join(x['reason'] for x in reason_evidence) if len(reason_evidence) == len(exit_ids) else 'Exit trigger was not recorded',
            stop_activation_verified=False)
        enqueue_learning_workflow(db, logical_trade_id=logical, broker='alpaca', payload=payload)
        completed.append(logical)
    with e.transaction(db) as conn:
        e.put_control(conn, 'alpaca_canonical_repair', dict(day=e.now_iso()[:10], cursor=start + len(selected_groups),
            status='completed', canonical_queued=completed, unresolved=blocked[:10]))
    return dict(canonical_queued=completed, unresolved=blocked[:10],
                limitation='Missing fee and exit evidence remains unknown; reporting and canonical reviews must not be counted as separate trades.')
