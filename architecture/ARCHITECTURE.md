# Architecture

## High-Level Architecture

```mermaid
flowchart TD
    Mobile[Expo Mobile App] -->|HTTPS JSON + Bearer token| API[Render Python API]
    Browser[Browser Report Views] -->|GET /reports/{id}| API
    API --> SQLite[(SQLite local / legacy store)]
    API --> Postgres[(Supabase Postgres for Always-On evidence when configured)]
    API --> Logs[Rotating logs]
    API --> OpenAI[OpenAI API]
    API --> Alpaca[Alpaca Paper API]
    API --> Kraken[Kraken API]
    API --> CoinGecko[CoinGecko Public API]
    API --> ExpoPush[Expo Push API]
    API --> RenderAPI[Render API optional config sync]
    API --> Orchestrator[Investment Orchestrator]
    Orchestrator --> Risk[Risk Engine]
    Orchestrator --> BrokerAdapters[Broker Adapter Layer]
    BrokerAdapters --> Alpaca
    BrokerAdapters --> Kraken
    API --> Scheduler[Background Scheduler Workers]
    Scheduler --> API
    Governance[Governance Documents] --> API
    Governance --> Orchestrator
```

## Runtime Components

### Mobile App

The mobile app is a single Expo React Native client implemented in `mobile/App.js`. It provides the founder-facing interface:

- Command
- Trade History
- Recommendations
- Intelligence
- Ask

The app does not execute broker calls directly. It calls the hosted or local API. Protected commands include a bearer token. The app displays readiness information so missing command token, Render connectivity, OpenAI availability, and broker connectivity are visible.

### Render

Render hosts the Python API as a Docker web service. `render.yaml` defines:

- Service name: `ai-trader-api`.
- Docker environment.
- Health path: `/healthz`.
- Persistent disk: `ai-trader-data` mounted at `/data`.
- Production environment variables.

Render is responsible for running the backend continuously. The mobile app is a Founder interface only; it must not be responsible for keeping research, reconciliation, shadow trading, or learning alive.

The code now supports explicit process entry points:

- `python -m ai_trader serve-api`
- `python -m ai_trader run-worker`
- `python -m ai_trader run-job <job-name>`

The current `render.yaml` keeps only the web service active until a shared production datastore is confirmed. Separate worker and cron services should only be enabled after `/operations-health` proves that Always-On evidence is using Supabase/Postgres.

## Phase 5 Autonomous Production Spine

Phase 5 adds `src/ai_trader/production_spine.py` as an additive production-readiness and closed-loop-learning layer. It does not replace the Investment Orchestrator, Risk Engine, Operational Truth, Experience Engine, or broker adapters. Instead, it coordinates their evidence into a clearer production spine:

- database spine readiness;
- worker supervision;
- canonical reconciliation cases;
- closed-loop learning completion;
- Portfolio Manager decisions;
- Market Data Gateway quality gates;
- strategy promotion and demotion gates.

The API exposes this through `GET /phase5-status` and includes the same evidence in `/status.phase5_status`. The mobile Dashboard shows a compact `Autonomous Production Spine` card.

Current readiness is expected to remain partial until all critical runtime families move to a shared production datastore.

### Supabase

Supabase/Postgres is now partially supported as the production target for Always-On operations evidence. When Render sets:

```text
AI_TRADER_DATABASE_BACKEND=postgres
DATABASE_URL=<Supabase Postgres connection string>
```

`src/ai_trader/always_on.py` stores these tables in Postgres:

- `SCHEDULED_JOB_RUNS`
- `WORKER_HEARTBEATS`
- `RESEARCH_FUNNELS`
- `SHADOW_TRADES`
- `OPERATIONS_INCIDENTS`

This is not yet a full application datastore migration. Broker runtime, recommendations, trade audit, canonical lifecycle, reports, and learning tables remain SQLite-oriented until each schema family is ported deliberately.

### SQLite

SQLite remains the default local/test store and the broad legacy application store. It stores:

- Trade audit events.
- Broker runtime state.
- Broker auto-trading settings.
- Recommendation sets.
- Broker trade history.
- Managed exits.
- Portfolio snapshots.
- Research runs.
- Intelligence records.
- Governance policy rows.
- Reports.
- Notifications.
- Performance attribution.

The database is initialized by multiple modules. Each module owns its own schema initializer and creates missing tables if needed.

### Investment Orchestrator

