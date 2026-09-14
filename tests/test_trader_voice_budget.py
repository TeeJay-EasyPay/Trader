import pytest
from types import SimpleNamespace
from test_experiments import db
from ai_trader import trader_voice as v


def test_one_session_reserved_and_usage_durable(db):
    a=v.budget(db,reserve=True,now='2026-09-14T00:00:00+00:00')
    with pytest.raises(ValueError,match='active'):
        v.budget(db,reserve=True,now='2026-09-14T00:01:00+00:00')
    v.charge(db,a['month'],a['session_id'],123456,close=True)
    b=v.budget(db,now='2026-09-14T00:02:00+00:00')
    assert b['session_id'] is None
    assert b['spent_usd']==pytest.approx(.173456)


def test_budget_cannot_be_freed_by_wrong_session(db):
    a=v.budget(db,reserve=True)
    with pytest.raises(ValueError):
        v.charge(db,a['month'],'wrong',close=True)
    assert v.budget(db)['session_id']==a['session_id']


def test_budget_exhaustion_and_unknown_usage_fail_closed(db):
    a=v.budget(db,reserve=True)
    v.charge(db,a['month'],a['session_id'],9_000_000,close=True)
    with pytest.raises(ValueError,match='allowance'):
        v.budget(db,reserve=True)
    with pytest.raises(ValueError):
        v.usage_cost({})
    assert v.usage_cost({'input_tokens':1000,'output_tokens':100})==38400


def test_no_implicit_start_from_other_modes_or_bad_offer(db):
    service=SimpleNamespace(settings=SimpleNamespace(db_path=db,openai_api_key='not-used'))
    for body in ({'mode':'both','confirmed':True}, {'mode':'trader'}, {'mode':'trader','confirmed':True,'sdp':'invalid'}):
        with pytest.raises(ValueError):
            v.start(service,body)
    assert v.budget(db)['spent_usd']==0
