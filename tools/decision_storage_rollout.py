"""Bounded, lossless server-side rollout. No orders, deletes, or VACUUM FULL.

prepare -> deploy all readers -> enable -> migrate -> verify.
Rollback: disable, restore, verify zero references, THEN roll back application.
Existing paused backup/retention jobs are not touched.
"""
import argparse
import json
import os
import time
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
    p.add_argument('--batch-size', type=int, default=25)
    p.add_argument('--pause-seconds', type=float, default=5)
    p.add_argument('--verify-mode', choices=['full', 'links'], default='full')
    args = p.parse_args()
    minimum_pause = 0.5 if args.action == 'verify' and args.verify_mode == 'links' else 3
    if not 1 <= args.batches <= 100 or not 1 <= args.batch_size <= 50 or not minimum_pause <= args.pause_seconds <= 30:
        p.error(f'Use 1..100 serial batches, 1..50 rows, and {minimum_pause}..30 seconds between batches')
    load_dotenv()
    table, pk = args.table, TABLES[args.table]
    with psycopg.connect(os.environ['AUDIT_DATABASE_URL'], connect_timeout=15) as c:
        # Explicit transaction mode, with a separate default-read-only check
        # below: never override a provider's protective read-only setting.
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
                if _:
                    time.sleep(args.pause_seconds)
                started = time.monotonic()
                with c.transaction():
                    c.execute("SET LOCAL statement_timeout='5s'")
                    c.execute("SET LOCAL lock_timeout='500ms'")
                    if c.execute("SHOW default_transaction_read_only").fetchone()[0] != 'off':
                        raise RuntimeError('Provider/database default is read-only; stopping')
                    if not c.execute('SELECT pg_try_advisory_xact_lock(71911902)').fetchone()[0]:
                        raise RuntimeError('Another storage batch is running; stopping')
                    # All large JSON stays in Postgres. Only counts/cursor leave it.
                    function = 'compact_decision_payload' if args.action == 'migrate' else 'expand_decision_payload'
                    rows = c.execute(f'''WITH selected AS MATERIALIZED (
                        SELECT {pk} AS id,payload_json FROM {table}
                        WHERE {pk}>%s ORDER BY {pk} LIMIT {args.batch_size} FOR UPDATE
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
                print(json.dumps(dict(progress=cursor, changed=changed, elapsed_seconds=round(time.monotonic()-started,3))), flush=True)
                if selected < args.batch_size or time.monotonic()-started > 2:
                    break
            print(json.dumps(dict(table=table, action=args.action, after=cursor, changed=total, last_batch_selected=selected)))
        elif args.action == 'verify':
            # Conversion already compares full reconstructed values inside its
            # committing transaction. Links mode verifies the compact checksum
            # and both blob references without repeatedly expanding large text.
            # Blob contents are protected by their SHA-256 CHECK constraint.
            invalid = """payload_json IS NULL OR
                encode(sha256(convert_to(expand_decision_payload(payload_json)::jsonb::text,'UTF8')),'hex')
                    <> original_hash"""
            if args.verify_mode == 'links':
                invalid = """payload_json IS NULL OR
                    encode(sha256(convert_to(payload_json::jsonb::text,'UTF8')),'hex') <> compact_hash OR
                    EXISTS (SELECT 1 FROM (VALUES
                        (payload_json::jsonb #>> '{intelligence,__decision_evidence_sha256_v1}'),
                        (payload_json::jsonb #>> '{proposal,intelligence,__decision_evidence_sha256_v1}')
                    ) refs(hash) WHERE hash IS NOT NULL AND NOT EXISTS
                        (SELECT 1 FROM decision_evidence_blobs b WHERE b.evidence_hash=refs.hash))"""
            cursor, checked = args.after, 0
            c.commit()
            for _ in range(args.batches):
                if _:
                    time.sleep(args.pause_seconds)
                started = time.monotonic()
                with c.transaction():
                    c.execute("SET LOCAL statement_timeout='5s'")
                    if not c.execute('SELECT pg_try_advisory_xact_lock(71911902)').fetchone()[0]:
                        raise RuntimeError('Another storage batch is running; stopping')
                    result = c.execute(f'''WITH selected AS MATERIALIZED (
                        SELECT m.source_id,m.original_hash,m.compact_hash,t.payload_json
                        FROM decision_storage_migrations m LEFT JOIN {table} t ON t.{pk}=m.source_id
                        WHERE m.source_table=%s AND m.source_id>%s ORDER BY m.source_id LIMIT {args.batch_size}
                    ) SELECT max(source_id),count(*),count(*) FILTER (WHERE {invalid})
                        FROM selected''', (table,cursor)).fetchone()
                    if result[2]:
                        raise RuntimeError('Verification failed: missing row or changed evidence')
                checked += result[1]
                cursor = result[0] or cursor
                print(json.dumps(dict(progress=cursor, verified=result[1])), flush=True)
                if result[1]<args.batch_size or time.monotonic()-started > 2:
                    break
            print(json.dumps(dict(table=table, checked=checked, mismatches=0, after=cursor, last_batch_selected=result[1])))
        else:
            print('policy', c.execute('SELECT enabled FROM decision_storage_policy WHERE id=1').fetchone())
            for name, key in TABLES.items():
                print(name, c.execute(f'''SELECT count(*),pg_total_relation_size(%s) FROM {name}''', (name,)).fetchone())
            print('blobs', c.execute("SELECT count(*),coalesce(sum(octet_length(payload_json)),0),pg_total_relation_size('decision_evidence_blobs') FROM decision_evidence_blobs").fetchone())


if __name__ == '__main__':
    main()
