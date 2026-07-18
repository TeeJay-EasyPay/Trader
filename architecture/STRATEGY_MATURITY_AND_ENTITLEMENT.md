# Strategy Maturity And Entitlement

## Maturity Ladder

```text
Research
Backtest
Walk Forward
Shadow
Paper
Micro Live
Production
Retired
```

## Sprint 6 Registry

Sprint 6 creates `STRATEGY_MATURITY_REGISTRY`.

The registry stores:

- strategy ID
- version
- current stage
- evidence
- sample size
- expectancy
- average and median net R
- profit factor
- drawdown
- win rate
- calibration error
- permitted asset classes
- permitted brokers
- permitted modes
- capital and risk limits
- approval authority
- suspension state

## Default Strategy

The seeded default is `current_recommendation_process`.

It is set to `Paper`.

It permits:

- shadow
- paper
- manual

It does not permit:

- micro-live
- production

## Execution Rule

No recommendation may proceed to execution unless the strategy is registered, not suspended, permitted for the broker, permitted for the asset type, and mature enough for the requested execution mode.

