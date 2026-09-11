"""Persist provenance-backed findings; reads never call a model or activate rules."""
import json
from . import experiments as e


def save(conn, *, source_type, source_id, recorded_at, broker, symbol, payload):
    version = e.digest(payload)
    fid = e.digest([source_type, str(source_id), version])
    prior = conn.execute('SELECT id FROM LEARNING_FINDINGS WHERE source_type=? AND source_id=? ORDER BY recorded_at DESC LIMIT 1',
                         (source_type,str(source_id))).fetchone()
    payload = {**payload, 'supersedes':prior[0] if prior and prior[0] != fid else None}
    conn.execute('INSERT INTO LEARNING_FINDINGS VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING',
                 (fid, recorded_at, broker, symbol, source_type, str(source_id), version, e.dump(payload)))
    return fid


def capture(db, now):
    """Incremental retained review import, capped at 200/day. No paid processing."""
    with e.transaction(db) as c:
        budget = e.control(c,'finding_capture_budget',{})
        count = budget.get('count',0) if budget.get('day') == now[:10] else 0
        if count >= 200:
            return
        cursor = e.control(c,'finding_review_cursor',0)
        rows = c.execute('SELECT review_id,created_at,broker,symbol,what_happened,lessons_json FROM POST_TRADE_REVIEWS WHERE review_id>? ORDER BY review_id LIMIT ?', (cursor,min(50,200-count))).fetchall()
        for r in rows:
            try:
                lessons = json.loads(r['lessons_json'])
            except (ValueError, TypeError):
                lessons = []
            text = '; '.join(str(v)[:300] for v in lessons[:3]) if isinstance(lessons,list) else ''
            text = text or str(r['what_happened'] or '')[:600]
            if text:
                save(c, source_type='trade_review', source_id=r['review_id'], recorded_at=r['created_at'],
                     broker=r['broker'] or 'unknown', symbol=r['symbol'],
                     payload={'what_was_learnt':text, 'evidence_at':r['created_at'], 'imported_at':now,
                              'source_excerpt':str(r['what_happened'] or '')[:700],
                              'evidence_status':'recorded hypothesis, not validated improvement',
                              'future_use':'Investigate this lesson; approved trading rules remain unchanged.',
                              'action':'investigate', 'activation':'not_activated'})
        if rows:
            e.put_control(c,'finding_review_cursor',rows[-1]['review_id'])
        e.put_control(c,'finding_capture_day',now[:10])
        e.put_control(c,'finding_capture_budget',{'day':now[:10],'count':count+len(rows)})


def period(db, start, end):
    with e.transaction(db) as c:
        rows = c.execute('SELECT id,recorded_at,broker,symbol,source_type,source_id,version,payload_json FROM LEARNING_FINDINGS WHERE recorded_at>=? AND recorded_at<? ORDER BY recorded_at DESC LIMIT 301',(start,end)).fetchall()
        findings, seen = [], {}
        superseded={json.loads(r['payload_json']).get('supersedes') for r in rows}
        for r in rows[:300]:
            if r['id'] in superseded:
                continue
            item=dict(r); item.update(json.loads(item.pop('payload_json')))
            key=(item['broker'],item['source_type'],item['what_was_learnt'].strip().lower())
            if key in seen:
                seen[key]['supporting_ids'].append(item['id'])
                continue
            item['supporting_ids']=[item['id']];seen[key]=item;findings.append(item)
        active=c.execute("SELECT id,version,spec_json,report_json FROM RULE_EXPERIMENTS WHERE status='shadow_running' ORDER BY created_at LIMIT 10").fetchall()
        tests=[]
        for r in active:
            spec=json.loads(r['spec_json']);report=json.loads(r['report_json'])
            tests.append({'id':r['id'],'version':r['version'],'hypothesis':spec['hypothesis'],
                          'source_outcomes':spec['evidence_ids'],'next_review':report.get('evaluate_after')})
        actions = c.execute("SELECT experiment_id,created_at,action,version FROM EXPERIMENT_EVENTS WHERE created_at>=? AND created_at<? AND action IN ('enable_paper','approve_library','request_development','suspend','automatically_suspended','implementation_updated') ORDER BY created_at DESC LIMIT 30",(start,end)).fetchall()
        for finding in findings:
            if finding.get('experiment_id'):
                state = c.execute('SELECT status FROM RULE_EXPERIMENTS WHERE id=? AND version=?',(finding['experiment_id'],finding['version'])).fetchone()
                finding['current_status']=state[0] if state else 'version changed; see history'
        return {'findings':findings,'truncated':len(rows)>300,'next_tests':tests,'actions':[dict(x) for x in actions],
                'caveat':'Trade reviews propose lessons; experiment reviews test them. Repeated or conflicting observations do not automatically change rules.'}


def relevant(db, symbol, broker):
    try:
        with e.transaction(db) as c:
            rows=c.execute('SELECT id,version,payload_json FROM LEARNING_FINDINGS WHERE broker=? AND (symbol=? OR source_type=?) ORDER BY recorded_at DESC LIMIT 2',(broker,symbol,'experiment_review')).fetchall()
            return [{'id':r['id'],'version':r['version'],'finding':json.loads(r['payload_json'])['what_was_learnt'][:350],
                     'use':'Evidence for consideration only; do not override approved safeguards.'} for r in rows]
    except Exception:
        return []
