import json
import sqlite3
from unittest.mock import Mock
import pytest
from ai_trader.readiness_broker_evidence import kraken_orders
from ai_trader.alpaca_reconciliation import _alpaca_fill_rows


def test_broker_read_rejects_unowned_and_only_uses_two_read_methods(tmp_path):
    db=tmp_path/'owned.db'
    with sqlite3.connect(db) as c:
        c.execute('CREATE TABLE KRAKEN_AI_ORDER_OWNERSHIP(broker_order_id TEXT)')
        c.execute("INSERT INTO KRAKEN_AI_ORDER_OWNERSHIP VALUES('owned')")
    adapter=Mock()
    with pytest.raises(ValueError):kraken_orders(db,adapter,['personal'])
    adapter._private_request.assert_not_called()
    with pytest.raises(ValueError):kraken_orders(db,adapter,['owned']*11)
    adapter._private_request.side_effect=[{'result':{'owned':{'status':'closed','vol_exec':'1','secret_extra':'excluded'}}},
                                          {'result':{'ZGBP':'401.18','XXBT':'personal'}}]
    result=kraken_orders(db,adapter,['owned'])
    assert result['broker_orders']==0 and result['broker_gbp_cash']=='401.18'
    assert 'personal' not in json.dumps(result) and 'secret_extra' not in json.dumps(result)
    assert [x.args[0] for x in adapter._private_request.call_args_list]==['/0/private/QueryOrders','/0/private/Balance']


def test_cash_ledger_page_is_bounded_and_frozen(tmp_path):
    from ai_trader.readiness_broker_evidence import kraken_cash_page
    db=tmp_path/'cash.db'
    with sqlite3.connect(db) as c:
        c.execute('CREATE TABLE KRAKEN_AI_CAPITAL_LEDGER(event_time TEXT,entry_type TEXT)')
        c.execute("INSERT INTO KRAKEN_AI_CAPITAL_LEDGER VALUES('2026-01-01T00:00:00Z','founder_allocation')")
    adapter=Mock();adapter._private_request.return_value={'result':{'ledger':{},'count':0}}
    with pytest.raises(ValueError):kraken_cash_page(db,adapter,451)
    with pytest.raises(ValueError):kraken_cash_page(db,adapter,end=float('nan'))
    adapter._private_request.assert_not_called()
    page=kraken_cash_page(db,adapter,50,end=1770000000)
    assert page['end']==1770000000 and page['broker_orders']==0
    assert adapter._private_request.call_args.args==('/0/private/Ledgers',{'asset':'ZGBP','start':1767225600.0,'end':1770000000.0,'ofs':50})


def test_targeted_fill_reader_refuses_truncated_evidence():
    c=Mock();c.execute.return_value.fetchall.return_value=[None]*201
    with pytest.raises(ValueError,match='truncated'):_alpaca_fill_rows(c,order_ids=['one'])
    sql,params=c.execute.call_args.args
    assert 'LIMIT 201' in sql and params==('one',)
    with pytest.raises(ValueError,match='twenty'):_alpaca_fill_rows(c,order_ids=[str(n) for n in range(21)])
    assert _alpaca_fill_rows(c,order_ids=[])==[]


def test_legacy_direction_repair_preserves_learning_and_is_idempotent(tmp_path):
    from test_trader_readiness import load_tool
    from test_kraken_reconciliation import trade_fill
    from ai_trader import experiments as e
    from ai_trader.kraken_reconciliation import initialize_kraken_reconciliation_schema,register_kraken_order_ownership,replay_kraken_evidence
    from ai_trader.production_spine import initialize_production_spine_schema
    from ai_trader.canonical_trades import _refresh_trade_aggregate
    db=tmp_path/'legacy.db';initialize_kraken_reconciliation_schema(db)
    initialize_production_spine_schema(db);e.migrate(db)
    for n in (2,6,7,10):
        tid=f'kraken-managed-exit:{n}'
        for role in ('entry','exit'):
            register_kraken_order_ownership(db,broker_order_id=f'{role}{n}',logical_trade_id=tid,
                order_role=role,symbol='XRPGBP',side='buy' if role=='entry' else 'sell')
        replay_kraken_evidence(db,events=[trade_fill(f'entry{n}',f'e{n}','buy',1,f'2026-09-01T12:00:{n:02d}Z'),
                                        trade_fill(f'exit{n}',f'x{n}','sell',1.1,f'2026-09-02T12:00:{n:02d}Z')])
        with e.transaction(db) as c:
            c.execute("UPDATE LOGICAL_TRADES SET side='sell' WHERE logical_trade_id=?",(tid,))
            wrong=_refresh_trade_aggregate(db,tid,conn=c)
            c.execute("INSERT INTO CLOSED_LOOP_LEARNING_RUNS(created_at,logical_trade_id,status,lifecycle_marked,explanation,payload_json) VALUES(?,?,'completed',1,'retained',?)",(e.now_iso(),tid,json.dumps({'repair_evidence':{'original_proposal_id':'original','broker_fill_ids':[f'e{n}',f'x{n}']}})))
            c.execute("UPDATE PERFORMANCE_ATTRIBUTION SET proposal_id=?,side='sell',profit_loss=? WHERE primary_factors_json LIKE ?",(f'exit-{n}',wrong['net_pnl'],'%'+tid+'%'))
    tool=load_tool('repair_legacy_direction')
    assert len(tool.repair(db))==4
    assert all(r['status']=='repaired' for r in tool.repair(db,apply=True))
    assert all(r['status']=='already_applied' for r in tool.repair(db,apply=True))
    with e.transaction(db) as c:
        assert c.execute('SELECT COUNT(*) FROM CLOSED_LOOP_LEARNING_RUNS').fetchone()[0]==4
        assert c.execute("SELECT COUNT(*) FROM LOGICAL_TRADES WHERE side='buy' AND terminal=1").fetchone()[0]==4
