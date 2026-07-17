# World-Class Trading Intelligence Phase 2

Date: 2026-07-17

## Purpose

Phase 2 completes the first practical version of the Trading Intelligence implementation. The prior layer recorded evidence around recommendations. Phase 2 turns that layer into an evidence-discovery and reasoning engine that calculates market evidence, infers market regime, produces independent signals, reviews strategy fit, estimates probability with uncertainty, records lifecycle measurements, and supports early strategy-lab backtesting.

This sprint does not give AI Trader permission to trade. It improves the quality of the evidence a recommendation must carry before the existing Investment Orchestrator, Risk Engine, and broker adapters are allowed to consider it.

## Non-Negotiable Recommendation Rule

No recommendation may be produced unless AI Trader can articulate both:

- the strongest argument for the trade;
- the strongest argument against the trade.

This remains enforced in `evaluate_trade_intelligence`. If either side is missing, the proposal is rejected before recommendation persistence.

## Implemented Capabilities

### Market Intelligence

`build_market_intelligence` and `analyze_price_series` calculate deterministic market evidence from available candles or market payloads:

- trend score;
- momentum score;
- moving-average position;
- volatility;
- ATR percentage;
- relative strength proxy;
- volume trend;
- price structure;
- breakout or breakdown state;
- mean-reversion state;
- gap percentage;
- support;
- resistance;
- data-quality metadata;
- supporting evidence;
- contradictory evidence.

When a data source is missing, fields remain `None` or `unknown`; the platform does not fabricate technical evidence.

### Regime Engine

`infer_market_regime` now consumes the market-intelligence metrics as well as crypto score data. It records:

- primary regime;
- volatility regime;
- trend regime;
- liquidity regime;
- risk regime;
- confidence;
- evidence;
- contradictory evidence.

Supported regime outputs include bull, bear, range, transition, crisis, recovery, contraction, trending, mean-reverting, high volatility, low volatility, risk-on, risk-off, liquid, thin liquidity, and unknown.

### Independent Signal Engine

`build_signal_evidence` now produces scores from market evidence and context rather than mirroring the AI proposal confidence score. Signal records include supporting evidence and opposing evidence. Signals currently cover:

- trend;
- momentum;
- breakout;
- volume;
- ATR/volatility;
- support/resistance;
- sentiment or catalyst context;
- reward/risk;
- data quality;
- crypto liquidity and risk when crypto data exists.

### Strategy Registry

The seeded strategy registry now includes a richer Phase 2 family:

- Conservative AI-Assisted Equity Setup;
- Crypto Trend Following 2R;
- Paper Validation 2R;
- Trend Following;
- Momentum;
- Pullback;
- Breakout;
- Mean Reversion;
- Range Trading;
- Volatility Expansion;
- Swing Continuation;
- Crypto Infrastructure Trend;
- Institutional Accumulation;
- Quality Growth;
- Value Pullback.

Every strategy object carries supported assets, supported regimes, holding period, historical-edge statement, minimum evidence, maximum risk, exit methodology, invalid conditions, production status, entry conditions, exit conditions, sizing assumptions, ideal/poor regimes, historical statistics placeholder, required evidence, invalidating evidence, minimum reward/risk, maximum acceptable volatility, and minimum sample-size expectations.

### Trading Committee

The committee is now made of independent deterministic reviewers:

- Macro Analyst;
- Technical Analyst;
- Quantitative Analyst;
- Portfolio Manager;
- Risk Officer;
- Execution Specialist;
- Crypto Specialist or Fundamental Analyst.

Each member records an opinion, score, recommendation, supporting evidence, opposing evidence, and open questions. Committee outcomes can be:

- Approve;
- Approve with caution;
- Reject;
- Wait;
- Insufficient evidence.

Disagreements are stored explicitly so the Founder can see where the system is uncertain rather than being shown one flattened confidence number.

### Probability And Calibration

`estimate_probability` now blends:

- independent signal score;
- trade setup quality;
- regime confidence;
- strategy historical statistics where available;
- signal history where available;
- regime history where available;
- volatility penalty;
- small-sample penalty;
- calibration evidence.

The result includes probability of success, expected R, expected drawdown R, historical sample size, confidence interval, expected holding time, expected volatility, calibration status, and evidence. Small samples widen the confidence interval and mark the estimate as `uncalibrated_small_sample`.

`calculate_calibration_metrics` computes Brier score, calibration error, observed win rate, mean predicted probability, sample size, and probability buckets where closed attribution exists.

### Strategy Lab

`record_historical_candle` and `run_strategy_backtest` introduce the first Strategy Lab primitives. Backtests are intentionally simple and deterministic. They provide early trade count, win rate, average R, expectancy R, profit factor, max drawdown R, Sharpe proxy, Sortino proxy, and raw R-values.

The Strategy Lab is a research aid. It does not approve strategies, change guardrails, or update broker execution logic automatically.

### Performance Intelligence

`calculate_performance_metrics` and `PERFORMANCE_INTELLIGENCE` store strategy-level performance summaries from available closed trade attribution:

- sample size;
- win rate;
- average R;
- expectancy R;
- profit factor;
- max drawdown R;
- average holding time;
- Brier score;
- calibration error.

### Lifecycle Measurement

`TRADE_LIFECYCLE` now supports additional measurable fields:

- fees;
- slippage;
- R-multiple;
- MAE;
- MFE;
- holding time in seconds.

The code performs additive SQLite migration with `ALTER TABLE` where an existing database does not yet have these columns.

### Recommendation API Merge

`/recommendations` now merges the rich intelligence payload stored in `trade_audit` with the normalized intelligence tables. This prevents the UI from losing strategy, regime, or market-intelligence fields when normalized committee/probability records exist.

## Database Additions

Phase 2 adds:

- `HISTORICAL_CANDLES`;
- `STRATEGY_BACKTEST_RESULTS`;
- `PERFORMANCE_INTELLIGENCE`.

Phase 2 extends:

- `TRADE_LIFECYCLE` with measurable cost and outcome fields.

## Verification

Automated verification completed:

```powershell
.\.venv\Scripts\python.exe -m py_compile src\ai_trader\trading_intelligence.py src\ai_trader\api.py
.\.venv\Scripts\python.exe -m unittest tests.test_trading_intelligence -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Result:

```text
Ran 96 tests
OK
```

## What This Does Not Do

Phase 2 does not:

- execute trades directly;
- weaken guardrails;
- enable broker trading;
- alter Kraken or Alpaca permissions;
- change governance automatically;
- claim a proven live trading edge;
- fabricate unavailable data;
- copy successful traders' live trades.

All execution remains behind the Investment Orchestrator, Risk Engine, broker adapters, and Founder-approved trading switches.
