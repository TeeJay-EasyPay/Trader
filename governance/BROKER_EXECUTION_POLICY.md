# Broker Execution Policy

Status: Founder-governed constitutional document
Applies to: Trader autonomous investment platform

## Broker Selection

The Investment Orchestrator selects the broker. AI recommendations may suggest a broker but cannot execute orders.

## Exchange Selection

The selected broker must support the exchange and asset type. Unsupported exchanges are rejected.

## Asset Availability

The broker adapter must confirm the asset is available and tradable before execution.

## Market Availability

Equities must pass market-open checks. Crypto may be 24/7 only when broker policy and crypto trading policy are explicitly enabled.

## Broker Health

Broker account, position, order, and balance retrieval must be healthy enough to validate the trade.

## Execution Validation

Every order must pass governance, policy, due diligence, risk, broker, exchange, market, and capital allocation checks.

## Order Routing

Orders route through the broker adapter layer only. Direct broker calls from AI components are prohibited.

## Broker Failover

Failover requires explicit broker policy support. If a preferred broker is unavailable and no approved failover exists, execution is rejected.

## Paper Trading

Paper trading is the default and required mode until the Founder explicitly approves live trading.

## Live Trading Approval

Live trading requires a Founder-approved governance change, broker policy update, risk review, and successful paper trading validation.

## Governance Rule

The AI may propose broker improvements but must never modify this policy autonomously.
