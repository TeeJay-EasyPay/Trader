# Render Production Topology

Date: 2026-07-18

## Target Services

`render.yaml` now defines the intended production topology.

### API Service

Name: `ai-trader-api`

Command:

```text
python -m ai_trader serve-api
```

Responsibilities:

- serve HTTP endpoints;
- expose Founder dashboard data;
- accept authenticated governed commands;
- initialize schemas;
- refuse hosted SQLite when production Postgres is required.

The API should not own critical continuous scheduling when `AI_TRADER_DISABLE_API_BACKGROUND_WORKERS=true`.

### Background Worker

Name: `ai-trader-worker`

Command:

```text
python -m ai_trader run-worker --sleep-seconds 60
```

Responsibilities:

- broker polling;
- managed exit monitoring;
- auto-execution eligibility evaluation;
- learning workflow outbox processing;
- worker heartbeat updates;
- incident generation on cycle failure.

### Cron Jobs

The blueprint declares:

- `ai-trader-premarket-equity`
- `ai-trader-market-open-equity`
- `ai-trader-midday-equity`
- `ai-trader-market-close-equity`
- `ai-trader-overnight-crypto`
- `ai-trader-daily-learning`
- `ai-trader-daily-report`
- `ai-trader-weekly-report`
- `ai-trader-monthly-report`

Cron jobs use idempotent scheduled-job claims. If Render retries the same scheduled job, the duplicate should be recorded as skipped instead of executing twice.

## Required Shared State

All services must use the same Postgres database. Production should not use separate SQLite files across API, worker, and cron containers.

## Release Warning

This topology is implemented in code and blueprint form, but not verified live from this environment. The deployment gate remains open until Render confirms the services are created, deployed, and producing persisted job records.
