# Consolidated Trading Brain Forensic Audit

Date: 2026-07-17

Scope: analysis only. No production behaviour was changed.

## 1. Purpose

This consolidated audit answers one central question:

> How does AI Trader currently decide that something is a good trade, and what is missing before it can be considered a mature trading intelligence platform?

The audit reviewed the recommendation, research, guardrail, orchestrator, broker, scheduler, OpenAI, and learning paths in the current implementation.

## 2. Primary Conclusion

AI Trader currently has a strong governance and execution shell around a still-early trading brain.

The platform has:

- broker-specific controls;
- deterministic guardrails;
- an Investment Orchestrator;
- broker adapters;
- audit storage;
- recommendation history;
- background workers;
- founder reports;
- read-only Ask AI explanations.

The platform does not yet have:

- formal strategy definitions;
- a market regime engine;
- calibrated confidence;
- backtested edge;
- strategy-level performance attribution;
- canonical trade lifecycle normalization;
- outcome-driven strategy improvement.

The system is therefore operationally governed but not yet quantitatively proven.

## 3. Current Recommendation Flow

### 3.1 Equity Flow

The equity flow starts in `LocalApiService.run_analysis` in `src/ai_trader/api.py`.

It gathers symbols, market/news context, account information, positions, and guardrail settings. It then calls `AITradingAgent.propose_trades` in `src/ai_trader/agent.py`.

If an OpenAI analyzer is configured, the agent delegates to `OpenAIProposalAnalyzer.propose` in `src/ai_trader/ai.py`. The OpenAI prompt asks for a structured JSON proposal or `null`.

If OpenAI is not available and the system is not in demo mode, the production equity path can return no proposal through `_no_trade_probe`.

If a proposal is created, it is validated by `validate_trade_proposal` in `src/ai_trader/guardrails.py` and stored as an `agent_proposal` event in the audit database.

### 3.2 Kraken Crypto Flow

The Kraken crypto flow starts in `LocalApiService.run_crypto_analysis` in `src/ai_trader/api.py`.

It loads or bootstraps crypto assets, refreshes crypto scores, then calls `propose_crypto_trades` in `src/ai_trader/agent.py`.

The crypto proposal logic:

- reads `CRYPTO_RESEARCH_SCORES`;
- requires confidence above the configured minimum;
- requires positive technical trend above 0.5;
- gets a current Kraken price;
- creates a buy proposal;
- applies a fixed stop loss percentage;
- applies a fixed 2R take profit;
- calculates position size from notional and price;
- validates the proposal.

This is a useful early crypto trade generator, but it is not a full strategy engine.

### 3.3 Recommendation Display And Freshness

`LocalApiService.recommendations` reads stored `agent_proposal` events and enriches them with:

- freshness;
- expiry;
- scores;
- guardrail status;
- broker and exchange metadata;
- auto-trade eligibility.

Freshness is currently based on confidence:

- high confidence recommendations live for a shorter, fresher window;
- stale and expired recommendations remain visible for audit;
- expired recommendations are blocked from execution.

### 3.4 Execution Flow

Manual execution starts in `LocalApiService.approve_and_execute`.

Automatic execution starts in `LocalApiService.auto_execute_recommendations`.

Both paths route through `InvestmentOrchestrator.evaluate_recommendation` in `src/ai_trader/orchestrator.py`.

The orchestrator independently checks policy, due diligence, score thresholds, capital allocation, broker availability, portfolio limits, and base guardrails before broker execution.

Broker-specific controls are then enforced in adapter code, especially `KrakenAdapter._validate_live_order` for live Kraken orders.

## 4. Deterministic Logic Versus OpenAI Logic

### Deterministic

Deterministic logic includes:

- base guardrails in `src/ai_trader/guardrails.py`;
- orchestrator validation in `src/ai_trader/orchestrator.py`;
- policy and capital allocation in `src/ai_trader/foundation.py`;
- Kraken live-order validation in `src/ai_trader/broker_adapters.py`;
- crypto proposal construction in `propose_crypto_trades`;
- recommendation freshness and expiry logic in `src/ai_trader/api.py`;
- background scheduler and worker logic in `src/ai_trader/scheduler.py` and `LocalApiService.start_background_workers`.

