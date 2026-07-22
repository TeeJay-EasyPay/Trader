# AI Trading Assistant V1

## Production Completion and Architectural Cutover

The repository now has one mandatory hosted database and execution contract:

- Supabase Postgres is the only permitted hosted runtime database;
- SQLite is retained only for local development, isolated tests, migration input and local inspection;
- the Investment Orchestrator owns strategy maturity, Portfolio Manager, Risk Engine, Sentinel, execution intent and broker submission;
- one logical trade ID links intent, broker events, fills, fees, P&L and terminal learning;
- terminal learning is idempotent and incomplete historical evidence is labelled rather than invented;
- individual worker jobs have persisted timeout and incident evidence.

Historical SQLite data can be copied additively after Postgres schema initialization:

```powershell
python -m ai_trader migrate-sqlite-to-postgres --source data/audit.sqlite3
```

Repository verification passes 153 authoritative Python tests. This does **not** claim the hosted cutover is complete: deploy, Supabase migration, a real Alpaca paper round trip and the production soak protocol remain mandatory release evidence.

Start with:

- [`architecture/PRODUCTION_COMPLETION_ARCHITECTURE_AUDIT.md`](architecture/PRODUCTION_COMPLETION_ARCHITECTURE_AUDIT.md)
- [`architecture/PRODUCTION_COMPLETION_ARCHITECTURE.md`](architecture/PRODUCTION_COMPLETION_ARCHITECTURE.md)
- [`architecture/PRODUCTION_DATABASE_CUTOVER.md`](architecture/PRODUCTION_DATABASE_CUTOVER.md)
- [`architecture/CANONICAL_TRADE_AND_LEARNING.md`](architecture/CANONICAL_TRADE_AND_LEARNING.md)
- [`architecture/PRODUCTION_COMPLETION_VERIFICATION.md`](architecture/PRODUCTION_COMPLETION_VERIFICATION.md)
- [`architecture/PRODUCTION_COMPLETION_FOUNDER_BRIEFING.md`](architecture/PRODUCTION_COMPLETION_FOUNDER_BRIEFING.md)

## Production Evidence Activation

AI Trader now has a shared Founder evidence path for the paid Render worker. The worker performs recurring crypto research, market-aware equity research, broker polling, managed-exit checks, execution eligibility, evidence snapshots and learning without the phone being open. Results are projected to Supabase/Postgres and exposed through authenticated `GET /founder-evidence` and `GET /founder/trades` endpoints.

The Expo app hydrates from its last successful evidence cache and refreshes from this bounded endpoint. Dashboard, Activity, Recommendations, Portfolio, Market and Learning therefore use the same worker-visible production evidence instead of depending on the slow legacy `/status` aggregate.

Required hosted ownership settings:

```text
RESEARCH_SCHEDULER_ENABLED=false
AI_TRADER_WORKER_RESEARCH_ENABLED=true
AI_TRADER_PRODUCTION_SNAPSHOT_INTERVAL_SECONDS=300
```

This enables autonomous work, not unconditional trading. Orders still require every existing strategy, portfolio, risk, execution and broker-permission gate.

### Founder evidence snapshot recovery

The worker now materializes the complete Founder evidence view for `1h`, `24h`, `7d`, and `30d` every five minutes. Mobile refreshes read one persisted Postgres row rather than rebuilding eight evidence datasets synchronously. A missing first snapshot returns an immediate truthful warm-up state; a snapshot older than 15 minutes remains visible and is marked stale. Database connection and statement timeouts prevent an unavailable query from occupying the API indefinitely.

This fixes application-owned evidence latency. It does not remove Render infrastructure cold starts: a free sleeping web service may still take tens of seconds before the API process can answer. Eliminating that provider delay requires an always-on Render web-service plan.

Personal AI-assisted paper trading system for Alpaca.

## CTO Handover Pack

The current engineering handover lives in [`architecture/`](architecture/). Start with:

- [`architecture/CTO_HANDOVER.md`](architecture/CTO_HANDOVER.md)
- [`architecture/ARCHITECTURE.md`](architecture/ARCHITECTURE.md)
- [`architecture/SYSTEM_OVERVIEW.md`](architecture/SYSTEM_OVERVIEW.md)
- [`architecture/DATABASE_REFERENCE.md`](architecture/DATABASE_REFERENCE.md)
- [`architecture/BROKER_ARCHITECTURE.md`](architecture/BROKER_ARCHITECTURE.md)
- [`architecture/RISK_ENGINE.md`](architecture/RISK_ENGINE.md)

The handover reflects the current implementation: Render-hosted Python API, Expo mobile app, SQLite persistence, Alpaca paper trading, Kraken live micro-trading under explicit seatbelts, broker-specific auto-trading controls, recommendation history, trade history, reports, and the read-only Ask AI screen.

## World-Class Trading Intelligence Layer

The current recommendation path now includes a formal Trading Intelligence layer before the Investment Orchestrator.

New recommendations must have structured evidence covering:

- strategy;
- market regime;
- signal evidence;
- trade setup;
- portfolio fit;
- trading committee review;
- probability estimate;
- strongest argument for the trade;
- strongest argument against the trade;
- lifecycle stage.

The AI still cannot execute trades directly. Execution remains controlled by the Investment Orchestrator, Risk Engine, and broker adapters.

Start with:

