# Risk Management Policy

Status: Founder-governed constitutional document
Applies to: Trader autonomous investment platform

## Maximum Capital Allocation %

Default total capital allocation limit is stored in SQLite `RISK_POLICIES.maximum_capital_allocation_pct`.

## Maximum Position Size %

Default single-position size limit is stored in `RISK_POLICIES.maximum_position_size_pct`.

## Maximum Exposure %

Default concurrent exposure limit is stored in `RISK_POLICIES.maximum_concurrent_exposure_pct`.

## Risk Per Trade %

Default maximum risk per trade is stored in `RISK_POLICIES.risk_per_trade_pct`.

## Maximum Daily Loss %

Default daily loss shutdown threshold is stored in `RISK_POLICIES.maximum_daily_loss_pct`.

## Maximum Weekly Loss %

Default weekly loss threshold is stored in `RISK_POLICIES.maximum_weekly_loss_pct`.

## Maximum Monthly Loss %

Default monthly loss threshold is stored in `RISK_POLICIES.maximum_monthly_loss_pct`.

## Emergency Shutdown Balance

If account equity falls at or below `RISK_POLICIES.emergency_shutdown_balance`, autonomous execution must stop.

## Default Stop Loss %

Default stop loss distance is stored in `RISK_POLICIES.default_stop_loss_pct`.

## Maximum Stop Loss %

Any trade exceeding `RISK_POLICIES.maximum_stop_loss_pct` must be rejected.

## Trailing Stop Policy

Trailing stops remain disabled unless enabled by Founder-approved policy.

## Take Profit Policy

Take profit is mandatory for autonomous execution unless Founder policy changes.

## Maximum Concurrent Positions

Maximum open positions are controlled by `RISK_POLICIES.maximum_concurrent_positions`.

## Maximum Drawdown

Maximum tolerated drawdown is stored in `RISK_POLICIES.maximum_drawdown_pct`.

## Volatility Controls

Trader should reduce or reject exposure when volatility makes stop loss, liquidity, or risk estimation unreliable.

## Broker Failure Handling

If broker health, balances, market status, or order confirmation cannot be verified, execution must be rejected.

## Market Failure Handling

If market data is unavailable, stale, inconsistent, or unsupported, due diligence is incomplete and execution must be rejected.

## Governance Rule

The AI may recommend risk policy changes but must never modify this policy autonomously.
