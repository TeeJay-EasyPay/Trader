"""Repair bounded owned closures only when exact saved fills balance. Preview first.

No live order is cancelled or submitted. Never treats a small real remainder as
zero. Immutable fills are retained; original aggregate scalars are audit-recorded.
"""
import argparse
from decimal import Decimal
import json
import os
from pathlib import Path
from uuid import uuid4
from ai_trader import experiments as e
from ai_trader.config import load_dotenv
from ai_trader.canonical_trades import _refresh_trade_aggregate, canonical_trade
from ai_trader.kraken_reconciliation import _refresh_reconciled_result, _mark_managed_exit_reconciled, _learning_payload


def repair(db, *, apply=False):
    results=[]
    with e.transaction(db) as c:
        candidates=c.execute("""SELECT logical_trade_id FROM LOGICAL_TRADES
            WHERE broker='kraken' AND terminal=0 AND remaining_quantity>0
              AND exit_filled_quantity>0 AND logical_trade_id IN
              (SELECT logical_trade_id FROM KRAKEN_AI_ORDER_OWNERSHIP)
            ORDER BY logical_trade_id LIMIT 8""").fetchall()
    for (tid,) in ((r[0],) for r in candidates):
        with e.transaction(db) as c:
            if apply and e.uses_postgres():
                c.execute('SELECT logical_trade_id FROM LOGICAL_TRADES WHERE logical_trade_id=? FOR UPDATE',(tid,))
            before=dict(c.execute('SELECT logical_trade_id,state,terminal,remaining_quantity,entry_filled_quantity,exit_filled_quantity,net_pnl,updated_at FROM LOGICAL_TRADES WHERE logical_trade_id=?',(tid,)).fetchone())
            fills=c.execute('SELECT fill_role,payload_json,broker_order_id FROM LOGICAL_TRADE_FILLS WHERE logical_trade_id=? ORDER BY fill_id LIMIT 51',(tid,)).fetchall()
            totals={'entry':Decimal(0),'exit':Decimal(0)}
            valid=bool(fills) and len(fills)<=50
            for f in fills:
                p=json.loads(f['payload_json'])
                owned=c.execute('SELECT order_role FROM KRAKEN_AI_ORDER_OWNERSHIP WHERE logical_trade_id=? AND broker_order_id=?',(tid,f['broker_order_id'])).fetchone()
                if p.get('record_type')!='trade_fill' or f['fill_role'] not in totals or not owned or owned[0]!=f['fill_role']:
                    valid=False;break
                q=Decimal(str(p.get('filled_quantity')))
                if not q.is_finite() or q<=0:valid=False;break
                totals[f['fill_role']]+=q
            if not valid or not totals['entry'] or totals['entry']!=totals['exit']:
                results.append({'id':tid,'status':'not_exactly_balanced_no_change'});continue
            item={'id':tid,'status':'verified_exact_fill_balance','previous_remaining':before['remaining_quantity']}
            from ai_trader.trade_reasons import to_iso
            exit_times=[to_iso(json.loads(f['payload_json']).get('timestamp'))
                        for f in fills if f['fill_role']=='exit']
            if not exit_times or any(t is None for t in exit_times):
                results.append({'id':tid,'status':'missing_exit_timestamp_no_change'});continue
            if apply:
                before['managed_controls']=[dict(r) for r in c.execute("""SELECT managed_exit_id,status,updated_at,last_checked_at
                    FROM MANAGED_TRADE_EXITS WHERE broker='kraken' AND status IN ('open','exit_submitted')
                    AND managed_exit_id IN (SELECT managed_exit_id FROM KRAKEN_AI_ORDER_OWNERSHIP
                    WHERE logical_trade_id=? AND order_role='exit') LIMIT 12""",(tid,)).fetchall()]
                trade=_refresh_trade_aggregate(db,tid,conn=c)
                if not trade['terminal']:raise ValueError('Exact evidence did not produce a closed aggregate')
                # The repair date is not the execution date. Preserve the real
                # latest exit time so daily learning does not count an old exit today.
                c.execute('UPDATE LOGICAL_TRADES SET closed_at=? WHERE logical_trade_id=?',
                          (max(exit_times),tid))
                result=_refresh_reconciled_result(db,tid,conn=c)
                _mark_managed_exit_reconciled(db,logical_trade_id=tid,result=result,conn=c)
                full=canonical_trade(db,tid,conn=c)
                payload={'broker':'kraken',**_learning_payload(full,result)}
                now=e.now_iso()
                c.execute("""INSERT INTO SPRINT6_WORKFLOW_OUTBOX
                    (workflow_id,created_at,workflow_type,entity_id,status,attempts,next_attempt_at,last_error,payload_json,idempotency_key)
                    VALUES(?,?,'closed_loop_learning',?,'pending',0,?,NULL,?,?)
                    ON CONFLICT(idempotency_key) DO NOTHING""",
                    (str(uuid4()),now,tid,now,json.dumps(payload,default=str),'closed-loop-learning:kraken:'+tid))
                e.put_control(c,'verified_closure_repair_20260924:'+tid,{'at':now,'before':before,'after_terminal':True,'broker_orders':0})
                item['status']='repaired_and_learning_queued_or_existing'
            results.append(item)
    return {'items':results,'broker_orders':0,'risk_limits_changed':False}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--env',required=True);p.add_argument('--apply',action='store_true')
    a=p.parse_args();load_dotenv(Path(a.env))
    os.environ['DATABASE_URL']=os.environ['AUDIT_DATABASE_URL'];os.environ['AI_TRADER_DATABASE_BACKEND']='postgres'
    print(json.dumps(repair(Path('.'),apply=a.apply),indent=2))
