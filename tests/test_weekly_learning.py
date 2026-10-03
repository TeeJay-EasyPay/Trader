import json
import pytest
from test_experiments import db, create, op
from ai_trader import experiments as e, experiment_assurance as a
from ai_trader.experiment_reviews import grouped_review, compact_review_evidence
from ai_trader.learning_findings import period, relevant


def variants(db, count):
    raw=dict(rule_type='minimum_target_r',threshold=1.1,
        hypothesis='Test a distinct target risk threshold under shared opportunities.', evidence_ids=[1])
    return [e.create_experiment(db,{**raw,'threshold':1.1+i*.1},queue=True,now='2026-09-01T00:00:00+00:00') for i in range(count)]


def test_compact_review_keeps_numbers_unknowns_and_envelope_identity():
    payload = dict(id='wrong', version='wrong', currency='GBP', observations=59,
                   baseline_net=-50.07, candidate_net=0, uncertain=2, action='continue',
                   reason='x' * 500, what_was_learnt='repeated narrative' * 500,
                   future_use='No rule activated.' * 100)
    rows = [dict(id=str(i), version='v', payload_json=json.dumps(payload)) for i in range(10)]
    compact = compact_review_evidence(rows)
    assert len(e.dump(compact)) + 5800 < 16000
    assert compact[0]['id'] == '0' and compact[0]['version'] == 'v'
    assert compact[0]['baseline_net'] == -50.07 and compact[0]['candidate_net'] == 0
    assert compact[0]['uncertain'] == 2 and compact[0]['completed'] is None
    assert compact[0]['reason_truncated'] is True
    assert 'what_was_learnt' not in compact[0]
    assert json.loads(rows[0]['payload_json']) == payload


def test_compact_batch_reaches_one_call_without_changing_experiments(db, monkeypatch):
    rows = variants(db, 2)
    a.start_queued(db, '2026-09-01T00:00:00+00:00')
    for row in rows:
        e.settle_bars(db, row['id'], [], now='2026-09-04T01:00:00+00:00')
    with e.transaction(db) as c:
        for event in c.execute("SELECT id,payload_json FROM EXPERIMENT_EVENTS WHERE action='weekly_review'").fetchall():
            p = json.loads(event['payload_json'])
            p['what_was_learnt'] = 'repeated explanation ' * 1000
            c.execute('UPDATE EXPERIMENT_EVENTS SET payload_json=? WHERE id=?', (e.dump(p), event['id']))
    calls = []
    def answer(q, context):
        calls.append(context)
        assert '120 words' in q and 'estimated simulation costs' in q
        return json.dumps({'reviews': [dict(id=r['id'], version=r['version'], summary='Insufficient evidence; continue observing.') for r in context['reviews']]})
    policy = {**e.DEFAULT_POLICY, 'model_enabled': True}
    grouped_review(db, None, '2026-09-04T02:00:00+00:00', policy, answer)
    grouped_review(db, None, '2026-09-04T03:00:00+00:00', policy, answer)
    assert len(calls) == 1
    with e.transaction(db) as c:
        assert e.control(c, 'proposal_attempt')['status'] == 'grouped_review_completed'
    assert all(e.detail(db, r['id'])['status'] == 'shadow_running' for r in rows)


def test_three_high_value_slots_per_broker_and_shared_inputs(db):
    rows=variants(db,11)
    a.start_queued(db,'2026-09-01T01:00:00+00:00')
    active=[x for x in rows if e.detail(db,x['id'])['status']=='shadow_running']
    assert len(active)==3
    for row in active:
        for n in range(20):
            e.add_opportunity(db,row['id'],op(source='p'+str(n),symbol='A'+str(n)))
    with e.transaction(db) as c:
        assert c.execute('SELECT COUNT(*) FROM EXPERIMENT_OPPORTUNITIES').fetchone()[0]==60
    with pytest.raises(ValueError,match='Daily'):
        e.add_opportunity(db,active[0]['id'],op(source='overflow',symbol='Z'))
    assert e.detail(db,rows[-1]['id'])['status']=='queued'


def test_equivalent_hypothesis_is_not_a_new_test(db):
    row=create(db)
    with pytest.raises(ValueError,match='Equivalent'):
        e.create_experiment(db,row['spec'],queue=True)


def test_three_day_continuation_keeps_books_and_stops_stalled_test(db):
    row=create(db)
    e.add_opportunity(db,row['id'],{**op(),'eligible':False,'rejection_reasons':['risk_limit']})
    first=e.settle_bars(db,row['id'],[],now='2026-09-04T01:00:00+00:00')
    assert first['status']=='shadow_running'
    assert first['state']['review_cycle']==1
    assert first['report']['observations']==1
    assert first['state']['next_review_at']=='2026-09-07T01:00:00+00:00'
    e.settle_bars(db,row['id'],[],now='2026-09-07T01:00:00+00:00')
    third=e.settle_bars(db,row['id'],[],now='2026-09-10T01:00:00+00:00')
    assert third['status']=='insufficient_evidence'
    assert third['report']['closed_trades']=={'baseline':0,'candidate':0}
    findings=period(db,'2026-09-01','2026-10-01')['findings']
    assert len(findings)>=2
    assert all(f['source_type']=='experiment_review' for f in findings)


