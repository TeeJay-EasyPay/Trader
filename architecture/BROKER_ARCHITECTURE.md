# Broker Architecture

## Purpose

The broker architecture lets AI Trader route approved trades to different brokers while keeping each broker independently governed. A broker is not just a connection; it has its own permission state, account data, position history, trade history, and safety rules.

## Execution Authority

The Investment Orchestrator is the only execution authority. It receives proposals and decides whether the trade can be submitted.

The AI Trading Agent does not communicate with brokers. The mobile app does not communicate with brokers. Ask AI does not communicate with brokers.

## Broker Adapter Interface

`broker_adapters.py` defines the broker adapter boundary. Adapters expose capabilities such as:

- Broker name.
- Supported asset types.
- Market-open check.
- Asset-availability check.
- Account retrieval.
- Position retrieval.
- Order placement.
- Order/fill history polling.

The orchestrator sees all brokers through this adapter interface.

## Current Brokers

### Alpaca

Status: implemented for paper trading.

Use:

- Equity paper trading.
- Account retrieval.
- Position retrieval.
- Paper order placement.
- Order/fill history sync.

Safety:

- Alpaca live trading is not approved in Version 1.
- `PAPER_TRADING_ONLY=true` is expected.
- App displays Alpaca as paper trading.
- Auto-trading can be enabled per broker, but orders remain paper.

### Kraken

Status: implemented for live micro-trading with mechanical seatbelts.

Use:

- GBP crypto balances.
- Holdings.
- Open orders.
- Closed orders.
- Trade history.
- Current prices.
- Real micro-orders when all explicit switches are enabled.
- Managed exits for stop loss and take profit.

Key Kraken environment variables:

- `KRAKEN_API_KEY`
- `KRAKEN_PRIVATE_KEY` or adapter-compatible Kraken secret
- `KRAKEN_API_SECRET`
- `KRAKEN_AUTO_TRADING`
- `KRAKEN_TRADING_ENABLED`
- `KRAKEN_LIVE_TRADING_APPROVED`
- `KRAKEN_SUBMIT_REAL_ORDERS`
- `KRAKEN_TRADING_ALLOCATION_GBP`
- `KRAKEN_MAX_ORDER_GBP`
- `KRAKEN_MIN_ORDER_GBP`
- `KRAKEN_MAX_OPEN_TRADES`
- `KRAKEN_ALLOWED_PAIRS`

Kraken real orders require:

1. Broker auto trading enabled.
2. Broker trading enabled.
3. Live trading approved.
4. Submit real orders enabled.
5. Pair in allowed list.
6. Order amount within min/max.
7. Trading allocation not exceeded.
8. AI-managed open trade slots available.
9. Recommendation fresh and valid.
10. Orchestrator validation passed.

Existing Kraken holdings do not automatically count as AI-managed trades unless recorded as AI-managed managed exits. This prevents pre-existing personal holdings from blocking the AI’s separately allocated micro-trading budget.

### Coinbase

Status: placeholder.

The UI and adapter scaffold are present. Real trading is not configured. It should follow the same broker adapter and policy model when implemented.

### Binance

Status: future broker.

The UI includes broker placeholders. No implemented Binance adapter is currently active.

### Interactive Brokers

Status: placeholder.

Adapter placeholder exists. Real API integration is not implemented.

### Saxo

Status: placeholder adapter.

Not currently exposed as a primary mobile broker panel in the same way as Alpaca/Kraken/Coinbase/Binance/Interactive Brokers.

## Routing Logic

The orchestrator selects the first adapter that supports the proposal asset type. Current practical behavior:

- Stock/equity proposals route to Alpaca.
- Crypto proposals route to Kraken when Kraken supports the pair and is configured.

Future routing should become more explicit. A broker-selection policy should consider:

- Broker capability.
- Asset availability.
- Cost/fees.
- Currency.
- Liquidity.
- Current exposure.
- Founder broker preference.

## Broker Auto-Trading State

Each broker has independent auto-trading state stored in:

- Environment defaults.
- `BROKER_AUTO_TRADING_SETTINGS`.
- Optional Render config sync when Render API credentials are configured.

Enabling Kraken auto trading does not enable Alpaca. Enabling Alpaca does not enable Kraken.

## Broker History

Broker history is persisted in `BROKER_TRADE_HISTORY`. Current records are close to raw broker rows. This is useful for audit but not ideal for UX. A future canonical trade lifecycle layer should normalize:

- Entry order.
- Entry fill(s).
- Position status.
- Current live price.
- Target price.
- Stop loss.
- Exit order.
- Exit fill(s).
- Realized P&L.
- Fees.
- Holding period.
- Entry and exit reasons.

## Execution Idempotency

Before a broker submission, the orchestrator writes an `ORDER_INTENT_LOCKS` row using the proposal ID as the client order ID. This prevents duplicate order submission from retries or repeated button presses.

## Managed Exits

Kraken entries create `MANAGED_TRADE_EXITS` rows. The managed exit worker is responsible for closing those positions when stop loss, take profit, or trailing stop conditions apply.

Disabling auto trading stops new entries. It does not stop managed exits for positions already opened.
