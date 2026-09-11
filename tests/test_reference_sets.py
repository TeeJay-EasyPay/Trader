import json
import pytest
from types import SimpleNamespace
from test_experiments import db, op
from ai_trader import experiments as e
from ai_trader.reference_sets import snapshot, pair

def test_candidates_do_not_replace_live_library():
    a=snapshot('stock');b=snapshot('stock',candidate=True,topics=['costs'])
    assert a['version']!=b['version']
    assert all(len(p['text'])<=1200 for p in b['passages'])
    assert any('cost' in p['title'].lower() for p in b['passages'])

def test_reference_pair_requires_budget_and_preserves_safety(db):
    row=e.create_experiment(db,dict(rule_type='reference_set_filter',hypothesis='Compare revised reference material against existing guidance.',evidence_ids=[1]),now='2026-09-01T00:00:00+00:00')
    calls=[]
    def answer(q,c):
        calls.append(c)
        return json.dumps(dict(allow=True,reason='Fixture response only'))
    settings=SimpleNamespace(openai_model='fixture')
    with e.transaction(db) as c:e.put_control(c,'policy',{**e.DEFAULT_POLICY,'model_enabled':True})
    assert pair(db,row['id'],op(),settings,answer=answer,now='2026-09-01T13:00:00+00:00') is None
    assert len(calls)==1
    assert pair(db,row['id'],op(),settings,answer=answer,now='2026-09-01T14:00:00+00:00') is None
    assert len(calls)==1
    result=pair(db,row['id'],op(),settings,answer=answer,now='2026-09-02T13:00:00+00:00')
    assert result['status']=='completed' and len(calls)==2
    assert calls[0]['opportunity']==calls[1]['opportunity']
    e.add_opportunity(db,row['id'],{**op(),'eligible':False,'rejection_reasons':['risk_limit']})
    stored=e.detail(db,row['id'])['opportunities'][0]
    assert all(a['status']=='skipped' for a in stored['arms'].values())
    assert stored['time']=='2026-09-02T13:00:00+00:00'

def test_target_move_filter_is_not_target_r(db):
    row=e.create_experiment(db,dict(rule_type='minimum_target_move_bps',threshold=3500,
        hypothesis='Test gross target distance without assuming an expected return.',evidence_ids=[1]),now='2026-09-01T00:00:00+00:00')
    e.add_opportunity(db,row['id'],op(target=130))
    arms=e.detail(db,row['id'])['opportunities'][0]['arms']
    assert arms['baseline']['status']=='awaiting_bar' and arms['candidate']['status']=='skipped'

def test_stale_and_missing_reference_documents_fail_closed(monkeypatch):
    import ai_trader.reference_sets as r
    monkeypatch.setattr(r,'load_knowledge_index',lambda root:[])
    with pytest.raises(ValueError,match='unavailable'):snapshot('stock',candidate=True)
    monkeypatch.setattr(r,'load_knowledge_index',lambda root:[dict(applies_to=['stock'],topics=[],sectors=[],
        title='Stale fixture',file_path='fixture.md',excerpt='Do not use stale facts.',metadata={'review_due':'2000-01-01'})])
    with pytest.raises(ValueError,match='overdue'):snapshot('stock',candidate=True)
