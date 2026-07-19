# AI Trading Assistant V1 Status

Date: 2026-07-02 (Autonomous Trading Readiness Sprint completed 2026-07-07 - see below)

Status: Version 1 validation sprint passed; Sprint 2 Investment Intelligence Engine initialized; Sprint 3 mobile/API foundation added; Sprint 3.1 developer experience configured; hosted backend path added; Sprint 3.2 app intelligence refinements added; Sprint 4 Investment Orchestrator implemented; Sprint 5 operational clarity implemented locally; Foundation Sprint autonomous investment platform governance implemented; multi-broker autonomous platform controls implemented; Autonomous Trading Readiness Sprint implemented (2026-07-07); World-Class Trading Intelligence Phase 2 implemented (2026-07-17); Institutional Intelligence and Founder Experience Phase 3 implemented locally (2026-07-17); World-Class Trader Transformation Phase 4-8 foundation implemented locally (2026-07-17); Always-On Operations and Alpaca Research Recovery implemented locally (2026-07-17); Supabase/Postgres Always-On evidence backend implemented locally (2026-07-18); Phase 5 Autonomous Production Spine foundation implemented locally (2026-07-18); Sprint 6 institutional production control layer implemented locally (2026-07-18); Autonomous Operations Completion and Render activation repository work implemented locally (2026-07-18); Autonomous Activity screen implemented locally and verified against hosted API (2026-07-19); Production Evidence Activation implemented and locally verified (2026-07-19)

## 2026-07-19 Production Evidence Activation

- Activated recurring worker-owned crypto and market-aware equity research.
- Added shared Postgres/SQLite production evidence projections for research, recommendations, broker snapshots, broker trade observations and learning.
- Added bounded authenticated `/founder-evidence` and `/founder/trades` APIs.
- Reworked all six Founder screens to consume one shared evidence payload and use a local last-known-good cache.
- Removed the legacy `/status` endpoint from the critical mobile startup path.
- Removed long implementation-phase diagnostic cards from the primary Dashboard.
- Full Python suite passes: 148 tests. Expo Doctor passes: 17/17. Android Expo export passes.
- Hosted Render verification confirms shared Postgres evidence, a matching API/worker revision, broker snapshots, bounded trade rows and successful Kraken research. Installed-device verification remains required; this status does not claim a broker trade that has not been observed.

## 2026-07-19 Mobile Refresh Performance Hardening

- Updated the mobile app refresh flow so the screen no longer waits for every optional API endpoint before releasing the loading spinner.
- Primary refresh now loads the operating essentials first:
  - `/operations-health`;
  - `/activity/summary`;
  - `/activity/why-no-trade`;
  - `/portfolio`;
  - `/recommendations`.
- Secondary panels now hydrate in the background:
  - full `/status`;
  - full `/autonomous-activity`;
  - Founder brief;
  - benchmark brief;
  - themes;
  - companies;
  - notifications;
  - performance attribution;
  - daily learning update.
- Added client-side request timeouts so a slow optional endpoint cannot make the entire app appear stuck indefinitely.
- Boundary:
  - Render free-tier cold starts can still delay the first response after inactivity.
  - This change reduces mobile-side blocking once the API responds and prevents optional panels from holding up the whole UI.
- Follow-up hotfix after installed-app verification:
  - `/status` is now treated as a graceful degraded-status source during refresh rather than a whole-app failure.
  - If `/status` times out, the app shows a partial status message and keeps the UI usable instead of displaying a blocking `Backend unavailable` modal.
  - The primary timeout was adjusted to 18 seconds to give the hosted API slightly more room without returning to the previous 30+ second blocking behaviour.
- Follow-up Activity performance hardening after installed-app screenshots:
  - `/status` and `/autonomous-activity` are no longer first-load blockers.
  - Dashboard and Activity summary now render from lightweight persisted evidence first.
  - Full dashboard status, broker panels, and the complete Activity timeline hydrate in the background with a longer timeout.
  - This should make the app show worker/database/job evidence quickly even when the full hosted status payload is slow.

## 2026-07-19 Autonomous Activity Screen

- Added `src/ai_trader/autonomous_activity.py`, a read-only activity read model that aggregates persisted operational evidence without creating duplicate truth tables.
- Added authenticated activity endpoints:
  - `GET /autonomous-activity`
  - `GET /activity/status`
  - `GET /activity/summary`
  - `GET /activity/timeline`
  - `GET /activity/why-no-trade`
  - `GET /activity/brokers`
  - `GET /activity/founder-attention`
- Added a primary `Activity` tab to the mobile app.
- Added a compact `Autonomous Activity` card to the Dashboard.
- The Activity screen shows:
  - current autonomous status;
  - selected-period totals;
  - chronological timeline;
  - why-no-trade funnel;
  - Alpaca and Kraken broker activity;
  - Founder attention items;
  - latest completed actions.
- Truthfulness boundary:
  - no mock events;
  - no synthetic counts;
  - no API-health-only operating label;
  - missing evidence is shown honestly.
- Added architecture and Founder guide documentation:
  - `AUTONOMOUS_ACTIVITY_ARCHITECTURE.md`
  - `AUTONOMOUS_ACTIVITY_DATA_MAPPING.md`
  - `AUTONOMOUS_ACTIVITY_API.md`
  - `AUTONOMOUS_ACTIVITY_LIVE_VERIFICATION.md`
  - `FOUNDER_ACTIVITY_SCREEN_GUIDE.md`
- Verification:
  - `python -m py_compile src\ai_trader\autonomous_activity.py src\ai_trader\api.py` passed.
  - `python -m unittest tests.test_autonomous_activity` passed: 6/6.
- Remaining release gates:
  - deploy the API changes to Render;
  - publish the Expo OTA update;
  - verify `/autonomous-activity` from the hosted API;
  - close and reopen the phone app after a worker cycle to prove phone-closed activity appears.

## 2026-07-18 Autonomous Operations Completion and Render Activation

