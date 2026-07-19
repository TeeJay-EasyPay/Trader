# Render Service Topology

## Current Blueprint

`render.yaml` now declares:

- `ai-trader-api`: web service for HTTP API.
- `ai-trader-worker`: background worker for broker polling, managed exits, auto-execution evaluation, and learning outbox processing.
- cron jobs for equity research, crypto research, daily learning, and daily/weekly/monthly reports.

The blueprint also sets hosted runtime controls so the API does not own duplicate background scheduler loops when Render worker/cron services are active.

## Implemented Process Commands

The code now supports the target commands:

```text
python -m ai_trader serve-api
python -m ai_trader run-worker
python -m ai_trader run-job premarket-equity
python -m ai_trader run-job market-open-equity
python -m ai_trader run-job midday-equity
python -m ai_trader run-job market-close-equity
python -m ai_trader run-job overnight-crypto
python -m ai_trader run-job daily-learning
python -m ai_trader run-job daily-report
```

## Required Environment

All processes need the same broker, OpenAI, and governance environment variables.

Required:

- `AI_TRADER_API_TOKEN`
- `AI_TRADER_DB_PATH`
- `AI_TRADER_OUTPUT_DIR`
- `ALPACA_API_KEY`
- `ALPACA_SECRET_KEY`
- `ALPACA_PAPER_BASE_URL`
- `ALPACA_DATA_BASE_URL`
- `OPENAI_API_KEY` where AI explanations are required

Broker-specific:

- `ALPACA_AUTO_TRADING`
- `KRAKEN_AUTO_TRADING`
- `KRAKEN_TRADING_ENABLED`
- `KRAKEN_LIVE_TRADING_APPROVED`
- `KRAKEN_SUBMIT_REAL_ORDERS`
- `KRAKEN_TRADING_ALLOCATION_GBP`
- `KRAKEN_MAX_ORDER_GBP`
- `KRAKEN_MIN_ORDER_GBP`
- `KRAKEN_MAX_OPEN_TRADES`
- `KRAKEN_ALLOWED_PAIRS`

## Production Datastore Requirement

Production state must use managed PostgreSQL.

SQLite remains acceptable only for local development, tests, and offline demonstrations. It must not be described as multi-process safe and should not be used by independent Render API, worker, and cron processes.

The first Supabase/Postgres bridge is now implemented for Always-On operations evidence:

- scheduled job runs;
- worker heartbeats;
- research funnels;
- shadow trades;
- operations incidents.

These tables use Postgres when Render is configured with:

```text
AI_TRADER_DATABASE_BACKEND=postgres
DATABASE_URL=<Supabase Postgres connection string>
```

If `AI_TRADER_DATABASE_BACKEND=sqlite`, or if Postgres is requested without a database URL, AI Trader keeps using SQLite for those records.

## Hosted Fail-Close

When `AI_TRADER_REQUIRE_POSTGRES_IN_HOSTED=true`, hosted API, worker, and cron commands refuse to start unless:

```text
AI_TRADER_DATABASE_BACKEND=postgres
DATABASE_URL=<shared Postgres URL>
```

or:

```text
SUPABASE_DATABASE_URL=<shared Postgres URL>
```

This prevents AI Trader from silently splitting runtime truth across container-local SQLite databases.

## Production evidence activation

The API container must keep `RESEARCH_SCHEDULER_ENABLED=false`; it is not the recurring schedule owner. The paid background worker must run `python -m ai_trader run-worker --sleep-seconds 60` with `AI_TRADER_WORKER_RESEARCH_ENABLED=true`. It owns recurring crypto research, market-aware equity research, evidence snapshots, broker polling, managed exits, auto-execution evaluation and learning.

`AI_TRADER_PRODUCTION_SNAPSHOT_INTERVAL_SECONDS` controls broker/Founder evidence capture and defaults to 300 seconds. All services must share the same `DATABASE_URL`. A worker heartbeat without shared production evidence is not sufficient Founder proof.

## Verification

After deploy, verify:

- `/healthz`
- `/status`
- `/operations-health`
- `/scheduler-status`
- `/job-runs`
- `/research-funnel`
- `/shadow-trades`
- `/alpaca-inactivity-diagnosis`