- [`architecture/WORLD_CLASS_TRADING_INTELLIGENCE_ARCHITECTURE.md`](architecture/WORLD_CLASS_TRADING_INTELLIGENCE_ARCHITECTURE.md)
- [`architecture/WORLD_CLASS_TRADING_INTELLIGENCE_PHASE_2.md`](architecture/WORLD_CLASS_TRADING_INTELLIGENCE_PHASE_2.md)
- [`architecture/WORLD_CLASS_TRADING_INTELLIGENCE_IMPLEMENTATION_REPORT.md`](architecture/WORLD_CLASS_TRADING_INTELLIGENCE_IMPLEMENTATION_REPORT.md)
- [`architecture/WORLD_CLASS_TRADING_INTELLIGENCE_FOUNDER_BRIEFING.md`](architecture/WORLD_CLASS_TRADING_INTELLIGENCE_FOUNDER_BRIEFING.md)

Phase 2 adds deterministic market-intelligence discovery, regime inference from price evidence, independent signal scoring, a richer strategy registry, a multi-member trading committee, probability calibration, strategy-lab backtesting primitives, performance intelligence, and measurable lifecycle fields for fees, slippage, R-multiple, MAE, MFE, and holding time.

## Institutional Intelligence & Founder Experience Phase 3

Phase 3 adds evidence-driven strategy selection, Strategy Lab walk-forward validation, richer portfolio intelligence, and a five-screen Founder experience:

- Dashboard
- Recommendations
- Portfolio
- Market
- Learning

The app now follows this long-term architectural principle: every new capability must help AI Trader make a better investment decision, help the Founder make a better decision, or help AI Trader learn to make better decisions in the future.

Start with:

- [`architecture/INSTITUTIONAL_INTELLIGENCE_PHASE_3.md`](architecture/INSTITUTIONAL_INTELLIGENCE_PHASE_3.md)
- [`architecture/FOUNDER_EXPERIENCE_PHASE_3_MOCKUPS.md`](architecture/FOUNDER_EXPERIENCE_PHASE_3_MOCKUPS.md)
- [`governance/FOUNDER_BRIEFING_PHASE_3.md`](governance/FOUNDER_BRIEFING_PHASE_3.md)

## World-Class Trader Transformation Phase 4-8

Phase 4-8 adds the evidence spine for operational truth, market-data quality, portfolio intelligence, governed learning, and Founder AI decision support.

Start with:

- [`architecture/WORLD_CLASS_TRADER_PHASE_4_8_IMPLEMENTATION_PLAN.md`](architecture/WORLD_CLASS_TRADER_PHASE_4_8_IMPLEMENTATION_PLAN.md)
- [`architecture/WORLD_CLASS_TRADER_TRANSFORMATION_ARCHITECTURE.md`](architecture/WORLD_CLASS_TRADER_TRANSFORMATION_ARCHITECTURE.md)
- [`architecture/OPERATIONAL_TRUTH_AND_CANONICAL_LIFECYCLE.md`](architecture/OPERATIONAL_TRUTH_AND_CANONICAL_LIFECYCLE.md)
- [`architecture/MARKET_INTELLIGENCE_PLATFORM.md`](architecture/MARKET_INTELLIGENCE_PLATFORM.md)
- [`architecture/PORTFOLIO_INTELLIGENCE_STANDARD.md`](architecture/PORTFOLIO_INTELLIGENCE_STANDARD.md)
- [`architecture/EXPERIENCE_ENGINE_AND_GOVERNED_LEARNING.md`](architecture/EXPERIENCE_ENGINE_AND_GOVERNED_LEARNING.md)
- [`architecture/FOUNDER_AI_STANDARD.md`](architecture/FOUNDER_AI_STANDARD.md)
- [`architecture/DATA_AVAILABILITY_AND_UNKNOWN_VALUES_STANDARD.md`](architecture/DATA_AVAILABILITY_AND_UNKNOWN_VALUES_STANDARD.md)
- [`architecture/RENDER_EXPO_DEPLOYMENT_CONTRACT.md`](architecture/RENDER_EXPO_DEPLOYMENT_CONTRACT.md)
- [`architecture/WORLD_CLASS_TRADER_IMPLEMENTATION_REPORT.md`](architecture/WORLD_CLASS_TRADER_IMPLEMENTATION_REPORT.md)
- [`architecture/WORLD_CLASS_TRADER_TESTING_REPORT.md`](architecture/WORLD_CLASS_TRADER_TESTING_REPORT.md)

## Always-On Operations, Shadow Trading, and Alpaca Recovery

The always-on operations sprint separates the Founder mobile app from backend operational responsibility. The app is now an interface only; background work is represented by explicit API, worker, and scheduled-job entry points:

- `python -m ai_trader serve-api`
- `python -m ai_trader run-worker`
- `python -m ai_trader run-job <job-name>`

The mobile app now uses a two-stage refresh contract. It paints the Dashboard from lightweight persisted evidence first (`/operations-health`, `/activity/summary`, `/activity/why-no-trade`, `/portfolio`, and `/recommendations`) and hydrates heavyweight diagnostics (`/status` and `/autonomous-activity`) in the background. This keeps the Founder interface responsive while still preserving the deeper operational evidence model.

## Phase 5 Autonomous Production Spine

Phase 5 adds the first production-spine foundation for closed-loop autonomous operation. It does not loosen trading controls. It adds evidence and decision gates for:

- production database spine readiness;
- worker supervision and incident creation;
- canonical reconciliation cases;
- closed-loop learning idempotency;
- Portfolio Manager authority;
- Market Data Gateway quality blocking;
- strategy promotion and demotion gates.