- Updated `render.yaml` to define:
  - one API web service;
  - one background worker service;
  - cron jobs for equity research, crypto research, daily learning, and daily/weekly/monthly reports.
- Added hosted fail-close validation:
  - hosted runtime refuses startup when `AI_TRADER_REQUIRE_POSTGRES_IN_HOSTED=true` and Postgres is not configured;
  - this prevents API, worker, and cron services from silently writing separate SQLite runtime histories.
- Added `AI_TRADER_PROCESS_ROLE`, `AI_TRADER_DISABLE_API_BACKGROUND_WORKERS`, and `AI_TRADER_REQUIRE_POSTGRES_IN_HOSTED` settings.
- API background workers can now be disabled in production so Render worker/cron owns autonomous operations.
- Background worker now processes the Sprint 6 closed-loop learning outbox every cycle.
- Learning outbox processor:
  - claims pending/retryable workflows;
  - recovers abandoned claims after timeout;
  - preserves original evidence payloads;
  - sends incomplete evidence to manual review;
  - records processor outcomes as operational events.
- Report scheduled jobs now support daily, weekly, and monthly report generation.
- Updated environment templates for the Render/Supabase production contract.
- Added the Autonomous Operations completion documentation pack under `architecture/`.
- Verification:
  - `python -m py_compile src\ai_trader\config.py src\ai_trader\api.py src\ai_trader\cli.py src\ai_trader\sprint6.py` passed.
  - `python -m unittest tests.test_always_on_operations tests.test_sprint6_institutional_spine` passed: 23/23.
- Remaining release gates:
  - configure `DATABASE_URL` or `SUPABASE_DATABASE_URL` in Render;
  - deploy the updated Render blueprint;
  - verify `/operations-health` reports Postgres as active;
  - prove worker heartbeat and scheduled job rows while the mobile app is closed;
  - verify Alpaca paper research reaches either submitted paper order or persisted no-trade reason.

## 2026-07-18 Sprint 6 Institutional Production Control Layer

- Added `src/ai_trader/sprint6.py` with:
  - operational event log;
  - decision journal;
  - strategy maturity registry;
  - strategy entitlement decisions;
  - Production Risk Sentinel decisions;
  - kill switch state;
  - learning workflow outbox;
  - broker event mappings;
  - incident lifecycle;
  - founder operational reports.
- Wired Sprint 6 pre-execution packets into:
  - manual approval and execution;
  - auto-execute recommendations.
- Broker polling now normalizes broker events into the Sprint 6 mapping table before canonical reconciliation and queues terminal rows for learning workflow processing.
- Research cycles now record operational events for started, completed, no-action, and blocked-configuration outcomes.
- Added endpoints:
  - `GET /sprint6-status`
  - `GET /operational-events`
  - `GET /decision-journal`
  - `POST /generate-operational-report`
- Added `sprint6_status` to `GET /status`.
- Added a `Sprint 6 Production Control` card to the mobile Dashboard.
- Added Sprint 6 architecture documentation and Founder briefing.
- Verification:
  - `python -m compileall src` passed.
  - `python -m unittest tests.test_sprint6_institutional_spine` passed: 9/9.
  - `python -m unittest discover -s tests` passed: 133/133.
  - `npx expo-doctor` passed: 17/17.
- Remaining release gates:
  - verify Render/Supabase hosted runtime;
  - prove worker/cron operation with the phone closed;
  - process closed-loop learning outbox from real terminal Alpaca and Kraken records.

## 2026-07-18 Phase 5 Autonomous Production Spine

- Added `src/ai_trader/production_spine.py` with deterministic foundations for:
  - production database spine readiness;
  - worker supervision;
  - canonical reconciliation cases;
  - closed-loop learning runs;
  - Portfolio Manager decisions;
  - Market Data Gateway validation;
  - strategy promotion and demotion.
- Added Phase 5 schema initialization to the API startup path.
- Added `GET /phase5-status`.
- Added `phase5_status` to `GET /status`.
- Added an `Autonomous Production Spine` card to the mobile Dashboard.
- Added Phase 5 architecture documentation and Founder briefing.
- Verification:
  - `python -m compileall src` passed.
  - `python -m unittest tests.test_phase5_production_spine` passed: 9/9.
  - `python -m unittest tests.test_always_on_operations` passed: 10/10.
- Remaining release gates:
  - complete the full Postgres/Supabase migration for all critical runtime families;
  - deploy and verify `/phase5-status` from Render;
  - verify worker and cron evidence while the mobile app is closed;
  - wire Portfolio Manager and strategy maturity gates into every production approval path.

## 2026-07-18 Supabase/Postgres Always-On Evidence Backend

- Added `AI_TRADER_DATABASE_BACKEND` and `DATABASE_URL`/`SUPABASE_DATABASE_URL` configuration.
- Added Postgres support for the Always-On operations evidence tables:
  - `SCHEDULED_JOB_RUNS`
  - `WORKER_HEARTBEATS`
  - `RESEARCH_FUNNELS`
  - `SHADOW_TRADES`
  - `OPERATIONS_INCIDENTS`
- Kept SQLite as the default local/test backend.
- Added `database_backend` visibility to `/operations-health` so Render can prove whether Always-On evidence is using SQLite or Supabase/Postgres.
- Updated `render.yaml` with database backend placeholders while keeping worker/cron disabled until Postgres is confirmed active.
- Updated `architecture/SUPABASE_POSTGRES_MIGRATION_PLAN.md`, `architecture/RENDER_SERVICE_TOPOLOGY.md`, and `architecture/DATABASE_REFERENCE.md`.
- Remaining release gates:
  - set `AI_TRADER_DATABASE_BACKEND=postgres` and `DATABASE_URL` in Render;
  - deploy and verify `/operations-health` reports `database_backend.active_backend = postgres`;
  - enable Render worker/cron only after the shared datastore is confirmed;
  - migrate broker runtime, recommendations, lifecycle, audit, report, and learning tables in later controlled steps.

## 2026-07-17 Always-On Operations and Alpaca Research Recovery

