# Supabase egress reduction: deeper plan

Prepared 14 September 2026. This document records the diagnosis, implementation
sequence, and current delivery state. The first low-risk projection changes are now
implemented locally; production, trading cadence, risk controls, and broker behaviour
have not been changed.

## Implementation checkpoint — 14 September 2026

Implemented locally and covered by regression tests:

- Founder snapshots are written to a zlib-compressed database projection and read from
  that projection first. The previous text row remains as a safe mixed-version and
  corrupt-data fallback, so the HTTP response and mobile contract are unchanged.
- New recommendation writes create a compact Founder summary alongside the immutable
  full dossier. Snapshot generation reads the summary, with a legacy fallback for old
  rows and no bulk database backfill.
- Recurring Kraken broker snapshots omit reconciled-result history from the AI capital
  ledger. The full ledger remains available to explicit detail callers.
- Broker and managed-exit payloads are narrowed to fields consumed by Founder screens;
  the mobile mapper accepts both compact and legacy shapes.
- Worker-claimed job subprocesses no longer eagerly initialize every application schema.
  The persistent parent still performs complete deployment-time initialization, while
  manually invoked standalone jobs retain their full initialization path.
- PostgreSQL connections carry stable API/worker service names, with an exact
  `ai-trader-job:<job>` override for scheduled children. Future query windows can
  therefore identify the timezone and catalogue caller directly.
- The API coalesces bursts of identical Founder snapshot reads for 60 seconds. Local
  writes invalidate immediately and returned objects are isolated from caller mutation.
- Candle refresh was verified as already incremental: it supplies Kraken's `since`
  boundary from the newest durable candle and filters a repeated boundary candle. No
  second, riskier implementation was added.

The live 24-hour Founder response measured 520,426 bytes before these local changes.
Applying the implemented compaction to that captured shape produced approximately
383,490 bytes of JSON (26.3% smaller), and compressing it produced approximately
50,222 bytes (90.3% smaller than the current raw snapshot row). PostgreSQL BYTEA wire
encoding and protocol overhead mean this is a transfer estimate, not a Supabase billing
claim. A production deployment and complete provider-reported day are still required
to measure the actual account-level reduction.

## Executive finding

The supplied project-filtered Supabase chart shows a repeatable baseline of roughly
400-500 MB per complete day from 7-13 September. Cached egress is empty, and the
earlier billing evidence identifies the traffic as shared-pooler/database traffic.
This shape is consistent with recurring database reads, not trade count or one large
interactive export.

The chart is not yet a verdict on the most recent fixes. The four-path egress release
(`dc831720`) was verified on the API and worker at approximately 01:14 UTC on
14 September. Every complete bar in the screenshot predates it; 14 September is a
partial day. The first valid comparison is a complete, deployment-free day after
that release, allowing for Supabase reporting delay.

The target is:

1. below 150 MB/day on three comparable quiet days (at least 65-70% below the
   400-500 MB/day baseline);
2. no increase in stale Founder snapshots, missed broker corrections, delayed exits,
   reconciliation errors, or database CPU pressure;
3. a separately measured user-facing API transfer budget, because phone traffic and
   Supabase pooler egress are different network legs.

## What is already complete and must not be counted twice

- Mobile Founder refresh moved from two minutes to ten minutes and pauses while the
  app is backgrounded. The ten-minute interval matches snapshot production.
- The Founder payload now contains compact recommendation summaries; full dossiers
  are loaded on demand from `/recommendations`.
- Snapshot generation reads twelve recommendation rows rather than one hundred and
  selects the newest broker snapshot per broker in SQL.
- All four display periods reuse one shared database read per worker snapshot cycle.
- Strategy readiness and performance reuse the same outcome read within a calculation.
- Candle history, Founder projection inputs, Kraken reconciled results, Alpaca fills,
  and schema descriptions use database-verified changed-row transfer.
- Kraken totals are calculated in SQL rather than by downloading historical rows.

The latest production comparison recorded the following full versus unchanged
serialized results. These are transfer proxies, not billed-byte measurements:

| Projection | Cold/full response | Unchanged response |
| --- | ---: | ---: |
| Twelve recommendations | 475,597 bytes | 461 bytes |
| Latest broker snapshots | 131,407 bytes | 101 bytes |
| One hundred research rows | 66,763 bytes | 3,629 bytes |
| One hundred trade rows | 47,318 bytes | 3,629 bytes |
| Fifty-four Kraken results | 80,929 bytes | 1,973 bytes |

