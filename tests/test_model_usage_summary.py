from test_experiments import db
from ai_trader import experiments as e, model_usage as usage


def test_missing_balance_not_zero_and_bounded_daily_summary(db):
    day = e.now_iso()[:10]
    with e.transaction(db) as c:
        e.put_control(c, 'model_usage:'+day+':test', dict(calls=2,input_tokens=123,output_tokens=12,unknown_usage=1))
        e.put_control(c, 'model_usage:2000-01-01:old', dict(calls=999))
    result = usage.summary(db)
    assert result['prepaid_balance_usd'] is None
    assert result['balance_status'] == 'unavailable'
    assert result['calls'] == 2
    assert result['input_tokens'] == 123
    assert result['unknown_usage'] == 1
