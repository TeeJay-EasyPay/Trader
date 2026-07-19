# Portfolio Intelligence Production Flow

## Shared Founder snapshot

The worker periodically retrieves connected broker panels and persists `PRODUCTION_BROKER_SNAPSHOTS`. A snapshot stores broker, connection state, account mode, portfolio value, cash, buying power, open-position count, day/week/month P&L when supplied, capture time and the complete safe panel payload.

The Founder projection selects the latest snapshot per broker. The Portfolio and Dashboard screens therefore consume worker-captured evidence rather than requiring the phone to contact Alpaca or Kraken directly.

## Trade evidence

Broker polling projects observable order, fill and trade records into `PRODUCTION_TRADE_EVIDENCE` using an idempotent evidence key. It records broker IDs, symbol, side, state, quantity, entry/exit values, realized and unrealized P&L when available, timestamps, reason and source payload.

P&L rules:

- Closed realized P&L is shown only from broker or reconciled evidence.
- Open/unrealized P&L is labelled separately.
- Account value movement is not represented as a closed-trade result.
- Fees and slippage remain unavailable until supplied or reconciled.

## Authority boundary

This read model does not approve trades. Portfolio Manager remains a mandatory execution authority and may approve, approve smaller, wait, reject or require review. The projection only explains the resulting evidence.
