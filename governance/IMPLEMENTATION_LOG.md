# Implementation Log

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
