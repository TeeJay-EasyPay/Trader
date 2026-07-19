# Implementation Log

## 2026-07-18 Sprint 6 - Institutional Production Control Layer

- Reviewed Sprint 6 requirements and current Phase 5, Always-On, Operational Truth, Portfolio Intelligence, Market Intelligence, Experience Engine, API and mobile Dashboard integration points.
- Added `src/ai_trader/sprint6.py`.
- Added Sprint 6 schema tables:
  - `OPERATIONAL_EVENTS`
  - `DECISION_JOURNAL`
  - `STRATEGY_MATURITY_REGISTRY`
  - `STRATEGY_ENTITLEMENT_DECISIONS`
  - `PRODUCTION_RISK_SENTINEL_DECISIONS`
  - `KILL_SWITCH_STATE`
  - `SPRINT6_WORKFLOW_OUTBOX`
  - `BROKER_EVENT_MAPPINGS`
  - `INCIDENT_LIFECYCLE`
  - `FOUNDER_OPERATIONAL_REPORTS`
- Seeded a conservative default strategy registry entry:
  - strategy ID: `current_recommendation_process`
  - stage: `Paper`
  - permitted modes: `shadow`, `paper`, `manual`
  - not permitted by default: `micro_live`, `production`
- Wired mandatory Sprint 6 pre-execution decision packets into:
  - `approve_and_execute`
  - `auto_execute_recommendations`
- The pre-execution packet records:
  - Portfolio Manager decision
  - strategy entitlement decision
  - Production Risk Sentinel decision
  - strongest argument for
  - strongest argument against
  - market data quality label
  - final eligibility
- Broker polling now:
  - records broker polling incidents on failure;
  - normalizes broker events into `BROKER_EVENT_MAPPINGS`;
  - passes normalized rows into canonical reconciliation;
  - queues terminal rows into the closed-loop learning outbox idempotently.
- Research cycles now record Sprint 6 operational events.
- Added API endpoints:
  - `GET /sprint6-status`
  - `GET /operational-events`
  - `GET /decision-journal`
  - `POST /generate-operational-report`
- Added `sprint6_status` to `/status`.
- Added the mobile Dashboard `Sprint 6 Production Control` card.
- Added focused tests in `tests/test_sprint6_institutional_spine.py`.
- Created Sprint 6 architecture documents:
  - `architecture/SPRINT_6_IMPLEMENTATION_REPORT.md`
  - `architecture/INSTITUTIONAL_PRODUCTION_ARCHITECTURE.md`
  - `architecture/POSTGRES_RUNTIME_MIGRATION_REPORT.md`
  - `architecture/BROKER_RECONCILIATION_STANDARD.md`
  - `architecture/ALPACA_RECONCILIATION_CONTRACT.md`
  - `architecture/KRAKEN_RECONCILIATION_CONTRACT.md`
  - `architecture/STRATEGY_MATURITY_AND_ENTITLEMENT.md`
  - `architecture/PRODUCTION_RISK_SENTINEL.md`
  - `architecture/MARKET_DATA_AND_RESEARCH_FRESHNESS_STANDARD.md`
  - `architecture/AUTONOMOUS_LEARNING_WORKFLOW.md`
  - `architecture/RENDER_PRODUCTION_VERIFICATION.md`
  - `architecture/AUTONOMOUS_QUALIFICATION_REPORT.md`
  - `architecture/NEXT_STAGE_RECOMMENDATIONS.md`
  - `architecture/FOUNDER_BRIEFING_SPRINT_6.md`
- Verification completed so far:
  - `python -m compileall src` passed.
  - `python -m unittest tests.test_sprint6_institutional_spine` passed.
  - `python -m unittest discover -s tests` passed.
  - `npx expo-doctor` passed.
- Safety note: Sprint 6 does not increase capital, promote strategies, bypass the Investment Orchestrator, bypass the Risk Engine, weaken Kraken controls, or allow Ask AI Trader to trade.

## 2026-07-18 Phase 5 - Autonomous Production Spine and Closed-Loop Learning Foundation

- Reviewed the current governance, architecture, implementation history, Operational Truth, Experience Engine, Portfolio Intelligence, Market Intelligence, and Always-On Operations implementation before changing code.
- Added `src/ai_trader/production_spine.py`.
- Added Phase 5 schema tables:
  - `PRODUCTION_SPINE_SNAPSHOTS`
  - `WORKER_SUPERVISION_RUNS`
  - `CANONICAL_RECONCILIATION_CASES`
  - `CLOSED_LOOP_LEARNING_RUNS`
  - `PORTFOLIO_MANAGER_DECISIONS`
  - `MARKET_DATA_GATEWAY_RUNS`
  - `STRATEGY_PROMOTION_DECISIONS`
- Added deterministic functions for:
  - production database spine readiness;
  - worker supervision and stale-worker incident creation;
  - idempotent broker event reconciliation into logical trades;
  - idempotent closed-loop learning;
  - Portfolio Manager approve/approve-smaller/wait/reject/manual-review decisions;
  - Market Data Gateway quality blocking;
  - strategy promotion and demotion evidence gates.
- Added API support:
  - `GET /phase5-status`
  - `phase5_status` inside `GET /status`
- Added the mobile Dashboard `Autonomous Production Spine` card.
- Added focused tests in `tests/test_phase5_production_spine.py`.
- Created Phase 5 architecture documents:
  - `architecture/PHASE_5_IMPLEMENTATION_REPORT.md`
  - `architecture/AUTONOMOUS_PRODUCTION_SPINE.md`
  - `architecture/CANONICAL_RECONCILIATION_DESIGN.md`
  - `architecture/CLOSED_LOOP_LEARNING_ARCHITECTURE.md`
  - `architecture/DATABASE_ARCHITECTURE.md`
  - `architecture/TEST_RESULTS.md`
  - `architecture/KNOWN_LIMITATIONS.md`
  - `architecture/NEXT_PHASE_RECOMMENDATIONS.md`
  - `architecture/FOUNDER_BRIEFING.md`
- Verification:
  - `python -m compileall src` passed.
  - `python -m unittest tests.test_phase5_production_spine` passed.
  - `python -m unittest tests.test_always_on_operations` passed.
- Safety note: this phase does not enable trading, weaken guardrails, change broker permissions, or silently promote strategies. It adds evidence gates and readiness visibility.

## 2026-07-02

- Reviewed repository contents.
- No existing project governance documents were present.
- Created governance baseline before implementation:
  - Architecture Design Document
  - Implementation Plan
  - Decision Register
  - Implementation Log
- Began Version 1 implementation using a compact Python command-line architecture.
- Implemented shared trade proposal models, guardrail validation, SQLite audit storage, Alpaca paper client, optional OpenAI proposal analyzer, AI Trading Agent, Execution Engine, CLI, daily briefing generator, and unit tests.
- Added local mock end-to-end demonstration path using `--demo`.
- Attempted to run `python -m unittest discover -s tests`, but the local Windows Python shim failed to launch with: "A specified logon session does not exist. It may already have been terminated." No callable `py`, `pip`, or `uv` runtime was available in this environment.
- Ran `git diff --check` successfully.
- Added `governance/TRADING_LOG.md` as the append-only human-readable trading ledger.
- Updated audit writes so trade proposal and execution lifecycle events append to the trading log when `AI_TRADER_TRADING_LOG_PATH` is configured.

## 2026-07-02 Validation Sprint

- Installed Python 3.12.10 because the machine only exposed a broken Microsoft Store Python launcher shim.
- Installed missing `tzdata==2026.2` dependency required for `zoneinfo` on Windows.
- Added `tzdata>=2026.2` to `pyproject.toml`.
- Ran unit tests; initial run failed because SQLite database files were still held open on Windows during temporary directory cleanup.
- Fixed `AuditDatabase` to explicitly close SQLite connections.
- Re-ran unit tests successfully: 4 tests passed.
- Verified `.env` was present but not loaded by the application.
- Added standard-library `.env` loading in `src/ai_trader/config.py`.
- Verified safe config output reported Alpaca credentials present.
- Connected to Alpaca Paper Trading successfully.
- Retrieved account information successfully: status `ACTIVE`, currency `USD`, equity `100000`, buying power `400000`.
- Retrieved current positions successfully: 0 open positions.
- Attempted to generate one real AI trade proposal.
- Validation stopped at proposal generation because the OpenAI Responses API returned HTTP 401 Unauthorized for the configured `OPENAI_API_KEY`.
- Created validation report: `governance/VALIDATION_REPORT_2026-07-02.md`.
- Updated project status: `STATUS.md`.

