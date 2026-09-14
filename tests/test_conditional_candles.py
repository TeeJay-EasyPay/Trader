import hashlib
import json
from types import SimpleNamespace
import pytest
from ai_trader import candle_read_cache as cache


class Connection:
    _schema_key = 'test'
    _conn = SimpleNamespace(info=SimpleNamespace(user='reader'))
    def __init__(self):
        self.rows = [{'close': 1}]
        self.transfers = []
    def execute(self, sql, args):
        raw = json.dumps(self.rows)
        digest = hashlib.md5(raw.encode()).hexdigest()
        payload = None if args[-1] == digest else raw
        self.transfers.append(payload)
        return SimpleNamespace(fetchone=lambda: dict(digest=digest, payload=payload))


def test_unchanged_and_corrected_and_removed_rows(monkeypatch):
    monkeypatch.setattr(cache, '_disk', lambda *a: None)
    cache._cache.clear()
    c = Connection()
    first = cache.read(c, 'TEST', '1Day', 120)
    first[0]['close'] = 999
    assert cache.read(c, 'TEST', '1Day', 120) == [{'close': 1}]
    assert c.transfers[-1] is None
    c.rows = [{'close': 2}]
    assert cache.read(c, 'TEST', '1Day', 120) == c.rows
    c.rows = []
    assert cache.read(c, 'TEST', '1Day', 120) == []
    assert c.transfers[-1] is not None


def test_disk_integrity_and_isolation(tmp_path, monkeypatch):
    monkeypatch.setattr(cache.tempfile, 'gettempdir', lambda: str(tmp_path))
    raw = '[{"close":1}]'
    cache._disk(('one',), dict(digest=hashlib.md5(raw.encode()).hexdigest(), raw=raw))
    assert cache._disk(('one',))[1] == [{'close': 1}]
    assert cache._disk(('two',)) is None
    cache._disk(('one',), dict(digest='wrong', raw=raw))
    assert cache._disk(('one',)) is None
