# Render Production Verification

## What Source Code Can Prove

Source code can prove that endpoints and worker entry points exist.

It cannot prove:

- Render worker uptime.
- Cron execution.
- Supabase durability.
- Broker reconciliation after restart.
- Phone-closed operation.

## Required Hosted Checks

Before claiming production operation:

1. Verify Render API service health.
2. Verify background worker heartbeat records.
3. Verify scheduled job records.
4. Verify database backend is Supabase/Postgres.
5. Close the mobile app and wait through a scheduled cycle.
6. Confirm persisted records were created without mobile activity.
7. Confirm `/sprint6-status` from the installed app.
8. Confirm broker polling records survive redeploy.

## Current Sprint 6 Status

Local implementation and focused tests are complete. Hosted verification is not claimed from this sprint unless separately performed against Render logs and persisted records.

