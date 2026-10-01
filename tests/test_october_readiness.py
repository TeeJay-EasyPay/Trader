import gzip
import io
import json
import pytest
from urllib.error import HTTPError

from ai_trader import experiments as e, historical_screening as h
from ai_trader.experiment_worker import _merge_bars
from ai_trader.provider_errors import details
from ai_trader.research_health import snapshot


def test_frozen_data_roundtrips_compressed_without_discarding_legacy(tmp_path):
    root = tmp_path / 'research-cache'
    root.mkdir()
    legacy = root / 'old.json'
    legacy.write_text('{"old":"retained"}')
    data = {'signals': [], 'bars': [{'value': 'x' * 10000}]}
    version = h.freeze_dataset(tmp_path / 'db', data)
    target = root / (version + '.json.gz')
    assert json.loads(gzip.decompress(target.read_bytes())) == data
    assert target.stat().st_size < 1000
    assert legacy.read_text() == '{"old":"retained"}'
    assert h.freeze_dataset(tmp_path / 'db', data) == version


def test_provider_error_receipt_never_stores_arbitrary_prose():
    exc = HTTPError('https://api.openai.com', 400, 'bad', {}, io.BytesIO(json.dumps({
        'error': {'code': 'invalid_parameter', 'param': 'reasoning.effort',
                  'type': 'invalid_request_error', 'message': 'SECRET prompt and key'}}).encode()))
    result = details(exc)
    assert result['http_status'] == 400
    assert result['provider_param'] == 'reasoning.effort'
    assert 'SECRET' not in json.dumps(result)


def test_conflicting_prices_are_not_silently_selected():
    bar = dict(symbol='ABC', start='2026-09-27T00:00:00Z',
               end='2026-09-28T00:00:00Z', open=10, high=11, low=9, close=10)
    assert len(_merge_bars([bar], [bar])) == 1
    with pytest.raises(ValueError, match='Conflicting'):
        _merge_bars([bar], [{**bar, 'close': 10.5}])


def test_completed_job_does_not_hide_failed_research(tmp_path, monkeypatch):
    monkeypatch.setenv('AI_TRADER_DATABASE_BACKEND', 'sqlite')
    db = tmp_path / 'db'
    e.migrate(db)
    with e.transaction(db) as c:
        e.put_control(c, 'historical_screening_view', {'status': 'completed',
            'trials': [{'status': 'invalid', 'reason': 'cache capacity'}]})
    health = snapshot(db, '2026-10-01T12:00:00+00:00')
    assert health['historical']['status'] == 'failed'
    assert health['status'] == 'attention_required'
    assert health['strategy_improvement'] == 'not_established'


def test_strategy_qualification_uses_portable_boolean_predicate():
    from pathlib import Path
    import ai_trader.sprint6 as s
    assert 'qualification_date = CASE WHEN ? = 1 THEN' in Path(s.__file__).read_text()


def test_scheduler_cannot_call_fallback_or_invalid_research_successful():
    from ai_trader.cli import _verify_research_job_result
    with pytest.raises(RuntimeError, match='fallback'):
        _verify_research_job_result('self-assessment', {'status': 'evidence_fallback'})
    with pytest.raises(RuntimeError, match='screening'):
        _verify_research_job_result('historical-market-refresh', {'status': 'failed'})
    _verify_research_job_result('historical-market-refresh', {'status': 'completed'})
    _verify_research_job_result('managed-exits', {'status': 'skipped'})


def test_health_counts_only_started_recent_failures(tmp_path, monkeypatch):
    monkeypatch.setenv('AI_TRADER_DATABASE_BACKEND', 'sqlite')
    db = tmp_path / 'db'
    e.migrate(db)
    with e.transaction(db) as c:
        c.execute('CREATE TABLE SCHEDULED_JOB_RUNS(job_name TEXT,status TEXT,started_at TEXT,scheduled_for TEXT,completed_at TEXT)')
        c.execute('CREATE TABLE AI_SELF_ASSESSMENTS(created_at TEXT,status TEXT)')
        for started, scheduled in [('2026-10-01T10:00:00+00:00','2026-10-01T10:00:00+00:00'),
                                   (None,'2026-10-01T10:00:00+00:00'),
                                   ('2026-09-28T10:00:00+00:00','2026-10-01T10:00:00+00:00')]:
            c.execute('INSERT INTO SCHEDULED_JOB_RUNS VALUES (?,?,?,?,?)',
                      ('research','failed',started,scheduled,'2026-10-01T11:00:00+00:00'))
    health = snapshot(db, '2026-10-01T12:00:00+00:00')
    assert health['failed_jobs_24h'][0]['count'] == 1
    assert not any(issue.startswith('job_evidence_unavailable') for issue in health['issues'])
