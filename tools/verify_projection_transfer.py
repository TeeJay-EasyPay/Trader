"""Read-only production parity check. No model calls, broker calls, writes or DDL."""
import argparse
import json
import os
import time
from pathlib import Path
from unittest.mock import patch
from ai_trader.config import load_dotenv
from ai_trader.database import PostgresConnection, clear_schema_cache
from ai_trader import projection_transfer as transfer, production_evidence as p, alpaca_reconciliation as a

parser=argparse.ArgumentParser()
parser.add_argument('--env', type=Path, required=True)
args=parser.parse_args()
load_dotenv(args.env)
os.environ['AI_TRADER_DATABASE_BACKEND']='postgres'
os.environ['DATABASE_URL']=os.environ.get('AUDIT_DATABASE_URL') or os.environ['DATABASE_URL']
c=PostgresConnection(os.environ.get('AUDIT_DATABASE_URL') or os.environ['DATABASE_URL'])
c._conn.read_only=True
c._conn.execute("SET statement_timeout='8s'")
queries=[]
class Meter:
    def __init__(self,raw): self.raw=raw; self.info=raw.info; self.last_bytes=0
    def execute(self,*args):
        row=self.raw.execute(*args).fetchone()
        self.last_bytes=len(json.dumps(row).encode())
        from types import SimpleNamespace
        return SimpleNamespace(fetchone=lambda:row)
meter=Meter(c._conn)
def capture(db, batch, **kw):
    queries.extend((q.format(x='%s', n=100),v) for q,v in batch)
    return [[] for _ in batch]
try:
    with patch.object(p,'_query_batch',capture):
        p._load_founder_evidence_rows(Path('unused'),since='2026-08-15T00:00:00+00:00',trade_limit=100)
    queries.append(('SELECT * FROM public.KRAKEN_RECONCILED_RESULTS ORDER BY updated_at DESC',()))
    for index,(sql,params) in enumerate(queries):
        old=[dict(r) for r in c._conn.execute(sql,params).fetchall()]
        started=time.monotonic()
        first=transfer.read(meter,sql,params)
        second=transfer.read(meter,sql,params)
        assert old==first==second, f'Projection {index} differs'
        print(json.dumps(dict(projection=index,rows=len(old),old_json_bytes=len(json.dumps(old).encode()),
                              unchanged_json_bytes=meter.last_bytes,
                              parity=True,two_conditional_seconds=round(time.monotonic()-started,3))))
    # Same production fill SELECT, with only transfer disabled for the control.
    def direct(raw,sql,values=(),columns=None):
        names='('+','.join(columns)+')' if columns else ''
        return list(raw.execute(f'WITH selected{names} AS ({sql}) SELECT * FROM selected',values).fetchall())
    with patch.object(transfer,'read',direct):
        old=a._alpaca_fill_rows(c)
    assert old==a._alpaca_fill_rows(c)
    print(json.dumps(dict(alpaca_fills=len(old),parity=True)))
    for table in ('BROKER_TRADE_HISTORY','KRAKEN_RECONCILED_RESULTS'):
        clear_schema_cache()
        first=c._table_info(table).fetchall()
        clear_schema_cache()
        assert first==c._table_info(table).fetchall()
        assert first and any(r['pk'] for r in first)
        print(json.dumps(dict(schema=table,columns=len(first),parity=True)))
finally:
    c.close()
