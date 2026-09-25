"""Read-only bounded GBP cash bridge; prints aggregates, never exports histories."""
import argparse
from collections import defaultdict
from decimal import Decimal
import json
import os
from pathlib import Path
import urllib.request
import psycopg
from ai_trader.config import load_dotenv


def main():
    p=argparse.ArgumentParser();p.add_argument('--env',required=True);a=p.parse_args()
    load_dotenv(Path(a.env))
    entries={};end=None;total=None
    for offset in range(0,401,50):
        body={'offset':offset}
        if end is not None:body['end']=end
        req=urllib.request.Request('https://trader-no0f.onrender.com/readiness/kraken-cash-ledger',
            data=json.dumps(body).encode(),headers={'Authorization':'Bearer '+os.environ['AI_TRADER_API_TOKEN'],'Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=40) as r:page=json.load(r)
        end=page['end'];total=page['count']
        if not isinstance(total,int) or total>450:raise ValueError('Ledger exceeds bounded audit; no complete-bridge claim')
        entries.update(page['entries'])
        if len(entries)>=total:break
    if len(entries)!=total or not entries:raise ValueError('Incomplete or empty cash interval')
    with psycopg.connect(os.environ['AUDIT_DATABASE_URL'],options='-c default_transaction_read_only=on -c statement_timeout=8000') as c:
        rows=c.execute("""SELECT COALESCE(payload_json::jsonb#>>'{raw,id}',broker_fill_id),
                   amount_gbp::double precision FROM kraken_ai_capital_ledger
                   WHERE entry_type IN('entry_fill','exit_fill') LIMIT 1001""").fetchall()
        if len(rows)>1000:raise ValueError('Internal ledger exceeds audit bound')
        allocation=Decimal(str(c.execute("SELECT SUM(amount_gbp::double precision) FROM kraken_ai_capital_ledger WHERE entry_type='founder_allocation'").fetchone()[0]))
    local=defaultdict(Decimal)
    for ref,amount in rows:local[ref]+=Decimal(str(amount))
    matched=set();broker_net=Decimal(0);unmatched=defaultdict(Decimal);diff=Decimal(0);examples=[]
    sequence=sorted(entries.values(),key=lambda x:Decimal(str(x['time'])))
    for item in sequence:
        if item['asset'] not in ('GBP','ZGBP'):raise ValueError('Unexpected currency')
        delta=Decimal(item['amount'])-Decimal(item['fee']);broker_net+=delta
        ref=item['refid']
        if ref in local:
            matched.add(ref);diff+=delta-local[ref]
        else:
            unmatched[item['type']]+=delta
            if len(examples)<12:examples.append(dict(ref=ref,type=item['type'],net=str(delta),at=item['time']))
    opening=Decimal(sequence[0]['balance'])-Decimal(sequence[0]['amount'])+Decimal(sequence[0]['fee'])
    closing=Decimal(sequence[-1]['balance'])
    print(json.dumps(dict(entries=len(entries),pages=offset//50+1,frozen_end=end,
        opening_broker_cash=str(opening),broker_cash_movements=str(broker_net),closing_broker_cash=str(closing),
        bridge_residual=str(closing-opening-broker_net),internal_allocation=str(allocation),
        internal_cash=str(allocation+sum(local.values())),matched_refs=len(matched),
        matched_value_difference=str(diff),unmatched_broker_by_type={k:str(v) for k,v in unmatched.items()},
        unmatched_broker_examples=examples,unmatched_internal_count=len(set(local)-matched),
        unmatched_internal_cash=str(sum(local[k] for k in set(local)-matched)),
        broker_orders=0,limitation='Cash-flow match is not permission to assign unmatched movements to Trader or alter its capital.'),indent=2))


if __name__=='__main__':main()
