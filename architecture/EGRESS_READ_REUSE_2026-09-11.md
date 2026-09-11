# Egress reduction without reducing decision evidence

## Changes

Overall and per-coin strategy calculations now share their outcome and compact
proposal-context reads within one scoreboard refresh or demotion review. The
request-local context is discarded at completion, including on exceptions. There
is no new cross-cycle cache, no reduced evidence window, and no change to readiness,
fees, risk floors, scoring, or demotion conditions. No protection/reconciliation
schedule is changed. This is data reuse, not a reduction in the evidence supplied.

Identical SQL, parameters, database path and PostgreSQL schema identity are required
for reuse. Failed reads are not cached. Existing scoreboard cache duration is unchanged.

## Already implemented / deliberately retained

- Strategy context queries already project strategy ID and stop instead of full dossiers.
- Founder evidence already selects the latest broker snapshot per broker in SQL.
- Schema discovery already has positive-result caches and initialization guards.
  Invalidation after schema setup is retained to avoid stale column/identity information.
- Full decision evidence remains available through the compact-storage reader.
- No deletion, historical backfill, vacuum, backup work, or live trading activation.
- One backend release for these changes; no mobile release needed.

## Verification

- 87 targeted tests passed (fresh isolated pytest temp directory; initial default
  temp-directory attempt had filesystem permission errors, not assertion failures).
- Fixtures confirm exact output parity, four reads reduced to two, fresh subsequent
  evidence, database/parameter isolation and scope cleanup on error.
- Read-only production comparison returned identical results for four strategies
  and 37 strategy/symbol groups: four SELECTs without reuse, two with reuse.
  Five-second query timeouts; no broker or model calls, no production writes.

## What the saving means

This halves the repeated outcome/context SELECTs for these paired calculations,
not total Supabase egress. The supplied dashboard shows September 10 at 446.103 MB,
100% Shared Pooler Egress, and 4.607 GB for the selected last-seven-days window.
September 11 is incomplete. No total daily saving is claimed yet.

Further changes should follow matched steady-state query-counter windows and daily
provider totals, accounting for restarts. Do not remove required evidence or weaken
schema invalidation solely to reduce a historical counter. No monitoring schedule
or additional recurring database workload is added by this release.
