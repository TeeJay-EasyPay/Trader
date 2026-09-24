from dataclasses import replace
from ai_trader.canonical_trades import register_execution_intent, link_broker_order, canonical_trade
from ai_trader.production_spine import initialize_production_spine_schema
from ai_trader.sprint6 import _ensure_sprint6_schema, process_learning_outbox
from ai_trader.alpaca_reconciliation import collapse_fills, pair_round_trips
from ai_trader.alpaca_canonical_learning import reconcile_completed
from test_sprint6_institutional_spine import proposal


def setup(db, linked=True):
    p = proposal()
    register_execution_intent(db, proposal=p, broker='alpaca', decision_context={'proposal':p.to_dict()})
    initialize_production_spine_schema(db)
    _ensure_sprint6_schema(db)
    if linked:
        link_broker_order(db, logical_trade_id=p.proposal_id, broker_order_id='exit', order_role='exit', payload={})
    fills = [dict(fill_id='f1', order_id='entry', proposal_id=p.proposal_id, symbol='AAPL',side='buy',
        price=100,quantity=.1,cumulative_quantity=.1,filled_at='2026-09-01T12:00:00+00:00',leaves_quantity=0,broker_fee=None,exchange_fee=None),
        dict(fill_id='f2',order_id='exit',proposal_id=None,symbol='AAPL',side='sell',price=105,quantity=.1,
        filled_at='2026-09-02T12:00:00+00:00',cumulative_quantity=.1,leaves_quantity=0,broker_fee=None,exchange_fee=None)]
    orders = collapse_fills(fills)
    trips, _ = pair_round_trips(orders)
    return p, fills, orders, trips


def test_repair_real_fill_identity_and_unknown_fees(tmp_path):
    db = tmp_path/'learning.db'
    p, fills, orders, trips = setup(db)
    result = reconcile_completed(db, fills, orders, trips, {})
    assert result['canonical_queued'] == [p.proposal_id]
    trade = canonical_trade(db,p.proposal_id)
    assert trade['terminal'] == 1 and trade['entry_filled_quantity'] == .1
    assert trade['net_pnl'] is None
    assert trade['closed_at'] == fills[1]['filled_at']
    result = process_learning_outbox(db, worker_id='test')
    assert result['failed'] == 0 and result['processed'] == 1
    assert reconcile_completed(db, fills, orders, trips, {})['canonical_queued'] == []


def test_fifo_without_exit_ownership_is_not_canonical(tmp_path):
    db = tmp_path/'learning.db'
    p, fills, orders, trips = setup(db, linked=False)
    result = reconcile_completed(db, fills, orders, trips, {})
    assert not result['canonical_queued']
    assert result['unresolved'] and canonical_trade(db,p.proposal_id)['terminal'] == 0


def test_partial_or_mixed_round_trip_does_not_close(tmp_path):
    db = tmp_path/'learning.db'
    p, fills, orders, trips = setup(db)
    trips = [replace(trips[0], incomplete=True)]
    assert not reconcile_completed(db, fills, orders, trips, {})['canonical_queued']
    assert canonical_trade(db,p.proposal_id)['terminal'] == 0


def test_unowned_old_group_does_not_spend_repair_slot(tmp_path):
    db=tmp_path/'priority.db'
    p,fills,orders,trips=setup(db)
    old=replace(p,proposal_id='old-unlinked')
    register_execution_intent(db,proposal=old,broker='alpaca',decision_context={})
    old_fills=[{**f,'fill_id':'old-'+f['fill_id'],'order_id':'old-'+f['order_id'],
                'proposal_id':old.proposal_id if f['side']=='buy' else None} for f in fills]
    old_orders=collapse_fills(old_fills);old_trips,_=pair_round_trips(old_orders)
    result=reconcile_completed(db,old_fills+fills,old_orders+orders,old_trips+trips,{},limit=1)
    assert result['canonical_queued']==[p.proposal_id]
    assert result['unresolved'][0]['proposal_id']=='old-unlinked'


def test_targeted_checkpoint_does_not_reset_daily_repair_budget(tmp_path):
    from ai_trader import experiments as e
    db=tmp_path/'targeted.db'
    p,fills,orders,trips=setup(db);e.migrate(db)
    before={'day':e.now_iso()[:10],'cursor':50,'status':'completed'}
    with e.transaction(db) as c:e.put_control(c,'alpaca_canonical_repair',before)
    result=reconcile_completed(db,fills,orders,trips,{},limit=1,checkpoint_key='approved-targeted-repair')
    assert result['canonical_queued']==[p.proposal_id]
    with e.transaction(db) as c:assert e.control(c,'alpaca_canonical_repair')==before
