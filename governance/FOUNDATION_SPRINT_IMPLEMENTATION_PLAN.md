# Foundation Sprint Implementation Plan

Date: 2026-07-04
Status: Implemented

## Objective

Establish Trader as an autonomous investment platform governed by Founder-approved policies, due diligence, structured investment scoring, and deterministic orchestration.

## Implementation Steps

1. Create constitutional governance documents.
2. Add configurable policy tables for investment, risk, broker, learning, and capital allocation.
3. Add due diligence, investment score, broker decision, execution decision, and crypto knowledge tables.
4. Wire Investment Orchestrator to validate governance, policy, due diligence, risk, broker, market, exchange, universe, and capital allocation.
5. Keep only the existing three mobile screens while surfacing broker panels, due diligence, and investment scores.
6. Add tests for policy tables, due diligence, investment score, capital allocation, risk rejection, Kraken credential handling, broker routing, and emergency shutdown.
7. Update documentation, status, implementation log, architecture, and Founder brief.

## Non-Goals

- No live trading enablement.
- No new mobile screens.
- No secrets in mobile.
- No dummy crypto data.
