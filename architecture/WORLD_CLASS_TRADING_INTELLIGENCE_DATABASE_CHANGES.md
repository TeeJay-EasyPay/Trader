# World-Class Trading Intelligence Database Changes

Date: 2026-07-17

## New Tables

### `STRATEGY_REGISTRY`

Purpose:

Stores formal strategy definitions.

Producer:

`initialize_trading_intelligence_schema`

Consumer:

Trading Intelligence, Recommendations API, UI, future backtesting.

Retention:

Permanent. Strategy definitions are part of historical attribution.

### `MARKET_REGIME_SNAPSHOTS`

Purpose:

Stores the interpreted market regime at recommendation time.

Producer:

`infer_market_regime`

Consumer:

Trading Committee, Probability Engine, Recommendations UI, future regime attribution.

Retention:

Permanent.

### `TRADE_SIGNALS`

Purpose:

Stores structured signal evidence per proposal.

Producer:

`build_signal_evidence`

Consumer:

Trading Committee, Probability Engine, Recommendations UI, future signal attribution.

Retention:

Permanent.

### `TRADING_COMMITTEE_REVIEWS`

Purpose:

Stores committee votes, supporting evidence, opposing evidence, and the strongest argument for and against the trade.

Producer:

`run_trading_committee`

Consumer:

Recommendations UI, reports, Ask AI, audit review.

Retention:

Permanent.

### `PROBABILITY_ESTIMATES`

Purpose:

Stores probability estimates and uncertainty at recommendation time.

Producer:

`estimate_probability`

Consumer:

Recommendations UI, calibration, reporting, future performance analysis.

Retention:

Permanent.

### `TRADE_LIFECYCLE`

Purpose:

Records measurable lifecycle stages for each recommendation.

Producer:

Trading Intelligence and Investment Orchestrator.

Consumer:

Recommendations UI, reports, future lifecycle reconstruction.

Retention:

Permanent append-only lifecycle history.

### `CONFIDENCE_CALIBRATION`

Purpose:

Stores calibration snapshots comparing estimated probability with available observed outcomes.

Producer:

`estimate_probability` and `update_calibration_from_attribution`.

Consumer:

Learning reports and future calibration engine.

Retention:

Permanent.

### `STRATEGY_LAB_RUNS`

Purpose:

Reserved for offline research, backtests, walk-forward validation, parameter studies, and simulation summaries.

Producer:

Future Strategy Laboratory.

Consumer:

Founder review and future strategy promotion workflow.

Retention:

Permanent research record.

### `HISTORICAL_CANDLES`

Purpose:

Stores historical OHLCV candles used by the Strategy Lab and market-intelligence calculations.

Producer:

`record_historical_candle`, future broker/data ingestion jobs.

Consumer:

`run_strategy_backtest`, future walk-forward validation, future technical evidence enrichment.

Retention:

Permanent append/update-by-unique-key market history. Unique key is symbol, asset type, timeframe, and observed timestamp.

### `STRATEGY_BACKTEST_RESULTS`

Purpose:

Stores deterministic Strategy Lab results including trade count, win rate, average R, expectancy R, profit factor, max drawdown R, Sharpe proxy, Sortino proxy, and raw result payload.

Producer:

`run_strategy_backtest`.

Consumer:

Founder review, future strategy-promotion workflow, strategy registry calibration, future reporting.

Retention:

Permanent research record.

### `PERFORMANCE_INTELLIGENCE`

Purpose:

Stores strategy-level performance summaries calculated from closed trade attribution and probability calibration.

Producer:

`update_calibration_from_attribution`, `calculate_performance_metrics`.

Consumer:

Daily learning update, Ask AI, future strategy improvement reports.

Retention:

Permanent append-only performance snapshots.

## Phase 2 Column Additions

### `TRADE_LIFECYCLE`

Phase 2 adds:

- `fees`
- `slippage`
- `r_multiple`
- `mae`
- `mfe`
- `holding_time_seconds`

Existing databases are migrated additively with `ALTER TABLE` during Trading Intelligence initialization. Historical rows keep null values where these measurements were unavailable.

## Existing Tables Extended Indirectly

### `trade_audit`

`payload_json` now may include an `intelligence` object containing:

- strategy;
- regime;
- signals;
- trade setup;
- portfolio;
- committee;
- probability;
- explainability.

No existing columns were removed.
