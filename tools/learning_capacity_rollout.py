"""One-time, transactional shadow-only rollout. Preview unless --apply is supplied.

Retain old experiments and all observations. Replace only Kraken comparisons
whose entire recorded sample was skipped and includes a capital-only block.
No broker client, paid inference, risk-policy mutation or historical backfill.
"""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
from uuid import uuid4

from ai_trader import experiments as e
from ai_trader.config import load_dotenv

KEY = 'independent_shadow_capacity_rollout_20260924'


def rollout(db, *, apply=False, now=None):
    now = now or e.now_iso()
    results = []
    with e.transaction(db) as c:
        if e.uses_postgres():
            c.execute('SELECT pg_advisory_xact_lock(71911501)')
            c.execute('SELECT pg_advisory_xact_lock(71911502)')
        if e.control(c, KEY):
            return {'status': 'already_applied', 'result': e.control(c, KEY)}
        lease = e.control(c, 'lease', {})
        if apply and lease.get('until', '') > now:
            raise ValueError('Experiment tick active; wait for its lease to finish')
        records = c.execute("SELECT id FROM RULE_EXPERIMENTS WHERE status='shadow_running' ORDER BY created_at LIMIT 10").fetchall()
        for record in records:
            row = e._load(c, record[0])
            ops = [json.loads(r[0]) for r in c.execute('SELECT payload_json FROM EXPERIMENT_OPPORTUNITIES WHERE experiment_id=? ORDER BY created_at LIMIT 1200', (row['id'],)).fetchall()]
            report = e.evaluate(row, ops, now=e.stamp(now))
            replace = (row['spec']['broker'] == 'kraken'
                       and row['spec']['rule_type'] != 'reference_set_filter'
                       and not row['spec'].get('portfolio_basis') and bool(ops)
                       and all(a['status'] == 'skipped' for o in ops for a in o['arms'].values())
                       and any(set(o.get('rejection_reasons') or []) == {'maximum_capital_allocation_exceeded'} for o in ops))
            item = dict(id=row['id'], broker=row['spec']['broker'], observations=len(ops),
                        both_skipped=report['both_skipped'], informative=report['informative_completed'],
                        action='replace_prospectively' if replace else 'refresh_report_only')
            if apply:
                row['report'] = report
                if replace:
                    spec = deepcopy(row['spec'])
                    spec.update(portfolio_basis='independent-shadow-capacity-v1', max_total_notional_fraction=.25,
                                baseline='recorded safeguards with independent virtual capital only', frozen_at=now)
                    eid = str(uuid4())
                    book = dict(cash=spec['initial_cash'], equity=spec['initial_cash'], peak=spec['initial_cash'],
                                max_drawdown=0, realised=0, positions={})
                    cursor = c.execute('SELECT COALESCE(MAX(decision_id),0) FROM DECISION_JOURNAL').fetchone()[0]
                    state = dict(baseline=deepcopy(book), candidate=deepcopy(book), cursor=cursor,
                                 observations=0, blocked=0, supersedes=row['id'])
                    c.execute('INSERT INTO RULE_EXPERIMENTS VALUES (?,?,?,?,?,?,?,?,?)',
                              (eid,row['owner'],now,e.digest(spec),'shadow_running',0,e.dump(spec),e.dump({}),e.dump(state)))
                    new = e._load(c,eid)
                    new['report'] = e.evaluate(new, [], now=e.stamp(now))
                    e._save(c,new)
                    origin = e.control(c,'experiment_origin:'+row['id'],
                                       {'proposed_by':'Not recorded in original version'})
                    e.put_control(c,'experiment_origin:'+eid, {**origin,
                        'trigger':'founder_approved_independent_capacity_revision',
                        'original_experiment':row['id'],
                        'revision_author':'Codex implementation, not a new AI hypothesis'})
                    e._event(c,new,'engineering_restart',dict(previous_experiment=row['id'],
                        reason='Founder-approved independent virtual capital; original evidence retained, not pooled.'),KEY+':new:'+row['id'])
                    row['status'] = 'insufficient_evidence'
                    row['report'].update(finished=True, ended_at=now, verdict='insufficient_evidence',
                        reason='Capital-blocked sample preserved; prospective independent-capacity comparison '+eid)
                    e._event(c,row,'capacity_research_superseded',dict(replacement=eid),KEY+':old:'+row['id'])
                    item['replacement'] = eid
                e._save(c,row)
            results.append(item)
        result = dict(at=now, experiments=results, broker_orders=0, risk_settings_changed=False)
        if apply:
            e.put_control(c,KEY,result)
    return result


if __name__ == '__main__':
    p=argparse.ArgumentParser();p.add_argument('--apply',action='store_true');p.add_argument('--env',required=True)
    args=p.parse_args();load_dotenv(Path(args.env))
    os.environ['DATABASE_URL']=os.environ['AUDIT_DATABASE_URL']
    os.environ['AI_TRADER_DATABASE_BACKEND']='postgres'
    print(json.dumps(rollout(Path('.'),apply=args.apply),indent=2))