- Added explicit runtime entry points:
  - `python -m ai_trader serve-api`
  - `python -m ai_trader run-worker`
  - `python -m ai_trader run-job <job-name>`
- Added durable operations tables:
  - `SCHEDULED_JOB_RUNS`
  - `WORKER_HEARTBEATS`
  - `RESEARCH_FUNNELS`
  - `SHADOW_TRADES`
  - `OPERATIONS_INCIDENTS`
- Added idempotent scheduled job claiming so duplicate workers/jobs cannot silently double-run the same scheduled cycle.
- Added worker heartbeat recording and stale-worker operations health.
- Added research funnel recording for Alpaca and Kraken so no-trade outcomes now have primary and secondary reasons.
- Added shadow trade records from generated proposals. Shadow records remain separate from broker orders and never submit trades.
- Added endpoints:
  - `/operations-health`
  - `/scheduler-status`
  - `/job-runs`
  - `/shadow-trades`
  - `/shadow-performance`
  - `/research-funnel`
  - `/alpaca-inactivity-diagnosis`
- Added a Dashboard 24-Hour Operations card in the mobile app.
- Added worker/cron process commands and documented the Render target topology. `render.yaml` deliberately keeps only the current web service active until Supabase/Postgres is connected, because SQLite must not be treated as a safe multi-process production datastore.
- Added Always-On documentation pack under `architecture/`.
- Added `architecture/SUPABASE_POSTGRES_MIGRATION_PLAN.md` documenting Supabase Postgres as the recommended production datastore target.
- Verification:
  - Focused Always-On tests passed: 9/9.
- Remaining release gates:
  - migrate production state to Supabase/Postgres or equivalent shared datastore;
  - enable Render worker/cron services against that datastore;
  - verify live worker heartbeat;
  - verify cron job execution while the app is closed;
  - prove one fresh Alpaca research cycle reaches either a correctly submitted paper order or a persisted no-trade reason.

## 2026-07-17 World-Class Trader Transformation Phase 4-8

- Added a detailed implementation plan for the controlled Phase 4-8 programme.
- Added Operational Truth:
  - canonical broker-neutral lifecycle;
  - legal transition checks;
  - idempotent broker event recording;
  - Alpaca/Kraken reconciliation health;
  - execution cost, true R, MAE, and MFE calculation helpers.
- Added provider-neutral Market Intelligence foundation:
  - market observation schema;
  - candle quality validation;
  - multi-timeframe conclusions;
  - separated fundamental, macro/event, and news/catalyst evidence tables;
  - Regime 2.0 supporting/contradictory evidence.
- Added Portfolio Intelligence:
  - asset metadata;
  - exposure snapshots;
  - concentration warnings;
  - correlation warnings;
  - proposed-trade portfolio impact.
- Added Experience Engine:
  - immutable experience records;
  - post-trade reviews;
  - historical analogues;
  - governed learning proposals.
- Render startup now initializes the new schemas additively.
- Startup and broker-history writes now reconcile Alpaca/Kraken broker rows into the canonical lifecycle.
- Added `/operational-truth` and `/world-class-evidence`.
- `/status` now includes `world_class_evidence`.
- Recommendation auto-trade eligibility now requires both strongest argument for and strongest argument against.
- Mobile Dashboard now starts with a concise command summary and prioritizes Alpaca/Kraken; future brokers move to a compact Future Connections section.
- Mobile Portfolio now shows operational truth and portfolio intelligence summaries.
- Recommendation cards now show decision summary, why trade, why not trade, invalidation, and why waiting may be better before technical evidence.
- Verification so far:
  - `py_compile` passed for new backend modules and API.
  - Focused World-Class Transformation tests passed: 6/6.
  - Full suite, Expo Doctor, Render deploy verification, and installed-app verification remain release-gate items.

## 2026-07-17 Institutional Intelligence & Founder Experience Phase 3

- Added the architectural principle that every new capability must help AI Trader make a better investment decision, help the Founder make a better decision, or help AI Trader learn to make better future decisions.
- Reworked strategy selection so live intelligence chooses from candidate strategies using market intelligence, regime, trend, momentum, volatility, breakout/range evidence, and crypto risk/liquidity where available.
- Strategy selections now record selection rationale, candidate scores, rejected alternatives, production-readiness notes, and validation status.
- Added Strategy Lab walk-forward validation with train/test windows, out-of-sample aggregation, cost/slippage assumptions, buy-and-hold benchmark comparison, and bias-control notes.
- Expanded portfolio intelligence with exposure, proposed notional, largest position, proposed risk contribution, diversification, capital efficiency, and explicit unknown-data notes.
- Added `founder_experience` to `/status`, grouped into executive dashboard, portfolio command, market intelligence centre, and learning lab payloads.
- Reframed the mobile app into five Founder-facing screens: Dashboard, Recommendations, Portfolio, Market, and Learning.
- Added a dark executive shell with white decision cards, status pills, and plain-English cards for the Founder.
- Added Phase 3 documentation and Founder briefing.
- Verification so far:
  - `py_compile` passed for `src/ai_trader/trading_intelligence.py` and `src/ai_trader/api.py`.
  - Focused Trading Intelligence tests passed: 13/13.

## 2026-07-07 Autonomous Trading Readiness Sprint - Post-Sprint Status

Implemented against the Go-Live Readiness Review. Full change list in
`governance/IMPLEMENTATION_LOG.md`. Rated against what's enforced in code and verified in
this session, not against what's merely documented.

