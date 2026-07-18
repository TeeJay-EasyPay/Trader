# Next Stage Recommendations

## Phase 6 Priority

1. Complete Supabase/Postgres runtime migration for all critical runtime tables.
2. Add a worker-owned outbox processor for Sprint 6 learning workflows.
3. Make market data gateway rows mandatory for every actionable recommendation.
4. Add hosted Render soak validation with the mobile app closed.
5. Add broker-specific reconciliation tests using recorded Alpaca and Kraken fixtures.
6. Add strategy promotion review UI before any micro-live entitlement is granted.

## What Should Not Be Changed

- Investment Orchestrator remains execution authority.
- Risk Engine and guardrails remain mandatory.
- Ask AI Trader remains read-only.
- Strategy learning cannot silently change production parameters.
- Kraken live controls must remain explicit and broker-specific.

