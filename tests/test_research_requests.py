import json
import pytest
from test_experiments import db
from ai_trader import experiments as e
from ai_trader import research_requests as r
from ai_trader.experiment_batch import propose_batch


def test_request_is_durable_idempotent_and_not_experiment(db):
    a = r.enqueue(db, 'Test whether target distance covers realistic fees')
    b = r.enqueue(db, 'Test whether target distance covers realistic fees')
    assert a['id'] == b['id']
    assert a['status'] == 'pending'
    assert r.chat_context(db)['experiments'] == []


def test_batch_consumes_request_once_and_records_origin(db):
    request = r.enqueue(db, 'Test a higher planned target risk filter', broker='alpaca')
    calls = []
    def answer(q, ctx):
        calls.append(ctx)
        assert request['id'] in [x['id'] for x in ctx['research_requests']]
        assert r.OBJECTIVE in q
        return json.dumps({'proposals': [dict(broker='alpaca', rule_type='minimum_target_r', threshold=2.5,
            hypothesis='Test a higher planned target risk filter', evidence_ids=[1],source_request_ids=[request['id']])]})
    policy = {**e.DEFAULT_POLICY, 'model_enabled': True}
    result = propose_batch(db, None, '2026-09-01T01:00:00+00:00', policy, answer)
    row = r.annotate(db, e.detail(db, result['accepted'][0]))
    assert row['origin']['proposed_by'] == 'Trader AI'
    assert row['origin']['request_ids'] == [request['id']]
    assert propose_batch(db, None, '2026-09-01T02:00:00+00:00', policy, answer) == 'daily_model_budget_reached'
    assert len(calls) == 1


def test_chat_only_registers_bounded_research(db):
    text = r.interpret_reply(db, json.dumps({'answer': 'Worth testing.', 'research_request':
        {'idea': 'Test whether target distance covers fees', 'broker': 'kraken'}, 'place_order': {'symbol': 'BTC'}}))
    assert 'Research request' in text and 'not a running experiment' in text
    assert r.chat_context(db)['experiments'] == []
    assert r.interpret_reply(db, 'An ordinary answer.') == 'An ordinary answer.'
    with pytest.raises(ValueError):
        r.enqueue(db, 'Another justified research question', broker='unknown')


def test_scope_resets_after_exception():
    assert not r.CHAT_RESEARCH_ENABLED.get()
    with pytest.raises(RuntimeError):
        with r.chat_scope(True):
            assert r.CHAT_RESEARCH_ENABLED.get()
            raise RuntimeError()
    assert not r.CHAT_RESEARCH_ENABLED.get()
