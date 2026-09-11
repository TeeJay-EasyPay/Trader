"""Bounded, lossless server-side rollout. No orders, deletes, or VACUUM FULL.

prepare -> deploy all readers -> enable -> migrate -> verify.
Rollback: disable, restore, verify zero references, THEN roll back application.
Existing paused backup/retention jobs are not touched.
"""
import argparse
import json
import os
from pathlib import Path

import psycopg
from ai_trader.config import load_dotenv

TABLES = {'decision_journal': 'decision_id', 'execution_decisions': 'execution_decision_id', 'trade_audit': 'id'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['prepare', 'enable', 'disable', 'status', 'migrate', 'restore', 'verify'])
    p.add_argument('--table', choices=TABLES, default='decision_journal')
    p.add_argument('--after', type=int, default=0)
    p.add_argument('--batches', type=int, default=1)
    args = p.parse_args()
    if not 1 <= args.batches <= 100:
        p.error('batches must be 1..100 (200 rows per transaction)')
    load_dotenv()
    table, pk = args.table, TABLES[args.table]
    with psycopg.connect(os.environ['AUDIT_DATABASE_URL'], connect_timeout=15) as c:
        # Explicit per-transaction mode: transaction poolers may inherit a
        # server session's default left by a previous diagnostic connection.
        c.read_only = args.action in ('status', 'verify')
        c.execute("SET LOCAL statement_timeout='20s'")
        c.execute("SET LOCAL lock_timeout='2s'")
        if args.action == 'prepare':
            c.execute(Path(__file__).with_name('sql').joinpath('decision_storage.sql').read_text(encoding='utf-8'))
            print('Additive schema prepared; existing enablement preserved.')
        elif args.action in ('enable', 'disable'):
            c.execute('UPDATE decision_storage_policy SET enabled=%s WHERE id=1', (args.action == 'enable',))
            print(args.action)
        elif args.action in ('migrate', 'restore'):
            enabled = c.execute('SELECT enabled FROM decision_storage_policy WHERE id=1').fetchone()[0]
            if enabled != (args.action == 'migrate'):
                raise RuntimeError('Migrate requires enabled policy; restore requires disabled policy')
            c.commit()
            cursor, total = args.after, 0
            for _ in range(args.batches):
                with c.transaction():
                    c.execute("SET LOCAL statement_timeout='20s'")
                    c.execute("SET LOCAL lock_timeout='2s'")
                    # All large JSON stays in Postgres. Only counts/cursor leave it.
                    function = 'compact_decision_payload' if args.action == 'migrate' else 'expand_decision_payload'
                    rows = c.execute(f'''WITH selected AS MATERIALIZED (
                        SELECT {pk} AS id,payload_json FROM {table}
                        WHERE {pk}>%s ORDER BY {pk} LIMIT 200 FOR UPDATE
                    ), converted AS MATERIALIZED (
                        SELECT id,payload_json,{function}(payload_json) AS compact FROM selected
                    ), recorded AS (
                        INSERT INTO decision_storage_migrations
                          (source_table,source_id,original_hash,compact_hash,original_bytes,compact_bytes)
                        SELECT %s,id,encode(sha256(convert_to(payload_json::jsonb::text,'UTF8')),'hex'),
                          encode(sha256(convert_to(compact::jsonb::text,'UTF8')),'hex'),
                          octet_length(payload_json),octet_length(compact)
                        FROM converted WHERE %s AND compact::jsonb<>payload_json::jsonb
                        ON CONFLICT DO NOTHING RETURNING source_id
                    ), updated AS (
                        UPDATE {table} t SET payload_json=v.compact FROM converted v
                        WHERE t.{pk}=v.id AND v.compact::jsonb<>v.payload_json::jsonb
                          AND expand_decision_payload(v.compact)::jsonb=expand_decision_payload(v.payload_json)::jsonb
                        RETURNING t.{pk}
                    ) SELECT (SELECT max(id) FROM selected), (SELECT count(*) FROM selected),
                        (SELECT count(*) FROM updated),
                        (SELECT count(*) FROM converted WHERE compact::jsonb<>payload_json::jsonb)
                    ''', (cursor, table, args.action == 'migrate')).fetchone()
                    last, selected, changed, expected = rows
                    if changed != expected:
                        raise RuntimeError('Lossless comparison failed; entire batch rolled back')
                total += changed
                if last is not None:
                    cursor = last
                if selected < 200:
                    break
            print(json.dumps(dict(table=table, action=args.action, after=cursor, changed=total, last_batch_selected=selected)))
        elif args.action == 'verify':
            cursor, checked = args.after, 0
            c.commit()
            for _ in range(args.batches):
                with c.transaction():
                    c.execute("SET LOCAL statement_timeout='20s'")
                    result = c.execute(f'''WITH selected AS MATERIALIZED (
                        SELECT m.source_id,m.original_hash,t.payload_json
                        FROM decision_storage_migrations m LEFT JOIN {table} t ON t.{pk}=m.source_id
                        WHERE m.source_table=%s AND m.source_id>%s ORDER BY m.source_id LIMIT 200
                    ) SELECT max(source_id),count(*),count(*) FILTER (WHERE payload_json IS NULL OR
                        encode(sha256(convert_to(expand_decision_payload(payload_json)::jsonb::text,'UTF8')),'hex')
                          <> original_hash) FROM selected''', (table,cursor)).fetchone()
                    if result[2]:
                        raise RuntimeError('Verification failed: missing row or changed evidence')
                checked += result[1]
                cursor = result[0] or cursor
                if result[1]<200:
                    break
            print(json.dumps(dict(table=table, checked=checked, mismatches=0, after=cursor, last_batch_selected=result[1])))
        else:
            print('policy', c.execute('SELECT enabled FROM decision_storage_policy WHERE id=1').fetchone())
            for name, key in TABLES.items():
                print(name, c.execute(f'''SELECT count(*),pg_total_relation_size(%s) FROM {name}''', (name,)).fetchone())
            print('blobs', c.execute("SELECT count(*),coalesce(sum(octet_length(payload_json)),0),pg_total_relation_size('decision_evidence_blobs') FROM decision_evidence_blobs").fetchone())


if __name__ == '__main__':
    main()
