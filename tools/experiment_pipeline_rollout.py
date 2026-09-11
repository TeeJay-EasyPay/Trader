"""Audited shadow-only release; preserves legacy simulation evidence, no orders."""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
from ai_trader.config import load_dotenv
from ai_trader import experiments as e

BASE='8b187cef55b9a273188aea7855ae44b5326733e9'
KEY='pipeline_rollout_20260911'

def git_source(path):
    return subprocess.check_output(['git','show',BASE+':'+path],encoding='utf-8')

def verify_legacy_engine():
    def functions(source):
        return {n.name:ast.dump(n) for n in ast.parse(source).body if isinstance(n,ast.FunctionDef)}
    for filename,names in [('experiments.py',['step','passes','number','settle_bars']),
                           ('experiment_worker.py',['_decisions','_bars'])]:
        path='src/ai_trader/'+filename
        old,new=functions(git_source(path)),functions(Path(path).read_text(encoding='utf-8'))
        for name in names:
            if old[name]!=new[name]:raise ValueError('Legacy engine changed: '+name)
    for filename in ['sprint6.py','guardrails.py','decision_economics.py','experiment_market_data.py']:
        path='src/ai_trader/'+filename
        if git_source(path).replace('\r\n','\n')!=Path(path).read_text(encoding='utf-8').replace('\r\n','\n'):
            raise ValueError('Legacy controls changed: '+filename)
    names=('experiments.py','experiment_worker.py','experiment_market_data.py','experiment_assurance.py',
           'sprint6.py','guardrails.py','decision_economics.py')
    return hashlib.sha256(b''.join(git_source('src/ai_trader/'+n).replace('\r\n','\n').encode() for n in names)).hexdigest()

def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['verify','pause','migrate','resume','status'])
    args=p.parse_args()
    if args.action=='verify':print(verify_legacy_engine());return
    load_dotenv(Path('C:/Users/t_jeh/AI Trader/.env'))
    os.environ['DATABASE_URL']=os.environ['AUDIT_DATABASE_URL'];os.environ['AI_TRADER_DATABASE_BACKEND']='postgres'
    with e.transaction(Path('.')) as c:
        if e.uses_postgres():c.execute('SELECT pg_advisory_xact_lock(71911501)')
        policy=e.control(c,'policy',e.DEFAULT_POLICY)
        if args.action=='pause':
            if not e.control(c,KEY):e.put_control(c,KEY,dict(previous_policy=policy,at=e.now_iso()))
            e.put_control(c,'policy',{**policy,'enabled':False})
            print('Shadow scheduling paused; broker trading untouched.')
        elif args.action=='migrate':
            old=verify_legacy_engine()
            if policy['enabled'] or e.stamp(e.control(c,'lease',{}).get('until','2000-01-01T00:00:00+00:00'))>e.stamp(e.now_iso()):
                raise ValueError('Shadow worker must be paused and lease idle')
            for record in c.execute("SELECT id FROM RULE_EXPERIMENTS WHERE status IN ('queued','shadow_running') LIMIT 24").fetchall():
                row=e._load(c,record[0]);spec=row['spec']
                if spec['baseline_fingerprint']==e.baseline_fingerprint():continue
                if spec['baseline_fingerprint']!=old or spec['rule_type'] not in ('minimum_target_r','replace_target_r_gate'):
                    raise ValueError('Unverified legacy experiment: '+row['id'])
                previous=dict(version=row['version'],spec=spec.copy())
                spec['baseline_fingerprint']=e.baseline_fingerprint()
                row['version']=e.digest(spec)
                c.execute('UPDATE RULE_EXPERIMENTS SET version=?,spec_json=? WHERE id=?',(row['version'],e.dump(spec),row['id']))
                e._event(c,row,'compatible_engine_release',dict(previous=previous,
                    reason='Legacy fills, exits and eligibility unchanged; new rule branches isolated. Books, observations and schedule retained.'),KEY+':'+row['id'])
                print('Preserved experiment '+row['id'])
        elif args.action=='resume':
            prior=e.control(c,KEY)
            if not prior:raise ValueError('Missing prior policy')
            e.put_control(c,'policy',prior['previous_policy'])
            e.put_control(c,KEY+':completed',dict(at=e.now_iso(),commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()))
            print('Prior shadow policy restored, including unchanged spending limits.')
        else:
            print(json.dumps(dict(policy=policy,lease=e.control(c,'lease'),
                experiments=[dict(r) for r in c.execute('SELECT id,status,version FROM RULE_EXPERIMENTS ORDER BY created_at DESC LIMIT 12').fetchall()]),default=str))

if __name__=='__main__':main()