New status endpoint:

- `GET /phase5-status`

`GET /status` also includes `phase5_status`, and the mobile Dashboard displays an `Autonomous Production Spine` card.

Start with:

- [`architecture/PHASE_5_IMPLEMENTATION_REPORT.md`](architecture/PHASE_5_IMPLEMENTATION_REPORT.md)
- [`architecture/AUTONOMOUS_PRODUCTION_SPINE.md`](architecture/AUTONOMOUS_PRODUCTION_SPINE.md)
- [`architecture/CANONICAL_RECONCILIATION_DESIGN.md`](architecture/CANONICAL_RECONCILIATION_DESIGN.md)
- [`architecture/CLOSED_LOOP_LEARNING_ARCHITECTURE.md`](architecture/CLOSED_LOOP_LEARNING_ARCHITECTURE.md)
- [`architecture/DATABASE_ARCHITECTURE.md`](architecture/DATABASE_ARCHITECTURE.md)
- [`architecture/FOUNDER_BRIEFING.md`](architecture/FOUNDER_BRIEFING.md)

## Sprint 6 Institutional Production Control Layer

Sprint 6 adds the first enforced production-control layer around trade approval. It does not loosen guardrails or promote strategies to higher capital. Before a manual or autonomous trade can reach the Investment Orchestrator, AI Trader now records a Sprint 6 decision packet covering:

- Portfolio Manager approval or rejection;
- strategy maturity and execution entitlement;
- Production Risk Sentinel approval or rejection;
- strongest argument for the trade;
- strongest argument against the trade;
- market-data quality statement;
- final pre-execution eligibility.

New endpoints:

- `GET /sprint6-status`
- `GET /operational-events`
- `GET /decision-journal`
- `POST /generate-operational-report`

`GET /status` also includes `sprint6_status`, and the mobile Dashboard displays a `Sprint 6 Production Control` card.

Start with:

- [`architecture/SPRINT_6_IMPLEMENTATION_REPORT.md`](architecture/SPRINT_6_IMPLEMENTATION_REPORT.md)
- [`architecture/INSTITUTIONAL_PRODUCTION_ARCHITECTURE.md`](architecture/INSTITUTIONAL_PRODUCTION_ARCHITECTURE.md)
- [`architecture/POSTGRES_RUNTIME_MIGRATION_REPORT.md`](architecture/POSTGRES_RUNTIME_MIGRATION_REPORT.md)
- [`architecture/BROKER_RECONCILIATION_STANDARD.md`](architecture/BROKER_RECONCILIATION_STANDARD.md)
- [`architecture/STRATEGY_MATURITY_AND_ENTITLEMENT.md`](architecture/STRATEGY_MATURITY_AND_ENTITLEMENT.md)
- [`architecture/PRODUCTION_RISK_SENTINEL.md`](architecture/PRODUCTION_RISK_SENTINEL.md)
- [`architecture/AUTONOMOUS_QUALIFICATION_REPORT.md`](architecture/AUTONOMOUS_QUALIFICATION_REPORT.md)
- [`architecture/FOUNDER_BRIEFING_SPRINT_6.md`](architecture/FOUNDER_BRIEFING_SPRINT_6.md)

Important: Sprint 6 local tests prove the control layer and evidence records. They do not by themselves prove Render/Supabase hosted operation, phone-closed worker uptime, or increased-capital readiness.

New operations evidence is exposed through:

- `/operations-health`
- `/scheduler-status`
- `/job-runs`
- `/shadow-trades`
- `/shadow-performance`
- `/research-funnel`
- `/alpaca-inactivity-diagnosis`

Start with:

- [`architecture/ALWAYS_ON_RUNTIME_FORENSIC_AUDIT.md`](architecture/ALWAYS_ON_RUNTIME_FORENSIC_AUDIT.md)
- [`architecture/ALWAYS_ON_OPERATIONS_ARCHITECTURE.md`](architecture/ALWAYS_ON_OPERATIONS_ARCHITECTURE.md)
- [`architecture/RENDER_SERVICE_TOPOLOGY.md`](architecture/RENDER_SERVICE_TOPOLOGY.md)
- [`architecture/SHADOW_TRADING_STANDARD.md`](architecture/SHADOW_TRADING_STANDARD.md)
- [`architecture/ALPACA_INACTIVITY_ROOT_CAUSE_REPORT.md`](architecture/ALPACA_INACTIVITY_ROOT_CAUSE_REPORT.md)
- [`architecture/ALWAYS_ON_FOUNDER_BRIEFING.md`](architecture/ALWAYS_ON_FOUNDER_BRIEFING.md)
- [`architecture/SUPABASE_POSTGRES_MIGRATION_PLAN.md`](architecture/SUPABASE_POSTGRES_MIGRATION_PLAN.md)
- [`architecture/WORLD_CLASS_TRADER_FOUNDER_BRIEFING.md`](architecture/WORLD_CLASS_TRADER_FOUNDER_BRIEFING.md)

The core principle is unchanged: AI Trader should optimise for better decisions, not more trades. A recommendation is not actionable unless it can state the strongest argument for, strongest argument against, invalidation, and why doing nothing may be better.

## Supabase/Postgres Production State

AI Trader now supports a controlled first step toward Supabase/Postgres production storage. The Always-On operations evidence tables can use Postgres when the backend is configured with:

