import json
import pytest
from test_experiments import db
from ai_trader import experiments as e
from ai_trader.experiment_batch import propose_batch


def test_multiple_proposals_one_call_and_unfunded_broker_does_not_starve_other(db):
    calls=[]
    def answer(q, context):
        calls.append(context)
        return json.dumps({'proposals':[dict(broker='alpaca',rule_type='minimum_target_r',threshold=t,
            hypothesis='Test a specified target risk filter against unchanged decisions.',evidence_ids=[1]) for t in (1.5,2.5,2.6)]})
    result=propose_batch(db,None,'2026-09-01T01:00:00+00:00',{**e.DEFAULT_POLICY,'model_enabled':True},answer)
    assert len(result['accepted'])==2
    assert len(result['rejected'])==1
    assert len(calls)==1
    assert 'kraken' not in calls[0]['brokers']
    assert e.list_experiments(db)['proposal_eligibility']['brokers']['kraken']['reason']=='insufficient_new_linked_outcomes'


def test_direct_creation_obeys_broker_cap(db):
    for i in range(5):
        e.create_experiment(db,dict(rule_type='minimum_target_r',threshold=1+i*.4,hypothesis='A sufficiently detailed independent hypothesis.',evidence_ids=[1]))
    with pytest.raises(ValueError,match='Broker experiment'):
        e.create_experiment(db,dict(rule_type='minimum_target_r',threshold=3.5,hypothesis='Another sufficiently detailed hypothesis.',evidence_ids=[1]))
