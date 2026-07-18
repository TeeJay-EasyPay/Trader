# Render Configuration Audit

Date: 2026-07-18

Scope: repository blueprint and limited hosted endpoint verification.

## Blueprint Reviewed

File reviewed: `render.yaml`.

## Current Declared Services

`render.yaml` declares one active service:

| Service | Type | Command Source | Status |
|---|---|---|---|
| `ai-trader-api` | web | Dockerfile `CMD ["python", "-m", "ai_trader.cli", "serve-api"]` | Declared |

No active background worker service is declared.

No active Render cron jobs are declared.

## Disk

The blueprint declares a persistent disk:

```yaml
disk:
  name: ai-trader-data
  mountPath: /data
  sizeGB: 1
```

The Dockerfile sets:

```text
AI_TRADER_DB_PATH=/data/audit.sqlite3
AI_TRADER_OUTPUT_DIR=/data
AI_TRADER_TRADING_LOG_PATH=/data/TRADING_LOG.md
```

This is correct for a single web process using SQLite on a persistent disk.

It is not sufficient for a multi-process production topology with independent API, worker and cron processes. Existing architecture documents correctly state that Supabase/Postgres should be used before worker/cron services are enabled.

## Database Backend

The blueprint currently sets:

```yaml
AI_TRADER_DATABASE_BACKEND=sqlite
DATABASE_URL=<sync false placeholder>
```

Code support exists for Postgres-backed Always-On evidence tables when:

```text
AI_TRADER_DATABASE_BACKEND=postgres
DATABASE_URL=<Supabase Postgres connection string>
```

However, the active blueprint still selects SQLite.

## Worker And Cron Commands

The code implements:

```text
python -m ai_trader run-worker
python -m ai_trader run-job premarket-equity
python -m ai_trader run-job market-open-equity
python -m ai_trader run-job midday-equity
python -m ai_trader run-job market-close-equity
python -m ai_trader run-job overnight-crypto
python -m ai_trader run-job daily-learning
python -m ai_trader run-job daily-report
```

The Render blueprint lists those commands only in comments. They are not active services.

## Hosted Endpoint Verification

The following check succeeded:

```text
GET https://trader-no0f.onrender.com/healthz
HTTP 200
{"status":"ok", ...}
```

The following unauthenticated checks returned HTTP 401:

```text
GET /status
GET /recommendations
GET /portfolio
```

This proves the API is online and protected endpoints are locked without a token.

Authenticated checks for `/status`, `/operations-health`, `/scheduler-status`, `/alpaca-inactivity-diagnosis`, and `/phase5-status` could not connect from this environment during this audit. Therefore live hosted worker and scheduled-job evidence remains unverified.

## Render Logs

Render logs were not available from the local repository. No Render API log export was available in the workspace during the audit.

Because logs were not available, this audit cannot prove:

- live worker heartbeat in Render;
- live scheduled job execution in Render;
- live broker polling in Render;
- live Alpaca research execution in Render;
- live report generation in Render.

## Can AI Trader Continue If The Phone Is Closed?

Based on source code:

- If the Render web service stays alive, its internal daemon threads can continue running without the phone open.
- If the web service restarts, those daemon threads restart with the API process.
- If the web service sleeps, is redeployed, crashes, or is suspended, the in-process threads stop.
- No separate worker service exists in the blueprint to continue work independently.
- No Render cron jobs exist in the blueprint to guarantee named scheduled runs.

Therefore the correct answer is:

> The phone is not technically required by the code path, but production autonomy is not yet proven because the active Render topology relies on the API process and does not deploy independent worker/cron services.

## Render Root Cause Classification

| Area | Classification | Evidence |
|---|---:|---|
| API service | Green - Working | `/healthz` returned 200. |
| Auth lock | Green - Working | Protected endpoints returned 401 without token. |
| Worker service | Red - Not Working | No worker service declared. |
| Cron jobs | Red - Not Working | No cron services declared. |
| Persistent disk | Orange - Partially Working | Correct for SQLite single process, not for multi-process production. |
| Supabase/Postgres | Yellow - Waiting for configuration | Code supports partial Always-On Postgres, blueprint selects SQLite. |
| Hosted runtime evidence | Black - Unable to verify | Authenticated endpoint checks could not connect during audit. |

## Render Remediation Summary

Do not enable worker/cron against SQLite.

First:

1. Activate Supabase/Postgres for Always-On evidence.
2. Verify `/operations-health` reports Postgres.
3. Add worker service.
4. Add cron jobs.
5. Verify worker and cron records from persisted data while the app is closed.

