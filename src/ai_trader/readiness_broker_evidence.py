"""Founder diagnostic only: bounded, ownership-filtered broker reads. No orders."""
from contextlib import closing
from .database import connect


def kraken_orders(db, adapter, order_ids):
    if not isinstance(order_ids,list) or not 1<=len(order_ids)<=10 or any(not isinstance(x,str) or not x for x in order_ids):
        raise ValueError('One to ten explicit owned order IDs required')
    ids=sorted(set(order_ids))
    with closing(connect(db)) as c:
        rows=c.execute('SELECT broker_order_id FROM KRAKEN_AI_ORDER_OWNERSHIP WHERE broker_order_id IN ('+
                       ','.join('?' for _ in ids)+')',tuple(ids)).fetchall()
    if {r[0] for r in rows}!=set(ids):
        raise ValueError('Every requested order must have recorded Trader ownership')
    # Fixed read-only method names: never accept a client-selected broker endpoint.
    response=adapter._private_request('/0/private/QueryOrders',{'txid':','.join(ids),'trades':'true'})
    result=response.get('result',{})
    balance=adapter._private_request('/0/private/Balance').get('result',{})
    fields=('status','vol','vol_exec','cost','fee','price','opentm','closetm','trades')
    return dict(read_only=True,broker_orders=0,broker='kraken',
        broker_gbp_cash=balance.get('ZGBP',balance.get('GBP')),
        orders={oid:{**{k:result[oid].get(k) for k in fields},
                     'description':{k:result[oid].get('descr',{}).get(k) for k in ('pair','type','ordertype')}}
                for oid in ids if oid in result},
        missing_order_ids=[oid for oid in ids if oid not in result],
        limitation='Whole-account GBP cash is a spendability ceiling, not proof of ring-fenced ledger ownership. No settings or records changed.')
