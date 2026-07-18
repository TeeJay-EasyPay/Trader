# Always-On Runtime Forensic Audit

Date: 2026-07-17

## Purpose

This audit records what can be proven from the repository and local persisted runtime design after the Always-On Trading Operations sprint, and what still requires Render dashboard/log verification.

The audit does not infer operational success from source code alone.

## Current Render Blueprint Evidence

- Service type in `render.yaml`: one existing `web` service named `ai-trader-api`.
- Web plan in `render.yaml`: `starter`.
- Dockerfile: `Dockerfile`.
- Health check: `/healthz`.
- Persistent disk in `render.yaml`: `ai-trader-data` mounted at `/data`, size `1GB`.
- Docker environment database path: `AI_TRADER_DB_PATH=/data/audit.sqlite3`.
- Docker environment output path: `AI_TRADER_OUTPUT_DIR=/data`.
- Docker environment trading log path: `AI_TRADER_TRADING_LOG_PATH=/data/TRADING_LOG.md`.
- `RESEARCH_SCHEDULER_ENABLED=true` is present for the web service in the prior blueprint.
- `RESEARCH_SCHEDULER_INTERVAL_MINUTES=60`.
- `RESEARCH_SCHEDULER_LIMIT=30`.

## New Runtime Entry Points Added

The codebase now supports explicit process entry points:

- `python -m ai_trader serve-api`
- `python -m ai_trader run-worker`
- `python -m ai_trader run-job premarket-equity`
- `python -m ai_trader run-job market-open-equity`
- `python -m ai_trader run-job midday-equity`
- `python -m ai_trader run-job market-close-equity`
- `python -m ai_trader run-job overnight-crypto`
- `python -m ai_trader run-job daily-learning`
- `python -m ai_trader run-job daily-report`

## Durable Evidence Added

New tables:

- `SCHEDULED_JOB_RUNS`
- `WORKER_HEARTBEATS`
- `RESEARCH_FUNNELS`
- `SHADOW_TRADES`
- `OPERATIONS_INCIDENTS`

These tables prove whether background work actually ran, when it ran, what it processed, and why it did or did not submit a trade.

## Render Worker/Cron Status

The worker and cron commands are implemented, but the Render blueprint does not enable separate worker/cron services yet because the production datastore is still SQLite. Enabling multiple independent writers against SQLite on Render would not satisfy the sprint's operational-truth standard.

The next deployment architecture step is Supabase Postgres.

## Current Inconclusive Items

The following cannot be proven from source code alone and require Render logs or dashboard evidence:

1. Exact live Render plan currently active.
2. Whether the live service spins down after inactivity.
3. Whether the persistent disk is mounted on the currently deployed service.
4. Whether the live database path is `/data/audit.sqlite3`.
5. Whether `/data/audit.sqlite3` survived the last deployment.
6. Last 20 deployed research cycles.
7. Last 20 deployed auto-execution cycles.
8. Last 20 deployed broker polls.
9. Last successful Alpaca market-data retrieval on Render.
10. Last equity proposal generated on Render.
11. Last equity proposal rejected on Render.
12. Exact reason each recent Alpaca opportunity did not trade in production.

## Root-Cause Hypothesis Before Live Log Review

The strongest source-code hypothesis is that continuous work was previously owned by daemon threads inside the API process. That means the mobile app did not literally run the scheduler, but the practical production signal was still ambiguous because:

- the API service was the only deployed service;
- scheduler/worker loops had no durable heartbeat table;
- auto-execution cycles had no durable job-run table;
- no-trade decisions did not always produce a founder-facing funnel;
- shadow trading was not an independent always-on evidence stream.

## New Proof Standard

Going forward, AI Trader must prove always-on behaviour from persisted records:

- `WORKER_HEARTBEATS.last_heartbeat_at`
- `SCHEDULED_JOB_RUNS.status`
- `RESEARCH_FUNNELS.primary_reason`
- `SHADOW_TRADES.decision_status`
- `/operations-health`
- `/scheduler-status`
- `/alpaca-inactivity-diagnosis`

If those records are missing, the correct Founder-facing answer is:

> The system did not prove that the background operation ran.
