# Always-On Research Activation

## Scheduling authority

The Render API is a request-serving process. `RESEARCH_SCHEDULER_ENABLED=false` prevents it from starting a competing in-process scheduler. The Render background worker is the production scheduling authority when `AI_TRADER_WORKER_RESEARCH_ENABLED=true`.

The worker command is:

```text
python -m ai_trader run-worker --sleep-seconds 60
```

## Worker cadence

- Broker polling, managed exits and auto-execution eligibility are evaluated on the fast worker cadence.
- A production broker/evidence snapshot is captured every `AI_TRADER_PRODUCTION_SNAPSHOT_INTERVAL_SECONDS` seconds, default 300.
- Crypto research runs continuously in durable hourly buckets using `RESEARCH_SCHEDULER_INTERVAL_MINUTES`, default 60.
- Equity research uses `America/New_York` market-aware windows: pre-market preparation, market-open scans, mid-session refreshes and market-close review.
- Daily reporting is scheduled after the equity session.
- Learning continues independently of whether a new trade is permitted.

Each run uses `SCHEDULED_JOB_RUNS` and an idempotency key. A second worker cannot legitimately claim the same time bucket. `WORKER_HEARTBEATS` proves liveness independently of the phone.

## Research result states

A successful cycle may produce recommendations, or it may complete with no action. No-action results are persisted with the number of assets requested, assets processed, recommendations created and rejection/failure reason. This distinguishes healthy inactivity from a scheduler failure.

## Safety

Research can run while broker auto-trading is disabled. Order submission still requires a fresh recommendation, a qualified strategy, Portfolio Manager approval, Risk Engine approval, broker-specific permission and successful deterministic validation. Existing Kraken live controls and Alpaca paper-only controls remain unchanged.
