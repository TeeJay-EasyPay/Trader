from types import SimpleNamespace
import sqlite3

from ai_trader import experience_engine, operational_truth


class NoConflictLastId:
    """Exercise the PostgreSQL adapter contract without paid/external calls."""
    def __init__(self, path):
        self.conn = sqlite3.connect(path)
    def __enter__(self):
        self.conn.__enter__()
        return self
    def __exit__(self, *args):
        return self.conn.__exit__(*args)
    def close(self):
        self.conn.close()
    def execute(self, sql, parameters=()):
        cursor = self.conn.execute(sql, parameters)
        if sql.lstrip().upper().startswith('INSERT') and 'ON CONFLICT' in sql.upper():
            return SimpleNamespace(rowcount=cursor.rowcount, lastrowid=None)
        return cursor


def test_new_and_duplicate_experience_resolve_the_same_id(tmp_path, monkeypatch):
    db = tmp_path / 'ids.sqlite'
    experience_engine.initialize_experience_engine_schema(db)
    monkeypatch.setattr(experience_engine, 'initialize_experience_engine_schema', lambda _: None)
    monkeypatch.setattr(experience_engine, 'connect', NoConflictLastId)
    args = dict(symbol='TEST', broker='kraken', decision_context={'entry': 10})
    first = experience_engine.record_experience(db, **args)
    second = experience_engine.record_experience(db, **args)
    assert first['status'] == 'recorded'
    assert first['experience_id'] is not None
    assert second['status'] == 'duplicate'
    assert first['experience_id'] == second['experience_id']


def test_lifecycle_insert_has_an_id_with_conflict_clause(tmp_path, monkeypatch):
    db = tmp_path / 'lifecycle.sqlite'
    operational_truth.initialize_operational_truth_schema(db)
    monkeypatch.setattr(operational_truth, 'initialize_operational_truth_schema', lambda _: None)
    monkeypatch.setattr(operational_truth, 'connect', NoConflictLastId)
    result = operational_truth.record_lifecycle_event(db, stage='learning_completed',
        broker='kraken', symbol='TEST', idempotency_key='test:one', payload={})
    assert result['lifecycle_id'] is not None
