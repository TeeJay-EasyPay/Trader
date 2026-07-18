# Alpaca Inactivity Root-Cause Report

## Current Finding

Before this sprint, Alpaca inactivity could not be conclusively diagnosed from durable records because the system did not persist a complete research-to-no-trade funnel for every cycle.

## Likely Root Cause

The strongest technical cause was observability, not necessarily a trading failure:

- research loops existed as API-process background threads;
- no separate worker heartbeat was persisted;
- auto-execution cycles did not leave durable job-run records;
- no-trade decisions were not always persisted as a structured funnel;
- stale or unchanged research could appear current.

## New Diagnosis Endpoint

`GET /alpaca-inactivity-diagnosis` now answers:

- last successful research cycle;
- last proposal;
- last valid strategy;
- last eligible paper recommendation;
- last submitted paper order;
- last filled paper order;
- global trading state;
- Alpaca auto-trading state;
- top rejection reasons.

## Founder Interpretation

If no Alpaca trade occurs, the app should now distinguish:

- no fresh research ran;
- fresh research ran but no setup qualified;
- a setup qualified but auto trading was disabled;
- a setup qualified but guardrails blocked it;
- broker submission failed;
- market was closed;
- duplicate position or max-position limit blocked it.

