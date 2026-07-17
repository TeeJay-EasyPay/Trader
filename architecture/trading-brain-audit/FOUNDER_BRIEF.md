# Founder Brief

Date: 2026-07-17

Purpose: plain-English summary of the trading brain forensic audit.

## Short Answer

AI Trader is not just a random bot, and it is not reckless. It has a serious governance and execution framework around it.

But it is not yet a world-class trading brain.

Right now, AI Trader is best described as:

> a governed recommendation and execution platform with early-stage trading intelligence.

It can research, create recommendations, apply guardrails, route through an orchestrator, place broker orders when permissions allow, monitor positions, record events, and explain some of what happened. That is valuable.

The weaker part is the "why this is a great trade" brain. The current system uses useful heuristics and OpenAI-supported reasoning, but it does not yet have formal trading strategies, market-regime awareness, backtested edge, calibrated confidence, or deep outcome-driven learning.

## How AI Trader Currently Decides A Trade Looks Good

For stocks:

- The app uses `AITradingAgent.propose_trades` in `src/ai_trader/agent.py`.
- If the OpenAI key is available, `OpenAIProposalAnalyzer` in `src/ai_trader/ai.py` asks OpenAI to produce a conservative structured proposal.
- That proposal must include entry, stop loss, take profit, size, risk percentage, confidence, news, sentiment, technical summary, and plain-English reasoning.
- The proposal then goes through guardrails and orchestrator validation before any order can happen.

For Kraken crypto:

- The app uses `propose_crypto_trades` in `src/ai_trader/agent.py`.
- It reads crypto research scores from SQLite.
- It looks for coins with enough due-diligence confidence and a positive recent trend.
- It creates a buy proposal with a fixed stop loss and take profit.
- It then sends that proposal through the same guardrails, orchestrator, and Kraken adapter seatbelts.

## What This Means In Plain English

AI Trader is currently saying:

"This asset has enough score and passes the safety checks, so I can propose a controlled trade."

It is not yet saying:

"This is Strategy A, in Market Regime B, with a historically proven edge, a calibrated 85% confidence estimate, expected return of X, known failure modes, and a verified sample of similar past trades."

That second sentence is where the next architecture needs to go.

## Is The System Safe?

The system is meaningfully safer than a simple trading bot because:

- the AI does not directly call the broker;
- the Investment Orchestrator is the execution authority;
- guardrails run independently of AI reasoning;
- Kraken has extra live-order seatbelts;
- broker auto trading is separate per broker;
- every trade must pass validation;
- the app records decisions for audit;
- the Ask screen is read-only and cannot place trades.

These safety features should be protected.

## Is The System Smart?

It is partially smart.

It can gather data, score assets, use OpenAI for reasoning and explanation, apply policy, and produce recommendations. That is useful intelligence.

But it is not yet "learning to trade better" in the strong sense. It records evidence and reports lessons, but completed trades do not yet automatically recalibrate confidence, change strategy selection, improve entries, modify stops, or alter position sizing.

The system is building a memory. It is not yet turning that memory into a measured trading edge.

## Why Some App Answers Can Feel Unsatisfying

When Ask AI Trader says things like "no closed trade attribution" or "not available", that usually means:

- the broker row exists;
- the app saw a fill or an order;
- but the data has not been normalized into a full trade lifecycle with entry, exit, fees, P&L, and reason.

This is why a new canonical trade lifecycle is one of the most important next steps.

## Why The 85% Score Should Be Treated Carefully

An 85% score currently means the app's scoring logic says the trade passed the threshold.

It does not yet mean:

- 85% probability of winning;
- 85% historically proven accuracy;
- 85% expected profitability.

That distinction matters.

The next system should track what actually happens to trades in each confidence bucket, so that AI Trader can learn whether "85%" really behaves like a strong signal.

## Main Strengths

- Strong guardrails and seatbelts.
- Clear broker separation.
- Kraken live trading controls are deliberately mechanical.
- Recommendations are stored rather than disappearing.
- Execution is routed through the orchestrator.
- Ask AI Trader is read-only, which protects trading controls.
- The app has a growing audit trail.
- Tests currently pass.

## Main Weaknesses

- No formal strategy registry.
- No market regime engine.
- No backtesting.
- No calibrated confidence.
- No canonical trade lifecycle.
- Crypto scoring is still shallow.
- Equity trading depends heavily on OpenAI reasoning unless a deterministic strategy is added.
- Learning is mostly reporting rather than technique improvement.

## What Should Be Built Next

The next architecture should add a Trading Intelligence layer before the Investment Orchestrator:

```text
Research -> Signals -> Strategy Engine -> Recommendation -> Orchestrator -> Broker
```

The first practical build should include:

1. Strategy Registry.
2. Signal Evidence model.
3. Canonical Trade Lifecycle.
4. Strategy Attribution.
5. Market Regime Engine.
6. Confidence Calibration.
7. Backtesting harness.

## Founder Decision

The right next move is not to remove caution.

The right next move is to make the brain more precise while keeping the existing mechanical safety system.

The app should become better at proving why a trade deserves risk, not simply better at placing trades.

