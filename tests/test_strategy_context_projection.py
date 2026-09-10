import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ai_trader.strategy_performance import _strategy_context_projection


def test_sqlite_projection_returns_only_required_context():
    conn = sqlite3.connect(':memory:')
    conn.execute('CREATE TABLE trade_audit(payload_json TEXT)')
    payloads = [
        json.dumps({'proposal': {'strategy_id': 'trend', 'stop_loss': 12.5}, 'dossier': 'x' * 100000}),
        '{broken', 'null', '[]', '{"proposal":false}',
        '{"proposal":{"strategy_id":"s","stop_loss":"2.10"}}',
    ]
    conn.executemany('INSERT INTO trade_audit VALUES (?)', [(p,) for p in payloads])
    rows = conn.execute('SELECT ' + _strategy_context_projection(postgres=False) + ' FROM trade_audit').fetchall()
    assert json.loads(rows[0][0]) == {'proposal': {'strategy_id': 'trend', 'stop_loss': 12.5}}
    assert len(rows[0][0]) < 100
    assert json.loads(rows[1][0]) == {}
    assert json.loads(rows[-1][0])['proposal']['stop_loss'] == '2.10'
    conn.close()


def test_postgres_projection_guards_invalid_json():
    expression = _strategy_context_projection(postgres=True)
    assert 'pg_input_is_valid' in expression
    assert "'{proposal,strategy_id}'" in expression
    assert "'{proposal,stop_loss}'" in expression


def test_selection_fetches_once_per_evaluation_not_once_per_candidate():
    from ai_trader.trading_intelligence import select_strategy, STRATEGIES
    ids = list(STRATEGIES)[:2]
    proposal = SimpleNamespace(normalized=lambda: SimpleNamespace(plain_english_reasoning='Normal research'))
    def score(profile, *args):
        return dict(strategy_id=profile['strategy_id'], strategy_name='test', score=1,
                    reason='test', reason_rejected='test')
    with patch('ai_trader.strategy_performance.strategy_records', return_value={}) as read, \
         patch('ai_trader.trading_intelligence._candidate_strategy_ids', return_value=ids), \
         patch('ai_trader.trading_intelligence._score_strategy_candidate', side_effect=score):
        select_strategy(proposal, db_path=Path('unused'))
        assert read.call_count == 1
        select_strategy(proposal, db_path=Path('unused'))
        assert read.call_count == 2  # fresh on the next evaluation, not a stale global cache


def test_empty_shared_statistics_do_not_trigger_another_read():
    from ai_trader.trading_intelligence import strategy_definition
    with patch('ai_trader.strategy_performance.historical_statistics_for') as read:
        result = strategy_definition('equity_conservative_ai_assisted', Path('unused'), statistics={})
        assert not read.called
        assert result['historical_statistics']['sample_size'] == 0
