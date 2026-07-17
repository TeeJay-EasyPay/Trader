# Current Recommendation Flow

## Summary

There are two main current recommendation pathways:

1. Equity recommendations through `LocalApiService.run_analysis` -> `AITradingAgent.propose_trades`.
2. Kraken crypto recommendations through `LocalApiService.run_crypto_analysis` -> `propose_crypto_trades`.

Both persist recommendations as `agent_proposal` rows in `trade_audit`. Execution then flows through `LocalApiService.approve_and_execute` or `LocalApiService.auto_execute_recommendations`, both handing off to `InvestmentOrchestrator.evaluate_recommendation`.

## Equity Manual Research Path

Entry point:

- HTTP: `POST /run-analysis`
- Function: `LocalApiService.post` in `src/ai_trader/api.py`
- Main function: `LocalApiService.run_analysis`

Call path:

1. `LocalApiService.run_analysis(body)`.
2. If `broker == "kraken"`, delegates to `run_crypto_analysis`; otherwise defaults to Alpaca/equities.
3. Updates broker runtime with `update_broker_runtime`.
4. Determines symbols:
   - `body["symbols"]`, or
   - first 30 `COMPANY_MASTER.ticker` rows.
5. Requires Alpaca credentials through `settings.has_alpaca_credentials`.
6. Creates broker client through `self._broker()`.
7. Creates `OpenAIProposalAnalyzer` if `settings.openai_api_key` exists.
8. Creates `AITradingAgent(market_data=broker, audit=self.audit, guardrails=settings.guardrails, analyzer=analyzer)`.
9. Loads account context using `broker.account_context`.
10. Calls `agent.propose_trades([symbol], account)` per symbol.
11. Records analysis completion through `record_research_run` and `audit.record_execution_event`.
12. Creates notification through `record_notification`.
13. If proposals exist, calls `auto_execute_recommendations`.

Data collected:

- Alpaca latest bars via `MarketDataClient.get_latest_bars`.
- Alpaca news via `MarketDataClient.get_news`.
- Account equity, P&L, open positions from Alpaca.
- Watchlist symbols from `COMPANY_MASTER`.

Data transformation:

- Market/news/account are passed to either OpenAI analyzer or deterministic no-trade path.
- Valid proposals become `TradeProposal` objects.
- Base guardrail validation marks `ai_guardrails_passed`.

## Equity OpenAI-Assisted Proposal Path

Function:

- `OpenAIProposalAnalyzer.propose` in `src/ai_trader/ai.py`.

Prompt structure:

- JSON object with:
  - `instruction`
  - `symbol`
  - `market`
  - `news`
  - `account_equity`

Instruction requires:

- Return only JSON proposal or null.
- Use fields: `symbol`, `side`, `entry_price`, `stop_loss`, `take_profit`, `position_size`, `risk_percentage`, `confidence_score`, `news_summary`, `market_sentiment_summary`, `technical_summary`, `plain_english_reasoning`.
- `risk_percentage` is decimal.
- `confidence_score` must be at least `GuardrailConfig.min_confidence_score`.
- `risk_percentage` must be no more than `GuardrailConfig.max_risk_per_trade_pct`.
- Do not create more than `GuardrailConfig.max_open_positions`.
- Buy stop below entry, buy take profit above entry.
- Sell stop above entry, sell take profit below entry.
- Only propose clear and conservative trades.

OpenAI response format:

- Uses `/v1/responses`.
- Sends `text: {"format": {"type": "json_object"}}`.
- `_extract_response_text` extracts output text.
- `_proposal_from_response_text` parses JSON into `TradeProposal.from_dict`.

Important limitation:

- The OpenAI prompt does not define a formal strategy, timeframe, regime, indicator formula, entry trigger, or calibration standard. It asks the model to produce conservative proposals from supplied market/news context.

## Equity Deterministic Fallback Behaviour

If no analyzer exists and `demo=False`, `AITradingAgent._no_trade_probe` records `agent_no_trade` and returns `None`.

There is no non-demo deterministic equity strategy in the current code.

Demo mode:

- `AITradingAgent._demo_proposal`.
- Uses latest close or 100.
- Stop = 1% risk per share.
- Take profit = 2R.
- Quantity = account equity risk cap / risk per share.
- Confidence = max(min confidence, 0.72).
- Intended for validation only.

## Kraken Crypto Research Path

Entry points:

- HTTP: `POST /run-crypto-analysis`
- HTTP: `POST /run-analysis` with broker `kraken`
- Scheduler: `refresh_crypto_universe` calls `run_crypto_analysis`

Main functions:

- `LocalApiService.run_crypto_analysis`
- `propose_crypto_trades`
- `record_crypto_research_score`

Call path:

1. `LocalApiService.run_crypto_analysis(symbols=None, limit=10)`.
2. Requires configured Kraken adapter.
3. Loads active symbols from `CRYPTO_MASTER`.
4. If no symbols exist, calls `_bootstrap_crypto_universe_from_kraken_permissions`.
5. Builds Kraken account context using `_account_context_for_broker("kraken")`.
6. Calls `propose_crypto_trades`.
7. If proposals exist, calls `auto_execute_recommendations`.
8. Updates `BROKER_RUNTIME_STATE`.
9. Records notification, recommendation set, and research run.

