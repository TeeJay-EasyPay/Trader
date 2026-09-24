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


def test_targeted_fill_reader_refuses_truncated_evidence():
    c=Mock();c.execute.return_value.fetchall.return_value=[None]*201
    with pytest.raises(ValueError,match='truncated'):_alpaca_fill_rows(c,order_ids=['one'])
    sql,params=c.execute.call_args.args
    assert 'LIMIT 201' in sql and params==('one',)
    with pytest.raises(ValueError,match='twenty'):_alpaca_fill_rows(c,order_ids=[str(n) for n in range(21)])
    assert _alpaca_fill_rows(c,order_ids=[])==[]
