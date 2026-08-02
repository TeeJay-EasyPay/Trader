# AI Trader — Current-State Architecture Snapshot (for redesign planning)

**Date:** 2026-08-02. **Purpose:** factual as-is description of the codebase, written for feeding
into an external architecture-planning session (ChatGPT). This is a snapshot, not a proposal — it
describes what exists today, warts included, so the redesign has an accurate starting point.
The `architecture/` folder already contains dozens of older documents (many dated mid-July, before
a large bug-fixing session on 2026-08-01); this file supersedes them for current-state purposes.

## 1. What this is

A personal, single-operator, AI-driven trading assistant. It researches equities (via Alpaca,
paper-trading only) and crypto (via Kraken, real money, capped at a small founder-set allocation),
generates trade proposals with LLM-assisted reasoning, runs them through a multi-stage governance
chain, and — when everything passes — submits real orders autonomously. It also tracks its own
decisions, outcomes, and (in principle) learns from them over time.

## 2. Deployment topology

- **Two Render services**, both Docker, both auto-deploying from `master` on every push:
  - **`Trader`** (web service, `srv-d93osvflk1mc739nga9g`, free plan) — runs `python -m ai_trader.cli
    serve-api`. Serves the HTTP API the mobile app (and this session's diagnostics) talk to.
  - **`Background AI Trader`** (background worker, `srv-d9e0v1urnols73dbve6g`, starter plan) — runs
    `python -m ai_trader run-worker --sleep-seconds 60`. This is where all scheduled jobs actually
    execute (research, auto-execution, broker polling, evidence snapshots, etc).
- **Database:** Postgres, hosted on Supabase (not a Render-managed Postgres instance). Also supports
  SQLite for local dev/tests (`selected_backend()` in `database.py` switches behavior).
- **Mobile app:** Expo/React Native (`mobile/`), built via EAS. Talks to the `Trader` web service.
- **No message queue, no cache layer, no separate worker pool.** Every scheduled job runs as its own
  fresh OS subprocess on the single background-worker instance, claimed via an idempotency key
  (`job_name:scheduled_for`) in a `SCHEDULED_JOB_RUNS` table. Concurrency, where it exists at all
  (e.g. Alpaca + Kraken broker-poll running together), is a `ThreadPoolExecutor` inside one worker
  cycle, not separate processes/instances.

## 3. Runtime / scheduling model

- `cli.py`'s `run-worker` command loops forever with a ~60s sleep between cycles.
- Each cycle computes which jobs are "due" (`_research_worker_jobs`, the equity-hours-gated block,
  etc. — a mix of flat intervals and market-hours/weekday gating) and runs them via
  `_run_pulsed_job` / `_run_broker_job_group`, each in its own subprocess with its own timeout.
- **Every job is fully independent and stateless between runs** — there is no long-lived in-process
  state (e.g. an open exchange websocket, a warm cache) carried between cycles. Anything that looks
  like "memory" is a database row.
- Per-job timeouts are currently individually tuned magic numbers in `config.py`
  (`worker_job_timeout_seconds=180` default, `evidence_snapshot_job_timeout_seconds=450`,
  `research_job_timeout_seconds=450`, `auto_execution_job_timeout_seconds=600`) — each was raised
  ad hoc as specific jobs were found timing out, not derived from any capacity model.
- **No structured alerting exists.** A job can fail or time out silently and nobody is notified
  unless a human happens to check logs or the dashboard. (This is the reliability gap currently
  being closed — see the accompanying commit for the alerting mechanism.)

## 4. Codebase module map

Total: **~26,800 lines** across 38 files in `src/ai_trader/`. Largest by line count:

| File | Lines | Responsibility |
|---|---|---|
| `api.py` | 6,152 | **The monolith.** HTTP route dispatch for the entire API surface, plus most business-logic methods on `LocalApiService` (research triggers, portfolio views, broker panel data, auto-execution, report generation, founder evidence, admin endpoints...). Grew by accretion; almost every feature added a few more `if path == ...` branches and a few more methods here. |
| `trading_intelligence.py` | 2,449 | Strategy registry (hand-authored strategy definitions), signal/regime/committee/probability evidence generation, **backtest and walk-forward validation engine**, confidence calibration. |
| `sprint6.py` | 1,428 | The "production governance" layer: `pre_execution_decision_packet` (Strategy → Portfolio → Risk → Sentinel chain), strategy maturity/promotion registry, operational events, kill switch, incident lifecycle, decision journal. |
| `always_on.py` | 1,231 | Worker heartbeats, scheduled-job claiming/idempotency, incident recording, shadow trades, research funnels. |
| `multi_broker.py` | 1,200 | Cross-broker runtime state, auto-trading on/off settings, order-intent locking (double-submission protection), notifications, push tokens, recommendation sets. |
| `production_evidence.py` | 1,194 | Founder-facing "evidence" snapshots and the 24-Hour Operations job-health summary (`_JOB_HEALTH_SPECS`). |
| `kraken_reconciliation.py` | 1,170 | Kraken-specific: reconciles broker evidence against explicitly-owned AI orders, isolated AI capital ledger (excludes personal holdings), reconciliation hold/override. |
| `autonomous_activity.py` | 1,016 | Activity-timeline aggregation for the mobile Command/Activity screens. |
| `production_spine.py` | 1,012 | Portfolio-manager decision (concentration/exposure checks), production risk sentinel, closed-loop learning run tracking. |
| `cli.py` | 935 | CLI entrypoints, worker main loop, job dispatch table, due-job scheduling logic. |
| `foundation.py` | 881 | Trading policy, capital allocation sizing, due-diligence assessment, investment scoring, broker-decision recording. Also owns most of the crypto fundamentals/sentiment/tokenomics table definitions (20 tables — the single largest table owner, many of them likely under- or unused; worth auditing). |

Full remaining files (each 100–800 lines) cover: operational-truth reconciliation, canonical
(broker-agnostic) trade lifecycle, orchestrator decision logic, broker adapters (Alpaca/Kraken/
placeholders for IBKR/Saxo/Coinbase), portfolio risk/exposure, market-intelligence-platform evidence
tables, operational snapshots, benchmark-trader comparison, experience/learning engine, database
connection handling, the trading agent (equity proposal generation), config/settings, and the
Alpaca/Kraken HTTP clients themselves.

**Dependencies are deliberately minimal:** `pyproject.toml` lists only `tzdata` and `psycopg[binary]`
as runtime dependencies. There is no requests library, no OpenAI SDK, no ORM — all HTTP calls
(Alpaca, Kraken, OpenAI) go through stdlib `urllib`, and all database access is hand-written SQL via
`psycopg`/`sqlite3` directly, no query builder or ORM layer anywhere.

## 5. Data model — ~100 tables across 20 files

No single schema file; each module owns and creates its own tables via a `CREATE TABLE IF NOT
EXISTS` script, called (in most but not all modules — see §7) through a per-process-cached
`initialize_*_schema` function. Rough functional grouping:

- **Research/proposals:** `trade_audit`, `CRYPTO_RESEARCH_SCORES`, `RESEARCH_RUNS`, `RESEARCH_FUNNELS`, `RECOMMENDATION_SETS`, `SHADOW_TRADES`
- **Governance/decisions:** `BROKER_DECISIONS`, `ORCHESTRATOR_DECISIONS`, `DECISION_JOURNAL`, `PORTFOLIO_MANAGER_DECISIONS`, `PRODUCTION_RISK_SENTINEL_DECISIONS`, `STRATEGY_ENTITLEMENT_DECISIONS`, `EXECUTION_DECISIONS`, `AUTO_TRADE_EVENTS`
- **Strategy/backtesting:** `STRATEGY_REGISTRY`, `STRATEGY_MATURITY_REGISTRY`, `STRATEGY_BACKTEST_RESULTS`, `STRATEGY_LAB_RUNS`, `STRATEGY_PROMOTION_DECISIONS`, `HISTORICAL_CANDLES`, `MARKET_REGIME_SNAPSHOTS`, `CONFIDENCE_CALIBRATION`, `PROBABILITY_ESTIMATES`, `TRADING_COMMITTEE_REVIEWS`
- **Execution/order safety:** `ORDER_INTENT_LOCKS` (double-submission protection), `MANAGED_TRADE_EXITS`, `MECHANICAL_SEATBELT_EVENTS`, `LOGICAL_TRADES`/`LOGICAL_TRADE_FILLS`/`LOGICAL_TRADE_EVENTS` (canonical cross-broker trade representation)
- **Kraken-specific:** `KRAKEN_AI_CAPITAL_LEDGER` (isolated allocation, excludes personal holdings), `KRAKEN_AI_ORDER_OWNERSHIP`, `KRAKEN_RECONCILIATION_CONTROL`/`_CASES`, `KRAKEN_RECONCILED_RESULTS`
- **Portfolio/risk:** `PORTFOLIO_SNAPSHOTS`, `PORTFOLIO_EXPOSURE_SNAPSHOTS`, `PORTFOLIO_RISK_CONTRIBUTIONS`, `PORTFOLIO_STRESS_TESTS`, `PORTFOLIO_CORRELATION_WARNINGS`, `CAPITAL_ALLOCATION_HISTORY`
- **Learning/experience:** `EXPERIENCE_RECORDS`, `HISTORICAL_ANALOGUES`, `LEARNING_PROPOSALS`, `POST_TRADE_REVIEWS`, `CLOSED_LOOP_LEARNING_RUNS`, `PRODUCTION_LEARNING_EVIDENCE`
- **Operations/observability:** `SCHEDULED_JOB_RUNS`, `WORKER_HEARTBEATS`, `OPERATIONS_INCIDENTS`, `OPERATIONAL_EVENTS`, `INCIDENT_LIFECYCLE`, `KILL_SWITCH_STATE`, `WORKER_SUPERVISION_RUNS`
- **Founder evidence:** `PRODUCTION_BROKER_SNAPSHOTS`, `PRODUCTION_FOUNDER_EVIDENCE_SNAPSHOTS`, `PRODUCTION_RECOMMENDATION_EVIDENCE`, `PRODUCTION_RESEARCH_EVIDENCE`, `PRODUCTION_TRADE_EVIDENCE`
- **Reference/fundamentals (crypto-heavy, `foundation.py`):** `CRYPTO_MASTER`, `CRYPTO_MARKET_DATA`, `CRYPTO_NEWS`, `CRYPTO_SENTIMENT`, `CRYPTO_ONCHAIN_METRICS`, `CRYPTO_TOKENOMICS`, `CRYPTO_PROJECT_ANALYSIS`, `CRYPTO_RISK`, `CRYPTO_BENCHMARK_ALIGNMENT`, `CRYPTO_DAILY_UPDATES`, `CRYPTO_TRADING_HISTORY`, plus equity equivalents in `intelligence.py` (`COMPANY_MASTER`, `COMPANY_FINANCIALS`, `COMPANY_DAILY_UPDATES`, `INVESTMENT_WATCHLIST`, `MARKET_THEMES`)
- **Market intelligence platform:** `MARKET_DATA_OBSERVATIONS`, `MARKET_DATA_QUALITY_EVENTS`, `MARKET_REGIME_EVIDENCE`, `MULTI_TIMEFRAME_INTELLIGENCE`, `NEWS_CATALYST_EVIDENCE`, `MACRO_EVENT_EVIDENCE`, `FUNDAMENTAL_EVIDENCE`
- **Benchmark comparison:** `BENCHMARK_TRADERS`, `BENCHMARK_DAILY_RESEARCH`

Many of these (particularly the ~20 crypto fundamentals tables in `foundation.py`, and several of
the market-intelligence-platform tables) were not touched or queried at all during an extensive
2026-08-01 production debugging session — worth explicitly auditing whether they're actually
populated/read anywhere, or are schema that was designed ahead of the feature that would use it.

## 6. How a trade actually happens today (equity or crypto)

1. A scheduled research job (`crypto-research` hourly for Kraken; `premarket-equity`/
   `market-open-equity`/`market-close-equity` for Alpaca, weekday market-hours-gated) generates
   `TradeProposal` objects and writes them to `trade_audit` as `agent_proposal` events, each carrying
   a bull case, bear case, confidence score, and (for crypto) technical/momentum/liquidity scores.
2. A separate scheduled job (`auto-execution-alpaca` / `auto-execution-kraken`) pulls recent
   proposals from `trade_audit`, and for each one whose resolved broker matches, calls
   `orchestrator.evaluate_recommendation`.
3. That function runs the proposal through: latest-intelligence lookup, broker/market-open checks,
   guardrail validation, trading-policy load, due-diligence assessment, investment scoring, capital
   allocation sizing (risk-based position sizing against the broker's *isolated* equity figure, not
   its whole account), then the "production governance" chain
   (`sprint6.pre_execution_decision_packet`: Strategy entitlement → Portfolio-manager concentration
   check → Risk Engine → Production Risk Sentinel), then a broker-specific reconciliation-hold check.
4. If approved: registers an execution intent, acquires an `ORDER_INTENT_LOCKS` row (a genuine
   double-submission safety mechanism — see §8), submits a real market order via the broker adapter
   (`place_bracket_order`), and on success records a `MANAGED_TRADE_EXITS` row so the position's exit
   is monitored going forward by a separate `managed-exits` job.
5. Exits, when triggered, feed back into `canonical_trades`/`LOGICAL_TRADES`, which (in principle)
   triggers the closed-loop learning workflow — this has never fired end-to-end in production yet,
   because no trade has gone terminal.

## 7. Known technical debt (found via a 2026-08-01 production debugging session)

- **`api.py` at 6,152 lines is the central maintainability problem.** It mixes HTTP routing, business
  logic, broker-panel formatting, report generation, and admin tooling in one file with no internal
  module boundaries. This is the primary target for the planned redesign.
- **The same bug was found independently in 7 different modules**: a schema-initialization function
  (`initialize_*_schema`) that ran its full `CREATE TABLE`/`ALTER`/seed sequence unconditionally on
  *every call* instead of once per process — the dominant, invisible cost behind several chronic job
  timeouts. Fixed with a `_SCHEMA_LOCK`/`_INITIALIZED_SCHEMA_KEYS` per-process cache pattern in:
  `kraken_reconciliation.py`, `trading_intelligence.py`, `multi_broker.py`, `operational.py`,
  `foundation.py`, `production_spine.py` (plus `always_on.py` and `canonical_trades.py`, which
  already had an equivalent pattern independently). **Still unfixed / still vulnerable to the same
  bug** as of this writing: `api.py`, `audit.py`, `benchmark.py`, `database_migration.py`,
  `experience_engine.py`, `intelligence.py`, `market_intelligence_platform.py`,
  `operational_truth.py`, `orchestrator.py`, `portfolio_intelligence.py`, `sprint6.py` (the last one
  has a partial guard — `_ensure_sprint6_schema` skips entirely on Postgres — but not the general
  per-process cache the others got). This recurring pattern strongly suggests the codebase has no
  shared base class or convention for schema-owning modules; each one reimplements
  connect-and-initialize from scratch.
- **No structured alerting.** A scheduled job (the real backtest/walk-forward engine,
  `strategy-lab-refresh`) crashed silently every single day for at least 3 consecutive days before
  anyone noticed, because nothing pages the founder on repeated job failure. This is the gap the
  accompanying reliability work closes.
- **No automated post-deploy verification.** Every fix on 2026-08-01 was verified by hand via curl
  against hosted endpoints and manually reading Render logs — there is no smoke-test suite that runs
  against the live/staging environment after a deploy.
- **Price staleness at execution time.** Stop-loss/take-profit levels and position sizing are
  computed from the price recorded when the research proposal was generated (up to 24h earlier for
  lower-confidence proposals), not refreshed immediately before order submission. Entries are market
  orders (so entry price itself is always live), but the *risk parameters* built around that entry
  can be stale relative to current price.
- **Crypto has no backtest coverage.** `refresh_strategy_lab` (the backtest/walk-forward job) is
  equity-only; crypto historical OHLC ingestion from Kraken was never built, so the crypto strategy
  (`crypto_trend_following_2r`) trades live without the same evidence-before-promotion rigor equity
  strategies get.
- **Heavy print()-based logging, no structured observability.** Diagnosis throughout the 2026-08-01
  session relied on grepping raw stdout log lines for `[stage=X]`-style prefixes added ad hoc to
  individual functions, not a consistent structured-logging/metrics layer.
- **Per-job timeouts are hand-tuned magic numbers**, raised reactively each time a specific job was
  found timing out, not derived from any load/capacity model. There is currently no mechanism that
  would catch a *new* job silently timing out other than someone noticing by hand (partially
  addressed by the alerting work).
- **~20 crypto fundamentals tables in `foundation.py`** (tokenomics, on-chain metrics, sentiment,
  project analysis, etc.) were not observed to be populated or read by anything during the debugging
  session — worth an explicit audit of whether they're live, dormant-but-planned, or dead schema.

## 8. Things that must be preserved, not just modularized

These are deliberate safety properties found and confirmed during 2026-08-01 debugging — a redesign
should keep them, not accidentally simplify them away:

- **Order-intent locking is deliberately one-directional-safe.** A lock only releases on a *definite*
  broker "no order was placed" answer. A process that dies mid-submission (crash, timeout kill)
  leaves its lock stuck forever *by design*, so a proposal can never be blindly resubmitted when the
  true outcome is unknown. (An admin endpoint exists to release a lock by hand, but only when the
  caller explicitly confirms independent proof — e.g. the broker's own order history — that nothing
  was placed.)
- **The Kraken AI capital ledger is deliberately isolated from personal/pre-existing holdings** on
  the same exchange account. Two guardrail bugs were found and fixed on 2026-08-01 specifically
  because *other* code paths (weekly-loss P&L, portfolio concentration) weren't respecting this
  isolation and were measuring against the whole account instead — any redesign touching sizing/risk
  must keep every risk calculation scoped to the AI's own allocation, never the founder's personal
  capital on the same account.
- **Kraken order validation (`KRAKEN_MAX_ORDER_GBP`/`KRAKEN_MIN_ORDER_GBP`/
  `KRAKEN_TRADING_ALLOCATION_GBP`/`KRAKEN_MAX_OPEN_TRADES`/`KRAKEN_ALLOWED_PAIRS`/buy-only-entries)
  is enforced independently in the broker adapter itself**, not just upstream in the governance
  chain — a second, broker-level backstop that should stay structurally separate from the
  Strategy/Portfolio/Risk/Sentinel chain, not merged into it.
- **Every job run is claimed via an idempotency key** (`job_name:scheduled_for`) so the same
  scheduled slot can never execute twice, even across worker restarts.

## 9. Open architectural questions for the redesign

- How to split `api.py`'s ~6,000 lines into cohesive modules (HTTP routing vs. business logic vs.
  broker-panel presentation vs. admin tooling) without breaking the mobile app's existing contract.
- Whether to introduce a shared base pattern (mixin/decorator/framework) for schema-owning modules,
  given the same bug independently recurred 7+ times — this is the strongest single signal that a
  structural fix (not another one-off patch) is warranted.
- Whether some of the ~100 tables represent genuinely dead/dormant schema that should be removed
  rather than carried into a new architecture unexamined.
- How much of the current print()-based ad hoc logging should be replaced with real structured
  logging/metrics before or during the redesign, given how much of 2026-08-01's debugging depended
  on log prefixes that happened to already exist (or didn't, and had to be added first).
- Whether job timeouts/concurrency should move toward a real task-queue model (separate worker pool,
  retries with backoff, dead-letter handling) rather than "one subprocess per job per worker-loop
  tick," given the app's stated ambition (deeper research, backtesting, eventually literature
  ingestion) will only add more scheduled work over time.
