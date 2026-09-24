"""Preview-first prospective admission rollout; no broker or model operations."""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
from uuid import uuid4
from ai_trader import experiments as e
from ai_trader.config import load_dotenv

KEY='informative_admission_rollout_20260924'


def rollout(db, *, apply=False, now=None):
    now=now or e.now_iso()
    with e.transaction(db) as c:
        if e.uses_postgres():
            c.execute('SELECT pg_advisory_xact_lock(71911501)')
            c.execute('SELECT pg_advisory_xact_lock(71911502)')
        if e.control(c,KEY): return {'status':'already_applied'}
        if apply and e.control(c,'lease',{}).get('until','')>now:
            raise ValueError('Experiment worker active; wait for lease completion')
        ids=c.execute("SELECT id FROM RULE_EXPERIMENTS WHERE status='shadow_running' ORDER BY created_at LIMIT 10").fetchall()
        cursor=c.execute('SELECT COALESCE(MAX(decision_id),0) FROM DECISION_JOURNAL').fetchone()[0]
        result=[]
        for item in ids:
            row=e._load(c,item[0])
            if row['spec'].get('admission_policy')=='informative-first-v1':continue
            entry=dict(previous=row['id'],broker=row['spec']['broker'],old_observations=row['state'].get('observations',0))
            if apply:
                spec=deepcopy(row['spec']);spec.update(admission_policy='informative-first-v1',frozen_at=now)
                eid=str(uuid4())
                book=dict(cash=spec['initial_cash'],equity=spec['initial_cash'],peak=spec['initial_cash'],max_drawdown=0,realised=0,positions={})
                state=dict(baseline=deepcopy(book),candidate=deepcopy(book),cursor=cursor,observations=0,blocked=0,supersedes=row['id'])
                c.execute('INSERT INTO RULE_EXPERIMENTS VALUES(?,?,?,?,?,?,?,?,?)',
                    (eid,row['owner'],now,e.digest(spec),'shadow_running',0,e.dump(spec),'{}',e.dump(state)))
                new=e._load(c,eid);new['report']=e.evaluate(new,[],now=e.stamp(now));e._save(c,new)
                e.put_control(c,'experiment_origin:'+eid,{**e.control(c,'experiment_origin:'+row['id'],{'proposed_by':'not_recorded'}),
                    'trigger':'founder_approved_admission_revision','original_experiment':row['id'],
                    'revision_author':'Codex engineering; not a new AI hypothesis'})
                e._event(c,new,'engineering_restart',{'previous_experiment':row['id'],'reason':'Prospective informative admission; no prior observations pooled.'},KEY+':new:'+row['id'])
                row['status']='insufficient_evidence'
                row['report'].update(finished=True,ended_at=now,verdict='insufficient_evidence',
                    reason='Original selection cohort preserved; informative-admission successor '+eid)
                e._event(c,row,'admission_superseded',{'replacement':eid},KEY+':old:'+row['id']);e._save(c,row)
                entry['replacement']=eid
            result.append(entry)
        answer=dict(at=now,experiments=result,broker_orders=0,budget_reset=False,risk_settings_changed=False)
        if apply:e.put_control(c,KEY,answer)
        return answer


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--env',required=True);p.add_argument('--apply',action='store_true')
    a=p.parse_args();load_dotenv(Path(a.env))
    os.environ['DATABASE_URL']=os.environ['AUDIT_DATABASE_URL'];os.environ['AI_TRADER_DATABASE_BACKEND']='postgres'
    print(json.dumps(rollout(Path('.'),apply=a.apply),indent=2))
