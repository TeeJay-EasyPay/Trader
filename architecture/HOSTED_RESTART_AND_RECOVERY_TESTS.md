# Hosted Restart And Recovery Tests

Date: 2026-07-18

## Required Test Cases

- API restart preserves persisted job runs.
- Worker restart updates the same worker identity or records a new worker identity.
- Abandoned learning workflow claims become retryable after timeout.
- Duplicate cron execution skips through idempotency keys.
- Broker polling after restart does not duplicate broker events.
- Reports generated before restart remain available.

## Implemented Code Support

- Scheduled jobs use idempotency keys.
- Worker cycles record heartbeats.
- Learning outbox claimed rows can be reclaimed after timeout.
- Hosted startup refuses SQLite when Postgres is required.

## Missing Production Evidence

These tests require Render deployment access and a shared Postgres database. They were not completed from this environment.
