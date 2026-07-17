# World-Class Trading Intelligence Architecture

Date: 2026-07-17

## Purpose

This sprint introduces a Trading Intelligence Platform layer ahead of the existing Investment Orchestrator.

The purpose is not to increase trade frequency. The purpose is to improve evidence quality, explainability, probability estimation, strategy attribution, and disciplined decision making.

The existing mature systems remain protected:

- Investment Orchestrator
- Risk Engine
- Broker Adapters
- Governance Framework
- Recommendation Persistence
- Portfolio Controls
- Execution Pipeline
- Audit History
- Scheduling
- Capital Allocation
- Kraken live-order safety limits
- Alpaca paper trading support

## New Reasoning Pipeline

```text
Market Data
  -> Data Quality
  -> Market Intelligence
  -> Market Regime
  -> Opportunity Discovery
  -> Signal Evidence
  -> Strategy Registry
  -> Strategy Selection
  -> Trade Setup Evaluation
  -> Portfolio Intelligence
  -> Trading Committee
  -> Probability Estimate
  -> Recommendation
  -> Investment Orchestrator
  -> Risk Engine
  -> Broker Adapter
  -> Canonical Trade Lifecycle
  -> Performance Attribution
  -> Governed Learning
  -> Founder Review
```

## New Module

`src/ai_trader/trading_intelligence.py`

This module owns:

- `STRATEGY_REGISTRY`
- `MARKET_REGIME_SNAPSHOTS`
- `TRADE_SIGNALS`
- `TRADING_COMMITTEE_REVIEWS`
- `PROBABILITY_ESTIMATES`
- `TRADE_LIFECYCLE`
- `CONFIDENCE_CALIBRATION`
- `STRATEGY_LAB_RUNS`

## Recommendation Gate

No recommendation may be persisted unless `evaluate_trade_intelligence` produces:

- a strategy reference;
- a market regime snapshot;
- signal evidence;
- trade setup evaluation;
- portfolio fit review;
- trading committee review;
- probability estimate;
- strongest argument for the trade;
- strongest argument against the trade.

If the strongest argument for or against is missing, the proposal is rejected before becoming a recommendation.

## Execution Authority

Trading Intelligence never executes.

Execution remains:

```text
Recommendation -> InvestmentOrchestrator.evaluate_recommendation -> BrokerAdapter
```

The intelligence layer informs recommendations. It does not bypass guardrails, broker adapters, or governance.

## Deterministic Strategy Registry

The initial registry contains only strategies supported by current data:

- `equity_conservative_ai_assisted`
- `crypto_trend_following_2r`
- `paper_validation_2r`

Each strategy defines:

- purpose;
- supported assets;
- supported regimes;
- expected holding period;
- historical edge statement;
- minimum evidence;
- maximum risk;
- exit methodology;
- invalid conditions;
- production status.

## Market Regime Engine

The first regime engine is intentionally conservative.

For crypto, it uses available crypto research scores:

- technical trend;
- volatility;
- liquidity;
- risk score.

For equities, the system records insufficient/unknown regime data unless richer market data is available.

The engine does not invent macro or order-book intelligence where no data source exists.

## Signal Evidence Engine

For crypto, signals include:

- trend;
- momentum;
- liquidity;
- risk;
- sentiment where available.

For equities, signals include:

- technical setup;
- market sentiment;
- catalyst/news;
- reward/risk;
- data quality.

Each signal stores:

- score;
- confidence;
- weight;
- evidence;
- strategy ID;
- regime ID.

## Trading Committee

The committee records structured votes from:

- Market Intelligence;
- Technical;
- Quantitative;
- Portfolio;
- Risk;
- Execution.

The committee records:

- member vote;
- member score;
- rationale;
- supporting evidence;
- opposing evidence;
- strongest argument for;
- strongest argument against;
- disagreements.

## Probability Engine

The probability engine creates an estimate containing:

- probability of success;
- expected return in R;
- expected drawdown in R;
- historical sample size;
- confidence interval;
- expected holding time;
- expected volatility;
- calibration status.

The probability estimate is explicitly not a guarantee.

When there is not enough historical data, calibration status is `uncalibrated_small_sample`.

## Canonical Trade Lifecycle

Lifecycle stages are now recorded into `TRADE_LIFECYCLE`.

Initial stages implemented:

- `candidate` when a proposal passes Trading Intelligence;
- `approved` when the orchestrator accepts the recommendation but manual approval is required;
- `submitted` when the orchestrator submits an order;
- `rejected` when intelligence or orchestrator validation rejects it.

The schema supports future stages:

- idea;
- research;
- executed;
- managing;
- partial_exit;
- closed;
- cancelled;
- expired.

## UI Exposure

The Recommendations screen now shows:

- strategy;
- market regime;
- probability of success;
- expected return;
- calibration status;
- committee view;
- strongest argument for;
- strongest argument against;
- signal evidence;
- lifecycle.

The UI remains read-only for intelligence. Execution still uses the existing approval and auto-execute paths.

