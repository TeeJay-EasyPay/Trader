"""Audited shadow-only rollout. No broker API, paid model calls or backup actions."""
import argparse
import ast
from datetime import timedelta
import json
import os
from pathlib import Path
import subprocess
from ai_trader.config import load_dotenv
from ai_trader import experiments as e


def migrate_schedule(db, now):
    with e.transaction(db) as c:
        if e.uses_postgres():
            c.execute('SELECT pg_advisory_xact_lock(71911501)')
        for record in c.execute("SELECT id FROM RULE_EXPERIMENTS WHERE status IN ('queued','shadow_running') LIMIT 24").fetchall():
            row=e._load(c,record[0])
            if row['spec'].get('weekly_reviews'):
                continue
            previous={'spec':row['spec'].copy(),'version':row['version'],'report':row['report'].copy()}
            row['spec'].update(weekly_reviews=True,evaluation_days=7,maximum_cycles=12,
                               baseline_fingerprint=e.baseline_fingerprint())
            row['version']=e.digest(row['spec'])
            row['state']['next_review_at']=(e.stamp(row['created_at'])+timedelta(days=7)).isoformat()
            row['state'].pop('execution_validation',None)
            row['report']['evaluate_after']=row['state']['next_review_at']
            c.execute('UPDATE RULE_EXPERIMENTS SET version=?,spec_json=? WHERE id=?',
                      (row['version'],e.dump(row['spec']),row['id']))
            e._event(c,row,'weekly_schedule_migrated',previous,'weekly-migration:'+row['id'])
            e._save(c,row)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['pause','migrate','resume','status'])
    args=parser.parse_args()
    load_dotenv(Path('C:/Users/t_jeh/AI Trader/.env'))
    os.environ['DATABASE_URL']=os.environ['AUDIT_DATABASE_URL']
    os.environ['AI_TRADER_DATABASE_BACKEND']='postgres'
    db=Path('.')
    if args.action=='pause':
        with e.transaction(db) as c:
            policy=e.control(c,'policy',e.DEFAULT_POLICY)
            if not e.control(c,'weekly_rollout_previous_policy'):
                e.put_control(c,'weekly_rollout_previous_policy',policy)
            e.put_control(c,'policy',{**policy,'enabled':False})
        print('Shadow scheduling paused for audited rollout. Trading untouched.')
    elif args.action=='migrate':
        # Exact simulator state transition unchanged: evidence may be retained.
        old=subprocess.check_output(['git','show','938bc956:src/ai_trader/experiments.py'],text=True)
        current=Path('src/ai_trader/experiments.py').read_text(encoding='utf-8')
        def step(source):
            return ast.dump(next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='step'))
        if step(old)!=step(current):
            raise RuntimeError('Simulator changed; cannot preserve old evidence under this migration')
        e.migrate(db)
        migrate_schedule(db,e.now_iso())
        from ai_trader.learning_findings import capture
        capture(db,e.now_iso())
        print('Weekly schedules migrated without resetting observations or virtual books.')
    elif args.action=='resume':
        with e.transaction(db) as c:
            prior=e.control(c,'weekly_rollout_previous_policy')
            if not prior:
                raise ValueError('No audited prior policy')
            policy={**prior,'max_active':10}
            e.put_control(c,'policy',policy)
            e.put_control(c,'weekly_rollout_completed',{'at':e.now_iso(),'commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()})
        print(json.dumps(policy))
    else:
        with e.transaction(db) as c:
            rows=c.execute('SELECT id,status,created_at,report_json FROM RULE_EXPERIMENTS ORDER BY created_at DESC LIMIT 24').fetchall()
            print(json.dumps({'policy':e.control(c,'policy'),'experiments':[dict(r) for r in rows],
                              'findings':c.execute('SELECT COUNT(*) FROM LEARNING_FINDINGS').fetchone()[0]},default=str))


if __name__=='__main__':
    main()
