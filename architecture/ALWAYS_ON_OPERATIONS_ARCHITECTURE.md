# Always-On Operations Architecture

## Objective

AI Trader separates Founder interaction from trading operations. The mobile app is a read/control interface only. It must not keep research, reconciliation, shadow trading, managed exits, or learning alive.

## Process Topology

```text
Mobile App
   |
   v
API Process: python -m ai_trader serve-api
   |
   v
Durable State: SQLite on persistent disk today, PostgreSQL target
   ^
   |
Background Worker: python -m ai_trader run-worker
   |
   +--> broker-poll job evidence
   +--> managed-exits job evidence
   +--> auto-execution job evidence

Cron Jobs: python -m ai_trader run-job <job-name>
   |
   +--> equity research windows
   +--> overnight crypto
   +--> daily learning
   +--> daily report
```

## API Process Responsibilities

- Serve HTTP endpoints.
- Expose Founder data.
- Accept governed commands.
- Initialize additive schemas.
- Perform startup reconciliation.
- Avoid being the only critical scheduler owner in production.

## Background Worker Responsibilities

- Record heartbeat.
- Poll broker activity.
- Monitor managed exits.
- Evaluate auto-execution eligibility.
- Record each worker cycle as a scheduled job run.
- Persist failures as incidents.

## Scheduled Job Responsibilities

- Claim one named job through an idempotency key.
- Execute the job once.
- Persist completion, no-action, blocked, or failure status.
- Exit cleanly.

## Distributed Job Lock

`SCHEDULED_JOB_RUNS.idempotency_key` is unique. The key is:

```text
<job_name>:<scheduled_for>
```

If a duplicate process attempts the same job, it receives `skipped_duplicate`.

## Durable Evidence

Every meaningful background operation must leave one or more records:

- Worker alive: `WORKER_HEARTBEATS`
- Scheduled cycle: `SCHEDULED_JOB_RUNS`
- Research/no-trade reason: `RESEARCH_FUNNELS`
- Shadow decision: `SHADOW_TRADES`
- Failure requiring Founder attention: `OPERATIONS_INCIDENTS`

## SQLite Limitation

SQLite on a Render disk is not a complete multi-process shared datastore. The code now uses idempotency and short transactions, but the governed production target should be managed PostgreSQL so API, worker, and cron jobs share state safely.

