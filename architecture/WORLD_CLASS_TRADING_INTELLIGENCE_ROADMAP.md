# World-Class Trading Intelligence Roadmap

Date: 2026-07-17

## Completed In This Sprint

- Trading Intelligence schema.
- Strategy registry.
- Market regime snapshot.
- Signal evidence engine.
- Trade setup evaluation.
- Portfolio fit evaluation.
- Trading committee review.
- Probability estimate.
- Bull/bear recommendation gate.
- Lifecycle stage recording.
- Recommendation API enrichment.
- Mobile recommendation card enrichment.
- Calibration snapshots.
- Regression tests.

## Next Sprint

### 1. Complete Canonical Trade Lifecycle

Normalize broker activity into:

- idea;
- research;
- candidate;
- approved;
- submitted;
- executed;
- managing;
- partial exit;
- closed;
- cancelled;
- rejected;
- expired.

### 2. Strategy Laboratory Version 1

Implement offline backtesting for one strategy and one asset class first.

Start with:

- crypto trend-following 2R;
- historical candles;
- fees;
- simple slippage;
- win rate;
- average R;
- drawdown;
- confidence bucket performance.

### 3. Regime Engine Version 2

Add richer regime inputs:

- equity market trend;
- volatility index or volatility proxy;
- market breadth;
- sector rotation;
- crypto dominance;
- stablecoin liquidity where available.

### 4. Probability Calibration

Connect closed lifecycle records to probability buckets:

- predicted probability;
- observed win rate;
- expected R;
- actual R;
- sample size;
- calibration drift.

### 5. Reporting

Update reports and Ask AI to explain:

- strategy performance;
- regime performance;
- signal performance;
- committee disagreement;
- probability calibration quality.

## Do Not Build Yet

- Reinforcement learning.
- Autonomous strategy creation.
- Automatic governance changes.
- Leverage.
- Derivatives.
- High-frequency trading.
- Multi-portfolio support.

