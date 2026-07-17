# Risk Engine

## Purpose

The risk engine prevents AI Trader from turning a recommendation into an order unless all founder-approved checks pass. It exists in multiple layers because a single check point is not sufficient for an autonomous trading system.

## Risk Layers

1. Proposal guardrails in `guardrails.py`.
2. Policy loading and scoring in `foundation.py`.
3. Orchestrator validation in `orchestrator.py`.
4. Broker-specific mechanical seatbelts in `broker_adapters.py` and `multi_broker.py`.
5. Runtime controls in `engine_control` and broker auto-trading settings.

## Base Guardrails

Base guardrails include:

- Paper trading account confirmed when required.
- Trade side is valid.
- Position size is positive.
- Entry price is positive.
- Stop loss is present.
- Take profit is present.
- Confidence meets minimum threshold.
- Account equity is positive.
- Trade risk is measurable.
- Trade risk stays within account risk limit.
- Declared risk percentage is within limit.
- Daily loss limit has not been breached.
- Open position limit has room.
- Duplicate long positions are blocked.
- Short selling is blocked unless explicitly enabled.
- Buy stop loss must be below entry.
- Buy take profit must be above entry.
- Sell stop loss must be above entry.
- Sell take profit must be below entry.
- Equity trades must be inside regular US market hours.

## Policy Guardrails

Policy values are seeded from `foundation.py` and represented in SQLite:

- Maximum capital allocation percentage.
- Maximum position size percentage.
- Maximum concurrent exposure percentage.
- Risk per trade percentage.
- Maximum daily loss percentage.
- Maximum weekly loss percentage.
- Maximum monthly loss percentage.
- Emergency shutdown balance.
- Default stop loss percentage.
- Maximum stop loss percentage.
- Trailing stop enabled/disabled.
- Trailing stop percentage.
- Take profit required.
- Maximum concurrent positions.
- Maximum drawdown percentage.
- Minimum investment policy score.
- Minimum overall confidence.
- Crypto enabled/disabled.
- Equities enabled/disabled.
- Broker enabled/disabled.

## Capital Allocation

`calculate_capital_allocation` compares:

- Requested notional.
- Maximum position notional.
- Risk-limited notional based on stop-loss distance.
- Account equity.

It writes `CAPITAL_ALLOCATION_HISTORY` and returns approved notional and quantity. If approved notional is zero, the trade is rejected.

## Broker-Specific Controls

### Alpaca

- Paper trading only in current implementation.
- Live trading not approved.
- Orders must pass orchestrator and guardrails.
- Auto trading is broker-specific.

### Kraken

Kraken has additional real-world mechanical seatbelts:

- `KRAKEN_AUTO_TRADING`
- `KRAKEN_TRADING_ENABLED`
- `KRAKEN_LIVE_TRADING_APPROVED`
- `KRAKEN_SUBMIT_REAL_ORDERS`
- `KRAKEN_TRADING_ALLOCATION_GBP`
- `KRAKEN_MAX_ORDER_GBP`
- `KRAKEN_MIN_ORDER_GBP`
- `KRAKEN_MAX_OPEN_TRADES`
- `KRAKEN_ALLOWED_PAIRS`

The system separates personal existing Kraken holdings from AI-managed open trades. AI-managed trade slots are based on managed exit records and system-created orders, not simply the total number of Kraken assets already held.

## Managed Exit Protection

When new auto trading is disabled:

- New entries stop.
- Existing AI-managed positions remain monitored.
- Stop loss and take profit exit logic remains active.

This prevents a disable action from removing protection on already-open positions.

## Drawdown And Loss Limits

Drawdown and loss checks use portfolio snapshots when available. If no prior snapshot exists, day/week P&L can be unavailable. This is a data availability limitation, not necessarily a risk failure.

The orchestrator avoids applying drawdown checks when the snapshot basis does not match current account equity closely enough. This prevents unrelated valuation differences from incorrectly blocking a trade.

## Trailing Stops

Trailing stop support exists in managed exit storage through:

- `trailing_stop_pct`
- `high_water_mark`
- `low_water_mark`

Trailing stops are disabled by default and require founder approval through policy/configuration. This is correct because a bad trailing-stop setting can prematurely close volatile crypto positions.

## Autonomous Trading

Auto trading is permission, not compulsion. Even when enabled:

1. A fresh recommendation must exist.
2. The recommendation must be for an allowed broker/pair.
3. Confidence and investment score thresholds must pass.
4. Due diligence must be complete.
5. Capital allocation must approve a size.
6. Broker-specific seatbelts must pass.
7. Order intent lock must be acquired.
8. Broker submission must succeed.

If any step fails, the system should reject and record the reason.
