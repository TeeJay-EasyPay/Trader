# Recommended Next Architecture

This is not an implementation sprint. It defines the smallest coherent architectural additions needed to create a genuine Trading Intelligence layer without duplicating existing systems.

## A. Must Build First

### 1. Strategy Registry

New module:

- `src/ai_trader/strategies.py`

Purpose:

- Define strategy IDs, asset classes, timeframes, entry rules, exit rules, stop method, target method, allowed regimes, failure conditions, and evidence requirements.

Do not replace:

- Investment Orchestrator.
- Risk Engine.
- Broker adapters.

### 2. Signal Evidence Model

New table/module:

- `TRADE_SIGNALS`
- `src/ai_trader/signals.py`

Purpose:

- Store raw signal components separately from final recommendation.
- Example: trend, momentum, volatility, liquidity, spread, volume, catalyst, regime, score timestamp.

Why:

- Current recommendations mix evidence, reasoning, and execution readiness.

### 3. Canonical Trade Lifecycle

New table/module:

- `TRADE_LIFECYCLE`
- `src/ai_trader/trade_lifecycle.py`

Purpose:

- Normalize broker fills into entry, open, exit, realized P&L, unrealized P&L, fees, and holding period.

Why:

- Learning and reports cannot become world-class while raw broker rows remain the main source.

### 4. Strategy Attribution

Extend:

- `PERFORMANCE_ATTRIBUTION`
- recommendation payloads

Add:

- `strategy_id`
- `signal_id`
- `regime_id`
- `expected_r`
- `actual_r`
- `fees`
- `slippage_estimate`

## B. Must Improve Soon

### 1. Market Regime Engine

New module:

- `src/ai_trader/regime.py`

Outputs:

- Trending/ranging.
- High/low volatility.
- Risk-on/risk-off.
- Liquidity stress.
- Crypto rotation.

### 2. Confidence Calibration

New module:

- `src/ai_trader/calibration.py`

Purpose:

- Convert heuristic confidence into empirically tracked confidence buckets.
- Track win rate, average R, drawdown, and sample size per strategy/confidence bucket.

### 3. Backtest Harness

New module:

- `src/ai_trader/backtesting.py`

Start small:

- One strategy.
- One asset class.
- Historical candles.
- Fees/slippage assumptions.

## C. Valuable Later

- Order-book/liquidity microstructure.
- News/sentiment provider integration.
- Crypto on-chain provider.
- Portfolio optimizer.
- Strategy lab UI.
- Walk-forward optimization.
- Broker cost router.

## D. Should Not Build Yet

- Fully autonomous strategy mutation.
- Multi-user infrastructure.
- Complex derivatives trading.
- Leverage.
- Short selling automation.
- High-frequency execution.
- Reinforcement learning.

## Existing Modules To Extend

- `agent.py`: call strategy/signal layer before producing proposals.
- `api.py`: expose signal, strategy, and lifecycle views.
- `foundation.py`: consume strategy evidence but keep policy separate.
- `orchestrator.py`: validate strategy approval and regime eligibility.
- `multi_broker.py`: feed canonical lifecycle and attribution.
- `mobile/App.js`: display strategy and lifecycle data after backend support exists.

## Architectural Rule

The new Trading Intelligence layer should sit before the Investment Orchestrator:

```text
Research -> Signals -> Strategy Engine -> Recommendation -> Orchestrator -> Broker
```

It must not bypass the orchestrator.
