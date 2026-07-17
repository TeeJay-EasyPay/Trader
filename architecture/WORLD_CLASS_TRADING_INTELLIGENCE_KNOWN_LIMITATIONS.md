# World-Class Trading Intelligence Known Limitations

Date: 2026-07-17

## Current Limitations

### Probability Is Not Yet Fully Calibrated

The probability engine records an estimate and confidence interval, but most strategies will initially be marked `uncalibrated_small_sample`.

This is correct. The system does not yet have enough clean closed-trade outcomes to claim statistical confidence.

### Market Regime Is Basic

Crypto regime uses available crypto research scores.

Equity regime is currently conservative and often records unknown/insufficient data.

There is no full macro, breadth, rates, volatility-index, or sector-rotation feed yet.

### Strategy Registry Is Initial

Only strategies supported by current data are registered:

- conservative AI-assisted equity setup;
- crypto trend-following 2R;
- paper validation 2R.

No leverage, options, futures, automated short selling, or experimental strategy automation was added.

### Signal Evidence Is Limited By Current Data Sources

The signal engine uses available data only.

It does not yet include:

- order book depth;
- spread;
- ATR;
- full multi-timeframe indicators;
- on-chain analytics;
- real-time macro feeds.

### Lifecycle Is Not Fully Canonical Yet

The new lifecycle table records proposal and orchestrator stages.

Future work should normalize broker fills into full entry, partial fill, open, managing, partial exit, closed, cancelled, expired, fee, slippage, and P&L states.

### Strategy Laboratory Is Schema-Ready Only

`STRATEGY_LAB_RUNS` exists for future offline research.

Backtesting, walk-forward validation, parameter optimization, and Monte Carlo simulation are not yet implemented.

### Mobile Build Check

The Expo mobile project does not currently include TypeScript, so `npx tsc --noEmit` is not available as a validation step.

