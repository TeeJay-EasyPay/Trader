# Autonomous Activity Live Verification

Date: 2026-07-19

## Goal

Prove that the Activity screen shows real autonomous work completed while the mobile app was closed.

## Hosted Verification Steps

1. Deploy the API commit to Render.
2. Publish the Expo OTA update.
3. Confirm `/healthz` returns `ok`.
4. Confirm authenticated `/operations-health` reports:
   - `overall=healthy`;
   - `worker_health=healthy`;
   - Postgres/Supabase active.
5. Confirm authenticated `/scheduler-status` shows a recent background-worker heartbeat.
6. Confirm authenticated `/job-runs` shows durable rows.
7. Confirm authenticated `/autonomous-activity?period=24h` returns:
   - `truthfulness.mock_data_used=false`;
   - `truthfulness.synthetic_activity_used=false`;
   - timeline items from persisted records.
8. Close the mobile app.
9. Wait for at least one worker cycle.
10. Reopen the mobile app.
11. Open `Activity`.
12. Confirm the timeline contains an event whose timestamp occurred while the app was closed.
13. Confirm Last 24 Hours totals changed if a new job, poll, research funnel, report, incident, or broker record was persisted.
14. Confirm Why No Trade explains the current no-trade state.

## Expected Healthy Result

The top card should not say healthy merely because the API is reachable. It should reflect worker, scheduler, database, research, broker, report, and incident evidence.

## Acceptable No-Trade Result

No trade is acceptable when the evidence says one of these:

- no opportunity found;
- opportunity found but rejected;
- approved or candidate blocked;
- approved but not submitted;
- order submitted or trade completed.

The Activity screen must not collapse these states into a generic no-trade message.

## Current Limitation

Activity reads the Always-On tables through the Postgres-aware helpers. Some legacy evidence tables are still SQLite-oriented modules and will only contribute hosted rows after their families are migrated or mirrored into the shared production database.