```text
AI_TRADER_DATABASE_BACKEND=postgres
DATABASE_URL=<Supabase Postgres connection string>
```

This currently applies to scheduled job runs, worker heartbeats, research funnels, shadow trades, and operations incidents. SQLite remains the default for local development and the wider legacy audit/trading schema. Do not enable separate Render worker or cron services until `/operations-health` reports `database_backend.active_backend = postgres` and `database_durability = supabase_postgres`.

## Autonomous Operations Completion And Render Activation

The latest operations sprint prepares the hosted topology for true phone-independent operation:

- Render API service: Founder HTTP/API surface only.
- Render worker service: broker polling, managed exits, auto-execution evaluation, and learning outbox processing.
- Render cron jobs: equity research, crypto research, daily learning, and daily/weekly/monthly reports.
- Hosted fail-close: production refuses silent SQLite when `AI_TRADER_REQUIRE_POSTGRES_IN_HOSTED=true`.
- API duplicate-loop prevention: set `AI_TRADER_DISABLE_API_BACKGROUND_WORKERS=true` when worker/cron services own background work.

Production activation requires a shared Supabase/Postgres connection string:

```text
AI_TRADER_DATABASE_BACKEND=postgres
DATABASE_URL=<Supabase Postgres connection string>
AI_TRADER_PROCESS_ROLE=render
AI_TRADER_DISABLE_API_BACKGROUND_WORKERS=true
AI_TRADER_REQUIRE_POSTGRES_IN_HOSTED=true
RESEARCH_SCHEDULER_ENABLED=false
```

Start with:

- [`architecture/AUTONOMOUS_OPERATIONS_COMPLETION_REPORT.md`](architecture/AUTONOMOUS_OPERATIONS_COMPLETION_REPORT.md)
- [`architecture/POSTGRES_PRODUCTION_MIGRATION_REPORT.md`](architecture/POSTGRES_PRODUCTION_MIGRATION_REPORT.md)
- [`architecture/RENDER_PRODUCTION_TOPOLOGY.md`](architecture/RENDER_PRODUCTION_TOPOLOGY.md)
- [`architecture/RENDER_DEPLOYMENT_EVIDENCE.md`](architecture/RENDER_DEPLOYMENT_EVIDENCE.md)
- [`architecture/OPEN_RELEASE_GATES.md`](architecture/OPEN_RELEASE_GATES.md)
- [`architecture/FOUNDER_COMPLETION_BRIEFING.md`](architecture/FOUNDER_COMPLETION_BRIEFING.md)

Important boundary: the repository is activation-ready, but hosted autonomy is not production-proven until Render/Supabase deployment evidence is captured.

## Autonomous Activity Screen

The mobile app now includes a primary `Activity` screen and a compact Dashboard card answering:

> What has AI Trader actually done while I was not looking?

The Activity screen is powered by persisted application evidence only. It aggregates worker heartbeats, scheduled jobs, research funnels, decision records, broker trade history, reconciliation cases, learning runs, reports, and incidents into:

- current autonomous status;
- selected-period activity totals;
- chronological activity timeline;
- why-no-trade funnel;
- Alpaca and Kraken broker activity;
- Founder attention items;
- latest completed actions.

New authenticated endpoints:

- `GET /autonomous-activity`
- `GET /activity/status`
- `GET /activity/summary`
- `GET /activity/timeline`
- `GET /activity/why-no-trade`
- `GET /activity/brokers`
- `GET /activity/founder-attention`

Start with:

- [`architecture/AUTONOMOUS_ACTIVITY_ARCHITECTURE.md`](architecture/AUTONOMOUS_ACTIVITY_ARCHITECTURE.md)
- [`architecture/AUTONOMOUS_ACTIVITY_DATA_MAPPING.md`](architecture/AUTONOMOUS_ACTIVITY_DATA_MAPPING.md)
- [`architecture/AUTONOMOUS_ACTIVITY_API.md`](architecture/AUTONOMOUS_ACTIVITY_API.md)
- [`architecture/AUTONOMOUS_ACTIVITY_LIVE_VERIFICATION.md`](architecture/AUTONOMOUS_ACTIVITY_LIVE_VERIFICATION.md)
- [`architecture/FOUNDER_ACTIVITY_SCREEN_GUIDE.md`](architecture/FOUNDER_ACTIVITY_SCREEN_GUIDE.md)

## Developer Setup

The project is configured for local Windows development in VS Code.

1. Clone the repository.
2. Open the folder in VS Code.
3. Run one command:

```powershell
.\start_project.ps1
```

This creates or uses `.venv`, activates it, sets local environment variables, initializes SQLite tables, starts the Local API, and opens the Developer Dashboard.

VS Code is configured by `.vscode/settings.json` to use:

```text
.venv\Scripts\python.exe
```

The previous `python` issue was caused by the Windows Store app execution alias at `C:\Users\t_jeh\AppData\Local\Microsoft\WindowsApps\python.exe`. The project now avoids that global shim by using the local virtual environment.

Run tests:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

## CLI

```powershell
.\.venv\Scripts\python.exe -m ai_trader.cli config
.\.venv\Scripts\python.exe -m ai_trader.cli propose --symbols AAPL,MSFT --demo
.\.venv\Scripts\python.exe -m ai_trader.cli execute --proposals data/proposals.json --demo
.\.venv\Scripts\python.exe -m ai_trader.cli briefing
.\.venv\Scripts\python.exe -m ai_trader.cli run-once --symbols AAPL --demo
.\.venv\Scripts\python.exe -m ai_trader.cli intelligence-init --report
.\.venv\Scripts\python.exe -m ai_trader.cli intelligence-refresh --report
.\.venv\Scripts\python.exe -m ai_trader.cli intelligence-report
.\.venv\Scripts\python.exe -m ai_trader.cli benchmark-init --report
```

