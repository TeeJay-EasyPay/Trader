# Supabase Postgres Migration Plan

## Decision

Supabase Postgres is the recommended production datastore for AI Trader.

SQLite remains useful for local development and fast tests, but it is not the right long-term database for a Render topology with:

- API process;
- background worker process;
- scheduled cron jobs;
- broker reconciliation;
- shadow trading;
- learning records;
- Founder reports.

## Why Supabase Is Better Than SQLite For Production

SQLite is a single-file database. It is simple and reliable for one local process, but multi-process production scheduling introduces risks:

- web, worker, and cron jobs may try to write at the same time;
- durable state depends on the Render disk attachment and mount path;
- backups, inspection, and operational monitoring are weaker;
- scaling beyond one write owner is awkward;
- forensic audit queries are harder to run safely in production.

Supabase Postgres gives AI Trader:

- one shared database for API, worker, and cron jobs;
- proper concurrent writes;
- stronger durability;
- managed backups;
- SQL inspection from the Supabase dashboard;
- future row-level security options;
- easier analytics for learning and calibration;
- a clean path to more brokers and more historical evidence.

## Migration Principle

Do not rip SQLite out abruptly.

AI Trader should support:

- SQLite for local development and unit tests.
- Supabase Postgres for production.

The application should choose the database backend from environment:

```text
AI_TRADER_DATABASE_BACKEND=sqlite
AI_TRADER_DB_PATH=data/audit.sqlite3
```

or:

```text
AI_TRADER_DATABASE_BACKEND=postgres
DATABASE_URL=<Supabase pooled or direct Postgres URL>
```

## Target Architecture

```text
Mobile App
  |
  v
Render API Service
  |
  v
Supabase Postgres
  ^
  |
Render Worker Service
  ^
  |
Render Cron Jobs
```

All services share:

- recommendations;
- broker runtime;
- scheduled job runs;
- worker heartbeats;
- research funnels;
- shadow trades;
- lifecycle records;
- attribution;
- learning records;
- reports.

## Required Workstreams

### 1. Database Abstraction

Create a small database access layer that can open either:

- SQLite connection;
- Postgres connection.

Avoid rewriting the whole app at once. Start with the Always-On tables because they are the most important for multi-process production truth.

Status: implemented for the Always-On operations evidence tables in `src/ai_trader/always_on.py`. When `AI_TRADER_DATABASE_BACKEND=postgres` and `DATABASE_URL` or `SUPABASE_DATABASE_URL` is configured, these tables are created and used in Postgres:

- `SCHEDULED_JOB_RUNS`
- `WORKER_HEARTBEATS`
- `RESEARCH_FUNNELS`
- `SHADOW_TRADES`
- `OPERATIONS_INCIDENTS`

When Postgres is not explicitly configured, the same helpers continue using SQLite. This keeps local development and the existing test suite stable.

### 2. SQL Compatibility Review

Review current SQLite SQL for:

- `INTEGER PRIMARY KEY AUTOINCREMENT`;
- `ON CONFLICT`;
- `json_extract`;
- SQLite-specific date handling;
- `?` positional parameters;
- table/column case sensitivity;
- boolean handling.

Translate schema to Postgres-compatible migrations.

### 3. Supabase Schema Migrations

Create migrations for:

- `SCHEDULED_JOB_RUNS` - implemented additively through the Always-On schema initializer;
- `WORKER_HEARTBEATS` - implemented additively through the Always-On schema initializer;
- `RESEARCH_FUNNELS` - implemented additively through the Always-On schema initializer;
- `SHADOW_TRADES` - implemented additively through the Always-On schema initializer;
- `OPERATIONS_INCIDENTS` - implemented additively through the Always-On schema initializer;
- broker runtime tables;
- canonical lifecycle tables;
- audit tables.

### 4. Production Read/Write Cutover

Suggested order:

1. Deploy Postgres connection read-only diagnostics.
2. Create Always-On tables in Supabase.
3. Write Always-On records to Supabase.
4. Verify worker and cron records survive deploys.
5. Migrate broker runtime and recommendations.
6. Migrate lifecycle and trade history.
7. Migrate audit/report/learning records.
8. Keep SQLite export as backup during transition.

### 5. Validation

Before declaring the migration complete, prove:

- API writes to Supabase.
- Worker writes to Supabase.
- Cron writes to Supabase.
- Duplicate job locks work under concurrent Postgres connections.
- App reads the same records the worker wrote.
- Alpaca inactivity diagnosis is based on Supabase records.
- Render deploy/restart does not lose operational state.

## Environment Variables Needed

```text
AI_TRADER_DATABASE_BACKEND=postgres
DATABASE_URL=<supabase postgres connection string>
```

Optional:

```text
SUPABASE_URL=<project url>
SUPABASE_SERVICE_ROLE_KEY=<server-side only, never mobile>
```

The mobile app should not receive the service role key.

## Security Notes

- Never put Supabase service role keys in Expo public variables.
- Use `DATABASE_URL` only in Render backend services.
- Keep `EXPO_PUBLIC_*` variables limited to non-secret frontend configuration.
- Do not log `DATABASE_URL`.

## Current Status

Partially implemented.

The first controlled migration step is complete: Always-On operations evidence can now use Supabase/Postgres while SQLite remains the default local/test backend. This specifically covers worker heartbeats, job runs, research funnels, shadow trades, and operations incidents.

The full application is not yet fully migrated. Broker runtime, recommendations, canonical lifecycle, audit, report, and learning tables still use the existing SQLite-oriented modules until their SQL is reviewed and ported in later controlled steps.

## Render Cutover Instructions

To activate Supabase/Postgres for Always-On operations evidence in Render:

```text
AI_TRADER_DATABASE_BACKEND=postgres
DATABASE_URL=<Supabase Postgres connection string>
```

After deploy, verify `/operations-health`. It should report:

```text
database_backend.active_backend = postgres
database_durability = supabase_postgres
```

Only after that verification should separate Render worker and cron services be enabled.