## 2026-07-02 Validation Sprint Resume

- Confirmed updated OpenAI API key worked against the OpenAI Responses API using `OPENAI_MODEL=gpt-4.1-mini`.
- Resumed validation from step 9 instead of rerunning completed setup, unit, config, and Alpaca connectivity checks.
- First resumed AI proposal was generated but correctly rejected by guardrails because `confidence_score` was below `MIN_CONFIDENCE_SCORE=0.85` and `risk_percentage` was returned as `1.0` instead of decimal `0.01`.
- Root cause: the OpenAI proposal prompt did not include the configured guardrail thresholds or the decimal risk contract.
- Fixed only that issue by passing `GuardrailConfig` into `OpenAIProposalAnalyzer` and adding the configured confidence, risk, open-position, and stop/take-profit constraints to the prompt.
- Re-ran the failed step onward and generated a valid AAPL proposal:
  - Proposal ID: `581de766-62ff-4d16-9e7e-6b27407c29b0`
  - Entry: `298.96`
  - Stop loss: `296.96`
  - Take profit: `305.96`
  - Position size: `333`
  - Risk percentage: `0.01`
  - Confidence score: `0.87`
- Execution Engine independently validated the proposal successfully.
- Submitted an Alpaca Paper Trading bracket order successfully.
- Confirmed Alpaca parent order `94de407a-8a6d-42ab-a991-de938ef27e6e` appeared and filled; bracket exit orders were present.
- Confirmed SQLite audit rows for `agent_proposal` and `execution_approved`.
- Confirmed `governance/TRADING_LOG.md` contains the successful proposal and execution entries.
- Generated Founder Brief: `data/founder_briefing_2026-07-02.md`.
- Updated project status and validation report with final passed results.

## 2026-07-02 Sprint 2 - Investment Intelligence Engine

- Treated Version 1.0 trading architecture as frozen.
- Did not redesign the AI Trading Agent.
- Did not redesign the Execution Engine.
- Did not modify the trading pipeline or Trading Journal.
- Continued using the existing local SQLite master database.
- Added `src/ai_trader/intelligence.py` with schema management, initial seeding, append-only daily refresh, and report generation.
- Added `src/ai_trader/intelligence_data.py` with an initial curated watchlist and market themes based on publicly available company/theme information.
- Created SQLite tables:
  - `COMPANY_MASTER`
  - `COMPANY_FINANCIALS`
  - `COMPANY_DAILY_UPDATES`
  - `INVESTMENT_WATCHLIST`
  - `MARKET_THEMES`
- Seeded 31 watchlist companies across precious metals, gold, silver, copper, mining, infrastructure, construction, utilities, clean energy, healthcare, airlines, and sports.
- Prioritised the United Kingdom, Europe, Asia, and Africa; avoided North American companies in the initial seed.
- Seeded 10 market themes:
  - Gold
  - Silver
  - Copper
  - Rare Earths
  - Construction
  - Clean Energy
  - Healthcare
  - Airlines
  - Infrastructure
  - Utilities
- Left unverified financial metrics as `NULL` placeholders rather than fabricating data.
- Added CLI commands:
  - `intelligence-init`
  - `intelligence-refresh`
  - `intelligence-report`
- Added local scheduled refresh helpers:
  - `scripts/run_daily_intelligence_refresh.ps1`
  - `scripts/register_daily_intelligence_refresh.ps1`
- Added schema documentation: `governance/INVESTMENT_INTELLIGENCE_SCHEMA.md`.
- Added Knowledge Engine Report: `governance/KNOWLEDGE_ENGINE_REPORT.md`.
- Generated data report: `data/INVESTMENT_INTELLIGENCE_ENGINE_REPORT.md`.
- Updated `README.md` with a short Investment Intelligence Engine section.
- Updated `STATUS.md` with Sprint 2 results.
- Added intelligence tests for initial seeding and append-only refresh behavior.
- Ran unit tests successfully: 6 tests passed.

## 2026-07-02 Sprint 3 - Mobile App and Benchmark Intelligence

- Treated Version 1.0 trading architecture, Execution Engine, guardrails, and SQLite storage as frozen.
- Added benchmark intelligence schema management in `src/ai_trader/benchmark.py`.
- Added public-information-only benchmark seed data in `src/ai_trader/benchmark_data.py`.
- Created SQLite tables:
  - `BENCHMARK_TRADERS`
  - `BENCHMARK_DAILY_RESEARCH`
- Left unavailable performance notes, drawdown notes, and consistency scores as `NULL`.
- Added benchmark schema documentation: `governance/BENCHMARK_INTELLIGENCE_SCHEMA.md`.
- Added benchmark initialization command: `benchmark-init`.
- Added small local HTTP API in `src/ai_trader/api.py`.
- Added API command: `serve-api`.
- Added local engine control state table for pause/resume/stop commands.
- Added guarded `approve-and-execute` endpoint that uses stored SQLite proposals and the existing Execution Engine.
- Added Expo app under `mobile/` with exactly three screens:
  - Trading Command Centre
  - AI Recommendations
  - Market Intelligence
- Added API/mobile run instructions to `README.md`.
- Added local run helpers: `scripts/start_local_api.ps1` and `scripts/start_mobile_app.ps1`.
- Added tests for benchmark seeding and API missing-data behavior.
- Ran unit tests successfully with installed Python 3.12 interpreter: 8 tests passed.
- Ran `benchmark-init --report`, seeding 4 monitored benchmark traders and 4 append-only research rows.
- Smoke-checked the local API service object: `/status` returned `running` and `/benchmark-traders` returned 4 rows.

## 2026-07-02 Sprint 3.1 - Developer Experience

- Investigated the broken `python` command.
- Confirmed `python` resolved to the Windows Store app execution alias at `C:\Users\t_jeh\AppData\Local\Microsoft\WindowsApps\python.exe`.
- Confirmed `py` was not available on PATH.
- Confirmed the real working interpreter is Python 3.12.10 at `C:\Users\t_jeh\AppData\Local\Programs\Python\Python312\python.exe`.
- Created local `.venv`.
- Installed the project into `.venv` with editable packaging and `tzdata`.
- Added VS Code workspace settings to select `.venv\Scripts\python.exe` automatically.
- Added VS Code tasks for project startup and Python tests.
- Added `start_project.ps1` for one-command startup.
- Updated `scripts/start_local_api.ps1` to use `.venv` and display API/dashboard URLs.
- Updated `scripts/start_mobile_app.ps1` to check Node/npm, install missing dependencies, check API availability, and start Expo with QR code output.
- Added `scripts/browse_database.ps1`.
- Added `src/ai_trader/db_browser.py`, a read-only local browser-based SQLite viewer with table listing, search, sorting, and record viewing.
- Added API Developer Dashboard endpoints:
  - `/developer-dashboard`
  - `/developer-status`
- Added root `developer_dashboard.html` launcher.
- Added `mobile/node_modules/` to `.gitignore`.
- Verified `.venv\Scripts\python.exe --version`: Python 3.12.10.
- Verified activated venv makes plain `python --version` return Python 3.12.10.
- Added developer experience tests for dashboard status and read-only database browsing.
- Ran tests in `.venv`: 10/10 passing.
- Verified CLI config runs in `.venv`.
- Verified Developer Dashboard status generation reports Python as Healthy.
- Verified read-only SQLite browser can list 11 tables.

## 2026-07-02 Hosted Backend Path

- Kept trading engine, execution engine, knowledge engine, and mobile UI logic intact.
- Added optional API-token authorization to the Python API for hosted deployment.
- Added unauthenticated `/healthz` for cloud health checks.
- Added Docker packaging for the existing Python backend.
- Added Render blueprint with persistent `/data` disk for SQLite.
- Added `cloud.env.example` for hosted environment variables.
- Added `scripts/test_hosted_api.ps1` to verify hosted API status, Paper mode, watchlist, themes, and benchmark trader counts.
- Updated the mobile app to send `Authorization: Bearer <token>` when `EXPO_PUBLIC_AI_TRADER_API_TOKEN` is configured.
- Added `hosted-preview` EAS build profile.
- Updated README and STATUS with hosted backend deployment instructions.
- Added tests for `/healthz` and API token authorization.
- Ran tests in `.venv`: 12/12 passing.
- Verified local token-auth smoke test: health check public, protected API rejects missing token, bearer token succeeds.
- Docker CLI was not available locally, so container build verification remains for the cloud host or a machine with Docker installed.

