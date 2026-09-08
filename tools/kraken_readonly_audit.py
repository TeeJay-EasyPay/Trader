"""Bounded, read-only production evidence collection for the Kraken review."""
import argparse
import json
import os
from urllib.request import Request, urlopen

from ai_trader.config import load_dotenv

load_dotenv()
parser = argparse.ArgumentParser()
parser.add_argument("mode", choices=["api", "schema", "sql"])
parser.add_argument("query")
parser.add_argument("--field")
args = parser.parse_args()
if args.mode == "api":
    req = Request("https://trader-no0f.onrender.com" + args.query,
                  headers={"Authorization": "Bearer " + os.environ["AI_TRADER_API_TOKEN"]})
    with urlopen(req, timeout=45) as response:
        result = json.load(response)
    if args.field:
        result = result.get(args.field)
    def compact(value):
        if isinstance(value, dict):
            return {k: compact(v) for k, v in value.items() if k not in {"payload", "raw_payload", "payload_json", "raw_balances", "raw_balance_rows"}}
        if isinstance(value, list):
            return [compact(v) for v in value[:12]]
        return value[:1600] if isinstance(value, str) else value
    print(json.dumps(compact(result)))
else:
    import psycopg
    from psycopg.rows import dict_row
    with psycopg.connect(os.environ["AUDIT_DATABASE_URL"], connect_timeout=15,
                         options="-c default_transaction_read_only=on -c statement_timeout=20000",
                         row_factory=dict_row) as conn:
        if args.mode == "schema":
            rows = conn.execute("SELECT table_name, column_name, data_type FROM information_schema.columns WHERE table_schema='public' AND table_name ILIKE %s ORDER BY table_name, ordinal_position", (args.query,)).fetchall()
        else:
            rows = conn.execute(args.query).fetchall()
        print(json.dumps(rows, default=str))