`--demo` uses local deterministic market context and a mock broker path for safe end-to-end demonstration. Real order placement requires Alpaca paper credentials and the paper base URL.

Trade lifecycle events are written to SQLite and appended to `governance/TRADING_LOG.md` by default.

## Investment Intelligence Engine

Sprint 2 adds a local SQLite knowledge base for long-term investment research. It keeps Version 1.0 trading frozen and does not redesign the AI Trading Agent, Execution Engine, guardrails, or Trading Journal.

The intelligence tables live in the same SQLite master database:

- `COMPANY_MASTER`
- `COMPANY_FINANCIALS`
- `COMPANY_DAILY_UPDATES`
- `INVESTMENT_WATCHLIST`
- `MARKET_THEMES`

Initialize the curated watchlist and market themes:

```powershell
$env:PYTHONPATH='src'
python -m ai_trader.cli intelligence-init --report
```

Run the daily append-only refresh:

```powershell
$env:PYTHONPATH='src'
python -m ai_trader.cli intelligence-refresh --report
```

The scheduled helper script is `scripts/run_daily_intelligence_refresh.ps1`. To register it as a local Windows Task Scheduler job, run `scripts/register_daily_intelligence_refresh.ps1`. It is local-only and writes to SQLite; it does not use Supabase or cloud storage.

## Sprint 3: Local API and Mobile App

Sprint 3 adds benchmark trader intelligence, a small local HTTP API, and a simple Expo mobile app. The trading engine, execution engine, guardrails, and SQLite storage remain unchanged.

Initialize benchmark intelligence:

```powershell
$env:PYTHONPATH='src'
python -m ai_trader.cli benchmark-init --report
```

Start the local API:

```powershell
scripts/start_local_api.ps1
```

Developer Dashboard:

```powershell
.\start_project.ps1
```

Then open `http://127.0.0.1:8765/developer-dashboard`.

API endpoints:

- `GET /status`
- `GET /portfolio`
- `GET /founder-brief`
- `GET /recommendations`
- `GET /intelligence/companies`
- `GET /intelligence/themes`
- `GET /benchmark-traders`
- `GET /benchmark-daily-brief`
- `POST /run-analysis`
- `POST /start-trading`
- `POST /pause-trading`
- `POST /resume-trading`
- `POST /stop-trading`
- `POST /auto-execute-recommendations`
- `POST /approve-and-execute`
- `POST /run-crypto-analysis`
- `POST /monitor-managed-exits`
- `GET /performance-attribution`
- `GET /daily-learning-update`
- `GET /trading-report`
- `POST /generate-report`
- `GET /notifications`
- `POST /notifications/ack`
- `POST /register-push-token`

Browse SQLite without SQL:

```powershell
scripts/browse_database.ps1
```

This opens a read-only local browser viewer at `http://127.0.0.1:8770`. It lists all tables, supports search, sorting, and record viewing, and exposes no edit controls.

Run the mobile app:

```powershell
scripts/start_mobile_app.ps1
```

For a physical phone, replace `127.0.0.1` with the laptop LAN IP address in `EXPO_PUBLIC_AI_TRADER_API_URL`.

The app has three screens only: Trading Command Centre, AI Recommendations, and Market Intelligence. Missing values are shown as `Not available`. Execution still goes through the existing Execution Engine guardrails.

Recommendation freshness:

- Each recommendation shows when it was generated, when it expires, and whether it is Fresh, Stale, or Expired.
- High-confidence trade ideas expire after 4 hours, medium-confidence ideas after 12 hours, and lower-confidence ideas after 24 hours.
- Expired recommendations are blocked from manual execution until analysis is run again.
- Saved recommendations remain visible in the Recommendations screen for historical reference after app restart.
- Recommendation cards are ordered from highest confidence to lowest confidence.

Auto execution:

- `POST /auto-execute-recommendations` submits only Paper Trading recommendations at or above 85% confidence.
- Auto execution still uses the existing Execution Engine and guardrails.
- Auto execution skips expired recommendations, already executed recommendations, and recommendations that did not pass guardrails.
- Recommendation cards show both passed guardrails and failed guardrails so high confidence is not confused with trade approval.

Mobile controls:

- Broker cards expose broker-specific Enable Auto Trading / Disable Auto Trading controls.
- The global control row is now reserved for Resume All Trading and Emergency Stop All; it is an all-broker safety switch, not the normal way to enable an individual broker.
- The Recommendations screen has Refresh, Run New Analysis, and Auto Execute 85%+ controls.
- Market Intelligence shows theme definitions, drivers, and risks so related themes are easier to understand.
- Market Intelligence also shows monitored companies so sectors/themes can be connected back to the recommendation cards.

## Hosted Backend

The phone app can run without the laptop when the backend runs on an always-on host.

Architecture:

```text
Honor Magic V3 app -> Hosted AI Trader API -> SQLite + Trading Engine + Alpaca/OpenAI
```

The hosted API uses the existing Python trading engine, execution engine, guardrails, knowledge engine, and SQLite schema. It does not move broker keys or execution logic into the phone.

