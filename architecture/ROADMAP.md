# Roadmap

## Completed

- Governance folder and core governance documents.
- Alpaca paper trading integration.
- AI proposal generation.
- Deterministic execution validation.
- SQLite audit database.
- Trading journal.
- Daily briefing/reporting foundation.
- Local API.
- Expo mobile app.
- Render deployment.
- Investment intelligence database.
- Benchmark trader learning database.
- Multi-broker runtime tables.
- Investment Orchestrator.
- Broker-specific auto-trading settings.
- Kraken live micro-trading adapter.
- Kraken mechanical seatbelts.
- Managed exits.
- Recommendation history persistence.
- Trade History screen.
- Ask AI read-only screen.
- App icon and mobile build pipeline.

## Near-Term Roadmap

1. Canonical trade lifecycle model.
   Create a normalized table that represents one logical trade from entry to exit, independent of broker payload shape.

2. Trade attribution reconciliation.
   Add a reconciler that converts raw broker fills into lifecycle rows and performance attribution.

3. Better open-position cards.
   Show current live price, unrealized P&L, stop loss, take profit, time held, and exit button for each AI-managed position.

4. Worker health dashboard.
   Add worker-level heartbeat: research, crypto refresh, broker polling, managed exits, auto execution, push dispatch.

5. UI component split.
   Refactor `mobile/App.js` into screen and component files.

6. Formal migrations.
   Add a migration table and versioned schema migrations.

7. Integration tests for broker adapters.
   Mock Alpaca and Kraken payloads, partial fills, order failures, timeouts, duplicate order attempts, and managed exits.

## Medium-Term Roadmap

1. Governed configuration console.
   Allow founder to edit allocations, allowed pairs, and auto-trading controls through the app with audit records and Render sync where appropriate.

2. Provider-backed data expansion.
   Add reliable news, sentiment, and on-chain data providers.

3. Improved OpenAI reasoning.
   Use structured tool/context packaging for Ask AI and proposal analysis with strict read-only boundaries.

4. Coinbase implementation.
   Add real Coinbase adapter using the same broker adapter contract and seatbelt model.

5. Strategy review workflow.
   Let AI propose strategy/guardrail changes into an approval queue without applying them.

## Long-Term Roadmap

1. Broker-agnostic execution router.
   Route based on broker capability, cost, liquidity, currency, risk, and founder preference.

2. Portfolio-level risk engine.
   Move from per-trade checks to more complete portfolio risk modeling.

3. Event sourcing.
   Convert critical state changes into append-only event stream with projections.

4. Complete Supabase/Postgres migration.
   Always-On operations evidence is now Postgres-capable. Next migrate broker runtime, recommendations, canonical lifecycle, trade audit, reports, and learning records before enabling full Render worker/cron production topology.

5. Multi-device identity and auth.
   Replace shared token model with user/device authentication if the platform grows beyond personal use.

## Roadmap Discipline

Future development should preserve:

- AI/execution separation.
- Orchestrator as execution authority.
- Broker independence.
- Audit-first persistence.
- Founder approval for governance changes.
