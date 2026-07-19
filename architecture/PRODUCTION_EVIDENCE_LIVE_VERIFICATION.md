# Production Evidence Live Verification

## Pre-deployment checks completed

- Python compilation passed for changed backend modules.
- Focused production-evidence and Always-On tests passed.
- Full Python suite passed: 148 tests.
- Expo Doctor passed: 17 of 17 checks.
- Android Expo production export completed successfully.

## Hosted verification procedure

After Render deploys the implementation commit:

1. Confirm `/healthz` responds.
2. Call authenticated `/operations-health`; require Postgres active and a fresh worker heartbeat.
3. Call authenticated `/scheduler-status`; require the paid worker to remain active.
4. Call authenticated `/job-runs`; confirm new `evidence-snapshot`, research and operational rows.
5. Call authenticated `/founder-evidence?period=24h&trade_limit=100`; record response time and verify snapshots, jobs and activity are populated.
6. Close the mobile app for at least one worker research interval.
7. Reopen it and verify the latest persisted worker activity appears without a manual analysis action.
8. Compare visible broker values and trade IDs with Alpaca/Kraken source evidence.
9. Confirm no-trade language identifies no opportunity, rejection, blocked execution or operational failure.
10. Confirm a realized P&L number appears only for reconciled/closed evidence.

## Acceptance thresholds

- Warm Founder payload target: 5 seconds or less.
- Mobile cached first render: immediate, followed by a visible refresh timestamp.
- Worker heartbeat: within two expected intervals.
- Broker snapshot: within the configured snapshot interval plus normal API latency.
- Research: within its market-aware or crypto cadence.

## Hosted evidence observed

- Render API and background worker deployed the shared-evidence implementation from Git revision `573c36b346a896e83886348a83204feaa9b1fe05`.
- Authenticated `/founder-evidence` returned shared Postgres evidence in about seven seconds on a warm request.
- A 70-second observation proved that the worker heartbeat advanced from `2026-07-19T23:02:23.635862+00:00` to `2026-07-19T23:03:40.208306+00:00` while autonomous work continued.
- `/scheduler-status` reported `active`; `/founder-evidence` reported `OPERATING NORMALLY`, worker `healthy`, and database `postgres`.
- The 24-hour payload contained four research runs, 36 assets analysed, 24 recommendations, two broker snapshots and 20 bounded trade-history rows.
- No new order passed every execution gate. The persisted conclusion was: `Opportunities were found, but none passed every portfolio, strategy, and risk gate.`
- Recorded net realised P&L was `-0.54616884`, consisting of known fees against zero matched realised trade P&L. This is not presented as full account mark-to-market performance.
- A protected Kraken research run reviewed nine Founder-approved symbols, created six proposals and recorded one explicit no-trade outcome.
- The run exposed and then verified the correction for an unsupported Kraken pair aborting an entire cycle.
- Live inspection exposed slow broker polling as a heartbeat-freshness problem. The worker now emits independent heartbeat pulses, prioritises managed exits and due research, and limits broker polling to durable ten-minute buckets.

## Mobile publication

- `hosted-preview` runtime `1.0.2`: update group `daa2d530-92b9-4ea8-b358-50ae8ced9648`.
- `preview` runtime `1.0.2`: update group `ca32b0ba-a219-4dbf-b418-138b32873749`.
- Both Android updates include the hosted URL and mobile command token from `mobile/.env.local`; secret values were not written to logs or documentation.

The remaining manual acceptance check is visual confirmation on the Founder's installed device after it downloads the OTA update. The backend evidence, autonomous worker operation and mobile bundle publication are proven.
