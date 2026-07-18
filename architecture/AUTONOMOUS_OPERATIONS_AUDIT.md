# Autonomous Operations Audit

Date: 2026-07-18

Scope: investigation only. No production functionality was changed as part of this audit.

## Executive Finding

AI Trader is not yet proven to be a continuously operating autonomous investment platform.

The codebase contains many of the required building blocks:

- hosted API service;
- in-process API background threads;
- explicit CLI entry points for worker and scheduled jobs;
- worker heartbeat tables;
- scheduled job run tables;
- research funnel tables;
- shadow trade tables;
- operations incident tables;
- broker adapters;
- broker polling;
- managed exit monitoring;
- auto-execution evaluation;
- learning and reporting functions.

However, the deployed Render blueprint currently declares only one active web service. It does not declare a separate background worker service or Render cron jobs. The current documentation also explicitly states that worker and cron services should not be enabled until Supabase/Postgres is confirmed as the shared runtime datastore.

Therefore the current production shape is best described as:

> A hosted API that can start internal daemon threads, plus local/test worker and job commands, but not yet a proven multi-process autonomous production operating system.

## Evidence Reviewed

Repository files reviewed:

- `render.yaml`
- `Dockerfile`
- `README.md`
- `STATUS.md`
- `governance/IMPLEMENTATION_LOG.md`
- `governance/*.md`
- `architecture/*.md`
- `src/ai_trader/api.py`
- `src/ai_trader/cli.py`
- `src/ai_trader/config.py`
- `src/ai_trader/scheduler.py`
- `src/ai_trader/always_on.py`
- `src/ai_trader/production_spine.py`
- `src/ai_trader/sprint6.py`
- `mobile/App.js`
- local SQLite database at `data/audit.sqlite3`

Hosted checks performed:

- `GET https://trader-no0f.onrender.com/healthz` returned HTTP 200 with JSON status `ok`.
- Unauthenticated `GET /status`, `/recommendations`, and `/portfolio` returned HTTP 401, proving protected endpoints are locked.
- Authenticated runtime checks using the local token could not connect from this environment during the audit window, so live worker and job state could not be verified from hosted endpoints.

Local SQLite evidence reviewed:

- `SCHEDULED_JOB_RUNS`: 4 rows, last local row dated 2026-07-17 22:35 UTC.
- `WORKER_HEARTBEATS`: 2 rows, last local row dated 2026-07-17 22:35 UTC.
- `RESEARCH_FUNNELS`: 0 rows.
- `SHADOW_TRADES`: 0 rows.
- `RESEARCH_RUNS`: 0 rows.
- `BROKER_TRADE_HISTORY`: 0 rows.
- `TRADING_REPORTS`: 0 rows.
- `SPRINT6_WORKFLOW_OUTBOX`: table missing in the local database inspected.
- `CLOSED_LOOP_LEARNING_RUNS`: table missing in the local database inspected.

This local database evidence does not prove production autonomy. It proves that local Always-On schema paths can create some records, but it does not show sustained research, shadow trading, broker reconciliation, reports, or learning output.

## Current Startup Reality

`Dockerfile` runs:

```text
python -m ai_trader.cli serve-api
```

`serve-api` calls `run_server()` in `src/ai_trader/api.py`.

During API startup, `run_server()`:

1. Loads settings.
2. Configures logging.
3. Creates `LocalApiService`.
4. Seeds initial intelligence and benchmark data.
5. Seeds crypto universe with `fetch_live=False`.
6. Runs startup reconciliation.
7. Starts in-process daemon threads:
   - research scheduler, only if `RESEARCH_SCHEDULER_ENABLED=true`;
   - managed exit monitor;
   - broker order/activity poller;
   - auto-executor;
   - crypto universe refresh;
   - push notification dispatcher.

This means the API process can do background work while it is alive. It does not prove independent autonomous operation under a proper worker/cron topology.

## Current Render Reality From Blueprint

`render.yaml` declares:

- one web service named `ai-trader-api`;
- Docker environment;
- starter plan;
- health check path `/healthz`;
- one persistent disk mounted at `/data`;
- `AI_TRADER_DATABASE_BACKEND=sqlite`;
- `RESEARCH_SCHEDULER_ENABLED=true`;
- worker and cron commands only as comments.

It does not declare:

- a background worker service;
- Render cron jobs;
- managed PostgreSQL;
- Supabase connection as active runtime truth.

The comments in `render.yaml` explicitly say not to enable worker/cron while SQLite is the active backend.

## Service Classification