def test_three_day_review_preserves_open_positions(db):
    row=create(db)
    e.add_opportunity(db,row['id'],op())
    first=e.settle_bars(db,row['id'],[],now='2026-09-04T00:00:00+00:00')
    assert first['report']['completed']==0
    assert e.detail(db,row['id'])['opportunities'][0]['arms']['baseline']['status']=='awaiting_bar'
    assert first['status']=='shadow_running'


def test_grouped_call_shared_budget_and_invalid_ids(db):
    rows=variants(db,2)
    a.start_queued(db,'2026-09-01T00:00:00+00:00')
    for row in rows:
        e.settle_bars(db,row['id'],[],now='2026-09-04T01:00:00+00:00')
    calls=[]
    def answer(q,context):
        calls.append(context)
        return json.dumps({'reviews':[{'id':'invented','version':'x','summary':'Great'}]})
    policy={**e.DEFAULT_POLICY,'model_enabled':True}
    assert grouped_review(db,None,'2026-09-04T02:00:00+00:00',policy,answer)
    grouped_review(db,None,'2026-09-04T03:00:00+00:00',policy,answer)
    assert len(calls)==1 and len(calls[0]['reviews'])==2
    with e.transaction(db) as c:
        assert e.control(c,'proposal_attempt')['status']=='grouped_review_failed'
    assert all(e.detail(db,r['id'])['status']=='shadow_running' for r in rows)


def test_failed_interpretation_can_recover_next_day_not_retry_forever(db):
    row=create(db)
    e.settle_bars(db,row['id'],[],now='2026-09-04T01:00:00+00:00')
    calls=[]
    def answer(q, context):
        calls.append(context)
        return json.dumps({'reviews': []})
    policy={**e.DEFAULT_POLICY,'model_enabled':True}
    for day in (4,4,5,6,7):
        grouped_review(db,None,f'2026-09-{day:02d}T03:00:00+00:00',policy,answer)
    assert len(calls)==3
    with e.transaction(db) as c:
        assert e.control(c,'proposal_attempt')['status']=='grouped_review_failed'
    assert e.detail(db,row['id'])['status']=='shadow_running'


def test_word_limit_applies_to_entire_batch_without_paid_retry(db):
    rows = variants(db, 2)
    a.start_queued(db, '2026-09-01T00:00:00+00:00')
    for row in rows:
        e.settle_bars(db, row['id'], [], now='2026-09-04T01:00:00+00:00')
    calls = []
    def answer(q, context):
        calls.append(context)
        return json.dumps({'reviews': [dict(id=r['id'], version=r['version'],
            summary=' '.join(['word'] * 61)) for r in context['reviews']]})
    policy = {**e.DEFAULT_POLICY, 'model_enabled': True}
    grouped_review(db, None, '2026-09-04T02:00:00+00:00', policy, answer)
    grouped_review(db, None, '2026-09-04T03:00:00+00:00', policy, answer)
    assert len(calls) == 1
    with e.transaction(db) as c:
        assert e.control(c, 'proposal_attempt')['status'] == 'grouped_review_failed'
    assert all(e.detail(db, row['id'])['status'] == 'shadow_running' for row in rows)


def test_source_findings_persist_and_deduplicate_without_claiming_activation(db):
    from ai_trader.learning_findings import capture
    with e.transaction(db) as c:
        c.execute('CREATE TABLE POST_TRADE_REVIEWS(review_id INTEGER,created_at TEXT,broker TEXT,symbol TEXT,what_happened TEXT,lessons_json TEXT)')
        for n in (1,2):
            c.execute('INSERT INTO POST_TRADE_REVIEWS VALUES (?,?,?,?,?,?)',
                      (n,'2026-09-07T12:00:00+00:00','alpaca','ABC','',json.dumps(['Fees can outweigh small gains.'])))
    capture(db,'2026-09-08T01:00:00+00:00')
    result=period(db,'2026-09-01','2026-10-01')
    assert len(result['findings'])==1
    assert len(result['findings'][0]['supporting_ids'])==2
    assert result['findings'][0]['activation']=='not_activated'
    assert len(relevant(db,'ABC','alpaca'))==2
    assert relevant(db,'ABC','kraken')==[]


def test_schedule_migration_keeps_existing_evidence_and_books(db):
    import importlib.util
    from pathlib import Path
    spec=importlib.util.spec_from_file_location('rollout',Path(__file__).parents[1]/'tools/weekly_learning_rollout.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    row=create(db)
    e.add_opportunity(db,row['id'],op())
    with e.transaction(db) as c:
        old=e._load(c,row['id']);old['spec'].pop('weekly_reviews');old['spec']['evaluation_days']=60
        c.execute('UPDATE RULE_EXPERIMENTS SET spec_json=? WHERE id=?',(e.dump(old['spec']),row['id']))
    module.migrate_schedule(db,'2026-09-02T00:00:00+00:00')
    updated=e.detail(db,row['id'])
    assert updated['created_at']==row['created_at']
    assert updated['state']['baseline']==row['state']['baseline']
    assert len(updated['opportunities'])==1
    assert updated['state']['next_review_at']=='2026-09-04T00:00:00+00:00'
    module.migrate_schedule(db,'2026-09-03T00:00:00+00:00')
    assert len([event for event in e.detail(db,row['id'])['events'] if event['action']=='review_schedule_migrated'])==1
