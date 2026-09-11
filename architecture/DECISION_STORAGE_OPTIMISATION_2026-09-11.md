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

## Rollout status: incomplete, database unavailable

- Runtime commit `9bacc6dc37bc0a5477ffe831f6f22c6e0915cf02` was confirmed on
  both API and background worker. Compaction policy was enabled only afterwards.
- 106 focused tests and two subtests passed in the clean release worktree.
  Two older foundation crypto fixtures fail identically on the unchanged base
  revision (fee hurdle); no trading rules were changed to make those pass.
- All 7,227 trade_audit rows converted and all 7,227 reconstructed hashes verified,
  with zero mismatches. No decision/audit rows or IDs were deleted.
- Last successful intermediate manifest check showed 12,811 execution_decisions
  compacted through ID 24205, and 9,788 decision_journal rows through ID 21219.
  Later batches may have committed; inspect manifests before resuming. IDs earlier
  than those cursors without a manifest were already small/unmodified.
- The deployed decision-journal endpoint returned HTTP 200. The recommendations
  endpoint first timed out, then reported database connection failure.
- Supabase then closed active connections and refused new connections with
  'database system is not accepting connections / Hot standby mode is disabled'.
  Migration processes stopped. No restart, vacuum, deletion or plan upgrade was
  attempted. The cause has not been established; migration load is not ruled out.
- Requested the user's project dashboard status. The available browser requires
  sign-in; database credentials cannot access the project control plane.
- No final storage-saving figure is claimed. Remaining decision migration and
  verification, app health verification and storage reuse assessment are pending.

Resume only after checking project health/capacity. First inspect the policy and
manifests, verify committed batches, and use serial small batches with adequate
headroom. Do not start with parallel migration commands. The additive compatibility
reader must remain deployed; rolling it back before restoring inline JSON is unsafe.

Provider context, not a diagnosis: https://status.supabase.com/ reported an
'Unresponsive Projects' incident resolved on 11 September at 19:06 UTC. This does
not establish that our later project outage is the same incident.