Cloud deployment files:

- `Dockerfile`
- `render.yaml`
- `cloud.env.example`

Recommended first host: Render with a persistent disk mounted at `/data`.

Render setup:

1. Push this repository to GitHub.
2. In Render, create a new Blueprint from `render.yaml`.
3. Add secret environment variables:
   - `AI_TRADER_API_TOKEN`
   - `ALPACA_API_KEY`
   - `ALPACA_SECRET_KEY`
   - `OPENAI_API_KEY`
4. Keep `PAPER_TRADING_ONLY=true` until the hosted app has been tested.
5. Deploy.

The backend exposes:

```text
GET /healthz
GET /status
GET /portfolio
GET /founder-brief
GET /recommendations
GET /intelligence/companies
GET /intelligence/themes
GET /benchmark-traders
GET /benchmark-daily-brief
POST /run-analysis
POST /start-trading
POST /pause-trading
POST /resume-trading
POST /stop-trading
POST /auto-execute-recommendations
POST /approve-and-execute
POST /run-crypto-analysis
POST /monitor-managed-exits
GET /performance-attribution
GET /daily-learning-update
GET /trading-report
POST /generate-report
GET /notifications
POST /notifications/ack
POST /register-push-token
```

## Sprint 4: Investment Orchestrator

Sprint 4 adds an Investment Orchestrator between AI recommendations and broker execution. The AI researches and recommends; the orchestrator decides whether a recommendation is executable.

Core additions:

- Broker adapter interface with `AlpacaBrokerAdapter`.
- Placeholder `InteractiveBrokersAdapter`, `SaxoAdapter`, and `KrakenAdapter` that return not configured until credentials exist.
- `ORCHESTRATOR_DECISIONS`, `AUTO_TRADE_EVENTS`, and `DAILY_BRIEFS` SQLite tables.
- `AUTO_PAPER_TRADING=false` by default.
- Auto paper trading requires confidence >= 85%, philosophy fit >= 85%, paper mode, stop loss, take profit, no short selling, market open, asset availability, and all guardrails.
- Morning and evening brief generators write Markdown and append `DAILY_BRIEFS`.
- `research-once` runs one safe 24/7 research cycle for local or hosted schedulers.
- Render web service starts a safe hourly background research scheduler when `RESEARCH_SCHEDULER_ENABLED=true`.

Render can schedule safe research by invoking the existing `POST /run-analysis` endpoint or by running:

```powershell
.\.venv\Scripts\python.exe -m ai_trader.cli research-once --limit 30
```

Required Sprint 4 environment variables are shown in `.env.example` and `cloud.env.example`.

## Sprint 5: Operational Clarity and Crypto Preparation

Sprint 5 keeps the app to the existing three screens and keeps live stock trading disabled.

- Recommendations now parse qualitative values such as `Good`, `Medium`, `High`, `Low`, `Cautious`, and `Positive` without crashing.
- Portfolio dashboard refreshes append `PORTFOLIO_SNAPSHOTS`.
- Scheduled and manual analysis append `RESEARCH_RUNS`.
- `CRYPTO_ASSET_MASTER` is created for a future public-data crypto universe. The system does not insert dummy rankings when live public rankings are unavailable.
- Kraken and Coinbase adapters are prepared with safe not-configured/disabled states.
- Kraken required permissions: view balances, view open orders/trades, create/cancel orders. Do not grant withdrawal permission.
- Coinbase required permissions: view and trade. Do not grant transfer permission.
- Crypto auto-trade limits are separate from equity limits and default to smaller amounts.
- Command screen now includes an executive summary and exchange selector for All, Alpaca, Kraken, and Coinbase.

When `AI_TRADER_API_TOKEN` is set, the mobile app must send:

```text
Authorization: Bearer <token>
```

Test a hosted API:

```powershell
scripts/test_hosted_api.ps1 -BaseUrl https://trader-no0f.onrender.com -ApiToken YOUR_TOKEN
```

Build a phone APK that points to the hosted backend:

```powershell
cd mobile
npx eas build --platform android --profile hosted-preview
```

Before building, update `mobile/eas.json`:

```json
{
  "EXPO_PUBLIC_AI_TRADER_API_URL": "https://your-hosted-api.example.com",
  "EXPO_PUBLIC_AI_TRADER_API_TOKEN": "your-api-token"
}
```

Important: `EXPO_PUBLIC_*` values are embedded in the app bundle. For a personal app this is acceptable as a first hosted preview, but a stronger production release should add real user login and short-lived tokens.

Current hosted preview backend:

```text
https://trader-no0f.onrender.com
```

Mobile JavaScript changes are published with EAS Update to the `preview` and `hosted-preview` channels after verification. The installed hosted APK should pick up eligible OTA updates on restart.

## Foundation Sprint: Autonomous Investment Platform

The Foundation Sprint establishes Trader as a Founder-governed autonomous investment platform while keeping the existing three-screen app and paper/sandbox safety posture.

Governance documents:

- `governance/INVESTMENT_POLICY_STATEMENT.md`
- `governance/RISK_MANAGEMENT_POLICY.md`
- `governance/BROKER_EXECUTION_POLICY.md`
- `governance/AI_LEARNING_POLICY.md`
- `governance/INVESTMENT_UNIVERSE.md`

New SQLite policy and decision tables:

