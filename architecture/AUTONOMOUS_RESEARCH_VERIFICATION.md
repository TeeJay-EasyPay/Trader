# Autonomous Research Verification

Date: 2026-07-18

## Implemented Verification Path

Research jobs can now be invoked independently of the mobile app:

```text
python -m ai_trader run-job premarket-equity --limit 30
python -m ai_trader run-job market-open-equity --limit 30
python -m ai_trader run-job midday-equity --limit 30
python -m ai_trader run-job market-close-equity --limit 30
python -m ai_trader run-job overnight-crypto --limit 20
```

Each job claims a durable scheduled-job record before work starts and completes the record with counts and outcome.

## Evidence Required In Production

Autonomous research is only proven when `SCHEDULED_JOB_RUNS` contains completed records created by Render worker or cron services while the mobile app was closed.

Required proof:

- a completed equity job;
- a completed crypto job;
- a research funnel row for Alpaca or Kraken;
- stale/no-trade reason if no proposal qualified;
- next scheduled scan visible in `/scheduler-status`.

## Current Status

Local entry points exist.

Hosted proof remains open because Render worker/cron activation was not verified in this environment.
