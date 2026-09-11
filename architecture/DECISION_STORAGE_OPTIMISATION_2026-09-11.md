# Lossless decision evidence storage

## Scope

Preserve every decision, audit, proposal and learning ID. Do not suppress repeated
risk checks, change orders, change experiment engines or alter paused maintenance.
Deduplicate large intelligence objects in decision_journal, execution_decisions
and trade_audit. Small fields used by SQL projections remain inline.

## Implementation

The PostgreSQL adapter wraps the payload parameter of these three INSERTs in
`compact_decision_payload`. This database function stores intelligence objects
of at least 1 KiB in `decision_evidence_blobs`, keyed by SHA-256 of their JSONB
text. Identical evidence, including the duplicate audit intelligence field, shares
one blob. Its immutable contents have a database hash constraint. Changed evidence
gets a different hash; historical evidence is never overwritten.

Full JSON reads through the adapter reconstruct their original logical contents,
batching references into one lookup per fetched batch and checking hashes. Missing
or corrupt evidence fails closed. SQLite remains inline. Both forms can coexist.
Existing SQL projections for prices, stops, strategy IDs, eligibility and reasons
remain unchanged. External SQL users needing full intelligence must explicitly use
`expand_decision_payload(payload_json)`; direct raw JSON now contains references.

No snapshot deletion/garbage collection is included. Existing retained evidence
must not be removed merely because one referencing decision is archived.

## Rollout and rollback

1. `tools/decision_storage_rollout.py prepare`: additive tables/functions, policy off.
2. Deploy compatible adapter to API and worker, verify both commit IDs.
3. Enable policy. New writes become compact; all existing rows remain readable.
4. Migrate bounded 200-row transactions. Large JSON never leaves PostgreSQL.
   Each updated row must reconstruct identically; migration records retain the
   original logical hash and sizes. A mismatch rolls back the whole batch.
5. Verify reconstructed hashes against the manifests for all migrated rows.

Rollback requires disabling compaction and restoring inline payloads with the
provided bounded command BEFORE deploying an older reader. Turning off the policy
alone does not make an old reader compatible with already compacted rows.

Ordinary vacuum can make old storage reusable. It does not promise an immediate
drop in allocated database bytes. VACUUM FULL/repacking is deliberately excluded:
it needs separate capacity/locking planning, not an unannounced trading outage.

## Verification

PostgreSQL transaction-only tests demonstrated disabled passthrough, shared blobs,
idempotence and exact reconstruction. Ten actual recent records from EACH table
were compacted and reconstructed successfully, with all test writes rolled back.
Unit coverage includes unchanged SQL, batch lookup, missing/corrupt evidence,
mixed inline records and cursor index/name access. Release measurements follow.
