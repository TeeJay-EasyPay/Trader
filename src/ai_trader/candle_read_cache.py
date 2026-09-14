"""Conditional transfer of unchanged daily candles, not a stale-data TTL cache.

Postgres computes a digest of the exact selected rows on EVERY read. It sends
the full payload only when that digest differs. Corrections, removals and new
rows invalidate immediately. One SQL snapshot and one round trip per lookup.
"""
from collections import OrderedDict
from copy import deepcopy
from threading import Lock
import json
import hashlib
import os
import sqlite3
import tempfile
from pathlib import Path
import time

_cache = OrderedDict()
_lock = Lock()
MAX_KEYS = 256


def _disk(key, value=None):
    """Public candle payloads only; shared by short-lived jobs on this host.

    Local cache errors are misses, never a reason to bypass the database digest.
    Private directory; bounded rows and payloads. No credentials stored in keys.
    """
    try:
        root = Path(tempfile.gettempdir()) / 'ai-trader-candle-cache-v1'
        root.mkdir(mode=0o700,exist_ok=True)
        identity=hashlib.sha256(repr(key).encode()).hexdigest()
        with sqlite3.connect(root/'cache.sqlite3',timeout=.1) as c:
            c.execute('CREATE TABLE IF NOT EXISTS entries(id TEXT PRIMARY KEY,payload TEXT NOT NULL,at REAL NOT NULL)')
            if value is None:
                row=c.execute('SELECT payload FROM entries WHERE id=?',(identity,)).fetchone()
                if row:
                    payload=json.loads(row[0])
                    raw=payload['raw']
                    if hashlib.md5(raw.encode()).hexdigest()==payload['digest']:
                        return payload['digest'],json.loads(raw)
            elif len(value['raw'])<=100000:
                c.execute('INSERT INTO entries VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,at=excluded.at',
                          (identity,json.dumps(value),time.time()))
                c.execute('DELETE FROM entries WHERE id NOT IN (SELECT id FROM entries ORDER BY at DESC LIMIT ?)',(MAX_KEYS,))
    except (OSError,sqlite3.Error,ValueError,KeyError,TypeError):
        return None
    return None


def read(conn, symbol, timeframe, limit):
    key = (conn._schema_key, str(conn._conn.info.user), symbol.upper(), timeframe, limit)
    with _lock:
        previous = _cache.get(key)
    if previous is None:
        previous = _disk(key)
    digest = previous[0] if previous else ''
    row = conn.execute('''WITH selected AS (
        SELECT observation_time, open, high, low, close, volume FROM (
            SELECT observation_time, open, high, low, close, volume
            FROM MARKET_DATA_OBSERVATIONS WHERE normalized_symbol=? AND timeframe=?
            ORDER BY observation_time DESC LIMIT ?
        ) history ORDER BY observation_time ASC
    ), packed AS (
        SELECT COALESCE(json_agg(selected ORDER BY observation_time)::text,'[]') AS payload FROM selected
    ) SELECT md5(payload) AS digest, CASE WHEN md5(payload)=? THEN NULL ELSE payload END AS payload FROM packed''',
        (symbol.upper(), timeframe, limit, digest)).fetchone()
    if row['payload'] is None:
        if previous is None or row['digest'] != previous[0]:
            raise ValueError('Candle digest response has no matching local data')
        return deepcopy(previous[1])
    values = json.loads(row['payload'])
    _disk(key, {'digest':row['digest'],'raw':row['payload']})
    with _lock:
        _cache[key] = (row['digest'], values)
        _cache.move_to_end(key)
        while len(_cache)>MAX_KEYS:
            _cache.popitem(last=False)
    return deepcopy(values)
