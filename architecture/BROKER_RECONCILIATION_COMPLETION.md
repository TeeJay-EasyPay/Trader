# Broker Reconciliation Completion

Date: 2026-07-18

## Current Connected Brokers

- Alpaca
- Kraken

## Implemented This Sprint

The background worker command now runs broker polling as an autonomous job. Broker polling remains independent of the mobile app when the Render worker service is active.

The Sprint 6 broker event normalization layer remains idempotent. Duplicate broker events are recorded as duplicates rather than new logical activity.

## Completion Boundary

This sprint did not rewrite the full Alpaca/Kraken reconciliation engine. It strengthens operational ownership and learning outbox processing around the existing broker polling and reconciliation path.

## Production Evidence Required

To mark broker reconciliation complete in hosted production, capture:

- a Render worker heartbeat;
- a `broker-poll` scheduled job run;
- latest Alpaca poll result;
- latest Kraken poll result;
- canonical lifecycle rows for any broker events;
- duplicate event count when polling returns already-seen rows.

## Safety

Kraken live controls remain unchanged. Broker polling and managed exits can continue while new-entry auto trading is disabled.
