# Architecture Assessment - Autonomous Trading Readiness Sprint

Date: 2026-07-07

## Assessment

The target architecture is now materially in place:

Research Engine -> Due Diligence Engine -> Risk Engine -> Investment Policy Statement -> Investment Orchestrator -> Broker Adapter -> Broker Execution -> Trade Monitoring -> Trade Exit -> Performance Learning.

## Strengths

- The Investment Orchestrator is the central execution authority for autonomous execution and manual approval.
- Broker auto-trading settings are broker-specific and persisted in SQLite.
- Kraken and Alpaca account contexts are no longer mixed for sizing and risk decisions.
- Broker panels are generated from backend broker state, so future brokers can reuse the same mobile layout.
- Recommendation history is persisted in SQLite and also cached on-device as a fallback.
- Background monitoring is separated from manual API calls.

## Architecture Risks

- `src/ai_trader/api.py` remains too large and owns API routing, orchestration glue, monitoring loops, push dispatch, and broker polling. This is acceptable for this sprint but should be split before more brokers are added.
- Broker adapters still differ in depth. Alpaca is mature, Kraken is active for controlled crypto trading, and Coinbase/Binance/IBKR remain future placeholders.
- Push delivery is backend-ready but the mobile client does not yet register native Expo push tokens.
- The crypto knowledge engine currently uses public CoinGecko market data. On-chain, news, and sentiment are intentionally marked as insufficient data until a real provider is connected.

## Recommendation

Proceed with controlled Kraken micro-live validation, then refactor `api.py` into smaller services before adding Coinbase/Binance/IBKR execution.

