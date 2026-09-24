"""One explicitly linked retained closure, preview first. No broker orders or research."""
import argparse
import json
import os
from contextlib import closing
from pathlib import Path
from ai_trader.config import load_dotenv
from ai_trader.database import connect
from ai_trader.alpaca_reconciliation import _alpaca_fill_rows, collapse_fills, pair_round_trips, recorded_exit_evidence
from ai_trader.alpaca_canonical_learning import reconcile_completed


def repair(db, logical_id, *, apply=False):
    with closing(connect(db)) as c:
        trade=c.execute("SELECT proposal_id,broker,side FROM LOGICAL_TRADES WHERE logical_trade_id=?",(logical_id,)).fetchone()
        if not trade or trade[1]!='alpaca' or trade[2]!='buy' or not trade[0]:
            raise ValueError('Owned Alpaca buy decision required')
        links=c.execute("SELECT DISTINCT broker_order_id FROM LOGICAL_TRADE_EVENTS WHERE logical_trade_id=? AND event_source='broker_submission' AND stage IN ('entry_order_linked','exit_order_linked') LIMIT 21",(logical_id,)).fetchall()
        if len(links)>20:raise ValueError('Too many linked orders for bounded repair')
        ids=[r[0] for r in links if r[0]]
        fills=_alpaca_fill_rows(c,order_ids=ids)
        orders=collapse_fills(fills);trips,unmatched=pair_round_trips(orders)
        exits=recorded_exit_evidence(c,[t.exit_order_id for t in trips])
    if any(t.entry_proposal_id!=trade[0] for t in trips) or unmatched:
        raise ValueError('Targeted evidence is not an isolated complete decision')
    preview=dict(logical_trade_id=logical_id,orders=len(orders),fills=len(fills),
                 round_trips=len(trips),broker_orders=0,fees_inferred=False)
    if apply:
        preview['result']=reconcile_completed(db,fills,orders,trips,exits,limit=1,
            checkpoint_key='approved_alpaca_closure_20260925:'+logical_id)
    return preview


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--env',required=True)
    p.add_argument('--logical-id',required=True);p.add_argument('--apply',action='store_true')
    a=p.parse_args();load_dotenv(Path(a.env))
    os.environ['DATABASE_URL']=os.environ['AUDIT_DATABASE_URL'];os.environ['AI_TRADER_DATABASE_BACKEND']='postgres'
    print(json.dumps(repair(Path('.'),a.logical_id,apply=a.apply),indent=2))
