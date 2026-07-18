# Known Limitations

## Sprint 6 Production Control

Sprint 6 installs mandatory pre-execution evidence gates locally, but hosted production qualification still requires Render/Supabase runtime evidence.

The following are not yet proven by local tests:

- phone-closed worker uptime;
- hosted cron execution;
- Supabase/Postgres as the shared runtime truth for every critical table;
- live Alpaca paper fill reconciliation through Sprint 6 mappings;
- real Kraken terminal trade learning through the Sprint 6 outbox;
- automatic outbox processing by a durable worker.

## Strategy Entitlement

The default Sprint 6 strategy is intentionally conservative. It is seeded at `Paper` and does not allow `micro_live` or `production` execution by default. Kraken micro-live strategy entitlement requires explicit evidence and governed promotion.

## Closed-Loop Learning Outbox

Terminal broker rows are queued idempotently for learning, but the durable worker-owned outbox processor still needs to be completed and verified against hosted runtime records.

## Database Spine

The production spine currently reports `partial_spine` until all critical runtime families are migrated to Postgres/Supabase.

Always-On operations evidence can use Postgres. Broker runtime, recommendations, lifecycle, reports, and learning remain SQLite-oriented unless migrated in a later phase.

## Reconciliation

The Phase 5 reconciliation layer groups and records broker events deterministically, but advanced cases still need expansion:

- complex broker corrections;
- replaced order chains;
- late events that contradict previously closed trades;
- full broker-specific fee normalization;
- complete partial-fill lifecycle analytics.

## Closed-Loop Learning

Closed-loop learning runs idempotently for supplied terminal trades. It still depends on terminal trade detection being called by reconciliation or the orchestrator.

## Portfolio Manager

Portfolio Manager authority is implemented as a deterministic decision function, but broader live integration into every approval path should be completed in the next controlled phase.

## Market Data Gateway

The gateway validates candles and records provenance. Full provider failover and production data-provider routing remain future work.

## Strategy Promotion

The strategy maturity ladder exists with evidence gates. Strategy execution eligibility should next be wired directly into recommendation and orchestrator approval.

## Deployment

This local implementation does not prove Render worker/cron uptime. Deployment verification remains required before claiming always-on production operation.
