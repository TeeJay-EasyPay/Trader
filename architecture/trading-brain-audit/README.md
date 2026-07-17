# Trading Brain Forensic Audit

Date: 2026-07-17

Scope: analysis only. No production behaviour, schema, scheduler, broker, risk, UI, or governance logic was changed.

## Primary Finding

AI Trader currently decides that something is a good trade through a combination of:

1. A recommendation generator:
   - equities: `AITradingAgent.propose_trades` in `src/ai_trader/agent.py`, optionally using `OpenAIProposalAnalyzer` in `src/ai_trader/ai.py`;
   - Kraken crypto: `propose_crypto_trades` in `src/ai_trader/agent.py`, using `CRYPTO_RESEARCH_SCORES`.
2. Base guardrail validation in `src/ai_trader/guardrails.py`.
3. Recommendation persistence in `trade_audit`.
4. Recommendation display and freshness logic in `LocalApiService.recommendations` in `src/ai_trader/api.py`.
5. Deterministic execution eligibility through `InvestmentOrchestrator.evaluate_recommendation` in `src/ai_trader/orchestrator.py`.
6. Policy, due diligence, investment scoring, capital allocation, and universe validation in `src/ai_trader/foundation.py`.
7. Broker-specific adapter and seatbelt checks in `src/ai_trader/broker_adapters.py`.

The current trading brain is robustly governed but not yet a world-class trading intelligence layer. It has risk controls, auditability, broker separation, and recommendation persistence. It does not yet have formal strategies, calibrated probabilities, regime-aware strategy selection, backtests, expected-value modelling, or outcome-driven parameter adaptation.

## Audit Files

- `CURRENT_RECOMMENDATION_FLOW.md`
- `TRADING_INTELLIGENCE_INVENTORY.md`
- `STRATEGY_AUDIT.md`
- `MARKET_REGIME_AUDIT.md`
- `INVESTMENT_VS_TRADE_AUDIT.md`
- `CONFIDENCE_SCORE_AUDIT.md`
- `LEARNING_ENGINE_AUDIT.md`
- `DATA_SOURCE_AUDIT.md`
- `SCHEDULER_AUDIT.md`
- `QUANTITATIVE_VALIDATION_AUDIT.md`
- `WORLD_CLASS_GAP_ANALYSIS.md`
- `PRESERVE_AND_PROTECT.md`
- `RECOMMENDED_NEXT_ARCHITECTURE.md`
- `FOUNDER_BRIEF.md`
- `CONSOLIDATED_TRADING_BRAIN_AUDIT.md`

## Test Baseline

Command run:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

Result: 86 tests passed.

Observed test logs included simulated OpenAI timeout, simulated worker failure, simulated auth lockout, and simulated scheduler failure. These are expected test scenarios, not production failures.
