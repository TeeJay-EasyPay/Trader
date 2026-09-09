from contextlib import closing
from datetime import datetime, timezone
import json
from unittest.mock import patch

import pytest
from ai_trader.database import connect, HybridRow
from ai_trader.learning_screen import _summary, _details, period_bounds, learning_summary, _cache

NOW = datetime(2026, 9, 9, 20, tzinfo=timezone.utc)


@pytest.fixture
def db(tmp_path):
    path = tmp_path / 'learning.sqlite'
    with closing(connect(path)) as conn, conn:
        conn.executescript("""
        CREATE TABLE KRAKEN_RECONCILED_RESULTS (symbol TEXT, exit_time TEXT, net_pnl REAL, status TEXT);
        CREATE TABLE PERFORMANCE_ATTRIBUTION (attribution_id INTEGER PRIMARY KEY, broker TEXT, symbol TEXT, closed_at TEXT, profit_loss REAL, exit_price REAL);
        CREATE TABLE SHADOW_TRADES (shadow_trade_id INTEGER PRIMARY KEY, created_at TEXT, intended_broker TEXT, symbol TEXT,
          strategy TEXT, decision_status TEXT, intended_entry REAL, stop_loss REAL, take_profit REAL,
          outcome_status TEXT, final_price REAL, estimated_net_r REAL, gross_r REAL, wait_or_rejection_reason TEXT);
        CREATE TABLE ORCHESTRATOR_DECISIONS (decision_id INTEGER PRIMARY KEY, created_at TEXT, selected_broker TEXT, symbol TEXT, decision TEXT, rejection_reason TEXT);
        CREATE TABLE POST_TRADE_REVIEWS (review_id INTEGER PRIMARY KEY, created_at TEXT, broker TEXT, symbol TEXT,
          outcome_classification TEXT, what_happened TEXT, lessons_json TEXT, experience_id INTEGER);
        CREATE TABLE LEARNING_PROPOSALS (proposal_id INTEGER PRIMARY KEY, created_at TEXT, proposal_type TEXT, current_value TEXT,
          proposed_value TEXT, sample_size INTEGER, expected_impact TEXT, approval_status TEXT);
        CREATE TABLE STRATEGY_BACKTEST_RESULTS (backtest_id INTEGER PRIMARY KEY, created_at TEXT, strategy_id TEXT, symbol TEXT,
          trades INTEGER, win_rate REAL, expectancy_r REAL, max_drawdown_r REAL, result_summary TEXT);
        CREATE TABLE STRATEGY_REGISTRY (strategy_id TEXT PRIMARY KEY, name TEXT, purpose TEXT, production_status TEXT, historical_edge TEXT, updated_at TEXT);
        """)
        conn.execute("INSERT INTO KRAKEN_RECONCILED_RESULTS VALUES ('XRP','2026-09-09T15:00:00Z',-2,'closed')")
        conn.execute("INSERT INTO PERFORMANCE_ATTRIBUTION VALUES (1,'alpaca','NEE','2026-09-09T16:00:00Z',7,82)")
        conn.execute("INSERT INTO POST_TRADE_REVIEWS VALUES (1,'2026-09-09T16:00:00Z','kraken','XRP','unknown','Missing fee evidence',?,1)",
                     (json.dumps(['Check costs before drawing a lesson.']),))
        for i in range(1, 27):
            conn.execute("INSERT INTO SHADOW_TRADES VALUES (?, '2026-09-09T16:00:00Z','kraken','XRP','crypto_research_refused','shadow_candidate',2,1.9,2.08,'pending',NULL,NULL,NULL,'Cost filter')", (i,))
    return path


def test_periods_have_calendar_boundaries_and_current_status():
    assert period_bounds('weekly', '2026-09-09', NOW)['start'] == '2026-09-07'
    assert period_bounds('monthly', '2026-09-09', NOW)['end'] == '2026-10-01'
    assert period_bounds('monthly', '2024-02-10', NOW)['end'] == '2024-03-01'
    assert period_bounds('daily', '2026-09-08', NOW)['in_progress'] is False
    assert period_bounds('daily', '2026-09-09', NOW)['in_progress'] is True
    for kind, stamp in [('yearly', None), ('daily', '2026-09-10'), ('daily', 'x')]:
        with pytest.raises(ValueError):
            period_bounds(kind, stamp, NOW)