## Why a residual can remain

Changed-row transfer avoids retransmitting unchanged rows, but the database still
executes each original query, converts selected rows to JSON, and hashes them. A cold
worker or cache miss still transfers the full result. This is a useful compatibility
bridge, not the final data architecture.

The historical 2.74-hour query-counter window estimated 178 MB/day of returned SQL
rows, while Supabase showed roughly 400-500 MB/day. That window contained four worker
starts and cannot be reconciled exactly to billing. Later counters over about 51 hours
also found 13,109 schema-column queries, 2,916 candle reads, 721 Kraken-ledger reads,
and an unidentified timezone-catalogue query returning 258,336 rows in 216 calls.
Those are cumulative rows, not bytes. The unexplained portion must be measured rather
than assigned to a convenient caller.

## Workstream 1: establish a trustworthy post-release baseline

Collect one 24-hour quiet window, then two confirmation windows. For each window:

- record the AI Trader project-only Supabase egress total and the per-service tooltip
  split (shared pooler/database, Storage, Auth, Realtime, Edge Functions);
- take bounded before/after `pg_stat_statements` snapshots and retain query ID,
  calls, rows, execution time, and a locally calculated result-width estimate;
- record API and worker deployment revisions, starts/restarts, completed job counts,
  research runs, broker polls, app foreground time, and manual diagnostics;
- do not reset shared statistics or download full query histories;
- compare the same UTC boundaries and note Supabase reporting delay.

Deliverable: a reconciliation table with billed MB/day, estimated SQL result MB/day,
restart count, workload count, and the unexplained remainder. No optimisation is
credited until it appears in a full-day provider total.

## Workstream 2: replace wide recurring reads with purpose-built projections

### 2.1 Recommendation summary at write time

Add a compact, versioned recommendation-summary projection populated when a
recommendation is written. It should contain only the fields used by Founder screens:
identity, broker, symbol, side, status, confidence, prices/sizing, strategy identity,
committee result, concise reason, risks, guardrails, and philosophy fit.

Snapshot generation should read that projection directly. Full immutable dossier
JSON remains in its existing evidence/audit home and is fetched only when the Founder
opens recommendation detail. Existing records can fall back to the current twelve-row
read; avoid a database-wide JSON backfill that would itself generate egress.

Why: the current hash-transfer path still makes Postgres encode and hash approximately
476 KB of recommendation rows each cycle and retransfers it after cold starts. A
native summary removes both the wide read and most of that database CPU.

### 2.2 Split Founder data by volatility and screen demand

Measure the current post-release `/founder-evidence` payload by top-level section.
Then separate:

- fast/current: status, worker health, current portfolio and open positions;
- medium: recent activity and current recommendation summaries;
- on demand: closed history, long timelines, learning history and full dossiers.

Keep one bootstrap response for a coherent first render, but subsequent refreshes
should request only the current projection. Add a small snapshot version/ETag lookup
so an unchanged version returns no JSON payload. Historical screens fetch bounded,
paginated records when opened.

At the previously measured 459,280-byte Founder snapshot, a continuously foregrounded
ten-minute poll can transfer about 66 MB/day to the phone. That is not necessarily
Supabase pooler egress, because the API reads the snapshot from Supabase and then sends
it to the phone; both legs must be measured separately. The design should reduce both.

### 2.3 Stop hashing data that has a natural version

For append/update models with reliable primary keys and update timestamps, persist a
small projection version or content digest when writing. Readers first fetch only
version/key metadata and fetch row content only when the version changes. Keep the
current exact-hash method as a fallback for legacy rows and datasets without reliable
change identity.

This preserves detection of corrections and deletions while moving JSON encoding out
of every read. Verify that late broker fee corrections and ownership relinks still
invalidate the version.

## Workstream 3: remove high-frequency metadata and catalogue traffic

### 3.1 Schema discovery

Implementation status: the positive-result table/sequence cache already existed. The
remaining repeat-startup source is now reduced by skipping broad eager initialization
in worker-claimed child jobs. Production acceptance still requires the post-deployment
query counter specified below.

The compatibility layer previously generated material schema traffic. The latest
release transfers unchanged descriptions compactly but still runs catalogue SQL.
Hosted production should use a durable schema-generation marker updated only by
application migrations. Each process loads descriptions once for that generation;
DDL invalidates the generation explicitly. SQLite compatibility retains its existing
behaviour.

