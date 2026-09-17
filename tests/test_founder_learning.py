from ai_trader import experiments as e
from ai_trader.founder_learning import build, refresh
from test_experiments import db, create


def test_scorecard_does_not_claim_better_trading_from_activity(db):
    create(db)
    with e.transaction(db) as conn:
        result = build(conn, now='2026-09-17T09:00:00+00:00')
    assert result['headline'] == 'Learning activity only'
    assert result['experiments']['running'] == 1
    assert result['trading_better'] is False
    assert 'not yet proved better trading performance' in result['reflection']


def test_scorecard_labels_baseline_change_as_superseded(db):
    row = create(db)
    with e.transaction(db) as conn:
        current = e._load(conn, row['id'])
        e._event(conn, current, 'baseline_changed', {}, 'baseline:test')
        result = refresh(conn, now='2026-09-17T09:00:00+00:00')
    assert result['experiments']['superseded'] == 1
    assert e.detail(db, row['id'])['display_status'] == 'superseded_restarted'