| Category | Status | Why |
|---|---|---|
| Broker integrations | Green | Orchestrator-only execution (manual approval routed through it too); Kraken validate-mode default fixed; Kraken pair/price logic de-duplicated into one implementation. |
| Research engine | Green | Due-diligence floors removed; live CoinGecko-backed crypto knowledge engine; equities research unchanged (still Alpaca/OpenAI-backed). |
| Trading engine | Green | Continuous order/exit monitoring (60s loops, not manual-only); trailing stops; crypto proposal generation implemented and verified end-to-end (previously did not exist at all). |
| Risk management | Green | Daily/weekly/monthly loss, drawdown, and portfolio exposure limits enforced from real snapshot history; per-broker account context (previously Kraken sizing used Alpaca's paper equity). |
| Operational resilience | Green | Scheduler and monitoring loops survive exceptions and notify instead of dying silently; startup reconciliation; atomic exit bookkeeping. |
| Mobile | Amber | Risk Limits section, in-app notification center, broker-specific auto-trading controls, and clearer all-broker Emergency Stop copy added. Native push (`expo-notifications`) was not added to the client - backend is ready (`/register-push-token`, Expo push dispatch), but the client integration needs a rebuild this environment can't verify. |
| Security | Green | Hosted API without `AI_TRADER_API_TOKEN` now starts read-only and rejects POST trading/control commands; token comparison is constant-time; per-IP lockout added. `.env`'s live keys were left untouched - Founder action, not something this sprint could safely do. |
| Architecture | Amber (unchanged, out of scope) | The `api.py` god-file / broker-addition-touches-many-files findings remain - deliberately not tackled alongside dozens of behavior changes in one sprint. Recommended fast-follow. |

**Verified this session:** all 66 unit tests pass (55 pre-existing + 11 new); the full
crypto research -> due diligence -> proposal -> orchestrator -> order -> stop-loss exit ->
performance-attribution pipeline was exercised end-to-end with a fake broker adapter (no
real network/broker calls) and confirmed working, including catching and fixing three real
bugs (crypto trading-hours guardrail, risk-percentage miscalculation, paper-trading-only
misapplied to Kraken) that would otherwise have silently kept Kraken from ever trading.

**Not verified / Founder action required:**
- Live Alpaca/Kraken/OpenAI network calls (deliberately not exercised - real API quota and,
  for Kraken, real-money risk).
- Mobile push delivery end-to-end (needs a rebuilt app on a physical device).
- Render environment configuration (`AI_TRADER_API_TOKEN` actually being set in the live
  service) - not verifiable from the repo.
- Render post-deploy route stability is partial: `/healthz` and `/status` return 200 on the
  hosted service after the push, but `/notifications`, `/performance-attribution`, and a
  no-token POST check were not stable from external verification and need Render log review.
- Rotating the live keys found in the root `.env` file (present on disk, not committed to
  git - rotate in the Alpaca/OpenAI dashboards as a precaution).
- Enabling any live-trading switch (`KRAKEN_AUTO_TRADING`, `KRAKEN_LIVE_TRADING_APPROVED`,
  `INVESTMENT_POLICIES.crypto_enabled`) - this sprint made the system safe to enable, not
  enabled; flipping those switches is a deliberate Founder decision.

## 2026-07-07 Trading Learning and Kraken Allocation Follow-Up

- Kraken portfolio display now separates full exchange visibility from AI Trader's governed trading pot:
  - `Total Estimated Balance` estimates the whole Kraken balance in GBP where prices are available.
  - `GBP Cash` shows cash returned by Kraken.
  - `AI Trading Allocation` is capped by `KRAKEN_TRADING_ALLOCATION_GBP` and defaults to GBP 100.
- Kraken account context and risk sizing now use the trading allocation, not the full exchange balance.
- Command Centre trade history is now visually collapsible. Tapping a trade opens entry, exit, quantity, P&L, reasons, and broker payload; tapping again closes it.
- `GET /daily-learning-update` added for a daily plain-English review of closed trades, wins/losses, guardrail rejections, benchmark/successful-trader learning, and Founder-approved improvement recommendations.
- Intelligence screen now shows the Daily Trading Learning Update so the Founder can see what AI Trader learned the previous day without opening the database.
- Mobile app now reads performance attribution and broker trade history so Kraken/crypto trades can surface entry, exit, and P&L detail when available.
- Backend commit pushed: `79df559`.
- Mobile OTA updates published for runtime `1.0.1`:
  - `preview` update group: `854ca353-8bd3-4590-8153-dd7b1d4a0c7d`.
  - `hosted-preview` update group: `3388fe5e-18ee-4a19-8ee8-11b1049a4fbb`.
- Hosted checks after push: `/healthz`, `/status`, and `/recommendations` returned 200; `/daily-learning-update` and `/performance-attribution` were not reachable from this environment and need Render log review if they remain unavailable after deployment settles.

## 2026-07-07 On-Demand Trading Reports Follow-Up

- Added `GET /trading-report` and `POST /generate-report`.
- Reports can now be generated for today, yesterday, morning, evening, all brokers, or one selected broker.
- Mobile Command Centre now has a Reports section with Today Report, Yesterday Report, Morning Report, and Evening Report buttons.
- Each broker panel now includes a broker-specific Daily Report button.
- Generated reports are displayed in the app immediately and saved as Markdown under the configured output directory.
- Generated reports are now saved under the output folder's `reports/` directory, stored in SQLite table `TRADING_REPORTS`, and served in the browser at `/reports/{report_id}`.
- The mobile app opens the report browser page automatically and provides an `Open Report` button on the generated report panel.
- Reports explain P&L movement using broker snapshots, closed performance attribution, broker trade history, guardrail/orchestrator rejections, and learning recommendations.
- Reports now include a fuller trade-performance structure for daily, morning, evening, weekly, and monthly windows: start/end balance, period performance, all closed trades with entry/exit/times/P&L, broker trade rows, why money was won or lost, lessons learned, and Founder-approved improvement recommendations.
- Reports now also reconstruct P&L from raw broker fills where buy and sell fills can be matched, and explicitly list open/unmatched fills when the movement is likely unrealised/open-position P&L.
- Verified Python tests: 70/70.
- Verified Expo Doctor: 17/17.

## Working

- Python runtime installed and verified: Python 3.12.10.
- Required dependency installed: `tzdata`.
- Unit tests pass: 55/55.
- `.env` loading works.
- Alpaca Paper Trading connection works.
- Alpaca account retrieval works.
- Alpaca position retrieval works.
- OpenAI API key works with `OPENAI_MODEL=gpt-4.1-mini`.
- AI proposal generation works with configured guardrail constraints.
- Execution Engine validates proposals independently before submission.
- Alpaca Paper Trading bracket order submission works.
- SQLite audit logging works for the real proposal and execution lifecycle.
- Trading Journal append works for the real proposal and execution lifecycle.
- Founder Brief generation works.
- Investment Intelligence Engine schema works locally in SQLite.
- Initial curated investment watchlist seeded.
- Market themes seeded.
- Daily intelligence refresh appends company updates without overwriting historical rows.
- Knowledge Engine Report generated.
- Benchmark trader intelligence schema added.
- Benchmark trader seed research added using public-information-only rules.
- Local API added for mobile app reads and guarded commands.
- Expo mobile app added with three screens.
- Local `.venv` created and verified.
- VS Code interpreter pinned to `.venv\Scripts\python.exe`.
- One-command startup script added.
- Read-only browser-based SQLite viewer added.
- Developer Dashboard added.
- Hosted backend deployment path added.
- API token authorization added for hosted use.
- Mobile app can send a bearer token to hosted API.
- Docker and Render blueprint added.
- Recommendations now expose generated time, expiry time, and Fresh/Stale/Expired status.
- Expired recommendations are blocked before execution.
- Paper-only auto execution added for eligible recommendations at or above 85% confidence.
- Mobile recommendations screen now supports Refresh, Run New Analysis, and Auto Execute 85%+.
- Command Centre now shows richer recent transaction and recommendation summary data.
- Mobile broker cards now carry the normal Enable Auto Trading / Disable Auto Trading controls; the global row is an all-broker Resume/Emergency Stop safety switch.
- Market Intelligence now shows theme definitions, drivers, and risks.
- Expo OTA update published to the `preview` branch.
- Investment Orchestrator layer added between AI recommendations and broker execution.
- Standard broker adapter interface added.
- Alpaca integration wrapped as `AlpacaBrokerAdapter`.
- Placeholder IBKR, Saxo, and Kraken adapters added with not-configured responses only.
- Auto Paper Trading mode is controlled by `AUTO_PAPER_TRADING` and defaults to false.
- Orchestrator decisions, auto trade events, and morning/evening briefs are appended to SQLite.
- Research scheduler helper added for local or Render scheduled research runs.
- Render blueprint configured to run the hourly background research scheduler in Docker with auto paper trading disabled by default.
- Existing three mobile screens updated with orchestrator, auto-paper, broker, availability, market, and brief fields.
- Sprint 5 robust parsing prevents qualitative scores such as `Good` from crashing recommendations.
- Portfolio snapshots and research run tracking added.
- Command screen exchange selector and executive summary added.
- Kraken and Coinbase safe adapter preparation added.
- Crypto universe table added without dummy ranking data.
- Founder-governed policy documents added for investment policy, risk management, broker execution, AI learning, and investment universe.
- Foundation policy tables added for investment, risk, broker, learning, capital allocation, due diligence, investment scores, broker decisions, and execution decisions.
- Crypto knowledge schema expanded for project analysis, tokenomics, on-chain metrics, sentiment, risk, news, benchmark alignment, and trading history.
- Investment Orchestrator now records due diligence, investment score, broker decision, execution decision, and capital allocation before autonomous execution.
- Kraken adapter supports `KRAKEN_PRIVATE_KEY` while keeping trading disabled by default.
- Broker-specific auto trading is stored in SQLite and exposed through `POST /broker-auto-trading`.
- Command Centre broker panels are driven by backend broker runtime state.
- Recommendation history sets are persisted for audit.
- Recommendation cards are grouped by broker, collapsed by default, sorted by confidence, and filterable.
- Kraken read integration validates credentials, balances, holdings, open orders, closed orders, trade history, and ticker prices.
- Notification events are queued in SQLite for research, broker control, and trade lifecycle events.
- Kraken controlled live micro-trading path added behind explicit `KRAKEN_LIVE_TRADING_APPROVED` and `KRAKEN_SUBMIT_REAL_ORDERS` switches.
- Mechanical seatbelts added for Kraken: duplicate order locks, max/min order size, allowed pairs, max open trades, GBP balance check, mandatory exits, broker confirmation, managed exit tracking, and protective exit monitoring.
- Mobile recommendation history is cached locally as a fallback so reopening the app does not blank the screen during backend/network gaps.
- Intelligence company names link to matching recommendation cards when a recommendation exists.

## Multi-Broker Autonomous Platform Sprint

- New backend module: `src/ai_trader/multi_broker.py`.
- New SQLite tables:
  - `BROKER_AUTO_TRADING_SETTINGS`
  - `BROKER_RUNTIME_STATE`
  - `BROKER_TRADE_HISTORY`
  - `NOTIFICATION_EVENTS`
  - `RECOMMENDATION_SETS`
  - `CRYPTO_RESEARCH_SCORES`
- New endpoint: `POST /broker-auto-trading`.
- New environment variables:
  - `ALPACA_AUTO_TRADING`
  - `KRAKEN_AUTO_TRADING`
  - `COINBASE_AUTO_TRADING`
  - `BINANCE_AUTO_TRADING`
  - `IBKR_AUTO_TRADING`
- Tests: 55/55 passing inside `.venv`.

## Foundation Sprint Autonomous Investment Platform

- New governance documents:
  - `governance/INVESTMENT_POLICY_STATEMENT.md`
  - `governance/RISK_MANAGEMENT_POLICY.md`
  - `governance/BROKER_EXECUTION_POLICY.md`
  - `governance/AI_LEARNING_POLICY.md`
  - `governance/INVESTMENT_UNIVERSE.md`
- New implementation plan: `governance/FOUNDATION_SPRINT_IMPLEMENTATION_PLAN.md`.
- New Founder brief: `governance/EXECUTIVE_FOUNDER_BRIEF_FOUNDATION_SPRINT.md`.
- Mobile remains three screens only: Command, Recommendations, Intelligence.
- Command screen now exposes broker panels for Alpaca and Kraken.
- Recommendation cards expose due diligence status and structured Investment Score fields.
- Intelligence screen exposes Alpaca and Kraken intelligence sections.
- Tests: 48/48 passing inside `.venv`.

## Validation Result

The resumed Validation Sprint completed one end-to-end paper trade on 2026-07-02.

- Symbol: AAPL
- Proposal ID: `581de766-62ff-4d16-9e7e-6b27407c29b0`
- Alpaca parent order ID: `94de407a-8a6d-42ab-a991-de938ef27e6e`
- Quantity: 333 shares
- Alpaca confirmation: parent paper buy order filled; bracket exit orders present.
- Proposal file: `data/validation_proposals_2026-07-02.json`
- Founder Brief: `data/founder_briefing_2026-07-02.md`

## Notes

During the resumed run, the first AI proposal was correctly rejected because the prompt did not state the configured guardrail thresholds and decimal risk format. The fix was limited to passing guardrail constraints into the OpenAI proposal prompt. The next proposal passed guardrails and executed successfully in Alpaca Paper Trading.

## Sprint 2 Investment Intelligence Engine

Sprint 2 created a local SQLite-backed knowledge base for long-term investment research. Version 1.0 trading remains frozen and unchanged.

- Tables created: `COMPANY_MASTER`, `COMPANY_FINANCIALS`, `COMPANY_DAILY_UPDATES`, `INVESTMENT_WATCHLIST`, `MARKET_THEMES`.
- Initial watchlist: 31 companies.
- Market themes: 10.
- Database: `data/audit.sqlite3`.
- Schema document: `governance/INVESTMENT_INTELLIGENCE_SCHEMA.md`.
- Knowledge Engine Report: `governance/KNOWLEDGE_ENGINE_REPORT.md`.
- Generated data report: `data/INVESTMENT_INTELLIGENCE_ENGINE_REPORT.md`.
- Tests: 6/6 passing.

## Sprint 3 Mobile App + Benchmark Intelligence

Sprint 3 keeps Version 1.0 trading frozen and continues using local SQLite.

- New tables: `BENCHMARK_TRADERS`, `BENCHMARK_DAILY_RESEARCH`.
- Benchmark schema document: `governance/BENCHMARK_INTELLIGENCE_SCHEMA.md`.
- Benchmark brief output: `data/BENCHMARK_TRADER_INTELLIGENCE_BRIEF.md` when `benchmark-init --report` or `serve-api` runs.
- Local API module: `src/ai_trader/api.py`.
- CLI API command: `python -m ai_trader.cli serve-api --host 127.0.0.1 --port 8765`.
- Mobile app: `mobile/App.js`.
- Mobile screens: Trading Command Centre, AI Recommendations, Market Intelligence.
- Missing or unavailable data is surfaced as `Not available` rather than fabricated values.
- `approve-and-execute` reconstructs stored proposals and sends them through the existing Execution Engine guardrails.
- Current test suite: 33/33 passing inside `.venv`.

## Sprint 4 Investment Orchestrator

Sprint 4 keeps Paper Trading only and does not add mobile screens.

- New backend modules:
  - `src/ai_trader/broker_adapters.py`
  - `src/ai_trader/orchestrator.py`
  - `src/ai_trader/scheduler.py`
- New SQLite tables:
  - `ORCHESTRATOR_DECISIONS`
  - `AUTO_TRADE_EVENTS`
  - `DAILY_BRIEFS`
- New CLI commands:
  - `morning-brief`
  - `evening-brief`
  - `research-once`
- Updated mobile screens:
  - Trading Command Centre shows Auto Paper Trading status, selected brokers, next research run, last orchestrator decision, morning/evening brief summaries, cloud API health, and Paper mode.
  - AI Recommendations show asset availability, suggested broker, exchange, market status, auto eligibility, rejection reason, confidence, philosophy fit, stop loss, and take profit.
  - Market Intelligence shows 24/7 research status, market-open summary, benchmark observations, theme updates, and recent learning.
- Tests: 33/33 passing inside `.venv`.

## Sprint 5 Operational Clarity

- New table: `PORTFOLIO_SNAPSHOTS`.
- New table: `RESEARCH_RUNS`.
- New table: `CRYPTO_ASSET_MASTER`.
- Recommendations use robust score parsing for qualitative AI/intelligence values.
- Alpaca dashboard fields now include explicit unavailable reasons.
- Benchmark brief falls back to latest seeded research with an explicit reason when today's rows are unavailable.
- Kraken and Coinbase adapters return not-configured or disabled responses unless credentials and trading flags are explicitly configured.
- Existing Command screen now has an executive summary and exchange selector.
- Existing Intelligence screen now shows research freshness and benchmark source/confidence fields.
- Tests: 42/42 passing inside `.venv`.
- Published to GitHub `master` at commit `cfcd023` so Render can auto-deploy if auto-deploy is enabled.
- Hosted Render health checks were attempted immediately after push, but `https://trader-no0f.onrender.com` was not accepting connections from this environment at that moment.

## Sprint 3.1 Developer Experience

Root cause of the VS Code `python` issue:

- `python` resolved to the Windows Store app execution alias at `C:\Users\t_jeh\AppData\Local\Microsoft\WindowsApps\python.exe`.
- That shim failed with: "A specified logon session does not exist. It may already have been terminated."
- The working interpreter is Python 3.12.10.
- The project now uses `.venv\Scripts\python.exe` through VS Code settings and project scripts.

Developer workflow:

- One-command startup: `.\start_project.ps1`.
- Local API helper: `scripts/start_local_api.ps1`.
- Mobile helper: `scripts/start_mobile_app.ps1`.
- Read-only database browser: `scripts/browse_database.ps1`.
- Developer Dashboard: `developer_dashboard.html` and `http://127.0.0.1:8765/developer-dashboard`.
- Tests: 14/14 passing inside `.venv`.

## Sprint 3.2 Mobile Trading Usability

Sprint 3.2 keeps the trading engine, execution engine, knowledge engine, mobile app structure, and SQLite storage intact.

- Recommendation freshness added:
  - Fresh/Stale/Expired status.
  - Generated and expiry timestamps.
  - Execution blocked for expired recommendations.
- Auto execution added for Paper Trading only:
  - Minimum confidence: 85%.
  - Existing Execution Engine guardrails still enforce execution.
  - Expired, duplicate, and guardrail-failed recommendations are skipped.
- API controls added:
  - `POST /start-trading`
  - `POST /auto-execute-recommendations`
- Mobile app updates:
  - Recommendations screen has Refresh, Run New Analysis, and Auto Execute 85%+.
  - Trading Command Centre shows recent transactions and recommendation counts.
  - Pause/Resume/Stop button cluster replaced by broker-specific controls plus an all-broker emergency stop.
  - Market Intelligence shows theme definitions, key drivers, and key risks.
- Tests: 14/14 passing inside `.venv`.

## Sprint 3.2 OTA Update

An EAS Update was published for the mobile JavaScript changes.

- Branch: `preview`.
- Runtime version: `1.0.0`.
- Update group ID: `0727fd0a-4216-413c-affa-5c712cbc1155`.
- Android update ID: `019f2473-739d-78e5-849e-99092758dd78`.
- EAS dashboard: `https://expo.dev/accounts/nexuspay/projects/ai-trader-mobile/updates/0727fd0a-4216-413c-affa-5c712cbc1155`.

During the update, EAS installed and configured `expo-updates`:

- `expo-updates`: `~0.25.28`.
- `updates.url`: `https://u.expo.dev/58ca35af-2cf4-44a0-8da4-7f02563b635f`.
- `runtimeVersion.policy`: `appVersion`.

Important: the APK already installed before this configuration may not receive OTA updates. Builds created after this configuration are eligible for EAS Updates.

Fresh APK build after OTA channel configuration:

- Build ID: `d5ff21b3-6685-4940-a2d4-550cd0d9e984`.
- Preview channel: `preview`.
- APK: `https://expo.dev/artifacts/eas/c3aEW5gWWhVHVim0Mk2fwTGnRl7aCKosQkpYnC6n9VQ.apk`.
- Purpose: replace the earlier APK that did not have `expo-updates`/preview channel configured.

Follow-up OTA for mobile usability fixes:

- Update group ID: `c4e78a76-6233-48aa-a2ee-85ce3223007e`.
- Android update ID: `019f2657-bc70-7c6f-9e33-91ef6e217fc1`.
- EAS dashboard: `https://expo.dev/accounts/nexuspay/projects/ai-trader-mobile/updates/c4e78a76-6233-48aa-a2ee-85ce3223007e`.
- Added pull-to-refresh on all three app screens.
- Reformatted recommendation confidence from decimals to percentages.
- Reformatted timestamps into readable local date/time text.
- Added clearer auto-trade eligibility reason text.
- Added friendlier recent transaction wording.
- Restarted the local API after backend endpoint updates.

Hosted APK build:

- Build ID: `7e6b53a3-d492-4594-af36-4e56199878d4`.
- Channel: `hosted-preview`.
- APK: `https://expo.dev/artifacts/eas/s2G1DWe4aWyNiBCH7S1bJgXYmhoq8f8gSE3D6UQfe5U.apk`.
- Backend URL baked into original hosted build/update: `https://ai-trader-api.onrender.com`.
- Active Render backend URL: `https://trader-no0f.onrender.com`.
- Hosted OTA update group ID: `f9a4c794-8305-47d2-83a1-99fb5b777057`.
- Hosted Android update ID: `019f2669-3a99-765d-99f1-d747aff4f9db`.
- Hosted EAS dashboard: `https://expo.dev/accounts/nexuspay/projects/ai-trader-mobile/updates/f9a4c794-8305-47d2-83a1-99fb5b777057`.
- Current hosted backend check target: `https://trader-no0f.onrender.com/healthz`.
- Render health check passed: `GET /healthz` returned 200.
- Render status check passed: `GET /status` returned 200.
- Render portfolio check passed: `GET /portfolio` returned Alpaca Paper account data.
- Render themes check passed: `GET /intelligence/themes` returned SQLite theme data.
- Render recommendations check passed, currently returning an empty list because cloud SQLite has no generated proposals yet.

Hosted OTA update for active Render URL:

- Branch: `hosted-preview`.
- Update group ID: `bc319f3f-0bba-48fd-992a-30601f92c2d5`.
- Android update ID: `019f27ac-1393-79d5-b822-fa82ee3cfe37`.
- EAS dashboard: `https://expo.dev/accounts/nexuspay/projects/ai-trader-mobile/updates/bc319f3f-0bba-48fd-992a-30601f92c2d5`.

Follow-up OTA to remove laptop API URL from all preview builds:

- `preview` branch update group ID: `dd05b9df-40bd-43c9-99eb-7dd3d129e24b`.
- `preview` Android update ID: `019f27b7-de37-7fb0-97b6-d397fe7d2058`.
- `hosted-preview` branch update group ID: `895a6212-1e33-404f-8437-61ddf553adab`.
- `hosted-preview` Android update ID: `019f27b8-c67a-797e-8feb-19d810b71283`.
- Both mobile preview channels now use `https://trader-no0f.onrender.com`.

Hosted analysis/activity follow-up:

- Backend commit: `3b85c07`.
- Render `/run-analysis` now scans up to 30 companies and skips broker-rejected symbols instead of failing the whole request.
- Verified unsupported symbol handling with `AAPL` and `NOVO-B`: request returned 200 and listed `NOVO-B` in `skipped_symbols`.
- Mobile now handles empty/non-JSON backend responses more clearly.
- Mobile Run Analysis message now explains when no safe recommendations were generated.
- Mobile Command Centre now displays Alpaca recent orders/fills from `/portfolio` as broker activity.
- Recommendation cards now show passed guardrails as well as failed guardrails for clearer trade decisions.

## 2026-07-19 Production Evidence Activation

- Activated one shared Founder evidence feed over Supabase/Postgres for Dashboard, Activity, Recommendations, Portfolio, Market and Learning.
- The paid Render worker now schedules research independently of the phone and continues heartbeat updates during slow broker calls.
- Corrected Kraken research so one unavailable pair cannot abort the remaining approved universe.
- Live hosted proof on revision `573c36b3`:
  - worker heartbeat advanced during autonomous work;
  - scheduler `active`;
  - Founder state `OPERATING NORMALLY`;
  - database `postgres`;
  - four research runs, 36 assets analysed and 24 recommendations in the verified 24-hour view;
  - two broker snapshots and 20 bounded trade-history rows returned to the Founder read model.
- No new order passed every gate during verification. This is persisted and displayed as governed inactivity, not hidden as missing data.
- Recorded net realised P&L was `-0.54616884`, representing known fees against zero matched realised P&L; full account mark-to-market performance is not inferred from this number.
- Verification passed:
  - Python suite: 148 tests;
  - Expo Doctor: 17/17;
  - Android export: passed.
- Expo OTA runtime `1.0.2` published:
  - `hosted-preview`: `daa2d530-92b9-4ea8-b358-50ae8ced9648`;
  - `preview`: `ca32b0ba-a219-4dbf-b418-138b32873749`.
- `preview` OTA update group ID: `da0f2e4d-8ecc-4fff-b026-1693ca3ca139`.
- `hosted-preview` OTA update group ID: `b6ae021d-9936-4003-972f-b719f79fb4b1`.

Guardrail positives follow-up:

- Backend commit: `cdda131`.
- Recommendation API now includes side-aware `guardrail_checks` and `guardrail_passes`.
- Mobile recommendation cards now show overall result, passed guardrails, and failed guardrails.
- `preview` OTA update group ID: `bd26298e-5373-4c20-8319-b18f52135adc`.
- `hosted-preview` OTA update group ID: `2b920796-6648-4c8f-acb7-e2088213c4f0`.

Recommendation persistence follow-up:

- Backend commit: `2bb6f18`.
- Recommendation API now returns saved recommendation history from SQLite instead of only a short current list.
- Recommendation cards are ordered by highest confidence first, then newest.
- Auto Execute 85%+ now returns per-symbol skip reasons, including guardrail failures, expired ideas, and already executed recommendations.
- Market Intelligence now includes monitored companies so sectors/themes can be connected to recommendation cards.
- `preview` OTA update group ID: `55d45b77-db90-4f57-b411-38d067ef6382`.
- `hosted-preview` OTA update group ID: `93fa34c0-db77-4e8b-a198-6e85ac2e393f`.

Unsupported broker symbol follow-up:

- Run Analysis now treats Alpaca `asset not found` responses as unavailable market data instead of a full command failure.
- The AI Trading Agent records unsupported/no-bar symbols as `agent_no_trade` events and continues scanning the remaining watchlist.
- Empty AI JSON responses are treated as no-trade results instead of backend errors.

## Hosted Backend Path

Option B has been scaffolded so the phone app can point to an always-on backend instead of the laptop.

- Dockerfile: `Dockerfile`.
- Render blueprint: `render.yaml`.
- Environment template: `cloud.env.example`.
- Hosted API test helper: `scripts/test_hosted_api.ps1`.
- Mobile EAS profile: `hosted-preview`.
- Health check: `GET /healthz`.
- Auth: optional `AI_TRADER_API_TOKEN` checked through `Authorization: Bearer <token>` or `X-API-Key`.

The next release build should use a real hosted API URL and API token in `mobile/eas.json`.

Local token-auth smoke test passed:

- `/healthz`: 200 without token.
- `/status`: 401 without token.
- `/status`: 200 with bearer token.
# Status Update - 2026-07-17

World-Class Trading Intelligence Transformation sprint implemented.

Current status:

- Trading Intelligence layer added before recommendation persistence.
- No recommendation is persisted unless the platform can articulate both the strongest argument for and strongest argument against the trade.
- Strategy registry, regime snapshots, signal evidence, trading committee reviews, probability estimates, confidence calibration snapshots, and lifecycle records are now stored in SQLite.
- Recommendation API and mobile recommendation cards now expose strategy, regime, probability, committee, signal, bull/bear, and lifecycle evidence.
- Existing Investment Orchestrator, Risk Engine, broker adapters, governance controls, Kraken seatbelts, Alpaca paper support, and execution pipeline remain protected.
- Automated Python suite passed: 90 tests.
- Mobile TypeScript check is not available because the Expo app does not include TypeScript as a dependency.

## Status Update - 2026-07-17 Phase 2

World-Class Trading Intelligence Phase 2 implemented.

Current status:

- Market intelligence now calculates trend, momentum, moving-average position, volatility, ATR percentage, volume trend, price structure, breakout/breakdown state, mean-reversion state, support, resistance, and data-quality evidence from available candles.
- Regime inference now consumes market-intelligence evidence and stores confidence plus contradictory evidence.
- Signal evidence is now independently scored from market data/context rather than simply mirroring proposal confidence.
- Strategy registry expanded to trend following, momentum, pullback, breakout, mean reversion, range trading, volatility expansion, swing continuation, crypto infrastructure trend, institutional accumulation, quality growth, and value pullback.
- Trading Committee now has deterministic independent member votes, questions, disagreements, and outcomes.
- Probability estimation now includes small-sample uncertainty, calibration evidence, signal/regime history, expected R, expected drawdown R, and confidence intervals.
- Strategy Lab primitives added for historical candle storage and deterministic backtest result storage.
- Performance Intelligence added for strategy-level win rate, expectancy, profit factor, drawdown, holding time, Brier score, and calibration error.
- Trade lifecycle records now support fees, slippage, R-multiple, MAE, MFE, and holding time fields.
- Recommendation API now merges normalized intelligence rows with the richer audit payload so strategy/regime/market evidence remains visible.
- Automated Python suite passed: 96 tests.