Acceptance: at least a 95% reduction in `information_schema.columns` calls during a
no-deploy day, with schema-change and added-column tests proving invalidation.

### 3.2 Identify the timezone-catalogue caller

Implementation status: database application-name attribution is now wired for the
Render API, persistent worker and every scheduled child job. The caller can be named
from the next production statistics window; timezone behaviour has not been changed
speculatively before that evidence exists.

Do not assume the 1,196-row timezone query belongs to AI Trader. Capture its query
text, database role, client/application name, and occurrence times. Correlate those
times with API starts, worker starts, Supabase Studio use, pooler activity, and cron
jobs. Add distinct safe `application_name` values to API, worker, and one-off job
connections for future attribution. If the caller is external tooling, fix that tool;
if it is application startup, cache the timezone choice in the process and avoid a
catalogue enumeration.

Acceptance: named caller and reason, or an explicitly documented provider limitation;
no speculative code change based on row count alone.

## Workstream 4: make reconciliation incremental without weakening safety

Protective exits and current open-order checks remain at their present cadence. Split
those safety-critical reads from historical verification:

- frequent path: open positions, open orders, recent fills, unresolved ownership and
  records changed since a durable cursor;
- correction path: bounded overlap window to catch late fees/status corrections;
- assurance path: complete historical parity sweep at a measured lower frequency and
  after deployments/schema changes.

Use broker IDs plus updated timestamps/version fingerprints, not symbol-only joins.
Persist the cursor only after a complete successful transaction. On uncertainty,
fall back to the complete path. The existing changed-row cache remains a second layer,
not the source of truth.

Acceptance: exact parity against the current full reconciliation for orders, partial
fills, fees, ownership, realised P&L, deletions/corrections and restart recovery; no
change in exit monitoring latency.

## Workstream 5: bound storage so future reads stay bounded

Storage and egress are separate, but wide growing tables make cold reads and recovery
more expensive. Continue the existing summary-first design only after its paused
safety gates are met:

- thirty complete days of routine diagnostic detail;
- structured daily summaries through ninety days;
- compact monthly summaries thereafter;
- permanent exact trade, fill, fee, cash, learning, identity and unresolved-incident
  evidence;
- verified archive and restore test before destructive cleanup.

Do not run database-wide deletion or `VACUUM FULL` as an egress fix. Deletion cannot
undo billed egress and physical rewrites require a separate maintenance decision.

## Workstream 6: add a low-egress technical monitor

Precompute one small hourly row containing database size, estimated egress by query
family, reads/writes, broker polls, trades, worker restarts, deployment revision and
measurement quality. The app reads that row; it must never execute
`pg_stat_statements` on screen view. Show Supabase's provider total only when a
management API source is configured; otherwise label the SQL estimate clearly and
link to the provider dashboard.

Alert thresholds:

- warning above 150 MB/day estimated or provider-reported;
- critical above 250 MB/day for two complete days;
- separate cold-start warning when restarts exceed the agreed operational baseline;
- never suppress trading evidence or delay protection solely to clear an alert.

## Ordered implementation sequence

1. Complete one post-release 24-hour measurement and service split.
2. Attribute the top residual query families and timezone catalogue traffic.
3. Implement recommendation summary-at-write and measure query/result parity.
4. Split/version the Founder projection and add conditional mobile reads.
5. Replace schema catalogue polling with schema-generation invalidation.
6. Introduce incremental reconciliation with periodic full assurance.
7. Re-measure for three quiet days; stop when the target is met and remaining traffic
   is justified.
8. Only then resume separately approved storage retention/archive work.

Each code change gets a focused parity test, a relevant wider regression set, a
deployment revision check, and a before/after production measurement. Batch related
backend changes into one release so deployment restarts do not contaminate the
measurement or repeatedly refill cold caches.

## Access and current measurement boundary

The repository, historical measurements, and authenticated deployed API are available.
The API supplied the live payload sizing used above, but the current Codex in-app
browser has no open Supabase tab. Completing Workstream 1 still requires the signed-in
Supabase project dashboard or equivalent provider billing data for a complete post-
deployment day.

The defensible conclusion is: the historical 400-500 MB/day problem is real; the
previous four-path fix is deployed; this checkpoint implements another substantial
recurring-path reduction locally; and no provider-level saving should be claimed until
this version is deployed and measured over comparable complete days.
