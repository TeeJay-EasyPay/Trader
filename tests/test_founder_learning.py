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


def test_scorecard_calls_recorded_research_a_provisional_lesson_not_proven_improvement(db):
    create(db)
    with e.transaction(db) as conn:
        from ai_trader.learning_findings import save
        save(conn, source_type='historical_screening', source_id='day:alpaca',
             recorded_at='2026-09-17T08:00:00+00:00', broker='alpaca', symbol=None,
             payload={'what_was_learnt':'The historical sample needs more independent days.',
                      'future_use':'Collect forward evidence.', 'evidence_status':'provisional',
                      'action':'research', 'activation':'not_activated'})
        result = build(conn, now='2026-09-17T09:00:00+00:00')
    assert result['learned_something'] is True
    assert result['lesson_status'] == 'provisional'
    assert result['trading_better'] is False
    assert 'provisional research finding' in result['reflection']

