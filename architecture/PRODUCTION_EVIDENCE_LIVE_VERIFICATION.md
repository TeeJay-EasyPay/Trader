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

- Render API and background worker deployed the shared-evidence implementation from the same Git revision.
- Authenticated `/founder-evidence` returned shared Postgres evidence in about seven seconds on a warm request.
- The payload contained two broker snapshots, 20 bounded trade rows and persisted learning evidence.
- A protected Kraken research run reviewed nine Founder-approved symbols, created six proposals and recorded one explicit no-trade outcome.
- The run exposed and then verified the correction for an unsupported Kraken pair aborting an entire cycle.
- Live inspection exposed slow broker polling as a heartbeat-freshness problem. The worker now emits independent heartbeat pulses, prioritises managed exits and due research, and limits broker polling to durable ten-minute buckets.

Installed-device display and the next autonomous worker research cycle remain final acceptance checks after the heartbeat-hardening deployment and Expo OTA publication.
