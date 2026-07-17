# Module Reference

## Top-Level Folders

| Folder | Purpose | Owner |
|---|---|---|
| `src/ai_trader` | Python backend package: API, orchestration, research, broker integrations, persistence helpers. | Backend/Platform |
| `mobile` | Expo React Native mobile app. | Mobile/Product |
| `governance` | Founder-approved governance, policy, implementation, and validation documents. | Founder/CTO |
| `data` | Local runtime output: SQLite database, reports, logs, generated briefs. Hosted runtime uses Render disk. | Runtime |
| `scripts` | Developer and operations helper scripts. | DevOps |
| `tests` | Unit and integration tests for current backend behavior. | Engineering |
| `architecture` | CTO handover documentation. | CTO |

## Backend Modules

| Module | Purpose |
|---|---|
| `api.py` | Hosted/local HTTP API, service facade, route handling, report generation, broker polling, Ask AI, scheduler startup. |
| `cli.py` | Command-line entrypoint for configuration, proposing, execution, briefing, intelligence, benchmark, and server commands. |
| `config.py` | Environment loading and typed settings. Reads Alpaca, OpenAI, database, Render, scheduler, and risk variables. |
| `models.py` | Domain dataclasses including trade proposals, account context, positions, auto-trade config, guardrail config, and orchestrator decision. |
| `agent.py` | AI Trading Agent and crypto proposal creation helpers. Produces proposals but does not execute trades. |
| `ai.py` | OpenAI integration for proposal analysis and read-only Ask AI explanations. |
| `alpaca.py` | Alpaca paper/data API client. Handles account, positions, orders, and market data calls. |
| `broker_adapters.py` | Broker adapter protocol and concrete adapters for Alpaca, Kraken, Coinbase placeholder, Interactive Brokers placeholder, and Saxo placeholder. |
| `orchestrator.py` | Deterministic Investment Orchestrator. Selects broker, validates, allocates capital, locks order intent, submits approved orders. |
| `guardrails.py` | Base trade proposal guardrail validation. |
| `execution.py` | Earlier deterministic execution engine path for proposal execution. Maintained for tests and compatibility. |
| `audit.py` | Core audit database tables and trading journal append behavior. |
| `foundation.py` | Investment/risk/broker/learning policy tables, due diligence, investment scoring, capital allocation, universe validation. |
| `multi_broker.py` | Multi-broker runtime state, auto-trading settings, trade history, notifications, recommendation sets, crypto scores, managed exits, push tokens, attribution, seatbelt events. |
| `operational.py` | Portfolio snapshots, research runs, crypto asset universe seeding, P&L snapshot calculation, display helpers. |
| `intelligence.py` | Investment intelligence database for company master, financials, daily updates, watchlist, and themes. |
| `intelligence_data.py` | Seed data for companies and market themes. |
| `benchmark.py` | Benchmark trader intelligence database and reporting. |
| `benchmark_data.py` | Seed data for benchmark traders and daily research lessons. |
| `briefing.py` | Daily founder briefing generation. |
| `scheduler.py` | Research scheduler and generic interval worker. |
| `proposals.py` | Proposal persistence/loading helpers. |
| `db_browser.py` | Lightweight SQLite browser server for local inspection. |

## Mobile Modules

| File | Purpose |
|---|---|
| `mobile/App.js` | Main React Native app. Contains navigation tabs, API client, Command screen, Trade History, Recommendations, Intelligence, and Ask UI. |
| `mobile/app.json` | Expo app identity, icon, splash, Android package, EAS project, OTA update URL. |
| `mobile/eas.json` | EAS build profiles. |
| `mobile/package.json` | Mobile dependencies and Expo scripts. |
| `mobile/plugins/with-cleartext-traffic.js` | Android cleartext plugin for local development API access. |
| `mobile/assets/*` | App icon, adaptive icon, and splash image. |

## Scripts

| Script | Purpose |
|---|---|
| `start_project.ps1` | Local development bootstrap. Creates/uses virtual environment, starts local services/dashboard. |
| `scripts/start_local_api.ps1` | Starts local backend API. |
| `scripts/start_mobile_app.ps1` | Starts Expo mobile app workflow. |
| `scripts/test_hosted_api.ps1` | Hosted API smoke testing. |
| `scripts/browse_database.ps1` | Starts local database browser. |
| `scripts/run_daily_intelligence_refresh.ps1` | Runs daily intelligence refresh. |
| `scripts/register_daily_intelligence_refresh.ps1` | Registers local Windows scheduled task for intelligence refresh. |
| `scripts/configure_control_token.ps1` | Helps configure command token values. |

## Deployment Files

| File | Purpose |
|---|---|
| `Dockerfile` | Container build for Render API service. |
| `render.yaml` | Render service, disk, health check, and environment variable declarations. |
| `pyproject.toml` | Python package metadata and dependencies. |
| `.env.example` | Local environment template. |
| `cloud.env.example` | Cloud deployment environment template. |

## Ownership Boundaries

The core ownership boundary is:

- `agent.py` and `ai.py` may reason.
- `orchestrator.py`, `guardrails.py`, and `foundation.py` decide whether execution is allowed.
- `broker_adapters.py` performs broker calls.
- `audit.py`, `multi_broker.py`, and `operational.py` record events.
- `mobile/App.js` displays state and sends commands; it does not own business rules.
