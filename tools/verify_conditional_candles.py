"""Read-only, bounded production parity check; no schema setup or broker calls."""
import argparse
import json
import os
from pathlib import Path
from ai_trader.config import load_dotenv
from ai_trader.database import PostgresConnection
from ai_trader.candle_read_cache import read

p=argparse.ArgumentParser()
p.add_argument('--env',type=Path,default=Path('.env'))
a=p.parse_args()
load_dotenv(a.env)
c=PostgresConnection(os.environ.get('AUDIT_DATABASE_URL') or os.environ['DATABASE_URL'])
try:
    c._conn.read_only=True
    c.execute("SET LOCAL statement_timeout='5s'")
    symbols=c.execute("SELECT normalized_symbol FROM MARKET_DATA_OBSERVATIONS ORDER BY observation_id DESC LIMIT 3").fetchall()
    for symbol in dict.fromkeys(r[0] for r in symbols):
        old=[dict(r) for r in c.execute('''SELECT observation_time,open,high,low,close,volume FROM
          (SELECT observation_time,open,high,low,close,volume FROM MARKET_DATA_OBSERVATIONS
           WHERE normalized_symbol=? AND timeframe=? ORDER BY observation_time DESC LIMIT 120) x
          ORDER BY observation_time ASC''',(symbol,'1d')).fetchall()]
        first=read(c,symbol,'1d',120)
        second=read(c,symbol,'1d',120)
        assert old==first==second
        print(json.dumps({'symbol':symbol,'rows':len(old),'parity':True,
                          'prior_json_bytes':len(json.dumps(old).encode()),
                          'unchanged_transfer':'one digest and null payload; excludes protocol overhead'}))
finally:
    c.close()
