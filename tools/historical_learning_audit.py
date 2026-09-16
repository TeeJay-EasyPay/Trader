"""Small read-only production readiness check; no price exports or paid calls."""
import argparse
import json
import os
from pathlib import Path
from ai_trader.config import load_dotenv
from ai_trader import experiments as e

parser = argparse.ArgumentParser()
parser.add_argument('--env', type=Path, default=Path('.env'))
parser.add_argument('--dataset', action='store_true', help='Read the bounded replay sample; print counts only')
args = parser.parse_args()
load_dotenv(args.env)
if os.getenv('AUDIT_DATABASE_URL'):
    os.environ['DATABASE_URL'] = os.environ['AUDIT_DATABASE_URL']
    os.environ['AI_TRADER_DATABASE_BACKEND'] = 'postgres'
if not e.uses_postgres():
    raise SystemExit('No configured production PostgreSQL connection; refusing local fallback.')
with e.transaction(Path('data/audit.sqlite3')) as conn:
    conn.execute('SET TRANSACTION READ ONLY')
    rows = conn.execute("SELECT r.spec_json::jsonb->>'broker' AS broker,COUNT(*) AS stored_rows,"
        "COUNT(DISTINCT o.source_id) AS unique_sources,COUNT(DISTINCT SUBSTRING(o.created_at,1,10)) AS signal_days,"
        "MIN(o.created_at) AS first_signal,MAX(o.created_at) AS latest_signal,"
        "SUM(CASE WHEN jsonb_array_length(COALESCE(o.payload_json::jsonb->'bars','[]'::jsonb))>0 THEN 1 ELSE 0 END) AS rows_with_bars "
        "FROM EXPERIMENT_OPPORTUNITIES o JOIN RULE_EXPERIMENTS r ON r.id=o.experiment_id GROUP BY 1").fetchall()
    coverage = [dict(row) for row in rows]
    worker = conn.execute('SELECT last_heartbeat_at,deployment_commit FROM WORKER_HEARTBEATS ORDER BY last_heartbeat_at DESC LIMIT 1').fetchone()
    print(json.dumps(dict(coverage=coverage,worker=dict(worker) if worker else None,
        measurement=e.control(conn,'learning_measurement_view',{}),
        historical=e.control(conn,'historical_screening_view',{})),default=str))
if args.dataset:
    from ai_trader.historical_screening import dataset
    for broker in ('alpaca','kraken'):
        with e.transaction(Path('data/audit.sqlite3')) as conn:
            conn.execute('SET TRANSACTION READ ONLY')
            sample=dataset(conn,broker,e.now_iso())
        print(json.dumps(dict(broker=broker,signals=len(sample['signals']),bars=len(sample['bars']),
            days=len({s['time'][:10] for s in sample['signals']}),
            reason=sample.get('reason'),scope=sample.get('scope'))))
