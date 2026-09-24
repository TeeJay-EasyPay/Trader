"""Align four canonical directions with their already-corrected learning evidence.

Preview first. Preserve old fields and linked attribution in an audit checkpoint.
No new learning runs, orders, fee assumptions or capital changes.
"""
import argparse
import json
import os
from pathlib import Path
from ai_trader import experiments as e
from ai_trader.config import load_dotenv
from ai_trader.canonical_trades import _refresh_trade_aggregate
from ai_trader.kraken_reconciliation import _refresh_reconciled_result


def repair(db, *, apply=False):
    result=[]
    for suffix in (2,6,7,10):
        tid='kraken-managed-exit:'+str(suffix)
        key='legacy_direction_20260925:'+tid
        with e.transaction(db) as c:
            if e.control(c,key):
                result.append(dict(id=tid,status='already_applied'));continue
            before=c.execute('SELECT logical_trade_id,side,terminal,gross_pnl,net_pnl,closed_at FROM LOGICAL_TRADES WHERE logical_trade_id=?',(tid,)).fetchone()
            learning=c.execute('SELECT learning_run_id,status,payload_json FROM CLOSED_LOOP_LEARNING_RUNS WHERE logical_trade_id=?',(tid,)).fetchone()
            if not before or not learning or not before['terminal'] or before['side']!='sell':
                raise ValueError('Expected legacy terminal sell record absent')
            proof=json.loads(learning['payload_json']).get('repair_evidence',{})
            if learning['status']!='completed' or not proof.get('original_proposal_id') or not proof.get('broker_fill_ids'):
                raise ValueError('Existing verified learning repair evidence required')
            fills=c.execute('SELECT fill_role,side,payload_json,broker_order_id FROM LOGICAL_TRADE_FILLS WHERE logical_trade_id=? LIMIT 11',(tid,)).fetchall()
            if len(fills)!=2 or {f['fill_role'] for f in fills}!={'entry','exit'}:
                raise ValueError('Expected isolated two-fill legacy case')
            for f in fills:
                if f['side']!=('buy' if f['fill_role']=='entry' else 'sell'):
                    raise ValueError('Retained direction conflicts')
                owned=c.execute('SELECT order_role FROM KRAKEN_AI_ORDER_OWNERSHIP WHERE broker_order_id=? AND logical_trade_id=?',(f['broker_order_id'],tid)).fetchone()
                if not owned or owned[0]!=f['fill_role']:raise ValueError('Ownership not verified')
            from ai_trader.trade_reasons import to_iso
            exit_at=to_iso(json.loads(next(f['payload_json'] for f in fills if f['fill_role']=='exit')).get('timestamp'))
            if not exit_at:raise ValueError('Verified execution time required')
            ledger=c.execute('SELECT SUM(CAST(amount_gbp AS DOUBLE PRECISION)) FROM KRAKEN_AI_CAPITAL_LEDGER WHERE logical_trade_id=?',(tid,)).fetchone()[0]
            old_net=float(before['net_pnl'])
            # Reversing direction changes gross sign, never fees. Require agreement
            # with the independent cash ledger before touching the canonical row.
            expected=old_net-2*float(before['gross_pnl'])
            if ledger is None or abs(expected-float(ledger))>.001:
                raise ValueError('Corrected direction does not reconcile to cash flows')
            item=dict(id=tid,previous_net=old_net,ledger_net=float(ledger),status='verified_direction_mismatch')
            if apply:
                attrs=[dict(r) for r in c.execute("SELECT attribution_id,side,profit_loss FROM PERFORMANCE_ATTRIBUTION WHERE broker='kraken' AND proposal_id=? LIMIT 3",('exit-'+str(suffix),)).fetchall()]
                if len(attrs)!=1:raise ValueError('Attribution identity is ambiguous')
                # Save provenance before the existing reconciliation helpers commit.
                e.put_control(c,key+':before',dict(canonical=dict(before),attribution=attrs,repair_evidence=proof))
                c.execute("UPDATE LOGICAL_TRADES SET side='buy' WHERE logical_trade_id=? AND side='sell'",(tid,))
                corrected=_refresh_trade_aggregate(db,tid,conn=c)
                if not corrected['terminal'] or abs(float(corrected['net_pnl'])-float(ledger))>.001:
                    raise ValueError('Unexpected corrected aggregate; audit checkpoint retained')
                c.execute('UPDATE LOGICAL_TRADES SET closed_at=? WHERE logical_trade_id=?',(exit_at,tid))
                _refresh_reconciled_result(db,tid,conn=c)
                c.execute("UPDATE PERFORMANCE_ATTRIBUTION SET side='buy',profit_loss=? WHERE attribution_id=?",(corrected['net_pnl'],attrs[0]['attribution_id']))
                e.put_control(c,key,dict(at=e.now_iso(),corrected_net=corrected['net_pnl'],existing_learning_preserved=True,broker_orders=0))
                item.update(status='repaired',corrected_net=corrected['net_pnl'])
            result.append(item)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--env',required=True);p.add_argument('--apply',action='store_true')
    a=p.parse_args();load_dotenv(Path(a.env))
    os.environ['DATABASE_URL']=os.environ['AUDIT_DATABASE_URL'];os.environ['AI_TRADER_DATABASE_BACKEND']='postgres'
    print(json.dumps(repair(Path('.'),apply=a.apply),indent=2))
