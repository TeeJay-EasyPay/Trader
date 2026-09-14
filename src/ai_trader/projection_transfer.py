"""Transfer changed rows, verifying the full SQL result on every read.

Only explicitly selected TEXT/REAL/integer projections use this helper. This is
not a generic DB type adapter, a TTL, or a high-water-mark reconciliation shortcut.
The ordered digest list preserves duplicates, deletions and reordering. Database
errors propagate; a cache failure only loses the bandwidth saving.
"""
import hashlib
import json
import os
import sqlite3
import tempfile
import time
from pathlib import Path

MAX_BYTES = 2_000_000
MAX_ENTRIES = 48


def _cache(key, value=None):
    try:
        root = Path(tempfile.gettempdir()) / 'trader-projection-transfer-v1'
        root.mkdir(mode=0o700, exist_ok=True)
        path = root / 'rows.sqlite3'
        with sqlite3.connect(path, timeout=.15) as c:
            if os.name != 'nt':
                path.chmod(0o600)
            c.execute('CREATE TABLE IF NOT EXISTS entries(id TEXT PRIMARY KEY, payload TEXT, at REAL)')
            if value is None:
                r = c.execute('SELECT payload FROM entries WHERE id=?', (key,)).fetchone()
                result = json.loads(r[0]) if r else {}
                # A corrupt local row must not be advertised as available.
                return {h: raw for h, raw in result.items() if isinstance(raw, str)
                        and hashlib.md5(raw.encode()).hexdigest() == h}
            raw = json.dumps(value, separators=(',', ':'))
            if len(raw.encode()) <= MAX_BYTES:
                c.execute('INSERT INTO entries VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,at=excluded.at',
                          (key, raw, time.time()))
                c.execute('DELETE FROM entries WHERE id NOT IN (SELECT id FROM entries ORDER BY at DESC LIMIT ?)', (MAX_ENTRIES,))
    except (OSError, sqlite3.Error, ValueError, TypeError, AttributeError):
        return {}
    return {}


def read(raw_conn, sql, values=(), *, columns=None):
    """raw_conn is psycopg with dict rows; sql/columns are trusted code constants."""
    identity = tuple(str(getattr(raw_conn.info, k, '')) for k in ('host', 'port', 'dbname', 'user'))
    # Parameters intentionally do not partition the cache: rolling time boundaries
    # should reuse rows. The database still executes the exact parameters and its
    # ordered hashes, never the cache, determine the complete authorised result.
    key = hashlib.sha256(repr((identity, sql, columns)).encode()).hexdigest()
    prior = _cache(key)
    names = '(' + ','.join(columns) + ')' if columns else ''
    statement = f'''WITH selected{names} AS ({sql.strip().rstrip(';')}),
        encoded AS MATERIALIZED (SELECT row_number() OVER () AS pos, row_to_json(selected)::text AS raw FROM selected),
        hashed AS MATERIALIZED (SELECT pos,md5(raw) AS hash,raw FROM encoded)
        SELECT COALESCE((SELECT json_agg(hash ORDER BY pos) FROM hashed),'[]'::json) AS ordering,
               COALESCE((SELECT json_object_agg(hash,raw) FROM hashed
                         WHERE NOT ((%s::jsonb) ? hash)), '{{}}'::json) AS changed'''
    result = raw_conn.execute(statement, (*values, json.dumps(list(prior)))).fetchone()
    ordering, changed = result['ordering'], result['changed']
    available = {**prior, **changed}
    retained = {h: available[h] for h in ordering}
    _cache(key, retained)
    return [json.loads(retained[h]) for h in ordering]
