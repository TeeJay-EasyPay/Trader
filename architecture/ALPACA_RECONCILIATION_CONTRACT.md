# Alpaca Reconciliation Contract

## Scope

Alpaca remains the paper-trading broker for equities.

## Expected Inputs

The Alpaca adapter should provide:

- orders
- order status
- fills where available
- average fill price
- filled quantity
- cancellations
- rejected orders
- open positions
- closed positions where available

## Sprint 6 Handling

Broker polling now sends Alpaca order and trade history rows into Sprint 6 normalization. The normalized events are written to `BROKER_EVENT_MAPPINGS` before canonical reconciliation.

## Required Future Hardening

- Verify fill-level events from Alpaca paper trading.
- Map bracket order relationships.
- Preserve stop and target child orders.
- Reconstruct realized P&L when Alpaca does not provide it directly.
- Run hosted paper-trade reconciliation after Render deployment.