## 2026-07-02 Sprint 3.2 - Mobile Trading Usability

- Kept the trading engine, execution engine, knowledge engine, SQLite storage, and three-screen mobile structure intact.
- Added recommendation freshness metadata to the API:
  - `created_at`
  - `expires_at`
  - `freshness_status`
  - `freshness_note`
- Added expiry rules:
  - 85%+ confidence: 4-hour trade idea lifetime.
  - 75%-84% confidence: 12-hour trade idea lifetime.
  - Lower confidence: 24-hour trade idea lifetime.
- Blocked manual execution when a recommendation has expired.
- Added paper-only auto execution endpoint: `POST /auto-execute-recommendations`.
- Auto execution only considers recommendations at or above 85% confidence and still sends every proposal through the existing Execution Engine guardrails.
- Added `POST /start-trading` as the simpler mobile control while keeping existing pause/resume endpoints for compatibility.
- Enriched `/status` with recent transactions and recommendation summary counts.
- Enriched `/portfolio` with recent Alpaca orders and fill activities when Alpaca credentials are configured.
- Updated mobile Command Centre:
  - Start Trading and Stop Trading controls.
  - Recent Transactions section.
  - Active/expired recommendation counts.
  - Auto Trade Mode.
- Updated mobile Recommendations:
  - Refresh button.
  - Run New Analysis button.
  - Auto Execute 85%+ button.
  - Freshness, generated time, expiry time, and auto eligibility display.
  - Expired recommendations show as blocked.
- Updated mobile Market Intelligence to show theme definitions, key drivers, and key risks from SQLite.
- Added tests for recommendation freshness metadata and expired-recommendation execution blocking.
- Ran tests in `.venv`: 14/14 passing.

## 2026-07-02 Sprint 3.2 - EAS OTA Update

- Ran `npx eas update --branch preview --message "Sprint 3.2 mobile trading usability"`.
- EAS installed and configured `expo-updates`.
- EAS configured `updates.url` to `https://u.expo.dev/58ca35af-2cf4-44a0-8da4-7f02563b635f`.
- EAS configured `runtimeVersion` with the `appVersion` policy.
- Published update group `0727fd0a-4216-413c-affa-5c712cbc1155`.
- Published Android update `019f2473-739d-78e5-849e-99092758dd78`.
- EAS dashboard: `https://expo.dev/accounts/nexuspay/projects/ai-trader-mobile/updates/0727fd0a-4216-413c-affa-5c712cbc1155`.
- Added `mobile/dist/` to `.gitignore` because EAS Update creates it during export.
- Verified Expo Doctor after the OTA configuration: 17/17 checks passed.
- Note: the previously installed APK may not receive OTA updates because `expo-updates` was configured during this publish. Builds made after this configuration are eligible for EAS Updates.
- Added `channel: preview` to the EAS `preview` and `hosted-preview` build profiles.
- Built a fresh Android preview APK after OTA channel configuration.
- Build ID: `d5ff21b3-6685-4940-a2d4-550cd0d9e984`.
- APK: `https://expo.dev/artifacts/eas/c3aEW5gWWhVHVim0Mk2fwTGnRl7aCKosQkpYnC6n9VQ.apk`.

## 2026-07-03 Mobile UX Follow-Up

- Confirmed the installed APK had the new UI but was calling a stale local API process.
- Restarted the local API so `/start-trading` and `/auto-execute-recommendations` are available.
- Verified `/start-trading` returns `running`.
- Verified `/auto-execute-recommendations` no longer returns `not_found`.
- Confirmed `0.87` confidence means 87%; auto-trade was skipped because execution guardrails did not pass, not because of decimal confidence format.
- Added `auto_trade_reason` to recommendation API rows.
- Updated mobile cards to show:
  - readable generated/expiry timestamps,
  - confidence as percentages,
  - guardrail pass status,
  - auto-trade eligibility reason.
- Added pull-to-refresh to the main scroll view so each screen can be refreshed by dragging down.
- Improved recent transaction wording for non-technical users.
- Added fallback from `/start-trading` to `/resume-trading` for older API processes.
- Published EAS OTA update:
  - Branch: `preview`.
  - Update group ID: `c4e78a76-6233-48aa-a2ee-85ce3223007e`.
  - Android update ID: `019f2657-bc70-7c6f-9e33-91ef6e217fc1`.
  - Dashboard: `https://expo.dev/accounts/nexuspay/projects/ai-trader-mobile/updates/c4e78a76-6233-48aa-a2ee-85ce3223007e`.
- Verification:
  - Python tests: 14/14 passing.
  - Python compile check passed.
  - Expo Doctor: 17/17 checks passed.

## 2026-07-03 Hosted APK Build

- Separated `hosted-preview` from the laptop `preview` OTA channel.
- Removed the placeholder public API token from the hosted mobile build profile.
- Built hosted Android APK with initial backend URL `https://ai-trader-api.onrender.com`.
- Build ID: `7e6b53a3-d492-4594-af36-4e56199878d4`.
- APK: `https://expo.dev/artifacts/eas/s2G1DWe4aWyNiBCH7S1bJgXYmhoq8f8gSE3D6UQfe5U.apk`.
- Published hosted OTA update to branch `hosted-preview`.
- Hosted OTA update group ID: `f9a4c794-8305-47d2-83a1-99fb5b777057`.
- Hosted Android update ID: `019f2669-3a99-765d-99f1-d747aff4f9db`.
- User created Render service at `https://trader-no0f.onrender.com`.
- Updated hosted mobile build config to use `https://trader-no0f.onrender.com`.
- Verified Render `/healthz`, `/status`, `/portfolio`, `/recommendations`, and `/intelligence/themes`.
- Published hosted OTA update to point the installed hosted app at `https://trader-no0f.onrender.com`.
- Hosted OTA update group ID: `bc319f3f-0bba-48fd-992a-30601f92c2d5`.
- Hosted Android update ID: `019f27ac-1393-79d5-b822-fa82ee3cfe37`.
- Render recommendations currently return an empty list because the cloud SQLite database has no generated proposals yet.

## 2026-07-03 Remove Laptop API URL From Preview Channels

- Updated `mobile/eas.json` so the `preview` build profile also uses `https://trader-no0f.onrender.com`.
- Updated mobile error copy from "Local API unavailable" to "Backend unavailable" and included the active API URL in the alert.
- Updated the app header fallback text to show the backend host.
- Published OTA to `preview`:
  - Update group ID: `dd05b9df-40bd-43c9-99eb-7dd3d129e24b`.
  - Android update ID: `019f27b7-de37-7fb0-97b6-d397fe7d2058`.
- Published OTA to `hosted-preview`:
  - Update group ID: `895a6212-1e33-404f-8437-61ddf553adab`.
  - Android update ID: `019f27b8-c67a-797e-8feb-19d810b71283`.
- Verified `https://trader-no0f.onrender.com/healthz` returned 200 before publishing.

## 2026-07-03 Hosted Analysis and Activity Follow-Up

- Fixed mobile JSON parsing so empty or non-JSON backend responses produce a readable app error instead of `JSON Parse error`.
- Changed mobile Run Analysis to request the 30-company watchlist scan.
- Added clearer mobile messaging when analysis completes but no safe recommendations are generated.
- Added Alpaca broker orders/fills from `/portfolio` into the mobile Command Centre Recent Transactions section.
- Changed backend `/run-analysis` to scan symbols independently so one broker-rejected symbol does not fail the full analysis.
- Added `skipped_symbols` to the analysis response.
- Added `analysis_completed` events so the app can show that an analysis ran even if no recommendation was created.
- Verified Render `/run-analysis` with `AAPL` succeeds.
- Verified Render `/run-analysis` with `AAPL` and `NOVO-B` returns 200 and lists `NOVO-B` in `skipped_symbols`.
- Published OTA to `preview`: `da0f2e4d-8ecc-4fff-b026-1693ca3ca139`.
- Published OTA to `hosted-preview`: `b6ae021d-9936-4003-972f-b719f79fb4b1`.

## 2026-07-03 Guardrail Positives Follow-Up

- Added a backend `guardrail_checks` checklist to each recommendation so the app can show passed checks and failed checks from the same validation result.
- Added `guardrail_passes` to recommendation API rows for a simple positive guardrail summary.
- Updated mobile recommendation cards to show:
  - overall guardrail result,
  - passed guardrails,
  - failed guardrails.