### OpenAI

OpenAI is used for:

- equity trade proposal reasoning through `OpenAIProposalAnalyzer`;
- read-only founder conversation through `OpenAIReadOnlyExplainer`;
- plain-English explanation where configured and available.

OpenAI does not directly place trades.

OpenAI does not bypass the orchestrator.

OpenAI does not change guardrails.

OpenAI does not currently perform formal backtesting, calibrated probability estimation, or autonomous strategy improvement.

## 5. Trading Intelligence Inventory

The codebase contains several trading concepts, but most are partial.

Implemented or partially implemented:

- trend;
- momentum;
- volatility;
- liquidity;
- risk score;
- confidence threshold;
- position sizing;
- stop loss;
- take profit;
- duplicate prevention;
- recommendation freshness;
- broker availability;
- account risk limits;
- open position limits;
- managed exits.

Stored but not materially used:

- RSI;
- MACD;
- moving average position;
- market structure;
- on-chain fields;
- some sentiment/news fields.

Not meaningfully implemented:

- support/resistance;
- breakouts;
- mean reversion;
- ATR;
- spread checks;
- order book;
- multi-timeframe confluence;
- formal market regime;
- expected value;
- calibrated probability;
- strategy-specific edge.

## 6. Strategy Audit

No formal strategy registry was found.

The system has strategy-like behaviours:

1. OpenAI conservative equity proposal.
2. Kraken crypto positive trend heuristic.
3. Demo 1R/2R validation proposal.

These are not yet complete strategies because they lack:

- strategy IDs;
- approved asset universe per strategy;
- explicit entry rules;
- invalidation logic;
- timeframe;
- allowed regimes;
- backtest evidence;
- expected R;
- performance history;
- retirement criteria.

## 7. Market Regime Audit

No market regime engine was found.

Crypto research stores trend, momentum, volatility, liquidity, and risk, but the app does not convert those into an explicit regime such as:

- trending;
- ranging;
- high volatility;
- low volatility;
- risk-on;
- risk-off;
- liquidity-stressed.

As a result, the app does not yet choose or block strategies based on regime.

## 8. Investment Versus Trade Audit

The system currently blends investment quality and trade setup quality.

`calculate_investment_score` in `src/ai_trader/foundation.py` combines:

- fundamental score;
- technical score;
- market score;
- macro score;
- behavioural score;
- policy score;
- risk score.

This creates a useful composite, but it does not clearly separate:

- long-term asset quality;
- short-term entry setup;
- execution feasibility;
- risk/reward;
- catalyst timing;
- regime fit.

The next architecture should separate these so the app can explain whether an asset is good, the setup is good, or both.

## 9. Confidence Score Audit

Current confidence is heuristic.

For crypto, confidence is generally based on `overall_due_diligence_score`.

For equities, confidence can come from OpenAI or demo logic.

The confidence score is used as a threshold and display value. It is not yet calibrated to observed outcomes.

Therefore:

- 85% does not mean 85% probability of profit;
- scores across brokers are not guaranteed to be comparable;
- scores across strategies are not yet meaningful because strategies are not formalized;
- high confidence does not yet have a tracked historical win rate or expectancy.

## 10. Learning Engine Audit

The app stores useful evidence:

- trade audit records;
- broker trade history;
- orchestrator decisions;
- performance attribution;
- auto-trade events;
- research runs;
- benchmark daily research;
- trading reports.

The app can generate learning notes and founder reports.

However, learning is currently mostly reflective. It does not yet automatically adjust:

- strategy choice;
- entry timing;
- confidence calibration;
- position sizing;
- stop distance;
- take-profit distance;
- holding period;
- asset ranking.

This is good from a governance perspective because strategy changes should require founder approval. But the system still needs structured learning evidence so it can propose improvements more intelligently.

## 11. Data Source Audit

