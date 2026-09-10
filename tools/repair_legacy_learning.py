"""Preview four identified legacy runs; --apply replays exact reconciled evidence.

No trading, broker requests, model calls, deletion, or invented expectations.
"""
import argparse
import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import psycopg
from ai_trader.config import load_dotenv


def reconcile_fills(rows):
    unique = {}
    for fill_id, side, qty, cost, fee, at in rows:
        item = (side, Decimal(str(qty)), Decimal(str(cost)), Decimal(str(fee)), str(at))
        if fill_id in unique and unique[fill_id] != item:
            raise ValueError('Conflicting snapshots for broker fill ' + fill_id)
        unique[fill_id] = item
    buys = [r for r in unique.values() if r[0] == 'buy']
    sells = [r for r in unique.values() if r[0] == 'sell']
    if not buys or not sells or len(buys) + len(sells) != len(unique):
        raise ValueError('Missing or unsupported fill direction')
    quantity = sum(r[1] for r in buys)
    if quantity <= 0 or quantity != sum(r[1] for r in sells):
        raise ValueError('Round-trip quantities do not match')
    entry_cost = sum(r[2] for r in buys)
    exit_cost = sum(r[2] for r in sells)
    fees = sum(r[3] for r in unique.values())
    if fees < 0:
        raise ValueError('Negative fee requires separate reconciliation')
    entry_time = min(Decimal(r[4]) for r in buys)
    exit_time = max(Decimal(r[4]) for r in sells)
    return {'side': 'buy', 'quantity': float(quantity), 'entry_price': float(entry_cost/quantity),
        'exit_price': float(exit_cost/quantity), 'profit_loss': float(exit_cost-entry_cost),
        'gross_realized_pnl': float(exit_cost-entry_cost), 'exchange_fee': float(fees),
        'broker_fee': 0.0, 'fees_status': 'recorded', 'net_realized_pnl': float(exit_cost-entry_cost-fees),
        'entry_time': datetime.fromtimestamp(float(entry_time),timezone.utc).isoformat(),
        'exit_time': datetime.fromtimestamp(float(exit_time),timezone.utc).isoformat(),
        'holding_seconds': float(exit_time-entry_time), 'broker_fill_ids': sorted(unique)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply',action='store_true')
    args = parser.parse_args()
    load_dotenv()
    packets = []
    with psycopg.connect(os.environ['AUDIT_DATABASE_URL']) as c:
        c.read_only = True
        c.execute("SET LOCAL statement_timeout='15s'")
        for run_id, managed_id in [(1,2),(2,6),(3,10),(4,7)]:
            row = c.execute('''SELECT r.logical_trade_id,r.symbol,r.status,
                m.entry_order_id,m.exit_order_id,m.side,m.exit_reason,
                r.payload_json::jsonb#>>'{repair_assessment,matched_original_proposal_id}'
                FROM closed_loop_learning_runs r JOIN managed_trade_exits m ON m.managed_exit_id=%s
                WHERE r.learning_run_id=%s''',(managed_id,run_id)).fetchone()
            if row[2] != 'completed_insufficient_evidence':
                print({'run':run_id,'status':'already_processed'})
                continue
            if row[5] != 'buy' or not row[7]:
                raise ValueError('Original identity not established')
            decision = c.execute('''SELECT jsonb_build_object('proposal',jsonb_build_object(
                'proposal_id',proposal_id,'symbol',symbol,'side',side,'asset_type',asset_type,
                'entry_price',decision_context_json::jsonb#>'{proposal,entry_price}',
                'stop_loss',decision_context_json::jsonb#>'{proposal,stop_loss}',
                'take_profit',decision_context_json::jsonb#>'{proposal,take_profit}'),
                'evidence_basis','original canonical decision snapshot',
                'historical_fee_expectation','unavailable', 'stop_activation_verified',false)
                FROM logical_trades WHERE proposal_id=%s AND broker='kraken'
                AND EXISTS (SELECT 1 FROM logical_trade_events e WHERE e.logical_trade_id=logical_trades.logical_trade_id
                    AND e.broker_order_id=%s)''',(row[7],row[3])).fetchall()
            if len(decision) != 1:
                raise ValueError('Ambiguous original decision')
            fills = c.execute('''SELECT external_id,side,quantity,payload_json::jsonb->>'cost',
                payload_json::jsonb->>'fee',payload_json::jsonb->>'time'
                FROM broker_trade_history WHERE broker='kraken' AND status='filled'
                AND payload_json::jsonb->>'ordertxid' IN (%s,%s)''',(row[3],row[4])).fetchall()
            attribution = reconcile_fills(fills)
            attribution.update(proposal_id=row[7],symbol=row[1],exit_reason=row[6])
            proof = {'broker_fill_ids': attribution.pop('broker_fill_ids'),'original_proposal_id':row[7],
                     'basis':'deduplicated broker fill costs and fees; matched entry order identity'}
            packets.append((row[0],row[1],attribution,decision[0][0],proof))
            print({'run':run_id,'gross':attribution['profit_loss'],'fees':attribution['exchange_fee'],
                   'net':attribution['net_realized_pnl'],'fill_ids':proof['broker_fill_ids']})
    if args.apply:
        os.environ['DATABASE_URL']=os.environ['AUDIT_DATABASE_URL']
        os.environ['AI_TRADER_DATABASE_BACKEND']='postgres'
        from ai_trader.production_spine import run_closed_loop_learning
        for logical,symbol,attribution,decision,proof in packets:
            result=run_closed_loop_learning(Path('data/trader.db'),logical_trade_id=logical,
                broker='kraken',symbol=symbol,attribution=attribution,decision_context=decision,repair_evidence=proof)
            print({'logical_trade_id':logical,'status':result['status'],'experience':result.get('experience')})


if __name__ == '__main__':
    main()
