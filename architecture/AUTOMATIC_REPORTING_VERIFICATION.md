# Automatic Reporting Verification

Date: 2026-07-18

## Implemented

The scheduled-job CLI can now generate:

- daily reports;
- weekly reports;
- monthly reports.

Commands:

```text
python -m ai_trader run-job daily-report --report-type daily
python -m ai_trader run-job weekly-report --report-type weekly
python -m ai_trader run-job monthly-report --report-type monthly
```

The Render blueprint schedules these jobs.

## Production Evidence Required

Automatic reporting is only complete when:

- Render cron invokes each reporting command;
- a `SCHEDULED_JOB_RUNS` record exists for the report job;
- `TRADING_REPORTS` contains the generated report;
- the mobile app can open the report from the hosted API.

## Current Status

Repository implementation is ready. Hosted cron execution is not yet proven.
