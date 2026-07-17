# Preserve And Protect

The following foundations are strong and should be preserved.

## AI / Execution Separation

Evidence:

- `OpenAIProposalAnalyzer` only returns proposals.
- `OpenAIReadOnlyExplainer` is explicitly read-only.
- Broker calls are made through orchestrator/adapters, not directly by AI.

Why protect:

- This is the most important safety boundary in the system.

## Investment Orchestrator

Evidence:

- `InvestmentOrchestrator.evaluate_recommendation` centralizes broker selection, validation, policy checks, capital allocation, order locking, and broker submission.

Why protect:

- It prevents UI, AI, or scheduler paths from bypassing execution checks.

## Risk Engine

Evidence:

- `validate_trade_proposal`.
- `load_trading_policy`.
- `calculate_capital_allocation`.
- Broker-specific Kraken seatbelts.

Why protect:

- Current trading intelligence is not yet advanced. Strong risk controls are what make experimentation survivable.

## Broker Adapter Layer

Evidence:

- `BrokerAdapter` protocol.
- Alpaca/Kraken/placeholder adapters.

Why protect:

- Future brokers can be added without rewriting the core decision flow.

## Audit History

Evidence:

- `trade_audit`.
- `BROKER_TRADE_HISTORY`.
- `ORCHESTRATOR_DECISIONS`.
- `EXECUTION_DECISIONS`.
- `PERFORMANCE_ATTRIBUTION`.
- `TRADING_REPORTS`.

Why protect:

- The founder needs traceability more than black-box autonomy.

## Broker-Specific Controls

Evidence:

- `BROKER_AUTO_TRADING_SETTINGS`.
- Kraken env switches and seatbelt display.

Why protect:

- Broker independence prevents accidental cross-broker enablement.

## Managed Exits

Evidence:

- `MANAGED_TRADE_EXITS`.
- `monitor_managed_exits`.
- `force_managed_exit`.

Why protect:

- Disabling new entries must not disable exit protection.

## Recommendation Persistence

Evidence:

- `trade_audit` proposal rows.
- `RECOMMENDATION_SETS`.
- Recommendation screen reads saved history.

Why protect:

- The founder should never lose decision history after app restart.

## Governance Boundaries

Evidence:

- Governance docs.
- Policy tables.
- Learning note says recommendations only.

Why protect:

- The AI should propose improvements, not silently mutate risk or strategy.
