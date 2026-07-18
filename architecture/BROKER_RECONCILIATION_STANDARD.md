# Broker Reconciliation Standard

## Objective

Every broker event must reconcile into one logical trade without duplicate lifecycle corruption.

## Implemented Standard

Sprint 6 normalizes raw broker events into `BROKER_EVENT_MAPPINGS`.

Each mapping stores:

- broker
- logical trade ID
- raw event hash
- normalized lifecycle stage
- confidence
- source endpoint
- raw payload
- canonical payload

The raw event hash is unique per broker, so duplicate polling does not create duplicate mappings.

## Canonical Flow

```text
Raw broker payload
  -> stable hash
  -> canonical broker event
  -> BROKER_EVENT_MAPPINGS
  -> production_spine.reconcile_logical_trade
  -> CANONICAL_TRADE_LIFECYCLE
```

## Confidence

Events with broker order IDs or trade IDs are assigned higher confidence. Events without durable broker IDs remain usable but lower-confidence and may require manual review.

## Manual Review

Manual review is required when deterministic matching is impossible, the event lacks identity, or lifecycle transitions are illegal.

