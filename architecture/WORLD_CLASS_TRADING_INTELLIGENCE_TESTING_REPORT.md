# World-Class Trading Intelligence Testing Report

Date: 2026-07-17

## Automated Tests

Command:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

Result:

```text
Ran 90 tests
OK
```

The suite includes simulated OpenAI timeout, scheduler failure, worker failure, and authentication lockout logs. These are expected resilience scenarios in existing tests.

## New Regression Tests

Added `tests/test_trading_intelligence.py`.

Coverage:

- Trading Intelligence schema creates and seeds `STRATEGY_REGISTRY`.
- Intelligence packet records both strongest argument for and strongest argument against.
- `trade_audit` can store the intelligence payload without breaking existing audit writes.
- Investment Orchestrator records lifecycle stages after evaluating a recommendation.

## Mobile Validation

Attempted:

```powershell
npx tsc --noEmit
```

Result:

The mobile app does not include TypeScript as a dependency. `npx tsc` attempted to run the unsupported placeholder `tsc` package and failed before checking the app. No dependency changes were made in this sprint.

## Paper Trading Validation

The automated suite exercises paper-trading style orchestrator and adapter paths with fake adapters.

No live Alpaca or Kraken order was submitted during this documentation/testing pass.

## Kraken Validation

Kraken-specific live trading behavior remains protected by existing adapter tests and safety controls.

No real Kraken order was submitted by this sprint validation.

## Phase 2 Automated Tests

Command:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Result:

```text
Ran 96 tests
OK
```

Focused Trading Intelligence command:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_trading_intelligence -v
```

Result:

```text
Ran 10 tests
OK
```

Phase 2 coverage added:

- market-intelligence price metrics are calculated from candles without using AI proposal confidence;
- regime inference uses market metrics and does not remain unknown when sufficient candle evidence exists;
- signal scores are not simple copies of recommendation confidence;
- committee disagreement is recorded when portfolio evidence raises a duplicate-position concern;
- probability estimates carry small-sample uncertainty;
- Strategy Lab backtests are recorded;
- calibration metrics compute Brier score from closed attribution;
- lifecycle rows store fees, slippage, R-multiple, MAE, MFE, and holding time.

Additional compile check:

```powershell
.\.venv\Scripts\python.exe -m py_compile src\ai_trader\trading_intelligence.py src\ai_trader\api.py
```

Result:

```text
OK
```