- Kept the trading engine, execution engine, guardrail logic, and SQLite storage unchanged.
- Verified Python tests: 16/16 passing.
- Published OTA to `preview`: `bd26298e-5373-4c20-8319-b18f52135adc`.
- Published OTA to `hosted-preview`: `2b920796-6648-4c8f-acb7-e2088213c4f0`.

## 2026-07-03 Recommendation Persistence Follow-Up

- Kept the trading engine, execution engine, guardrail logic, and SQLite storage unchanged.
- Changed the recommendation API to return a larger saved SQLite recommendation history.
- Sorted saved recommendations by highest confidence first, then newest.
- Improved auto-execute responses with per-symbol skipped reasons so high-confidence but guardrail-failed cards are understandable.
- Updated Market Intelligence to load monitored companies from `/intelligence/companies` and show company names alongside theme definitions.
- Added tests for saved recommendation ordering and auto-execute skip explanations.
- Verified Python tests: 18/18 passing.
- Verified Expo Doctor: 17/17 passing.
- Published OTA to `preview`: `55d45b77-db90-4f57-b411-38d067ef6382`.
- Published OTA to `hosted-preview`: `93fa34c0-db77-4e8b-a198-6e85ac2e393f`.

## 2026-07-03 Unsupported Broker Symbol Follow-Up

- Fixed Run Analysis failure caused by Alpaca returning `asset not found` for an unsupported watchlist symbol.
- Updated the Alpaca data client to return empty market/news payloads for missing assets instead of raising a fatal error.
- Updated the AI Trading Agent to record a no-trade event when no latest market bar is available for a symbol.
- Updated OpenAI proposal parsing so empty JSON objects are treated as no-trade results instead of constructor errors.
- Kept the trading engine, execution engine, guardrails, mobile app structure, and SQLite storage unchanged.
- Verified Python tests: 21/21 passing.
- Verified Expo Doctor: 17/17 passing.

## 2026-07-03 Sprint 4 Investment Orchestrator

- Implemented `AutoTradeConfig` and added Sprint 4 environment variables.
- Added broker adapter interface in `src/ai_trader/broker_adapters.py`.
- Wrapped existing Alpaca paper integration as `AlpacaBrokerAdapter`.
- Added placeholder `InteractiveBrokersAdapter`, `SaxoAdapter`, and `KrakenAdapter` with not-configured responses only.
- Implemented `InvestmentOrchestrator` in `src/ai_trader/orchestrator.py`.
- Added append-only SQLite tables:
  - `ORCHESTRATOR_DECISIONS`
  - `AUTO_TRADE_EVENTS`
  - `DAILY_BRIEFS`
- Routed API auto-execution through the Investment Orchestrator.
- Kept manual approve-and-execute path on the existing Execution Engine.
- Added `AUTO_PAPER_TRADING=false` default behavior so recommendations require manual approval unless explicitly enabled.
- Added morning and evening brief generation with Markdown output and SQLite persistence.
- Added `ResearchScheduler` and `research-once` CLI command for safe local or Render scheduled research.
- Wired the Render Docker web process to start hourly background research when `RESEARCH_SCHEDULER_ENABLED=true`.
- Updated `render.yaml` with Sprint 4 auto-trade and scheduler environment variables while keeping `AUTO_PAPER_TRADING=false`.
- Updated `cloud.env.example` and recreated `.env.example` with Sprint 4 variables.
- Updated only the three existing mobile screens:
  - Trading Command Centre
  - AI Recommendations
  - Market Intelligence
- Added tests for orchestrator routing, Alpaca adapter compatibility, market closed rejection, unavailable asset rejection, confidence rejection, missing stop loss rejection, max stop-loss rejection, auto mode enabled/disabled, morning brief generation, evening brief generation, and scheduler cycle execution.
- Verified Python tests: 33/33 passing.
- Committed Sprint 4 Render-ready changes as `cfcd023`.
- Pushed `master` to `origin` so Render can auto-deploy if auto-deploy is enabled.
- Attempted hosted health checks after push; `https://trader-no0f.onrender.com` was not accepting connections from this environment at that moment.

## 2026-07-04 Sprint 5 Operational Clarity and Crypto Preparation

- Added `src/ai_trader/operational.py` for robust score parsing, portfolio snapshots, research runs, and crypto universe schema.
- Fixed qualitative values such as `Good`, `Medium`, `High`, `Low`, `Cautious`, and `Positive` so recommendations no longer crash on numeric conversion.
- Added `PORTFOLIO_SNAPSHOTS`, `RESEARCH_RUNS`, and `CRYPTO_ASSET_MASTER` tables.
- Portfolio dashboard refresh now records an Alpaca snapshot and returns explicit `Not available - reason` values when data cannot be calculated.
- Research analysis now records auditable research run rows.
- Benchmark daily brief now falls back to the latest seeded benchmark research with an explicit reason when today's data is unavailable.
- Updated Command screen with executive summary and exchange selector for All, Alpaca, Kraken, and Coinbase.
- Renamed visible trade history to exchange-specific wording such as Alpaca Trade History.
- Added Kraken and Coinbase adapter preparation with trading disabled by default.
- Added crypto-specific auto-trade guardrail environment variables.
- Updated Render and cloud environment documentation for Sprint 5.
- Added Sprint 5 tests for qualitative parsing, P&L unavailable reasons, snapshots, research run tracking, benchmark fallback, exchange selector not-configured states, Kraken/Coinbase not configured, crypto universe table creation, and safe crypto auto-trade rejection.
- Verified Python tests: 42/42 passing.

## 2026-07-04 Foundation Sprint - Autonomous Investment Platform

- Reviewed governance documents, `STATUS.md`, `IMPLEMENTATION_LOG.md`, `README.md`, Render configuration, broker implementations, Investment Intelligence Engine, and mobile app.
- Created Founder-governed constitutional documents:
  - `INVESTMENT_POLICY_STATEMENT.md`
  - `RISK_MANAGEMENT_POLICY.md`
  - `BROKER_EXECUTION_POLICY.md`
  - `AI_LEARNING_POLICY.md`
  - `INVESTMENT_UNIVERSE.md`
- Added `src/ai_trader/foundation.py`.
- Added configurable SQLite policy tables:
  - `INVESTMENT_POLICIES`
  - `RISK_POLICIES`
  - `BROKER_POLICIES`
  - `LEARNING_POLICIES`
- Added permanent decision and audit tables:
  - `CAPITAL_ALLOCATION_HISTORY`
  - `DUE_DILIGENCE_ASSESSMENTS`
  - `INVESTMENT_SCORES`
  - `BROKER_DECISIONS`
  - `EXECUTION_DECISIONS`
- Added crypto knowledge tables:
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
- Updated the Investment Orchestrator so autonomous execution now validates governance policy, due diligence, investment scores, investment universe, broker state, market state, risk, and capital allocation.
- Updated API recommendations and status payloads with due diligence status, crypto projects reviewed, trading policy snapshot, and structured investment score fields.
- Updated mobile app without adding screens:
  - Command screen broker panels for Alpaca and Kraken.
  - Recommendation cards show due diligence and Investment Score fields.
  - Intelligence screen shows Alpaca and Kraken intelligence sections.
- Updated Kraken adapter to support Render `KRAKEN_PRIVATE_KEY` while preserving `KRAKEN_API_SECRET` compatibility and disabled-by-default trading.
- Updated `.env.example`, `cloud.env.example`, and `render.yaml`.
- Added foundation tests for policy seeding, due diligence, investment scores, capital allocation, orchestrator decision recording, emergency shutdown, and Kraken credential naming.
- Verified Python tests: 48/48 passing.

## 2026-07-04 Multi-Broker Autonomous Platform Sprint

- Added `src/ai_trader/multi_broker.py`.
- Added broker-specific auto-trading settings with SQLite persistence.
- Added broker runtime state so every broker can report connection, research, due diligence, current asset, current stage, queue, freshness, and last trade independently.
- Added broker trade history persistence for accepted, pending, filled, cancelled, closed, and other broker statuses.
- Added notification event queue for research, broker control, trade submission, and future push notification delivery.
- Added recommendation set persistence so the latest analysis run remains auditable and can be made active.
- Added crypto research score table for technical trend, momentum, RSI, moving average position, MACD, volume trend, volatility, liquidity, market structure, sentiment, news, on-chain activity, risk, due diligence, and confidence.
- Added broker-specific environment flags:
  - `ALPACA_AUTO_TRADING`
  - `KRAKEN_AUTO_TRADING`
  - `COINBASE_AUTO_TRADING`
  - `BINANCE_AUTO_TRADING`
  - `IBKR_AUTO_TRADING`
