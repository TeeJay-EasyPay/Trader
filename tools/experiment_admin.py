"""Local operator interface. Default audit is read-only; writes require explicit command.

Never prints credentials. Uses existing configured database, with AUDIT_DATABASE_URL
when present. This tool cannot submit broker orders or enable live trading.
"""
import argparse
import json
import os
from pathlib import Path

from ai_trader.config import load_dotenv
from ai_trader import experiments as e


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['audit', 'migrate', 'enable-shadow', 'disable-shadow', 'queue', 'implementation', 'status'])
    parser.add_argument('--id'); parser.add_argument('--version'); parser.add_argument('--revision', type=int)
    parser.add_argument('--commit', default=''); parser.add_argument('--tests', default=''); parser.add_argument('--deployment', default='')
    parser.add_argument('--status', default='implementing')
    args = parser.parse_args()
    load_dotenv()
    if os.getenv('AUDIT_DATABASE_URL'):
        os.environ['DATABASE_URL'] = os.environ['AUDIT_DATABASE_URL']
        os.environ['AI_TRADER_DATABASE_BACKEND'] = 'postgres'
    db = Path('data/audit.sqlite3')
    if args.command == 'migrate':
        e.migrate(db)
        print(json.dumps({'status': 'migrated', 'enabled': False}))
    elif args.command in ('enable-shadow', 'disable-shadow'):
        with e.transaction(db) as conn:
            if e.uses_postgres():
                conn.execute("SET LOCAL statement_timeout='12s'")
            policy = e.control(conn, 'policy', e.DEFAULT_POLICY)
            policy.update(enabled=args.command == 'enable-shadow', model_enabled=args.command == 'enable-shadow')
            e.put_control(conn, 'policy', policy)
        print(json.dumps(policy))
    elif args.command == 'implementation':
        print(json.dumps(e.implementation_update(db, args.id, version=args.version, revision=args.revision,
            status=args.status, commit=args.commit, tests=args.tests, deployment=args.deployment), default=str))
    elif args.command == 'queue':
        print(json.dumps(e.list_experiments(db, attention=True), default=str))
    elif args.command == 'status':
        from urllib.request import Request, urlopen
        with e.transaction(db) as conn:
            rows = conn.execute('SELECT worker_type,last_heartbeat_at,current_job,deployment_commit FROM WORKER_HEARTBEATS ORDER BY last_heartbeat_at DESC LIMIT 3').fetchall()
            print(json.dumps({'workers': [dict(r) for r in rows]}, default=str))
        request = Request('https://trader-no0f.onrender.com/experiments/health',
                          headers={'Authorization': 'Bearer ' + os.environ['AI_TRADER_API_TOKEN']})
        with urlopen(request, timeout=20) as response:
            print(response.read().decode())
    else:
        with e.transaction(db) as conn:
            # Shape and aggregate checks only, bounded small projections.
            rows = conn.execute('SELECT asset_type,timeframe,adjusted_status,source_quality_status,COUNT(*) AS n,MAX(observation_time) AS latest '
                                'FROM MARKET_DATA_OBSERVATIONS GROUP BY asset_type,timeframe,adjusted_status,source_quality_status').fetchall()
            print(json.dumps({'market_data': [dict(r) for r in rows]}, default=str))
            rows = conn.execute("SELECT decision_id,created_at FROM DECISION_JOURNAL WHERE broker='alpaca' ORDER BY decision_id DESC LIMIT 1").fetchall()
            print(json.dumps({'decisions': [dict(r) for r in rows]}, default=str))
            rows = conn.execute('SELECT asset_type,source,COUNT(*) AS n,MAX(observed_at) AS latest FROM HISTORICAL_CANDLES GROUP BY asset_type,source').fetchall()
            print(json.dumps({'historical_candles': [dict(r) for r in rows]}, default=str))
            if e.uses_postgres():
                print(json.dumps({'database_bytes': conn.execute('SELECT pg_database_size(current_database()) AS bytes').fetchone()[0]}))


if __name__ == '__main__':
    main()
