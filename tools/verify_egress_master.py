"""Read-only release parity check; no orders, models, DDL or database writes."""
import ast
import os
from pathlib import Path
from unittest.mock import patch
from ai_trader.config import load_dotenv
from ai_trader import production_evidence as p, projection_transfer as t, db_telemetry as m
from ai_trader.database import PostgresConnection

load_dotenv(Path(os.environ["TRADER_AUDIT_ENV"]))
os.environ["AI_TRADER_DATABASE_BACKEND"]="postgres"
os.environ["DATABASE_URL"]=os.environ.get("AUDIT_DATABASE_URL") or os.environ["DATABASE_URL"]
c=PostgresConnection(os.environ["DATABASE_URL"])
c._conn.read_only=True
queries=[]
def capture(db,batch,**kw):
    queries.extend(batch)
    return [[] for _ in batch]
try:
    with patch.object(p,"_query_batch",capture):
        p._load_founder_evidence_rows(Path("unused"),since="2026-09-15",trade_limit=100)
    sql,values=next((s,v) for s,v in queries if "FROM PRODUCTION_BROKER_SNAPSHOTS" in s)
    keys=", ".join("'"+k+"', payload_json::jsonb->'"+k+"'" for k in p._BROKER_FOUNDER_PAYLOAD_KEYS)
    projected=sql.replace("payload_json","jsonb_build_object("+keys+")::text AS payload_json",1)
    def broker_shape(rows):
        result=[]
        for row in rows:
            r=p._lift_broker_payload_fields(p._decode_row(row,{"payload_json","positions_json"}))
            r.pop("payload_json",None);r.pop("positions_json",None)
            r["payload"]=p._compact_broker_payload_for_founder(r.get("payload"))
            result.append(r)
        return result
    raw=list(c._conn.execute(sql,values).fetchall())
    optimized=t.read(c._conn,projected,values)
    assert broker_shape(raw)==broker_shape(optimized)
    print("Broker summary semantic parity passed",len(raw))
    module=ast.parse(Path("src/ai_trader/foundation.py").read_text())
    fn=next(n for n in module.body if isinstance(n,ast.FunctionDef) and n.name=="load_trading_policy")
    policy=next(n.value.value for n in ast.walk(fn) if isinstance(n,ast.Assign) and any(isinstance(a,ast.Name) and a.id=="policy_sql" for a in n.targets))
    expected=list(c._conn.execute(policy).fetchall())
    assert t.read(c._conn,policy)==expected==t.read(c._conn,policy)
    print("Policy fresh/warm parity passed",len(expected))
    m._pending={}
    cur=c._conn.execute("SELECT n FROM generate_series(1,4) n")
    assert cur.fetchone()["n"]==1
    assert cur.fetchmany(1)[0]["n"]==2
    assert [r["n"] for r in cur]==[3,4]
    assert sum(x.get("rows",0) for x in m._pending.values())==4
    assert sum(x.get("row_bytes",0) for x in m._pending.values())==4
    print("Real psycopg fetchone/fetchmany/iteration measured once per row")
finally:
    c.close()