def test_summary_keeps_currency_unknowns_and_hypotheses_separate(db):
    result = _summary(db, period_bounds('daily', '2026-09-09', NOW), NOW)
    assert result['unavailable'] == []
    assert {x['broker']: x['pnl'] for x in result['outcomes']} == {'kraken': -2, 'alpaca': 7}
    assert 'total_pnl' not in result
    assert result['assessment']['validated'] is None
    assert result['assessment']['status'] == 'insufficient_evidence'
    assert result['reviews'][0]['lessons'] == ['Check costs before drawing a lesson.']
    assert result['shadows'][0]['total'] == 26
    assert result['shadows'][0]['outcome_status'] == 'pending'
    assert 'hypotheses' in result['summary']


def test_detail_pages_bounded_and_every_link_has_real_read_path(db):
    bounds = period_bounds('daily', '2026-09-09', NOW)
    first, second = [_details(db, 'rejected', bounds, 'kraken', n) for n in (0, 1)]
    assert len(first['rows']) == 20 and first['has_more']
    assert len(second['rows']) == 6 and not second['has_more']
    assert set(x['id'] for x in first['rows']).isdisjoint(x['id'] for x in second['rows'])
    assert first['rows'][0]['estimated_net_r'] is None
    assert _details(db, 'rejected', bounds, 'alpaca', 0)['rows'] == []
    for kind in ('decisions', 'trades', 'reviews', 'strategies', 'tests', 'proposals'):
        assert 'rows' in _details(db, kind, bounds, 'all', 0)


def test_missing_source_is_unavailable_not_success(db):
    with closing(connect(db)) as conn, conn:
        conn.execute('DROP TABLE POST_TRADE_REVIEWS')
    result = _summary(db, period_bounds('daily', '2026-09-09', NOW), NOW)
    assert 'trade reviews' in result['unavailable']
    assert result['review_count'] is None
    assert result['summary'].startswith('Report incomplete')
    assert len(result['outcomes']) == 2


def test_summary_cache_avoids_repeat_database_reads(db):
    _cache.clear()
    with patch('ai_trader.learning_screen._summary', return_value={'ok': True}) as build:
        for _ in range(3):
            learning_summary(db, 'daily', '2026-09-09', NOW)
        assert build.call_count == 1


def test_all_projections_work_with_dictionary_row_adapter(db):
    class DictConnection:
        def __init__(self): self.conn = connect(db)
        def execute(self, sql, params):
            assert 'SELECT *' not in sql
            assert 'UPDATE ' not in sql and 'INSERT ' not in sql
            cursor = self.conn.execute(sql, params)
            names = [d[0] for d in cursor.description]
            assert len(names) == len(set(names))
            self.rows = [HybridRow(zip(names, row)) for row in cursor.fetchall()]
            return self
        def fetchall(self): return self.rows
        def close(self): self.conn.close()
    with patch('ai_trader.learning_screen.connect', side_effect=lambda *_: DictConnection()):
        result = _summary(db, period_bounds('daily', '2026-09-09', NOW), NOW)
        assert result['unavailable'] == []


def test_day_buckets_normalize_offsets_and_epoch(db):
    with closing(connect(db)) as conn, conn:
        conn.execute("INSERT INTO KRAKEN_RECONCILED_RESULTS VALUES ('OLD','2026-09-09T00:15:00+01:00',100,'closed')")
        conn.execute("INSERT INTO KRAKEN_RECONCILED_RESULTS VALUES ('EPOCH','1757376000',100,'closed')")
    result = _summary(db, period_bounds('daily', '2026-09-09', NOW), NOW)
    assert next(x for x in result['outcomes'] if x['broker'] == 'kraken')['pnl'] == -2


def test_api_routes_validate_and_do_not_run_learning_jobs(db):
    from types import SimpleNamespace
    from ai_trader.api import LocalApiService
    service = object.__new__(LocalApiService)
    service.settings = SimpleNamespace(db_path=db)
    _cache.clear()
    with patch.object(LocalApiService, 'daily_learning_update', side_effect=AssertionError('No mutation')):
        status, result = service.get('/learning-summary', {'date': ['2026-09-09']})
        assert status == 200 and result['unavailable'] == []
        status, result = service.get('/learning-details', {'date': ['2026-09-09'], 'kind': ['trades']})
        assert status == 200 and len(result['rows']) == 2
        for query in ({'period': ['yearly']}, {'page': ['-1']}, {'kind': ['bad']}):
            assert service.get('/learning-details', query)[0] == 400