- Updated the API:
  - `GET /status` now includes broker panels, continuous research state, and broker-specific auto-trading state.
  - `GET /brokers` returns broker panels.
  - `POST /broker-auto-trading` enables or disables new autonomous entries for one broker only.
  - `POST /auto-execute-recommendations` no longer reports `AUTO_PAPER_TRADING is false`; it reports broker-specific enablement.
- Completed Kraken read adapter surface:
  - Authenticated balance check.
  - Holdings from balances.
  - Open orders.
  - Closed orders.
  - Trade history.
  - Current prices through public ticker helper.
  - Authentication failures are returned with reasons when credentials exist.
- Kept Kraken order submission disabled pending final Founder-approved execution method.
- Updated mobile app without adding screens:
  - Broker panels are generated from backend brokers.
  - Enable/Disable Auto Trading buttons control one broker only.
  - Recommendations are grouped by broker, collapsed by default, sorted by confidence, and filterable.
  - Intelligence displays broader continuous research state.
- Updated `.env.example`, `cloud.env.example`, `render.yaml`, `README.md`, `STATUS.md`, and `governance/FOUNDER_BRIEF.md`.
- Added tests for independent broker auto-trading, API broker control, recommendation set persistence, crypto research score storage, and legacy auto flag compatibility.
- Verified Python tests: 53/53 passing.

## 2026-07-04 Kraken Controlled Live Micro-Trading Seatbelts

- Added explicit live Kraken approval switches:
  - `KRAKEN_LIVE_TRADING_APPROVED`
  - `KRAKEN_SUBMIT_REAL_ORDERS`
  - `KRAKEN_MAX_ORDER_GBP`
  - `KRAKEN_MIN_ORDER_GBP`
  - `KRAKEN_MAX_OPEN_TRADES`
  - `KRAKEN_ALLOWED_PAIRS`
- Implemented Kraken `AddOrder` market order submission behind broker-specific auto trading, live approval, and hard mechanical checks.
- Added duplicate order intent locks before broker submission.
- Added managed exit records after accepted Kraken entries.
- Added protective exit monitoring through `POST /monitor-managed-exits`.
- Added SQLite tables:
  - `ORDER_INTENT_LOCKS`
  - `MANAGED_TRADE_EXITS`
  - `MECHANICAL_SEATBELT_EVENTS`
- Added queued notifications for trade accepted, stop loss, take profit, and exit submission.
- Added mobile recommendation cache using AsyncStorage so recommendation history survives app restarts and backend/network gaps.
- Added Intelligence-to-Recommendations linking: monitored company names link to matching recommendation cards and open the selected card.
- Added tests for Kraken live micro-order rejection and validation-mode submission.
- Verified Python tests: 55/55 passing.

## 2026-07-07 Autonomous Trading Readiness Sprint

Implemented the Go-Live Readiness Review's findings. Full detail in `STATUS.md`; summary below.

- **Broker execution is now orchestrator-only.** `approve_and_execute` (manual approval) now
  calls `InvestmentOrchestrator.evaluate_recommendation` instead of the legacy
  `ExecutionEngine` directly - it now gets due diligence, investment scoring, capital
  allocation, and the `ORDER_INTENT_LOCKS` duplicate-order lock for free.
- **Kraken safety defaults fixed.** `KRAKEN_SUBMIT_REAL_ORDERS` now defaults to validate/
  dry-run mode when unset (previously defaulted to submitting real orders).
- **Risk limits actually enforced.** Daily/weekly/monthly loss limits, a new max-drawdown
  check, and portfolio-level exposure/concentration limits are now checked against real
  `PORTFOLIO_SNAPSHOTS` history inside `InvestmentOrchestrator.evaluate_recommendation`
  (previously the daily-loss check was fed a hardcoded `0.0` and the exposure/drawdown
  checks did not exist).
- **Continuous monitoring, not manual-only.** Kraken's stop-loss/take-profit monitor and a
  new broker order/fill poller now run on background `IntervalWorker` loops (60s cadence)
  started from `run_server`, independent of whether research scheduling is enabled.
  Previously both only ran if something manually called `/monitor-managed-exits`.
- **Resilience.** `ResearchScheduler` and the new `IntervalWorker` loops catch and log any
  exception and keep running (a `research_failure`/`broker_failure` notification is fired),
  instead of the background thread dying silently. Added a startup reconciliation pass
  (`reconcile_on_startup`) that flags stuck order-intent locks left over from a prior crash.
- **Trailing stops.** Added a governed `trailing_stop_pct` risk policy and high/low
  water-mark tracking on `MANAGED_TRADE_EXITS`; `monitor_managed_exits` ratchets the
  effective stop as price moves favorably when enabled.
- **Due diligence is evidence-based, not floored.** Removed the hardcoded 0.70/0.75 score
  floors in `calculate_investment_score`; macro/behavioural factors and due-diligence
  statuses now reflect real backing data (a matching market theme, a same-day benchmark
  trader research entry, or a crypto research score) or are honestly marked
  `insufficient_data`/scored `0.0`.
- **Live crypto knowledge engine.** `seed_crypto_universe` now fetches CoinGecko's actual
  market-cap/AI/privacy-coin category endpoints (previously keyword-matched a single
  market-cap page) and populates `CRYPTO_MASTER` (previously never populated, which
  silently blocked every crypto proposal) and `CRYPTO_MARKET_DATA`, with genuine
  technical/momentum/volatility/liquidity scores computed from live price data.
  On-chain/sentiment/news remain explicitly `insufficient_data` - no fabricated scores.
- **Crypto can now actually trade autonomously.** Added `propose_crypto_trades` (in
  `agent.py`) - previously nothing in the codebase ever generated a crypto trade proposal,
  so Kraken's entire autonomous-entry path was unreachable regardless of configuration.
  While verifying this end to end (not just via unit tests), found and fixed three real
  bugs that would have silently blocked every Kraken trade: the equity trading-hours
  guardrail was wrongly applied to 24/7 crypto, `risk_percentage` was computed from the
  stop-loss distance instead of capital-at-risk, and `paper_trading_only` incorrectly
  rejected Kraken's genuinely non-paper account.
- **Performance attribution.** Added `PERFORMANCE_ATTRIBUTION` table populated atomically
  when a managed exit closes: entry/exit price, P&L, holding period, entry/exit reason,
  and the investment-score reasoning that justified entry.
- **Notifications.** Added `GET /notifications`, `POST /notifications/ack`, and best-effort
  Expo push delivery (`POST /register-push-token`, a `PUSH_TOKENS` table, and a background
  dispatcher) for high-priority events. Mobile push delivery is implemented server-side and
  unit-tested, but not end-to-end verified - that requires a rebuilt app on a physical device.
- **Security.** Hosted API startup now fails closed for trading/control actions: when
  started on a non-loopback host with no `AI_TRADER_API_TOKEN`, the service enters
  read-only mode and rejects all POST commands until the token is configured. Token
  comparison uses `hmac.compare_digest`. Added a per-IP lockout after repeated auth failures.
- **Mobile.** Added an in-app notification center with unread badge, a Risk Limits section
  surfacing the policy the orchestrator enforces, and clarified that Stop Trading halts new
  entries/approvals but does not disable already-running managed-exit protection.
- **Consolidated duplicated logic.** Kraken pair-formatting/last-price parsing existed
  independently in `api.py` and would have existed a third time in the new crypto proposal
  code; moved the canonical implementation into `broker_adapters.py` and had all three call
  sites use it.
- Added 11 new tests (55 -> 66 passing) covering every behavior change above, including
  regression tests for the three crypto guardrail bugs and the P&L sign-correctness fix.
- **Explicitly out of scope this sprint:** the `api.py` god-file / broker-addition-touches-
  many-files architecture findings (Amber, not safety-blocking - flagged as a fast-follow);
  native mobile push client integration (`expo-notifications`) was not added, since it
  requires a rebuild I cannot verify from this environment - the backend is ready for it.
  No live-trading enablement switches (`KRAKEN_AUTO_TRADING`, `KRAKEN_LIVE_TRADING_APPROVED`,
  `INVESTMENT_POLICIES.crypto_enabled`) were changed - that remains a deliberate Founder
  action. The `.env` file's live keys were left untouched (rotation is a Founder action in
  the Alpaca/OpenAI dashboards, not something this sprint could safely do on its own).
