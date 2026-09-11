"""Lossless shared intelligence storage for the three decision/audit writers.

Postgres is enabled only after the additive SQL migration and all readers are
deployed. SQLite keeps inline JSON. IDs and the small SQL-projected rule fields
never change. Do not delete evidence blobs while any decision references them.
"""
from __future__ import annotations

import hashlib
import json
import re

MARKER = '__decision_evidence_sha256_v1'


def prepare_insert(sql):
    """Wrap ONLY the payload parameter of the three existing simple INSERTs.

    Keep writers and SQLite SQL unchanged; never alter IDs/decision semantics.
    Unknown SQL shapes remain inline (safe, just less compact).
    """
    match = re.match(r'^(\s*INSERT\s+INTO\s+(?:trade_audit|execution_decisions|decision_journal)\s*\()'
                     r'([^)]*)(\)\s*VALUES\s*\()([^)]*)(\).*)$', sql, re.I | re.S)
    if not match:
        return sql
    columns = [c.strip().lower() for c in match[2].split(',')]
    values = [v.strip() for v in match[4].split(',')]
    if 'payload_json' not in columns or len(values) != len(columns) or any(v != '?' for v in values):
        return sql
    values[columns.index('payload_json')] = 'compact_decision_payload(?)'
    return match[1] + match[2] + match[3] + ', '.join(values) + match[5]


def hydrate_rows(rows, raw_connection):
    """Resolve a fetched batch in one extra query, only when references occur.

    Raw psycopg connection avoids recursion through the application cursor.
    Fail closed for missing/corrupt evidence, never hand a partial proposal to
    execution. No process cache: transaction rollback cannot leave ghost blobs.
    """
    parsed, hashes = [], set()

    def collect(value):
        if isinstance(value, dict):
            if set(value) == {MARKER}:
                hashes.add(value[MARKER])
            else:
                for child in value.values():
                    collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    for i, row in enumerate(rows):
        for key, value in row.items():
            if isinstance(value, str) and MARKER in value:
                try:
                    decoded = json.loads(value)
                except ValueError:
                    continue
                collect(decoded)
                parsed.append((i, key, decoded))
    if not hashes:
        return rows
    blobs = raw_connection.execute(
        'SELECT evidence_hash, payload_json FROM decision_evidence_blobs WHERE evidence_hash = ANY(%s)',
        (sorted(hashes),),
    ).fetchall()
    evidence = {}
    for row in blobs:
        digest, text = row['evidence_hash'], row['payload_json']
        if hashlib.sha256(text.encode('utf-8')).hexdigest() != digest:
            raise ValueError('Decision evidence integrity check failed: ' + digest)
        evidence[digest] = json.loads(text)
    if hashes != evidence.keys():
        raise ValueError('Missing decision evidence; refusing partial payload')

    def expand(value):
        if isinstance(value, dict):
            if set(value) == {MARKER}:
                return evidence[value[MARKER]]
            return {key: expand(child) for key, child in value.items()}
        if isinstance(value, list):
            return [expand(child) for child in value]
        return value

    result = [dict(row) for row in rows]
    for i, key, value in parsed:
        result[i][key] = json.dumps(expand(value), sort_keys=True)
    return result
