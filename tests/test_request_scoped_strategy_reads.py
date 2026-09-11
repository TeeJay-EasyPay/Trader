"""Read savings must preserve evidence, isolation, and fresh subsequent decisions."""
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from ai_trader import strategy_performance as sp


def test_scope_reuses_only_identical_successful_reads_and_resets():
    conn = Mock(_schema_key="database-a")
    conn.execute.return_value.fetchall.return_value = [(1,)]
    with sp.strategy_read_scope():
        assert sp._read_rows(conn, Path('a'), 'SELECT ?', (1,)) == [(1,)]
        sp._read_rows(conn, Path('a'), 'SELECT ?', (1,))
        assert conn.execute.call_count == 1
        sp._read_rows(conn, Path('b'), 'SELECT ?', (1,))
        sp._read_rows(conn, Path('a'), 'SELECT ?', (2,))
        conn._schema_key = 'database-b'
        sp._read_rows(conn, Path('a'), 'SELECT ?', (1,))
        assert conn.execute.call_count == 4
    sp._read_rows(conn, Path('a'), 'SELECT ?', (1,))
    assert conn.execute.call_count == 5


def test_failed_read_is_not_cached_and_exception_cleans_scope():
    conn = Mock(_schema_key='a')
    conn.execute.side_effect = [RuntimeError('unavailable'), Mock()]
    with pytest.raises(RuntimeError), sp.strategy_read_scope():
        sp._read_rows(conn, Path('a'), 'SELECT 1')
    assert sp._read_scope.get() is None
    with sp.strategy_read_scope():
        sp._read_rows(conn, Path('a'), 'SELECT 1')
    assert conn.execute.call_count == 2


def test_paired_views_identical_with_half_the_reads_and_fresh_next_time(tmp_path):
    db = tmp_path / 'audit.sqlite3'
    with sqlite3.connect(db) as conn:
        conn.execute('CREATE TABLE PERFORMANCE_ATTRIBUTION(proposal_id, profit_loss, entry_price, exit_price, quantity, closed_at, created_at, symbol)')
        conn.execute('CREATE TABLE TRADE_AUDIT(proposal_id, event_type, payload_json)')
        for i in range(8):
            conn.execute('INSERT INTO PERFORMANCE_ATTRIBUTION VALUES (?,?,?,?,?,?,?,?)',
                         (str(i), i-3, 10, 11, 2, '2026-09-11', '2026-09-11', 'AAA' if i%2 else 'BBB'))
            conn.execute('INSERT INTO TRADE_AUDIT VALUES (?,?,?)',
                         (str(i), 'agent_proposal', json.dumps({'proposal': {'strategy_id': 'trend', 'stop_loss': 9}, 'unused': 'x'*10000})))
    reads = []
    def connect(_):
        conn = sqlite3.connect(db)
        conn.set_trace_callback(lambda sql: reads.append(sql) if sql.lstrip().startswith('SELECT') else None)
        return conn
    with patch.object(sp, 'connect', side_effect=connect), patch.object(sp, 'readiness_from_outcomes', return_value=SimpleNamespace(ready=True)):
        expected = (sp.strategy_records(db), sp.strategy_symbol_records(db))
        assert len(reads) == 4
        reads.clear()
        with sp.strategy_read_scope():
            actual = (sp.strategy_records(db), sp.strategy_symbol_records(db))
        assert actual == expected
        assert len(reads) == 2
        with sqlite3.connect(db) as conn:
            conn.execute('UPDATE PERFORMANCE_ATTRIBUTION SET profit_loss=20')
        with sp.strategy_read_scope():
            assert sp.strategy_records(db) != expected[0]


def test_callers_use_scoped_reads():
    from ai_trader import strategy_scoreboard, strategy_demotion
    assert hasattr(strategy_scoreboard._sources, '__wrapped__')
    assert hasattr(strategy_demotion.review_strategies_for_demotion, '__wrapped__')
