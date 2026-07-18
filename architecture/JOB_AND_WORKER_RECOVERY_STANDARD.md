# Job And Worker Recovery Standard

## Job Records

Every scheduled job must create a `SCHEDULED_JOB_RUNS` row.

Allowed statuses:

- scheduled;
- started;
- completed;
- completed_no_action;
- partially_completed;
- failed;
- timed_out;
- skipped_duplicate;
- blocked_configuration;
- blocked_market_closed.

## Heartbeats

Every worker must update `WORKER_HEARTBEATS`.

A stale heartbeat means:

> Background work may not be running.

## Restart Recovery

After restart:

- API runs startup reconciliation.
- Worker resumes heartbeat.
- Cron jobs claim new idempotency keys.
- Duplicate jobs are skipped.
- Incomplete lifecycle records remain visible for review.

## Incident Policy

Failures create `OPERATIONS_INCIDENTS`, not silent logs only.