Current data sources:

- Alpaca for paper account, positions, orders, fills, bars, news, and asset checks.
- Kraken for balances, orders, trade history, and current prices.
- CoinGecko for crypto market-cap, volume, and percentage-change data.
- OpenAI for proposal reasoning and read-only explanation.
- Local SQLite for research, recommendations, audit events, broker history, reports, and learning notes.
- Static benchmark learning records.

Key data limitations:

- no deep historical candle store across all assets;
- no order-book or spread model;
- no robust crypto news/sentiment provider;
- no on-chain provider;
- no formal data quality scoring;
- broker rows are not always normalized into complete trade lifecycles.

## 12. Scheduler Audit

The current scheduler and workers are operational, not adaptive.

Important workers:

- `ai-trader-exit-monitor`;
- `ai-trader-order-monitor`;
- `ai-trader-auto-executor`;
- `ai-trader-crypto-refresh`;
- `ai-trader-push-dispatch`.

The scheduler can repeatedly research, refresh crypto, execute eligible recommendations, poll brokers, and monitor exits.

It does not currently change research priorities, strategy weights, confidence calibration, or trade selection based on performance.

## 13. Quantitative Validation Audit

The unit test suite passed:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

Result:

```text
Ran 86 tests
OK
```

This proves many software behaviours are protected by tests.

It does not prove trading edge.

Missing quantitative validation:

- backtesting;
- out-of-sample testing;
- walk-forward testing;
- fee and slippage modelling;
- expected value;
- strategy performance distribution;
- confidence calibration;
- drawdown simulation;
- benchmark comparison.

## 14. Dead, Duplicate, Or Compatibility Pathways

The audit found pathways that should be treated carefully:

- `ExecutionEngine` in `src/ai_trader/execution.py` appears to be a legacy or compatibility execution path. Current API approval and auto-execution paths route through the Investment Orchestrator.
- Demo proposal logic exists and should not be confused with production strategy intelligence.
- Some schema fields exist for advanced crypto indicators but are not currently computed or used by production decisions.
- UI/report fields can display "not available" where raw broker data exists but no normalized lifecycle record exists.

These are not necessarily bugs, but they are architectural ambiguity points.

## 15. What Must Be Preserved

Do not weaken these:

- AI cannot talk directly to brokers.
- Investment Orchestrator remains the execution authority.
- Guardrails must run independently of AI reasoning.
- Broker-specific live-order seatbelts must remain mechanical.
- Kraken live order controls must require explicit environment-level approval.
- Ask AI Trader must stay read-only.
- Audit records must remain append-only.
- Recommendation expiry must continue blocking stale trades.
- Existing tests must remain green.

## 16. Recommended Next Architecture

Add a Trading Intelligence layer before the Investment Orchestrator:

```text
Research
  -> Signal Evidence
  -> Strategy Engine
  -> Recommendation
  -> Investment Orchestrator
  -> Broker Adapter
  -> Broker Execution
  -> Trade Lifecycle
  -> Performance Attribution
  -> Learning Recommendation
```

First modules to add:

- `src/ai_trader/strategies.py`;
- `src/ai_trader/signals.py`;
- `src/ai_trader/trade_lifecycle.py`;
- `src/ai_trader/regime.py`;
- `src/ai_trader/calibration.py`;
- `src/ai_trader/backtesting.py`.

First tables to add:

- `TRADE_SIGNALS`;
- `STRATEGY_REGISTRY`;
- `MARKET_REGIMES`;
- `TRADE_LIFECYCLE`;
- `CONFIDENCE_CALIBRATION`;
- strategy fields on recommendations and attribution.

## 17. Founder-Level Answer

AI Trader can trade with governance.

AI Trader can explain some decisions.

AI Trader can store evidence.

AI Trader can protect capital with mechanical controls.

AI Trader cannot yet prove that its trading technique is improving in a rigorous, statistical way.

The next sprint should not be "make it trade more." The next sprint should be "make every trade belong to a named strategy with measurable evidence and clean outcome attribution."