Crypto deterministic scoring inputs:

- `CRYPTO_RESEARCH_SCORES.overall_due_diligence_score`
- `technical_trend_score`
- Kraken live current price
- `settings.auto_trade.min_confidence`
- `settings.auto_trade.crypto_max_trade_amount`
- `settings.auto_trade.crypto_default_stop_loss_pct`

Crypto proposal rules:

- Confidence = `overall_due_diligence_score`.
- Requires confidence >= min confidence.
- Requires `technical_trend_score > 0.5`.
- Requires current Kraken price.
- Side is always `buy`.
- Stop loss = price * (1 - default stop loss pct).
- Take profit = price * (1 + default stop loss pct * 2).
- Quantity = requested notional / price.
- Risk percentage = quantity * abs(price - stop loss) / account equity.
- Philosophy fit = confidence.

Important limitation:

- This is a simple positive-trend heuristic, not a full crypto trading strategy.

## Crypto Research Score Creation

CoinGecko path:

- `seed_crypto_universe(fetch_live=True)` in `operational.py`.
- Fetches market cap, AI coins, and privacy/security categories.
- `_crypto_metrics_from_market_row` computes:
  - 24h change -> momentum score.
  - 7d change -> technical trend score.
  - 30d absolute change -> volatility.
  - volume / market cap -> liquidity.
  - 1 - volatility -> risk score.
- `record_crypto_research_score` computes overall due diligence score if missing.

Fallback path:

- `_bootstrap_crypto_universe_from_kraken_permissions`.
- Reads `KRAKEN_ALLOWED_PAIRS`.
- Inserts `CRYPTO_MASTER`.
- Records synthetic scores:
  - technical trend 0.62
  - momentum 0.6
  - risk 0.72
  - sentiment 0.55
  - liquidity 0.75
  - overall/confidence max(min confidence, 0.85)

Important limitation:

- Approved-pair fallback creates heuristic scores without market-derived trend evidence. It is constrained by allowed pairs and live price but should not be treated as serious market intelligence.

## Recommendation Persistence

Proposal persistence:

- `AuditDatabase.record_trade_event("agent_proposal", proposal, validation=validation)`.
- Writes `trade_audit`.
- Appends to `governance/TRADING_LOG.md` if configured.

Recommendation-set persistence:

- `record_recommendation_set` writes `RECOMMENDATION_SETS`.

Recommendation retrieval:

- `LocalApiService.recommendations`.
- Reads `trade_audit` where `event_type = 'agent_proposal'`.
- Joins company intelligence tables.
- Sorts by `ai_confidence DESC`, `created_at DESC`, `id DESC`.
- Deduplicates by proposal ID.
- Adds freshness, due diligence, investment score, auto-trade eligibility, guardrail summaries, and latest orchestrator decision.

## Manual Execution Path

Entry point:

- HTTP: `POST /approve-and-execute`
- Function: `LocalApiService.approve_and_execute`

Flow:

1. Requires `engine_control.trading_state == "running"`.
2. Looks up proposal by `proposal_id`; fallback by symbol.
3. Blocks expired recommendation.
4. Rehydrates `TradeProposal` from `trade_audit.payload_json`.
5. Selects broker through `orchestrator._select_adapter`.
6. Checks broker-specific managed capacity.
7. Builds account context.
8. Applies manual amount override through `_proposal_with_manual_amount`.
9. Calls `InvestmentOrchestrator.evaluate_recommendation(..., auto_execute=True)`.

Manual approval does not bypass orchestrator validation.

## Autonomous Execution Path

Entry point:

- HTTP: `POST /auto-execute-recommendations`
- Worker: `IntervalWorker(service.auto_execute_recommendations, ...)`

Flow:

1. Requires trading state `running`.
2. Requires at least one broker auto-trading setting enabled.
3. Requires `PAPER_TRADING_ONLY` guardrail still true.
4. Reads latest 50 `agent_proposal` rows ordered by confidence/time.
5. Skips if confidence below auto threshold.
6. Skips expired recommendations.
7. Skips if proposal guardrails did not pass at recommendation time.
8. Skips already executed proposals.
9. Rehydrates `TradeProposal`.
10. Selects broker.
11. Requires broker auto-trading enabled.
12. Requires AI-managed trade capacity.
13. Calls `InvestmentOrchestrator.evaluate_recommendation(..., auto_execute=True)`.

## Orchestrator Handoff

Function:

- `InvestmentOrchestrator.evaluate_recommendation`.

Validation and scoring:

- Select adapter by asset type.
- Check market open and asset availability.
- Run `validate_trade_proposal`.
- Load `TradingPolicy`.
- Create due diligence assessment.
- Calculate investment score.
- Calculate capital allocation.
- Check confidence, philosophy fit, stop loss, take profit, stop-loss percentage, emergency shutdown, concurrent positions, weekly/monthly loss, drawdown, exposure, allocation, investment universe, and validation failures.
- Record broker decision.
- If approved and auto enabled, acquire order intent lock.
- Submit bracket/managed order through adapter.
- Record orchestrator decision and execution decision.

This is the real execution gate.
