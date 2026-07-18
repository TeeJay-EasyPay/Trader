# Kraken Reconciliation Contract

## Scope

Kraken is the controlled micro-live crypto broker. Sprint 6 does not weaken existing Kraken safety controls.

## Expected Inputs

The Kraken adapter should provide:

- order submission result
- transaction ID
- order status
- partial fills
- completed fills
- average execution price
- volume
- exchange fees when returned
- cancellations
- rejected orders
- open holdings
- closed trades

## Sprint 6 Handling

Kraken broker rows are normalized into `BROKER_EVENT_MAPPINGS`, deduplicated by hash, and reconciled into canonical lifecycle records.

Terminal rows enqueue closed-loop learning workflows but do not automatically alter strategy, guardrail or capital settings.

## Safety Position

Default Sprint 6 strategy entitlement does not permit micro-live execution unless a strategy is promoted beyond `Paper`.

