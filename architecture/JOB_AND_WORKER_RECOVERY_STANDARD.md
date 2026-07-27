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

## Timeout Isolation

Production worker jobs execute in a dedicated child process after the worker
supervisor has claimed the durable job record.

When a job exceeds `AI_TRADER_WORKER_JOB_TIMEOUT_SECONDS`:

- only the child job process is terminated;
- the `SCHEDULED_JOB_RUNS` row is completed as `timed_out`;
- an `OPERATIONS_INCIDENTS` record identifies the job and worker;
- the supervisor heartbeat remains alive;
- the worker continues to later durable job buckets;
- the same job bucket cannot be claimed again because its idempotency key
  remains authoritative.

A timeout must not terminate the Render background-worker service. Repeated
process exits are treated by Render as crashes and can result in automatic
service suspension.

## Incident Policy

Failures create `OPERATIONS_INCIDENTS`, not silent logs only.
