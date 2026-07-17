# Operational Truth and Canonical Lifecycle

Date: 2026-07-17

## Objective

Operational Truth creates one broker-neutral trade lifecycle for Alpaca and Kraken. It prevents the Founder experience from relying on raw broker rows, duplicated notifications, or incomplete order fragments.

## Canonical Lifecycle

Supported stages include idea discovery, research, candidate, committee, approval, broker submission, acknowledgement, partial/full fill, open management, exits, cancellation, closure, attribution, and learning completion.

Illegal transitions are rejected into `LIFECYCLE_TRANSITION_REJECTIONS`. Duplicate broker events are ignored through idempotency keys.

## Tables

- `CANONICAL_TRADE_LIFECYCLE`: one append-only event stream.
- `LIFECYCLE_TRANSITION_REJECTIONS`: invalid transitions and reasons.
- `TRADE_EXECUTION_COSTS`: intended/actual prices, slippage, fees, total costs, basis points, fee status.
- `TRADE_R_MULTIPLES`: initial monetary risk, planned R, gross R, net R, fee impact, prediction error.
- `TRADE_EXCURSIONS`: MAE/MFE with granularity, gaps, and confidence.
- `BROKER_RECONCILIATION_RUNS`: broker reconciliation health.

## Reconciliation

Startup and broker-history writes reconcile Alpaca and Kraken rows into the canonical lifecycle. Duplicate polling does not create false lifecycle changes. If broker data lacks a symbol or lifecycle identity, reconciliation is marked for manual review.

## Founder Meaning

The Founder can now see whether the system is fully reconciled, waiting for broker data, incomplete, failed, or requiring review. Closed trades can later be tied to costs, R, MAE/MFE, and lessons.
