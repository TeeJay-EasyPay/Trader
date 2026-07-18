# Postgres Production Migration Report

Date: 2026-07-18

## Current State

AI Trader still supports SQLite for local development, tests, and offline demos. The hosted Render deployment must now use Postgres when production safeguards are enabled.

The configuration layer supports:

```text
AI_TRADER_DATABASE_BACKEND=postgres
DATABASE_URL=<Supabase pooled Postgres URL>
SUPABASE_DATABASE_URL=<alternative Postgres URL>
AI_TRADER_REQUIRE_POSTGRES_IN_HOSTED=true
```

If hosted runtime is detected and Postgres is not configured, startup fails with a clear error instead of writing critical evidence to SQLite.

## Migrated Runtime Families

The Always-On operations evidence backend already supports Postgres for:

- scheduled job runs;
- worker heartbeats;
- research funnels;
- shadow trades;
- operations incidents.

These are the records needed to prove that the backend ran while the phone was closed.

## Remaining SQLite-Oriented Families

The following critical runtime families remain SQLite-oriented until their owners are ported deliberately:

- recommendations;
- proposal state;
- broker runtime;
- broker history;
- order intent locks;
- managed exits;
- canonical lifecycle;
- execution costs;
- attribution;
- R multiples;
- MAE/MFE;
- portfolio intelligence;
- market intelligence;
- experience records;
- learning proposals;
- reports;
- operational events from Sprint 6.

## Production Rule

Do not enable independent Render worker and cron writers against SQLite. Production autonomy requires one shared durable database visible to API, worker, and scheduled jobs.

## Migration Plan

1. Keep SQLite as the test/local backend.
2. Promote Always-On evidence to Supabase/Postgres first.
3. Port broker runtime and broker history.
4. Port recommendations and proposal state.
5. Port canonical lifecycle and reconciliation.
6. Port attribution, costs, R multiples, MAE/MFE.
7. Port reports, experience records, learning proposals, and operational events.
8. Run parallel-read verification before retiring production SQLite writes.

## Current Release Gate

Set `DATABASE_URL` or `SUPABASE_DATABASE_URL` in Render before activating worker and cron services.