`src/ai_trader/orchestrator.py` contains `InvestmentOrchestrator`. It is the execution authority. It evaluates recommendations against:

- Broker support.
- Market availability.
- Asset availability.
- Guardrail validation.
- Investment policy.
- Due diligence status.
- Investment score.
- Capital allocation.
- Broker-specific permission.
- Account exposure.
- Drawdown and loss thresholds.

Only after passing these checks does it call a broker adapter.

### Research Engine

Research is coordinated by API methods and `src/ai_trader/scheduler.py`. Research can be manual or scheduled. It can review:

- Equity watchlist companies.
- Crypto assets.
- Benchmark trader learning data.
- Existing recommendations and broker state.

Research results are persisted as research runs, crypto research scores, recommendation sets, and trade proposals.

### Knowledge Engine

The knowledge engine consists of:

- `InvestmentIntelligenceDatabase` for companies, themes, watchlists, and company updates.
- `BenchmarkIntelligenceDatabase` for public benchmark trader lessons.
- Crypto research storage in foundation and multi-broker tables.
- Daily learning and reporting logic in `api.py`.

The knowledge engine stores evidence and lessons. It does not automatically modify trading rules.

### Crypto Engine

Crypto research uses:

- CoinGecko public market data where available.
- Kraken approved pairs as fallback/universe inputs.
- Crypto scoring logic in `api.py`, `operational.py`, and `multi_broker.py`.
- Kraken adapter price and order capabilities.

Current crypto scoring includes technical trend, momentum, volatility, liquidity, risk, confidence, and due diligence score. Sentiment, news, and on-chain data are left unavailable unless a provider exists; the system should not fabricate those values.

### Due Diligence

Due diligence is recorded in `DUE_DILIGENCE_ASSESSMENTS`. It checks whether the proposal has:

- Fundamental context.
- Technical context.
- Market context.
- Macro context.
- Behavioural/benchmark or sentiment context.
- Policy fit.

Incomplete due diligence blocks autonomous execution.

### Recommendations

Recommendations are normalized `TradeProposal` objects. They are persisted through `trade_audit` proposal events and grouped through `RECOMMENDATION_SETS`. The mobile recommendations screen displays saved sets from SQLite and does not rely only on in-memory state.

### Notifications

Notifications are stored in `NOTIFICATION_EVENTS`. The app can show in-app events, and the backend can dispatch high-priority events through Expo push when tokens are registered.

### Risk Engine

The risk engine is split across:

- `guardrails.py` for base proposal validation.
- `foundation.py` for policy loading, due diligence, investment scores, capital allocation, and universe validation.
- `orchestrator.py` for final cross-checks and execution blocking.
- `multi_broker.py` for order locks, managed exits, and seatbelt events.

### Broker Adapters

`broker_adapters.py` defines a protocol and concrete adapters:

- `AlpacaBrokerAdapter`
- `KrakenAdapter`
- `CoinbaseAdapter`
- `InteractiveBrokersAdapter`
- `SaxoAdapter`

Only Alpaca and Kraken have meaningful current implementation. Future brokers should implement the same adapter interface and should not require changes to the orchestrator flow beyond registration and broker-specific policy.

### Scheduler

`ResearchScheduler` runs research cycles. `IntervalWorker` runs recurring background tasks. The API starts workers for:

- Managed exit monitoring.
- Broker trade polling.
- Auto execution.
- Crypto universe refresh.
- Push notification dispatch.

### API

`api.py` exposes HTTP endpoints through Python `ThreadingHTTPServer`. It uses JSON request/response handling and direct route dispatch inside `ApiHandler`.

Key endpoint classes:

- Read endpoints: status, health, portfolio, recommendations, intelligence, trade history, reports.
- Command endpoints: run analysis, approve and execute, auto execute, broker auto trading, managed exit, report generation, Ask AI.

### Authentication

Hosted protected calls require `AI_TRADER_API_TOKEN`. Mobile builds must include `EXPO_PUBLIC_AI_TRADER_API_TOKEN`. The API uses bearer-token validation and blocks protected POST commands if the token is missing or wrong.

### Logging

`configure_logging` writes console logs and rotating file logs under the configured output directory. Render logs should be used for runtime failures, and SQLite audit tables should be used for domain decisions.

### Governance

Governance documents live in `governance/`. They are human-readable source-of-truth documents. Policy values are also seeded into SQLite policy tables for runtime validation. The AI may recommend changes but must not apply governance changes automatically.
