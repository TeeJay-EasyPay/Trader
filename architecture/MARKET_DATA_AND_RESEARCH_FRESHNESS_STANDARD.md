# Market Data And Research Freshness Standard

## Standard

AI Trader must never display stale research as current market evidence.

## Sprint 6 Implementation

Sprint 6 records operational events for:

- research started
- research completed
- research completed with no action
- research blocked by configuration

These events are persisted in `OPERATIONAL_EVENTS`.

## Required Evidence

A research cycle should store:

- provider
- symbol
- retrieval time
- latest market timestamp
- freshness
- data-quality result
- proposal count
- no-trade reasons

## Current Limitation

Sprint 6 records research-cycle evidence but does not yet make every proposal depend on a fresh `MARKET_DATA_GATEWAY_RUNS` row. That is a required next gate before higher autonomy claims.

