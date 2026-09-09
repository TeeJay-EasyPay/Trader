import json
import sqlite3
from unittest.mock import patch

from ai_trader.decline_reasons import recent_decline_reasons


def test_sample_groups_exchanges_and_preserves_both_types(tmp_path):
    path = tmp_path / 'sample.db'
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE execution_events (id INTEGER PRIMARY KEY, created_at TEXT, payload_json TEXT, event_type TEXT)')
        payloads = [
            {'broker': 'kraken', 'reason': 'fee_hurdle_not_cleared', 'symbol': 'DOT'},
            {'broker': 'alpaca', 'reason': 'fee_hurdle_not_cleared', 'symbol': 'ABC'},
            {'broker': 'kraken', 'reason': 'ai_review_declined', 'symbol': 'SOL', 'review': {'reasoning': 'Too risky.'}},
            [],
        ]
        for i, payload in enumerate(payloads):
            conn.execute('INSERT INTO execution_events VALUES (?, ?, ?, ?)', (i, f'2026-09-0{i+1}', json.dumps(payload), 'agent_no_trade'))
    # Deliberately isolated SQLite test, never touches the production connector.
    with patch('ai_trader.decline_reasons.connect', side_effect=lambda p: sqlite3.connect(p)):
        result = recent_decline_reasons(path)
    assert result['declines'][0]['broker'] == 'kraken'
    assert {r['broker'] for r in result['mechanical_summary']} == {'kraken', 'alpaca'}
    assert all(r['count'] == 1 for r in result['mechanical_summary'])
    assert result['sample'] == {'events_examined': 4, 'oldest': '2026-09-01', 'newest': '2026-09-04', 'complete_period_total': False}