| Subsystem | Classification | Evidence |
|---|---:|---|
| API | Green - Working | `/healthz` returned HTTP 200 from Render. |
| Protected API auth | Green - Working | `/status`, `/recommendations`, `/portfolio` returned 401 without token. |
| Background worker service | Red - Not Working as deployed blueprint | No Render worker service exists in `render.yaml`. |
| Render cron jobs | Red - Not Working as deployed blueprint | No cron services exist in `render.yaml`. |
| In-process API scheduler | Orange - Partially Working | Source starts daemon threads when API process is alive; hosted execution not verified. |
| Worker heartbeat | Yellow - Working locally only | Local rows exist, but no hosted heartbeat verified. |
| Scheduled job records | Yellow - Working locally only | Local rows exist, but no hosted cron evidence verified. |
| Supabase/Postgres runtime | Yellow - Waiting for configuration | Code supports Always-On evidence Postgres, but `render.yaml` sets sqlite. |
| SQLite persistent disk | Orange - Partially Working | Docker sets `/data/audit.sqlite3`; single web process can persist there, but it is not safe for multi-process production. |
| Research scheduler | Orange - Partially Working | API thread can run if enabled; local `RESEARCH_RUNS` and `RESEARCH_FUNNELS` are empty. |
| Market Data Gateway | Yellow - Working locally only | Validation function and tests exist; not wired as mandatory provider gateway for live research. |
| Recommendation generator | Orange - Partially Working | Manual and scheduled paths exist; local proposals are old and funnels empty. |
| Recommendation storage | Orange - Partially Working | `trade_audit` rows exist locally; current hosted state could not be verified. |
| Research freshness | Orange - Partially Working | UI and tables exist, but local evidence shows no current research runs. |
| Alpaca polling | Orange - Partially Working | API thread and worker job paths exist; local broker history empty. |
| Kraken polling | Orange - Partially Working | API thread and worker job paths exist; hosted state not verified. |
| Broker health | Orange - Partially Working | API can build broker panels; hosted detail not verified in this audit. |
| Paper trading | Orange - Partially Working | Alpaca adapter exists; recent autonomous paper execution not proven. |
| Kraken live micro-trading | Yellow - Waiting for configuration/governance | Strategy maturity defaults block micro-live unless promoted. |
| Managed exits | Orange - Partially Working | API thread and worker job paths exist; hosted loop not verified. |
| Broker reconciliation | Orange - Partially Working | Deterministic normalization exists; local broker history empty. |
| Closed trade detection | Orange - Partially Working | Reconciliation and attribution paths exist; local evidence empty. |
| Learning queue | Orange - Partially Working | Queue function exists; local inspected DB lacks outbox table. |
| Learning processor | Red - Not Working automatically | `run_closed_loop_learning()` exists, but no outbox consumer was found. |
| Daily report | Orange - Partially Working | API and `run-job daily-report` exist; local `TRADING_REPORTS` empty. |
| Weekly/monthly reports | Orange - Partially Working | API generation path exists; automatic scheduling not deployed. |
| Incident reports | Orange - Partially Working | Incident tables/functions exist; local incident evidence empty. |
| Founder dashboard | Orange - Partially Working | Mobile renders status if API contract succeeds; recent UI failures indicate contract/runtime fragility. |

## Why The Platform Appears Alive But Not Autonomous

The hosted API is alive. That is different from the investment operating system being autonomous.

Autonomy requires durable evidence that, without the phone being open:

1. a worker heartbeats;
2. scheduled jobs are claimed;
3. research runs;
4. market data refreshes;
5. recommendations are generated or rejected with reasons;
6. brokers are polled;
7. fills reconcile;
8. terminal trades trigger learning;
9. reports are generated;
10. the Founder can verify the above from persisted records.

The current codebase has many of these mechanisms, but the active Render topology does not yet prove them.

## Key Root Causes

1. Separate Render worker and cron services are not enabled.
2. Supabase/Postgres is not active as the shared production truth in `render.yaml`.
3. Critical runtime state is still mixed between SQLite-oriented schemas and partial Postgres-capable Always-On tables.
4. The API web process still owns important background loops in production.
5. Local persisted evidence does not show sustained research, shadow trades, reports, broker history, or learning output.
6. Closed-loop learning can be run idempotently but no durable outbox processor was found.
7. Strategy maturity deliberately blocks live/micro-live execution unless promotion evidence exists.
8. Auto-execution only acts on fresh eligible proposals. If research is stale or no proposal passes the gates, no broker order is expected.

## Conclusion

AI Trader has the foundations for autonomy, but the current evidence does not support saying it is fully autonomous in production.

The biggest issue is not one missing trading indicator. It is the production operating spine: shared durable database, separate worker, scheduled jobs, verified heartbeat, verified research cycles, verified broker polling, and visible no-trade reasons.

