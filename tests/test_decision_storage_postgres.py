"""Opt-in real Postgres regression, transaction rolled back even on success.

Use a dedicated test database: AI_TRADER_TEST_POSTGRES_URL. Never implicitly
connect using production runtime credentials during a test suite.
"""
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from ai_trader.database import PostgresCursor


@pytest.mark.skipif(not os.getenv('AI_TRADER_TEST_POSTGRES_URL'), reason='explicit Postgres test database required')
def test_same_statement_compaction_reconstruction_and_projection():
    import psycopg
    from psycopg.rows import dict_row
    with psycopg.connect(os.environ['AI_TRADER_TEST_POSTGRES_URL'], row_factory=dict_row) as conn:
        try:
            conn.execute("SET LOCAL statement_timeout='15s'")
            conn.execute((Path(__file__).parents[1] / 'tools/sql/decision_storage.sql').read_text())
            conn.execute('UPDATE decision_storage_policy SET enabled=true WHERE id=1')
            body = {'source': str(uuid4()), 'text': 'Retained evidence £ '*300}
            original = json.dumps({'proposal': {'intelligence': body, 'entry_price': 1.34}, 'intelligence': body})
            # Both functions execute within ONE statement. STABLE expansion is
            # wrong here: it cannot see the freshly inserted evidence blob.
            result = conn.execute('SELECT expand_decision_payload(compact_decision_payload(%s)) AS body', (original,)).fetchone()
            assert json.loads(result['body']) == json.loads(original)
            cursor = conn.execute('SELECT compact_decision_payload(%s) AS payload_json', (original,))
            assert json.loads(PostgresCursor(cursor, raw_connection=conn).fetchone()['payload_json']) == json.loads(original)
            assert conn.execute("SELECT compact_decision_payload(%s)::jsonb #>> '{proposal,entry_price}' AS price", (original,)).fetchone()['price'] == '1.34'
            conn.execute('UPDATE decision_storage_policy SET enabled=false WHERE id=1')
            assert conn.execute('SELECT compact_decision_payload(%s) AS body', (original,)).fetchone()['body'] == original
        finally:
            conn.rollback()
