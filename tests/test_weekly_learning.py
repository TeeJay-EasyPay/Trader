import json
import pytest
from test_experiments import db, create, op
from ai_trader import experiments as e, experiment_assurance as a
from ai_trader.experiment_reviews import grouped_review
from ai_trader.learning_findings import period, relevant


def variants(db, count):
    raw=dict(rule_type='minimum_target_r',threshold=1.1,
        hypothesis='Test a distinct target risk threshold under shared opportunities.', evidence_ids=[1])
    return [e.create_experiment(db,{**raw,'threshold':1.1+i*.1},queue=True,now='2026-09-01T00:00:00+00:00') for i in range(count)]


def test_ten_global_slots_same_broker_and_shared_inputs(db):
    rows=variants(db,11)
    a.start_queued(db,'2026-09-01T01:00:00+00:00')
    active=[x for x in rows if e.detail(db,x['id'])['status']=='shadow_running']
    assert len(active)==10
    for row in active:
        for n in range(20):
            e.add_opportunity(db,row['id'],op(source='p'+str(n),symbol='A'+str(n)))
    with e.transaction(db) as c:
        assert c.execute('SELECT COUNT(*) FROM EXPERIMENT_OPPORTUNITIES').fetchone()[0]==200
    with pytest.raises(ValueError,match='Daily'):
        e.add_opportunity(db,active[0]['id'],op(source='overflow',symbol='Z'))
    assert e.detail(db,rows[-1]['id'])['status']=='queued'


def test_equivalent_hypothesis_is_not_a_new_test(db):
    row=create(db)
    with pytest.raises(ValueError,match='Equivalent'):
        e.create_experiment(db,row['spec'],queue=True)


def test_weekly_continuation_keeps_books_and_stops_stalled_test(db):
    row=create(db)
    e.add_opportunity(db,row['id'],{**op(),'eligible':False,'rejection_reasons':['risk_limit']})
    first=e.settle_bars(db,row['id'],[],now='2026-09-08T01:00:00+00:00')
    assert first['status']=='shadow_running'
    assert first['state']['review_cycle']==1
    assert first['report']['observations']==1
    assert first['state']['next_review_at']=='2026-09-15T01:00:00+00:00'
    e.settle_bars(db,row['id'],[],now='2026-09-15T01:00:00+00:00')
    third=e.settle_bars(db,row['id'],[],now='2026-09-22T01:00:00+00:00')
    assert third['status']=='insufficient_evidence'
    assert third['report']['closed_trades']=={'baseline':0,'candidate':0}
    findings=period(db,'2026-09-01','2026-10-01')['findings']
    assert len(findings)>=2
    assert all(f['source_type']=='experiment_review' for f in findings)


def test_weekly_review_preserves_open_positions(db):
    row=create(db)
    e.add_opportunity(db,row['id'],op())
    first=e.settle_bars(db,row['id'],[],now='2026-09-08T00:00:00+00:00')
    assert first['report']['completed']==0
    assert e.detail(db,row['id'])['opportunities'][0]['arms']['baseline']['status']=='awaiting_bar'
    assert first['status']=='shadow_running'


def test_grouped_call_shared_budget_and_invalid_ids(db):
    rows=variants(db,2)
    a.start_queued(db,'2026-09-01T00:00:00+00:00')
    for row in rows:
        e.settle_bars(db,row['id'],[],now='2026-09-08T01:00:00+00:00')
    calls=[]
    def answer(q,context):
        calls.append(context)
        return json.dumps({'reviews':[{'id':'invented','version':'x','summary':'Great'}]})
    policy={**e.DEFAULT_POLICY,'model_enabled':True}
    assert grouped_review(db,None,'2026-09-08T02:00:00+00:00',policy,answer)
    grouped_review(db,None,'2026-09-08T03:00:00+00:00',policy,answer)
    assert len(calls)==1 and len(calls[0]['reviews'])==2
    with e.transaction(db) as c:
        assert e.control(c,'proposal_attempt')['status']=='grouped_review_failed'
    assert all(e.detail(db,r['id'])['status']=='shadow_running' for r in rows)


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
    assert updated['state']['next_review_at']=='2026-09-08T00:00:00+00:00'
    module.migrate_schedule(db,'2026-09-03T00:00:00+00:00')
    assert len([event for event in e.detail(db,row['id'])['events'] if event['action']=='weekly_schedule_migrated'])==1
