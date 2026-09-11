import hashlib
import json
from unittest.mock import Mock

import pytest

from ai_trader.decision_storage import MARKER, hydrate_rows, prepare_insert
from ai_trader.database import PostgresCursor


@pytest.mark.parametrize('table', ['trade_audit', 'EXECUTION_DECISIONS', 'DECISION_JOURNAL'])
def test_only_payload_parameter_is_wrapped(table):
    sql = f'INSERT INTO {table} (proposal_id,payload_json,reason) VALUES (?, ?, ?)'
    assert prepare_insert(sql) == f'INSERT INTO {table} (proposal_id,payload_json,reason) VALUES (?, compact_decision_payload(?), ?)'


@pytest.mark.parametrize('sql', ['SELECT payload_json FROM trade_audit',
    'INSERT INTO execution_events (payload_json) VALUES (?)',
    'UPDATE trade_audit SET payload_json=? WHERE id=?',
    'INSERT INTO trade_audit (payload_json) VALUES (some_function(?))'])
def test_other_queries_unchanged(sql):
    assert prepare_insert(sql) == sql


def fixture():
    body = json.dumps({'news': 'example '*1000, 'numbers': [1, None, 2.5], 'unicode': '£'}, ensure_ascii=False)
    digest = hashlib.sha256(body.encode()).hexdigest()
    raw = Mock()
    raw.execute.return_value.fetchall.return_value = [dict(evidence_hash=digest, payload_json=body)]
    original = dict(proposal={'entry_price': 1.34, 'intelligence': json.loads(body)}, intelligence=json.loads(body))
    compact = dict(proposal={'entry_price': 1.34, 'intelligence': {MARKER: digest}}, intelligence={MARKER: digest})
    return raw, original, compact


def test_batch_hydration_preserves_exact_values_and_uses_one_lookup():
    raw, original, compact = fixture()
    rows = [dict(id=i, payload_json=json.dumps(compact)) for i in range(100)]
    result = hydrate_rows(rows, raw)
    assert all(json.loads(r['payload_json']) == original for r in result)
    assert json.loads(rows[0]['payload_json']) == compact  # no mutation
    raw.execute.assert_called_once()


def test_inline_and_projected_reads_need_no_lookup():
    raw = Mock()
    rows = [{'payload_json': '{"proposal": {"entry_price": 1.34}}'}, {'count': 30}]
    assert hydrate_rows(rows, raw) == rows
    raw.execute.assert_not_called()


@pytest.mark.parametrize('corrupt', [False, True])
def test_missing_or_corrupt_evidence_fails_closed(corrupt):
    raw, _, compact = fixture()
    if corrupt:
        raw.execute.return_value.fetchall.return_value[0]['payload_json'] = '{}'
    else:
        raw.execute.return_value.fetchall.return_value = []
    with pytest.raises(ValueError):
        hydrate_rows([dict(payload_json=json.dumps(compact))], raw)


def test_cursor_contract_fetch_and_iteration():
    raw, original, compact = fixture()
    cursor = Mock()
    row = dict(id=5, payload_json=json.dumps(compact))
    cursor.fetchone.side_effect = [row, None]
    wrapped = PostgresCursor(cursor, raw_connection=raw, lastrowid=8)
    result = wrapped.fetchone()
    assert result[0] == result['id'] == 5
    assert json.loads(result['payload_json']) == original
    assert wrapped.fetchone() is None
    assert wrapped.lastrowid == 8
    cursor.fetchmany.side_effect = [[row], []]
    assert len(list(wrapped)) == 1