- `INVESTMENT_POLICIES`
- `RISK_POLICIES`
- `BROKER_POLICIES`
- `LEARNING_POLICIES`
- `CAPITAL_ALLOCATION_HISTORY`
- `DUE_DILIGENCE_ASSESSMENTS`
- `INVESTMENT_SCORES`
- `BROKER_DECISIONS`
- `EXECUTION_DECISIONS`

Crypto knowledge tables:

- `CRYPTO_MASTER`
- `CRYPTO_MARKET_DATA`
- `CRYPTO_DAILY_UPDATES`
- `CRYPTO_PROJECT_ANALYSIS`
- `CRYPTO_TOKENOMICS`
- `CRYPTO_ONCHAIN_METRICS`
- `CRYPTO_SENTIMENT`
- `CRYPTO_RISK`
- `CRYPTO_NEWS`
- `CRYPTO_BENCHMARK_ALIGNMENT`
- `CRYPTO_TRADING_HISTORY`

Execution rule:

```text
AI research -> due diligence -> investment score -> Investment Orchestrator -> broker adapter
```

The Investment Orchestrator is the only autonomous execution gate. It validates governance, due diligence, policy, risk, broker health, asset availability, market status, investment universe, and capital allocation before any paper order can be submitted.

Kraken credentials are read from Render environment variables only:

```text
KRAKEN_API_KEY
KRAKEN_PRIVATE_KEY
KRAKEN_TRADING_ENABLED=false
```

`KRAKEN_API_SECRET` is still accepted as a backward-compatible local alias, but `KRAKEN_PRIVATE_KEY` is the preferred Render name. Withdrawal permissions must never be granted.

## Multi-Broker Autonomous Platform

The Investment Orchestrator is now the central execution authority for all brokers. Each broker has independent auto-trading state stored in SQLite and controlled through the API/mobile app.

Broker-specific auto-trading flags:

```text
ALPACA_AUTO_TRADING=false
KRAKEN_AUTO_TRADING=false
COINBASE_AUTO_TRADING=false
BINANCE_AUTO_TRADING=false
IBKR_AUTO_TRADING=false
```

`AUTO_PAPER_TRADING` remains only as a backward-compatible fallback. New broker controls should use the broker-specific settings or the mobile Command Centre buttons.

New API endpoint:

```text
POST /broker-auto-trading
```

Body:

```json
{
  "broker": "kraken",
  "enabled": true
}
```

Broker runtime and audit tables:

- `BROKER_AUTO_TRADING_SETTINGS`
- `BROKER_RUNTIME_STATE`
- `BROKER_TRADE_HISTORY`
- `NOTIFICATION_EVENTS`
- `RECOMMENDATION_SETS`
- `CRYPTO_RESEARCH_SCORES`

The Command Centre now renders broker panels from backend data. Enabling auto trading for Kraken does not enable Alpaca, Coinbase, Binance, or Interactive Brokers.

Recommendation history is persisted in SQLite through `RECOMMENDATION_SETS`, and the Recommendations screen continues to read saved recommendations from SQLite on open. Recommendation cards are grouped by broker, collapsed by default, sorted by confidence, and filterable by broker, confidence, asset type, and status.

Kraken read integration:

- Validates credentials when present.
- Fetches balances.
- Fetches holdings from balances.
- Fetches open orders.
- Fetches closed orders and trade history.
- Fetches ticker prices through the public API helper.
- Shows authentication failure reasons instead of pretending credentials are absent.

Kraken controlled live micro-trading:

- `KRAKEN_AUTO_TRADING=true` enables Kraken as a broker-specific autonomous entry candidate.
- `KRAKEN_LIVE_TRADING_APPROVED=true` is a separate Founder approval switch required before Kraken can submit real orders.
- `KRAKEN_SUBMIT_REAL_ORDERS=false` keeps Kraken AddOrder in validation mode; set it to `true` only when the Founder wants real spot orders. This is also the default when the variable is unset - an unset value never submits a real order.
- `KRAKEN_TRADING_ALLOCATION_GBP=100` is the AI Trader pot. The app may display the full Kraken account balance for visibility, but risk sizing and Kraken buying power are capped to this allocation and never the whole exchange account.
- `KRAKEN_MAX_ORDER_GBP=5` caps one Kraken order.
- `KRAKEN_MIN_ORDER_GBP=1` prevents invalid tiny orders.
- `KRAKEN_MAX_OPEN_TRADES=1` limits simultaneous Kraken entries.
- `KRAKEN_ALLOWED_PAIRS=XBTGBP,ETHGBP,SOLGBP` restricts trading pairs.

Mechanical live-execution seatbelts:

- duplicate order intent lock before broker submission,
- maximum order amount check,
- minimum order amount check,
- allowed pair check,
- open Kraken order count check,
- GBP balance check for buys,
- stop loss and take profit mandatory,
- broker submission confirmation,
- managed exit record after entry,
- `POST /monitor-managed-exits` checks open managed exits and submits the protective exit when stop loss or take profit is hit,
- notification events are queued for trade accepted, stop loss, take profit, and exit submission.

Disabling Kraken auto trading stops new entries. Existing managed exits remain eligible for protective exit submission.

## Autonomous Trading Readiness Sprint

This sprint made continuous autonomous operation actually continuous, not manual-demand-only, and closed the gaps identified in the Go-Live Readiness Review. Full detail: `governance/IMPLEMENTATION_LOG.md` and `STATUS.md`.