- Verified Python tests: 66/66 passing.

## 2026-07-07 Principal Review and Release Management Pass

- Reviewed the Autonomous Trading Readiness Sprint as release manager.
- Added formal governance review artefacts:
  - `governance/ENGINEERING_REVIEW_REPORT.md`
  - `governance/ARCHITECTURE_ASSESSMENT.md`
  - `governance/SAFETY_ASSESSMENT.md`
  - `governance/REMAINING_RISKS.md`
  - `governance/FOUNDER_RELEASE_BRIEF.md`
- Corrected the mobile Command Centre wording so broker-specific Enable/Disable Auto
  Trading remains the normal broker control path, while the global buttons are clearly
  labelled as Resume All Trading and Emergency Stop All.
- Added a deployment hotfix after Render verification showed the hosted service could not
  remain healthy without `AI_TRADER_API_TOKEN`: the API now starts in hosted read-only mode
  and rejects POST trading/control commands until the token is set, preserving safety without
  taking status/recommendation views offline.
- Updated README and STATUS to match the broker-independent operating model.
- Verification completed:
  - Python compile check passed.
  - Python unit test suite passed: 66/66.
  - `git diff --check` passed.
  - `npx expo-doctor` passed: 17/17 checks.
- Deployment verification:
  - GitHub push completed and Render served the new expanded `/status` payload.
  - Render `/healthz` and `/status` returned HTTP 200 after deployment.
  - `/notifications`, `/performance-attribution`, and an unauthenticated POST check were
    unstable from external verification and require Render log review before declaring the
    hosted backend fully green.

## 2026-07-07 Trading Learning and Kraken Allocation Follow-Up

- Added `KRAKEN_TRADING_ALLOCATION_GBP` with a default of GBP 100 to local, cloud, and Render configuration.
- Updated Kraken account context so trading/risk sizing uses the AI trading allocation instead of the full Kraken account balance.
- Updated Kraken broker panels to separate:
  - full estimated account balance,
  - GBP cash,
  - AI trading allocation,
  - valuation notes for unpriced assets.
- Added `GET /daily-learning-update`, combining closed trade attribution, orchestrator decisions, portfolio snapshots, and public benchmark trader learning into one Founder-facing daily update.
- Added mobile Intelligence screen rendering for the Daily Trading Learning Update.
- Added mobile collapsible trade history rows so trade detail is available on tap without overwhelming the Command Centre.
- Added Kraken/Coinbase broker trade-history rows and `PERFORMANCE_ATTRIBUTION` rows into the Command Centre trade history feed.
- Added tests for Kraken balance/allocation separation and the daily learning update.
- Verification completed:
  - Python compile check passed.
  - Python unit test suite passed: 69/69.
  - `git diff --check` passed.
  - `npx expo-doctor` passed: 17/17 checks.
- Committed and pushed backend/mobile changes as `79df559`.
- Published EAS OTA updates for runtime `1.0.1`:
  - `preview`: update group `854ca353-8bd3-4590-8153-dd7b1d4a0c7d`.
  - `hosted-preview`: update group `3388fe5e-18ee-4a19-8ee8-11b1049a4fbb`.
- Hosted verification after push:
  - `/healthz` returned 200.
  - `/status` returned 200.
  - `/recommendations` returned 200.
  - `/daily-learning-update` and `/performance-attribution` were not reachable from this environment; this matches the previously observed hosted instability around attribution endpoints and should be checked in Render logs if it persists.

## 2026-07-07 On-Demand Trading Reports Follow-Up

- Added `GET /trading-report` for read-only report retrieval.
- Added `POST /generate-report` for app-triggered daily, morning, and evening report generation.
- Report generation now combines:
  - portfolio snapshots,
  - closed trade performance attribution,
  - broker trade history,
  - orchestrator decisions and rejections,
  - daily learning update lessons,
  - benchmark/successful-trader learning notes.
- Mobile Command Centre now includes a Reports section with Today Report, Yesterday Report, Morning Report, and Evening Report buttons.
- Broker cards now include a broker-specific Daily Report button.
- Generated reports are shown immediately inside the app and saved as Markdown to the configured output directory.
- Added `TRADING_REPORTS` SQLite storage for generated reports.
- Generated report Markdown files now live under the backend output folder's `reports/` directory.
- Added browser report pages at `/reports/{report_id}`.
- Updated the mobile app to open the report browser URL automatically and show an `Open Report` button.
- Expanded report detail for daily, morning, evening, weekly, and monthly windows:
  - report window start/end,
  - start and end balances,
  - period performance summary,
  - every closed trade with opened/closed times, entry, exit, quantity, and P&L,
  - broker trade/order rows,
  - explanation of why money was won or lost,
  - lessons learned,
  - Founder-approved recommendations.
- Added Weekly Report and Monthly Report buttons to the mobile Reports section.
- Added broker-fill FIFO reconstruction to reports so buy/sell fills can be paired into realised P&L even when `PERFORMANCE_ATTRIBUTION` has no closed row.
- Reports now list open/unmatched fills separately so fills like an unmatched `SELL ROG` are visible and explained as not enough evidence to compute closed-trade P&L inside the report window.
- Updated broker trade-history recording to preserve Alpaca `transaction_time` for future fill rows.
- Added a regression test proving a negative P&L day and losing closed trade are explained in the generated report.
- Verification completed:
  - Python compile check passed.
  - Python unit test suite passed: 70/70.
  - `git diff --check` passed.
  - `npx expo-doctor` passed: 17/17 checks.
## 2026-07-17 World-Class Trading Intelligence Transformation

- Added `src/ai_trader/trading_intelligence.py` as the new evidence layer before recommendation persistence.
- Added SQLite schema for:
  - `STRATEGY_REGISTRY`
  - `MARKET_REGIME_SNAPSHOTS`
  - `TRADE_SIGNALS`
  - `TRADING_COMMITTEE_REVIEWS`
  - `PROBABILITY_ESTIMATES`
  - `TRADE_LIFECYCLE`
  - `CONFIDENCE_CALIBRATION`
  - `STRATEGY_LAB_RUNS`
- Seeded formal deterministic strategy definitions for:
  - conservative AI-assisted equity setup,
  - crypto trend-following 2R,
  - paper validation 2R.
- Updated stock and crypto proposal generation so recommendations are only persisted after Trading Intelligence creates:
  - strategy,
  - regime,
  - signal evidence,
  - trade setup,
  - portfolio fit,
  - trading committee review,
  - probability estimate,
  - strongest argument for,
  - strongest argument against.
- Updated the audit payload to store the full intelligence packet with each recommendation.
- Updated the Investment Orchestrator to append lifecycle stages after approved, submitted, and rejected outcomes.
- Updated `/recommendations` to expose strategy, market regime, committee, probability, signals, lifecycle, and bull/bear arguments.
- Updated the mobile Recommendations screen to show the new evidence without changing execution authority.
- Added regression tests in `tests/test_trading_intelligence.py`.
- Documentation added:
  - `architecture/WORLD_CLASS_TRADING_INTELLIGENCE_ARCHITECTURE.md`
  - `architecture/WORLD_CLASS_TRADING_INTELLIGENCE_IMPLEMENTATION_REPORT.md`
  - `architecture/WORLD_CLASS_TRADING_INTELLIGENCE_DATABASE_CHANGES.md`
  - `architecture/WORLD_CLASS_TRADING_INTELLIGENCE_TESTING_REPORT.md`
  - `architecture/WORLD_CLASS_TRADING_INTELLIGENCE_FOUNDER_BRIEFING.md`
  - `architecture/WORLD_CLASS_TRADING_INTELLIGENCE_KNOWN_LIMITATIONS.md`
  - `architecture/WORLD_CLASS_TRADING_INTELLIGENCE_ROADMAP.md`
- Verification:
  - Focused Trading Intelligence tests passed: 4/4.
  - Full Python unit test suite passed: 90/90.
  - `npx tsc --noEmit` is not available because the Expo mobile app does not include TypeScript; no dependency changes were made.

## 2026-07-17 World-Class Trading Intelligence Phase 2

- Extended `src/ai_trader/trading_intelligence.py` from evidence recording into evidence discovery.
- Added deterministic market-intelligence metrics from available candles:
  - trend score,
  - momentum score,
  - moving-average position,
  - volatility,
  - ATR percentage,
  - relative strength proxy,
  - volume trend,
  - price structure,
  - breakout/breakdown state,
  - mean-reversion state,
  - support,
  - resistance,
  - contradictory evidence.
