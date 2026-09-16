"""Compact daily observations, same-version daily/weekly comparisons, no inference calls."""
from datetime import timedelta
from . import experiments as e
from .experiment_assurance import json_field


def _projection():
    fields = {'broker':('spec_json',['broker']), 'currency':('spec_json',['currency']), 'hypothesis':('spec_json',['hypothesis']),
        'observations':('report_json',['observations']), 'completed':('report_json',['completed']),
        'usable':('report_json',['usable']), 'days':('report_json',['day_clusters']),
        'uncertain':('report_json',['uncertain']), 'verdict':('report_json',['verdict']),
        'baseline_net':('report_json',['baseline','realised']), 'candidate_net':('report_json',['candidate','realised']),
        'baseline_drawdown':('report_json',['baseline','max_drawdown']),
        'candidate_drawdown':('report_json',['candidate','max_drawdown'])}
    return ','.join(json_field(col,path)+' AS '+name for name,(col,path) in fields.items())


def differences(current, previous):
    """No pooling currencies, versions, or dependent experiments into an app return."""
    by_key = {(r['id'],r['version']):r for r in previous.get('experiments', [])}
    result = []
    for row in current['experiments']:
        before = by_key.get((row['id'],row['version']))
        if not before or any(row.get(k) is None or before.get(k) is None for k in ('baseline_net','candidate_net')):
            continue
        baseline = float(row['baseline_net'])-float(before['baseline_net'])
        candidate = float(row['candidate_net'])-float(before['candidate_net'])
        result.append(dict(id=row['id'], version=row['version'], broker=row['broker'], currency=row['currency'], hypothesis=row.get('hypothesis'),
            baseline_change=round(baseline,4), candidate_change=round(candidate,4), delta_change=round(candidate-baseline,4),
            new_resolved_pairs=int(row.get('completed') or 0)-int(before.get('completed') or 0),
            independent_days=int(row.get('days') or 0), uncertain_pairs=int(row.get('uncertain') or 0),
            candidate_drawdown=float(row['candidate_drawdown']) if row.get('candidate_drawdown') is not None else None,
            status='forward_checks_supported' if row.get('verdict')=='recommended' else 'not_established',
            since=previous['at']))
    return result


def refresh(db, now):
    """Once/day from small SQL projections; retain 35 snapshots, no large histories."""
    with e.transaction(db) as conn:
        from .database import uses_postgres
        if uses_postgres():
            conn.execute('SELECT pg_advisory_xact_lock(71911505)')
        saved = e.control(conn, 'learning_measurement', {})
        if saved.get('day') == now[:10]:
            return saved
        rows = conn.execute('SELECT id,version,status,'+_projection()+
            ' FROM RULE_EXPERIMENTS WHERE owner=? ORDER BY created_at DESC LIMIT 24', ('founder',)).fetchall()
        current = dict(day=now[:10],at=now,experiments=[dict(r) for r in rows])
        history = e.control(conn, 'learning_measurement_history', [])
        periods = {}
        for label, days in [('daily',1),('weekly',7),('monthly',30)]:
            cutoff = e.stamp(now)-timedelta(days=days)
            earlier = [s for s in history if e.stamp(s['at'])<=cutoff]
            # Do not call a two-day observation a week or compare across stale gaps.
            prior = earlier[-1] if earlier and cutoff-e.stamp(earlier[-1]['at'])<=timedelta(days=2) else None
            periods[label] = dict(status='available' if prior else 'collecting_baseline',
                                  comparisons=differences(current,prior) if prior else [])
        result = {**current, 'periods':periods,
            'evidence_coverage':e.control(conn,'learning_evidence_coverage',{}),
            'summary':'Recorded lessons are not proof of better trading. Compare the same frozen experiment version over time.',
            'caveat':'After estimated costs; realised changes can reflect when trades close. Resolved pairs include skips. Do not add overlapping experiments together. These are shadow results, not actual account returns or causal proof that a lesson helped.'}
        e.put_control(conn,'learning_measurement_history',(history+[current])[-35:])
        e.put_control(conn,'learning_measurement',result)
        e.put_control(conn,'learning_measurement_view',{k:v for k,v in result.items() if k!='experiments'})
        return result


def snapshot(conn):
    result = e.control(conn,'learning_measurement_view',{'status':'awaiting_first_daily_snapshot'})
    # Detailed versions remain in the stored audit record; UI uses compact report.
    return result