- The Investment Orchestrator is now the only execution path, including manual approvals (`POST /approve-and-execute`) - no code calls a broker adapter's `place_order`/`place_bracket_order` outside of it.
- `POST /monitor-managed-exits` and broker order/fill polling now also run automatically every 60 seconds from `run-api`/`serve-api`, independent of manual calls or `RESEARCH_SCHEDULER_ENABLED`.
- Daily, weekly, and monthly loss limits, a maximum drawdown check, and portfolio-level exposure limits are enforced from real portfolio snapshot history before every autonomous or manually-approved trade.
- A background research/monitoring loop that raises an exception now logs it, fires a notification, and keeps running on its next scheduled cycle - it does not stop permanently.
- Trailing stops are supported for Kraken managed exits, governed by `RISK_POLICIES.trailing_stop_enabled` and `RISK_POLICIES.trailing_stop_pct` (no hardcoded distance).
- Due diligence and investment scoring no longer floor macro/behavioural factors when there is no real data behind them - a symbol without a matching market theme, benchmark research entry, or crypto research score is honestly marked `insufficient_data` and scored `0.0`, not waved through.
- The crypto knowledge engine fetches CoinGecko's live market-cap, AI, and privacy/security category data on a schedule, populates `CRYPTO_MASTER` (previously empty, which silently blocked every crypto trade), and computes real technical/momentum/volatility/liquidity scores. On-chain, sentiment, and news data are not available without a paid provider and are left `insufficient_data` rather than fabricated.
- Kraken can now generate its own trade proposals from that research (`POST /run-crypto-analysis`) and route them through the same orchestrator, guardrail, and auto-execute path as equities - previously nothing in the codebase ever produced a crypto trade proposal.
- Every closed managed exit records a `PERFORMANCE_ATTRIBUTION` row: entry/exit price, P&L, holding period, and the reasoning that justified entry, queryable at `GET /performance-attribution`.
- `GET /daily-learning-update` summarises yesterday's closed trades, wins/losses, guardrail rejections, benchmark trader observations, and recommendations for Founder approval. It learns from AI Trader's own outcomes and public benchmark/successful-trader observations where available, but it does not copy trades or change guardrails automatically.
- `POST /generate-report` creates an on-demand daily, morning, or evening report for all brokers or a selected broker. The mobile Command Centre exposes Today Report, Yesterday Report, Morning Report, Evening Report, and per-broker Daily Report buttons. Reports explain P&L movement using portfolio snapshots, closed trades, broker trade history, orchestrator rejections, and learning notes.
- Each generated report is saved as Markdown under the backend output folder's `reports/` directory, stored in SQLite table `TRADING_REPORTS`, and exposed as a browser page at `/reports/{report_id}`. The mobile app opens that browser page automatically and also shows an `Open Report` button.
- Daily, morning, evening, weekly, and monthly reports share the same performance-review structure: report window, start/end balances, period performance, every closed trade with entry/exit/times/P&L, broker trade rows, why money was won or lost, lessons learned, and recommendations for Founder approval.
- Reports also reconstruct broker-fill P&L where possible by FIFO-matching buy and sell fills. If a fill cannot be matched inside the report window, it is shown as an open/unmatched lot so open or unrealised P&L is not mistaken for a completed losing trade.
- The mobile Command Centre shows trade history as collapsed rows. Tap a trade to see entry, exit, quantity, P&L, reasons, and broker payload; tap it again to collapse.
- `GET /notifications` / `POST /notifications/ack` back an in-app notification center; `POST /register-push-token` plus a background dispatcher deliver high-priority events (stop-loss, take-profit, broker/research failures) through Expo's push service. The backend is ready; the mobile client does not yet register a device token (needs `expo-notifications` added and a rebuilt app to verify end-to-end).
- On a non-loopback host (e.g. Render), if `AI_TRADER_API_TOKEN` is missing the API starts in hosted read-only mode: GET status/recommendation screens stay available, but all POST trading/control commands are rejected until the token is configured. Token checks use constant-time comparison and a source IP is locked out after repeated auth failures.

## Install On Honor Magic V3

Android preview build:

```text
https://expo.dev/artifacts/eas/1LZ_09cZkatp7D8bR09MlBl1KnR6ZcKQN7M-CU7nnQc.apk
```

Before opening the app on the phone:

1. Keep the laptop and Honor Magic V3 on the same WiFi network.
2. Start the local API on the laptop:

```powershell
scripts/start_local_api.ps1
```

3. Confirm the phone-facing API URL is reachable from the laptop:

```powershell
Invoke-WebRequest -UseBasicParsing http://192.168.0.142:8765/status
```

4. Open the APK link on the Honor Magic V3 and allow Android to install from the browser if prompted.
5. Open AI Trader.

This preview build embeds:

```text
EXPO_PUBLIC_AI_TRADER_API_URL=http://192.168.0.142:8765
```

If the laptop IP changes, update `mobile/eas.json`, rebuild with `npx eas build --platform android --profile preview`, and install the new APK.

## Troubleshooting

- If plain `python` fails in a fresh terminal, activate the venv first: `. .\.venv\Scripts\Activate.ps1`.
- If VS Code does not select the venv, run `Python: Select Interpreter` and choose `.venv\Scripts\python.exe`.
- If PowerShell blocks activation, run: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.
- If the mobile app cannot reach the API from a physical phone, use the laptop LAN IP in `EXPO_PUBLIC_AI_TRADER_API_URL`.
- If Expo dependencies are missing, run `npm install` from `mobile/`.