- Updated regime inference to use market-intelligence metrics and store contradictory evidence.
- Updated signal scoring so signals are independently calculated rather than copied from proposal confidence.
- Expanded strategy registry with:
  - Trend Following,
  - Momentum,
  - Pullback,
  - Breakout,
  - Mean Reversion,
  - Range Trading,
  - Volatility Expansion,
  - Swing Continuation,
  - Crypto Infrastructure Trend,
  - Institutional Accumulation,
  - Quality Growth,
  - Value Pullback.
- Expanded Trading Committee into deterministic independent reviewers with member votes, questions, disagreements, and outcomes.
- Enhanced probability estimation with strategy history, regime history, signal history, small-sample penalty, volatility penalty, calibration evidence, and confidence intervals.
- Added `HISTORICAL_CANDLES`, `STRATEGY_BACKTEST_RESULTS`, and `PERFORMANCE_INTELLIGENCE` tables.
- Added `record_historical_candle`, `run_strategy_backtest`, `calculate_calibration_metrics`, and `calculate_performance_metrics`.
- Extended `TRADE_LIFECYCLE` with fees, slippage, R-multiple, MAE, MFE, and holding-time fields using additive SQLite migration.
- Fixed `/recommendations` intelligence merging so normalized committee/probability rows do not hide richer strategy, regime, and market-intelligence payloads.
- Fixed a SQLite lock path in calibration refresh by calculating metrics outside the write transaction.
- Added Phase 2 documentation:
  - `architecture/WORLD_CLASS_TRADING_INTELLIGENCE_PHASE_2.md`.
- Verification:
  - `py_compile` passed for Trading Intelligence and API modules.
  - Focused Trading Intelligence tests passed: 10/10.
  - Full Python unit test suite passed: 96/96.

## 2026-07-17 Institutional Intelligence & Founder Experience Phase 3

- Added long-term architectural principle:
  - Does it help AI Trader make a better investment decision?
  - Does it help the Founder make a better decision?
  - Does it help AI Trader learn to make better decisions in the future?
- Updated strategy selection to score multiple candidate strategies against available evidence instead of relying on a fixed default.
- Strategy records now include selection reason, candidate scores, rejected strategies, production-readiness status, and validation status.
- Added Strategy Lab walk-forward validation with train/test windows, out-of-sample results, cost/slippage assumptions, benchmark comparison, and bias-control notes.
- Added richer portfolio intelligence fields for exposure, prospective exposure, largest position, proposed risk contribution, diversification, capital efficiency, liquidity-data availability, and risk-budget notes.
- Added a `founder_experience` payload to `/status` for executive dashboard, portfolio command, market intelligence centre, and learning lab screens.
- Reframed the mobile app into five Founder screens:
  - Dashboard
  - Recommendations
  - Portfolio
  - Market
  - Learning
- Added dark executive shell with white decision cards and plain-English status pills.
- Moved trade-history and broker-panel workflows under Portfolio.
- Moved strategy rankings, institutional tests, signal rankings, lessons, and Ask AI Trader under Learning.
- Added documentation:
  - `architecture/INSTITUTIONAL_INTELLIGENCE_PHASE_3.md`
  - `architecture/FOUNDER_EXPERIENCE_PHASE_3_MOCKUPS.md`
  - `governance/FOUNDER_BRIEFING_PHASE_3.md`
- Verification:
  - `py_compile` passed for Trading Intelligence and API modules.
  - Focused Trading Intelligence tests passed: 13/13.

## 2026-07-17 World-Class Trader Transformation Phase 4-8

- Reviewed existing architecture and governance before implementation.
- Created `architecture/WORLD_CLASS_TRADER_PHASE_4_8_IMPLEMENTATION_PLAN.md`.
- Added `src/ai_trader/operational_truth.py` for canonical lifecycle, reconciliation, execution costs, true R, MAE, and MFE.
- Added `src/ai_trader/market_intelligence_platform.py` for provider-neutral market observations, data quality, multi-timeframe conclusions, and Regime 2.0 evidence.
- Added `src/ai_trader/portfolio_intelligence.py` for metadata, exposure, concentration, correlation, and proposed-trade portfolio impact.
- Added `src/ai_trader/experience_engine.py` for immutable experience records, post-trade reviews, analogues, and governed learning proposals.
- Wired additive schema initialization into `LocalApiService`.
- Reconciled Alpaca/Kraken broker history into canonical lifecycle records during startup and broker-history writes.
- Added `/operational-truth` and `/world-class-evidence`.
- Added `world_class_evidence` to `/status` for Founder-facing truth, unknowns, operational health, portfolio intelligence, and learning boundaries.
- Tightened recommendation actionability: auto-trade eligibility now requires both strongest argument for and strongest argument against.
- Updated the mobile Dashboard, Portfolio, and Recommendation screens around progressive disclosure and explained unknowns.
- Added Phase 4-8 architecture, standards, testing, implementation, deployment-contract, and Founder briefing documents.
- Verification:
  - `py_compile` passed for new backend modules and API.
  - Focused World-Class Transformation tests passed: 6/6.

## 2026-07-17 Always-On Operations, Shadow Trading, and Alpaca Recovery

- Reviewed the existing Render blueprint, API startup scheduler, CLI, and operational tables.
- Confirmed the previous topology had one Render web service and background daemon threads owned by the API process.
- Added `src/ai_trader/always_on.py` with durable schemas and helpers for:
  - scheduled job runs;
  - worker heartbeats;
  - research funnels;
  - shadow trades;
  - operations incidents;
  - operations health;
  - scheduler status;
  - Alpaca inactivity diagnosis.
- Added package entry point `src/ai_trader/__main__.py` so `python -m ai_trader ...` works.
- Extended the CLI with:
  - `run-worker`;
  - `run-job`;
  - named jobs for premarket, market open, midday, market close, overnight crypto, daily learning, daily report, broker poll, managed exits, and auto execution.
- Wired additive always-on schema initialization into `LocalApiService`.
- Added API endpoints:
  - `/operations-health`;
  - `/scheduler-status`;
  - `/job-runs`;
  - `/shadow-trades`;
  - `/shadow-performance`;
  - `/research-funnel`;
  - `/alpaca-inactivity-diagnosis`.
- Added `operations_health` to `/status`.
- Added Alpaca and Kraken research funnel recording.
- Added proposal-to-shadow-trade recording for Alpaca and Kraken proposals.
- Added process commands for explicit API, worker, and cron job topology. Left `render.yaml` on the current single web service until Supabase/Postgres is connected, because SQLite on a persistent disk is not a safe multi-process shared datastore.
- Updated the mobile Dashboard with a 24-Hour Operations card.
- Added focused tests in `tests/test_always_on_operations.py`.
- Added Always-On architecture and Founder briefing documents.
- Added a governed Supabase Postgres migration plan. SQLite remains the current implementation; Supabase Postgres is the recommended production target for API, worker, and cron shared state.
- Verification:
  - Focused Always-On tests passed: 9/9.
- Not yet proven:
  - live Render worker heartbeat after deploy;
  - scheduled cron job execution while app is closed;
  - hosted Alpaca fresh research path from live provider to order or persisted no-trade reason.

## 2026-07-18 Supabase/Postgres Always-On Evidence Backend

- Implemented the next controlled datastore step after the Always-On sprint.
- Added settings for:
  - `AI_TRADER_DATABASE_BACKEND`;
  - `DATABASE_URL`;
  - `SUPABASE_DATABASE_URL`.
- Added `Settings.uses_postgres` and exposed safe database backend diagnostics through `ai-trader config`.
- Added Postgres schema support in `src/ai_trader/always_on.py` for:
  - `SCHEDULED_JOB_RUNS`;
  - `WORKER_HEARTBEATS`;
  - `RESEARCH_FUNNELS`;
  - `SHADOW_TRADES`;
  - `OPERATIONS_INCIDENTS`.
- Added dual-backend persistence for Always-On job claims, job completion, worker heartbeats, research funnels, shadow trades, shadow outcomes, operations incidents, and list/read helpers.
- Added `database_backend` details to `/operations-health` so the Founder/CTO can see whether Always-On evidence is using SQLite or Supabase/Postgres.
- Added `psycopg[binary]` as the Postgres driver dependency.
- Updated `render.yaml` with `AI_TRADER_DATABASE_BACKEND` and `DATABASE_URL` placeholders while keeping worker/cron disabled until Postgres is proven active.
- Updated:
  - `architecture/SUPABASE_POSTGRES_MIGRATION_PLAN.md`;
  - `architecture/RENDER_SERVICE_TOPOLOGY.md`;
  - `architecture/DATABASE_REFERENCE.md`;
  - `README.md`;
  - `STATUS.md`.
