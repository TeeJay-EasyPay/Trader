# Canonical Reconciliation Design

## Goal

Every broker event must reconcile into one logical trade without duplicate lifecycle corruption.

## Current Components

- `operational_truth.py` remains the canonical lifecycle event store.
- `production_spine.py` adds `reconcile_logical_trade`.
- `CANONICAL_RECONCILIATION_CASES` records reconciliation confidence and manual-review need.

## Event Grouping

Broker events are grouped by:

- `logical_trade_id`;
- `order_id`;
- `ordertxid`;
- `trade_id`;
- broker/symbol/side fallback when no broker ID exists.

## Lifecycle Mapping

The reconciliation engine maps broker states into canonical lifecycle stages:

- submitted;
- broker_acknowledged;
- partially_filled;
- fully_filled;
- cancelled;
- exit states where supplied.

Each lifecycle write uses an idempotency key.

## Confidence Scoring

Confidence decreases when:

- events require manual review;
- broker identifiers are missing;
- symbols are missing;
- event evidence is incomplete.

Manual review is required only when deterministic reconciliation is incomplete.

## Limits

This phase provides the reconciliation spine. It does not yet fully model complex broker corrections, order replacement trees, or all late/out-of-order combinations from live broker APIs.

