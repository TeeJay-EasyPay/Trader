# Egress release — 17 September 2026

Implements the verified first release of the consolidated egress plan.

## Changes

- Background experiment worker loads only core experiment state, no UI events or
  recent-opportunity attachments. Settlement reads and schedules are unchanged.
- Explicit schema-table cache partitions prevent A/B/A replacement of the same
  shared cache entry. Bounded eviction remains possible and is not a stale cache.
- Trading policies and filled-trade history validate their exact current result
  on every read and transfer only changed rows. No TTL for risk policies.
- Founder broker-summary SQL returns only the JSON fields that consumer retains.
  Source documents and other consumers remain unchanged.
- Period-independent accepted-order, managed-exit and daily-plan inputs are shared
  across the four Founder summaries within one refresh, never across refreshes.
- Both psycopg connection paths measure consumed row-value bytes, calls, failures,
  SQL duration, connection opens and projection reuse. Fetching and iteration do
  not issue extra SQL. No parameter values or dossiers are logged.
- Local aggregation is bounded by family and eight days of history. Worker ticks
  export at most one <=24 KB compact report per hour into an existing private
  control row (<=576 KB/day written, not downloaded). There are no per-query
  Supabase telemetry writes or AI requests.
- Authenticated /experiments/health exposes worker and API host reports. These
  are explicitly **not billed egress**; provider usage remains null until supplied.
  Worker report freshness is visible through generated_at. Logs also carry compact
  [db-transfer] summaries; tools/db_transfer_report.py combines exported log lines.
- Counter snapshots now capture reset/eviction metadata; comparisons reject
  incompatible windows. COUNT(*) is no longer estimated as a whole table row.

## Verification and tomorrow's comparison

Read-only production parity: both broker summaries and all 33 policy rows match
their prior semantic result, cold and warm. Real psycopg mixed fetchone/fetchmany/
iteration measured each row once. Initial iteration implementation failed that
check and was corrected before release.

Targeted regression suite: 107 tests and 2 subtests passed after publication
instrumentation; deployed revisions are recorded in the handoff.
A pre-release query baseline is saved locally at
data/egress-master-before-20260917.json (23:16:59 UTC September 16).

Use AI Trader-only Supabase usage, not All projects. September 17 includes the
release and cold-cache warmup; one partial day is not proof of sustained savings.
Read compact reports first, rank recurring job/query families, then compare two
or three complete days and accounting/protection health.

## Remaining measurement-dependent work

Connection pooling, further intelligence-packet reuse, refresh redesign and
incremental reconciliation are deliberately gated on the new measurements. They
are not claimed implemented or necessary yet. No projected daily saving is
guaranteed. The instrumentation measures consumed values, not TLS/row framing,
unfetched results or platform traffic; terminated processes can lose buffered
counts. First-day coverage is partial. Supabase provider totals remain authority.

No mobile rebuild, schema migration, evidence deletion, live activation, changed
trading thresholds, reduced protection checks or paid model calls. Existing paused
maintenance edits are excluded. Disable instrumentation with
AI_TRADER_DB_TELEMETRY=0 if runtime overhead is problematic; business-query errors
continue to propagate rather than returning stale cache data.