- Boundary:
  - This does not migrate the full trading/audit database yet.
  - Broker runtime, recommendations, canonical lifecycle, trade audit, reports, and learning records remain on the existing SQLite-oriented modules until their schemas are ported deliberately.

## 2026-07-18 Autonomous Operations Completion and Render Activation

- Reviewed the Sprint 6 production-control layer, Always-On worker commands, Render topology, database architecture, and hosted activation gates.
- Updated `render.yaml` from a web-only production shape to an activation-ready topology:
  - `ai-trader-api`;
  - `ai-trader-worker`;
  - premarket, market-open, midday, and market-close equity cron jobs;
  - overnight crypto cron job;
  - daily learning cron job;
  - daily, weekly, and monthly report cron jobs.
- Added hosted startup validation in `Settings.production_startup_errors`:
  - hosted runtime now requires `AI_TRADER_DATABASE_BACKEND=postgres` plus `DATABASE_URL` or `SUPABASE_DATABASE_URL`;
  - the check also honors `AI_TRADER_PROCESS_ROLE=render`;
  - this prevents silent hosted SQLite fallback.
- Added `AI_TRADER_DISABLE_API_BACKGROUND_WORKERS`:
  - when true, the API does not start duplicate scheduler, broker poll, exit monitor, auto-executor, crypto refresh, or push-dispatch loops;
  - Render worker/cron services become the intended background owners.
- Extended `python -m ai_trader run-worker` so every worker cycle processes the Sprint 6 closed-loop learning outbox after broker polling, managed exits, and auto-execution evaluation.
- Added the learning outbox processor:
  - idempotent claim/retry handling;
  - abandoned claim recovery;
  - manual review for incomplete deterministic evidence;
  - immutable preservation of the original queued payload;
  - operational-event evidence for every processor cycle.
- Extended `python -m ai_trader run-job` to support daily, weekly, and monthly report jobs.
- Updated `.env.example` and `cloud.env.example` with the production database/process-role contract.
- Added architecture evidence documents:
  - `AUTONOMOUS_OPERATIONS_COMPLETION_REPORT.md`;
  - `POSTGRES_PRODUCTION_MIGRATION_REPORT.md`;
  - `RENDER_PRODUCTION_TOPOLOGY.md`;
  - `RENDER_DEPLOYMENT_EVIDENCE.md`;
  - `RENDER_ENVIRONMENT_MANIFEST.md`;
  - `AUTONOMOUS_RESEARCH_VERIFICATION.md`;
  - `BROKER_RECONCILIATION_COMPLETION.md`;
  - `LEARNING_PROCESSOR_VERIFICATION.md`;
  - `AUTOMATIC_REPORTING_VERIFICATION.md`;
  - `PHONE_CLOSED_VERIFICATION.md`;
  - `HOSTED_RESTART_AND_RECOVERY_TESTS.md`;
  - `OPEN_RELEASE_GATES.md`;
  - `FOUNDER_COMPLETION_BRIEFING.md`.
- Updated `README.md`, `STATUS.md`, `architecture/RENDER_SERVICE_TOPOLOGY.md`, and `architecture/DATABASE_REFERENCE.md`.
- Verification completed locally:
  - `python -m py_compile src\ai_trader\config.py src\ai_trader\api.py src\ai_trader\cli.py src\ai_trader\sprint6.py` passed.
  - `python -m unittest tests.test_always_on_operations tests.test_sprint6_institutional_spine` passed: 23/23.
- Hosted activation not completed from this environment:
  - Render deployment ID not available;
  - Supabase/Postgres live connection not verified;
  - phone-closed worker/cron proof remains an open release gate.

## 2026-07-19 Always-On Worker Activation Wording Correction

- Founder-provided hosted evidence confirmed:
  - `/operations-health` returned `overall=healthy` and `worker_health=healthy`;
  - `/scheduler-status` returned `status=active` with a background-worker heartbeat;
  - `/job-runs` returned durable background job records, including auto-execution cycles.
- Corrected backend status wording so resolved deployment proof is not still presented as an open blocker:
  - `phase5_status` now reports `operational_with_hardening_backlog` when Supabase/Postgres and worker supervision are healthy;
  - `sprint6_status` now reports that production control gates are active when Postgres is configured and no kill switch/open incident blocks operation.
- Updated the mobile Dashboard label from `Still To Migrate` to `Hardening Backlog` so remaining database-spine work is not confused with a current trading blocker.
- Boundary:
  - No guardrails, broker permissions, risk limits, or trading thresholds were weakened.
  - Remaining hardening backlog still matters for institutional maturity, but it no longer masks the proven always-on worker milestone.

## 2026-07-19 Autonomous Activity Screen

- Implemented a new Founder-facing `Activity` tab in the mobile app.
- Added a compact Dashboard `Autonomous Activity` card so the home screen now shows:
  - operating state;
  - last meaningful action;
  - research runs;
  - recommendations;
  - orders submitted;
  - latest blocker or no-trade explanation.
- Added `src/ai_trader/autonomous_activity.py` as a deterministic read model over persisted evidence:
  - scheduled job runs;
  - worker heartbeats;
  - research funnels;
  - operational events;
  - decision journal rows;
  - Portfolio Manager decisions;
  - broker trade history;
  - canonical reconciliation cases;
  - closed-loop learning runs;
  - generated reports;
  - incident lifecycle.
- Added authenticated API routes:
  - `/autonomous-activity`;
  - `/activity/status`;
  - `/activity/summary`;
  - `/activity/timeline`;
  - `/activity/why-no-trade`;
  - `/activity/brokers`;
  - `/activity/founder-attention`.
- Added the mandatory Why No Trade funnel. It separates:
  - research did not run;
  - no opportunity found;
  - opportunity found but rejected;
  - approved/candidate blocked;
  - approved but not submitted;
  - order submitted or trade completed.
- Added timeline filtering by category and importance/action-required mode.
- Added Founder attention items for stale worker heartbeat, durable database not proven, connected-broker issues, disabled Alpaca paper auto-trading, and unresolved incidents.
- Added tests in `tests/test_autonomous_activity.py`.
- Added documentation:
  - `architecture/AUTONOMOUS_ACTIVITY_ARCHITECTURE.md`;
  - `architecture/AUTONOMOUS_ACTIVITY_DATA_MAPPING.md`;
  - `architecture/AUTONOMOUS_ACTIVITY_API.md`;
  - `architecture/AUTONOMOUS_ACTIVITY_LIVE_VERIFICATION.md`;
  - `architecture/FOUNDER_ACTIVITY_SCREEN_GUIDE.md`.
- Verification:
  - `python -m py_compile src\ai_trader\autonomous_activity.py src\ai_trader\api.py` passed.
  - `python -m unittest tests.test_autonomous_activity` passed: 6/6.
- Boundary:
  - No mock events or synthetic activity rows were added.
  - No guardrails, broker permissions, auto-trading settings, or risk thresholds were changed.
  - The Activity screen is evidence visibility only; it does not approve or place trades.

## 2026-07-19 Mobile Refresh Performance Hardening

- Investigated the slow mobile startup/refresh spinner reported by the Founder.
- Root cause found in the mobile refresh path:
  - the app waited for eleven API calls to complete before clearing the global loading spinner;
  - optional/secondary endpoints such as intelligence, reports, notifications, performance attribution, and daily learning could keep the whole interface waiting;
  - Render free-tier cold starts can still add startup delay before the first hosted API response.
- Updated `mobile/App.js` so refresh now happens in two phases:
  - primary evidence first: status, portfolio, recommendations, and autonomous activity;
  - secondary evidence in the background: Founder brief, benchmark, themes, companies, notifications, performance attribution, and daily learning.
- Added request timeouts:
  - primary refresh calls use a 14 second timeout;
  - secondary calls use an 8 second timeout;
  - long POST commands use a 45 second timeout.
- Expected Founder impact:
  - the app should show the main operating picture sooner;
  - optional panels can continue filling in after the main screen is usable;
  - a single slow optional endpoint should no longer make the entire app look frozen.
- Boundary:
  - this does not change trading logic, governance, guardrails, broker permissions, or autonomous execution behaviour.
  - a paid/no-spin-down Render web service or external uptime monitor is still required to remove Render cold-start delays entirely.
