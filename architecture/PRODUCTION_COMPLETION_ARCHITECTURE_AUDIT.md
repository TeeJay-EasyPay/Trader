# Production Completion Architecture Audit

Date: 2026-07-20
Basis: repository source at the current worktree, not prior completion claims
Scope: production database, execution, lifecycle, learning, worker, API, mobile, and configuration

## Executive finding

AI Trader is not yet a single production architecture. Hosted operational evidence is persisted in Postgres, while most trading-domain modules still open the configured SQLite file directly. The worker is real and autonomous, but its database writes are split between durable Postgres operational tables and process-local SQLite domain tables. This explains the recurring pattern in which the worker is healthy while Founder screens cannot see recommendations, broker state, portfolio evidence, lifecycle records, P&L, or learning evidence.

The four proposed cutover actions are necessary but not sufficient. Two further blockers must be completed in this programme:

1. The worker must isolate slow responsibilities so a slow research or broker call cannot prevent heartbeats, reconciliation, execution evaluation, or learning from progressing.
2. Founder APIs must read authoritative source records and report source completeness. Projection tables may accelerate reads, but must never conceal missing source truth or become an alternative authority.

## Decision gate

| Proposed action | Required | Sufficient by itself | Repository evidence |
|---|---:|---:|---|
| Move all hosted runtime state to Postgres | Yes | No | 21 production modules contain direct `sqlite3.connect` calls. |
| Enforce one execution pipeline | Yes | No | `ExecutionEngine` submits directly; API paths separately call the Sprint 6 gate before calling the Orchestrator; direct Orchestrator callers bypass that gate. |
| Canonical reconciliation and trade-level P&L | Yes | No | Broker history, lifecycle, reconstruction, attribution and learning use overlapping identifiers and tables. |
| Automatic terminal learning | Yes | No | Learning is queued from an API broker-poll path rather than from every deterministic terminal transition. |
| Isolate worker responsibilities | Yes | Yes, as an additional blocker | The worker executes managed exits, scheduled research, auto-execution, broker polling and learning serially in one loop. |
| Make Founder APIs source-aware | Yes | Yes, as an additional blocker | Several screens consume projections or aggregate payloads that can be empty while source work exists elsewhere. |

The implementation gate therefore passes with six mandatory workstreams, not four.

## Database audit

### Runtime database selection

- `config.py` selects Postgres when `DATABASE_URL` is present and otherwise defaults to SQLite.
- Hosted startup validation rejects a requested Postgres deployment without a URL.
- `always_on.py` and `production_evidence.py` contain explicit Postgres implementations.
- Most domain modules ignore the selected backend and call `sqlite3.connect(db_path)` directly.
- The hosted Docker image creates `/data`, but a worker and API do not share that filesystem. Even a persistent disk cannot be mounted as one safe multi-process SQLite authority.

### Direct SQLite owners

The following production modules directly open SQLite and therefore represent hosted cutover blockers:

| Module | Direct opens found | Domain |
|---|---:|---|
| `multi_broker.py` | 28 | broker runtime, history, locks, managed exits, notifications |
| `always_on.py` | 15 | local branch of jobs, heartbeats, funnels, shadow trades, incidents |
| `trading_intelligence.py` | 15 | recommendations, signals, committee, lifecycle, probability |
| `sprint6.py` | 15 | decision journal, strategy maturity, sentinel, outbox, incidents, reports |
| `foundation.py` | 11 | policies, due diligence, scores, allocation, decisions |
| `production_spine.py` | 10 | reconciliation, learning, portfolio manager, gateway and supervision |
| `operational_truth.py` | 10 | lifecycle, transition rejection, costs, R, excursions, reconciliation |
| `operational.py` | 9 | runtime state, snapshots, reports, attribution, push tokens |
| `experience_engine.py` | 6 | immutable experience, reviews, analogues, calibration, learning proposals |
| `production_evidence.py` | 4 | Postgres projection with SQLite compatibility branch |
| `orchestrator.py` | 4 | execution decisions, auto-trade events, briefs |
| `portfolio_intelligence.py` | 4 | exposure, risk, correlation and stress evidence |
| `api.py` | 3 | direct aggregate/read operations |
| `briefing.py` | 2 | Founder reporting |
| `market_intelligence_platform.py` | 2 | market observations and intelligence |
| `autonomous_activity.py` | 2 | activity read model |
| `audit.py` | 1 | permanent trade audit |
| `agent.py` | 1 | proposal persistence support |
| `benchmark.py` | 1 | benchmark learning data |
| `intelligence.py` | 1 | investment knowledge data |
| `db_browser.py` | 1 | local database inspection |

All production-capable modules must use one backend-aware connection provider. `db_browser.py` may remain explicitly local. No hosted path may silently fall back to SQLite.

### SQL compatibility blockers

The schemas and queries use SQLite-specific syntax:

- `INTEGER PRIMARY KEY AUTOINCREMENT`;
- `INSERT OR IGNORE`;
- `INSERT OR REPLACE`;
- `PRAGMA table_info`;
- `?` parameter placeholders;
- `sqlite3.Row` and integer/key row indexing;
- `cursor.lastrowid`;
- SQLite exception classes.

A cutover therefore requires a tested database abstraction and explicit replacement of ambiguous `INSERT OR REPLACE` operations with deterministic Postgres upserts. String replacement at deployment time without tests would risk corrupting authority.

### Table map and classification

Classification refers to the intended state after this programme. All authoritative and projection tables must reside in Postgres in hosted production. SQLite copies are local/test only.

#### Authoritative investment, research and recommendation truth

`COMPANY_MASTER`, `COMPANY_FINANCIALS`, `COMPANY_DAILY_UPDATES`, `INVESTMENT_WATCHLIST`, `MARKET_THEMES`, `BENCHMARK_TRADERS`, `BENCHMARK_DAILY_RESEARCH`, `CRYPTO_MASTER`, `CRYPTO_ASSET_MASTER`, `CRYPTO_MARKET_DATA`, `CRYPTO_NEWS`, `CRYPTO_SENTIMENT`, `CRYPTO_ONCHAIN_METRICS`, `CRYPTO_TOKENOMICS`, `CRYPTO_PROJECT_ANALYSIS`, `CRYPTO_RESEARCH_SCORES`, `CRYPTO_RISK`, `CRYPTO_TRADING_HISTORY`, `CRYPTO_DAILY_UPDATES`, `CRYPTO_BENCHMARK_ALIGNMENT`, `RESEARCH_RUNS`, `RESEARCH_FUNNELS`, `MARKET_DATA_OBSERVATIONS`, `MARKET_DATA_QUALITY_EVENTS`, `HISTORICAL_CANDLES`, `MULTI_TIMEFRAME_INTELLIGENCE`, `FUNDAMENTAL_EVIDENCE`, `MACRO_EVENT_EVIDENCE`, `NEWS_CATALYST_EVIDENCE`, `MARKET_REGIME_EVIDENCE`, `MARKET_REGIME_SNAPSHOTS`, `RECOMMENDATION_SETS`, `TRADE_SIGNALS`, `PROBABILITY_ESTIMATES`, `TRADING_COMMITTEE_REVIEWS`.

These tables are authoritative for recorded source observations and derived decisions. Static master/reference rows must be labelled as reference data and never presented as fresh research.

#### Authoritative governance and decision truth

`INVESTMENT_POLICIES`, `RISK_POLICIES`, `BROKER_POLICIES`, `LEARNING_POLICIES`, `DUE_DILIGENCE_ASSESSMENTS`, `INVESTMENT_SCORES`, `CAPITAL_ALLOCATION_HISTORY`, `BROKER_DECISIONS`, `EXECUTION_DECISIONS`, `ORCHESTRATOR_DECISIONS`, `PORTFOLIO_MANAGER_DECISIONS`, `STRATEGY_REGISTRY`, `STRATEGY_MATURITY_REGISTRY`, `STRATEGY_ENTITLEMENT_DECISIONS`, `STRATEGY_PROMOTION_DECISIONS`, `STRATEGY_BACKTEST_RESULTS`, `STRATEGY_LAB_RUNS`, `PRODUCTION_RISK_SENTINEL_DECISIONS`, `KILL_SWITCH_STATE`, `DECISION_JOURNAL`.

These are authoritative decision and governance records. Markdown governance remains the Founder-approved policy source; parsed/versioned policy rows are runtime authority for the approved version.

#### Authoritative broker and execution truth

`BROKER_AUTO_TRADING_SETTINGS`, `BROKER_RUNTIME_STATE`, `BROKER_TRADE_HISTORY`, `ORDER_INTENT_LOCKS`, `MANAGED_TRADE_EXITS`, `MECHANICAL_SEATBELT_EVENTS`, `BROKER_EVENT_MAPPINGS`, `AUTO_TRADE_EVENTS`, `EXECUTION_EVENTS`, `TRADE_AUDIT`, `NOTIFICATION_EVENTS`, `PUSH_TOKENS`, `ENGINE_CONTROL`.

Broker payloads are authoritative for what the broker reported. Internal intent and governance records are authoritative for what AI Trader intended and allowed. A broker payload never replaces internal reasoning.

#### Canonical trade authority

`CANONICAL_TRADE_LIFECYCLE`, `LIFECYCLE_TRANSITION_REJECTIONS`, `BROKER_RECONCILIATION_RUNS`, `CANONICAL_RECONCILIATION_CASES`, `TRADE_EXECUTION_COSTS`, `TRADE_R_MULTIPLES`, `TRADE_EXCURSIONS`, `PERFORMANCE_ATTRIBUTION`, `CLOSED_LOOP_LEARNING_RUNS`.

The current tables are incomplete as a single authority because lifecycle events do not universally share a logical trade identifier and fills are still reconstructed from broker-history rows. The cutover must add one logical-trade aggregate and immutable canonical events/fills, then make these calculation tables children of that identifier.

#### Authoritative portfolio truth

`ASSET_METADATA`, `PORTFOLIO_SNAPSHOTS`, `PORTFOLIO_EXPOSURE_SNAPSHOTS`, `PORTFOLIO_RISK_CONTRIBUTIONS`, `PORTFOLIO_CORRELATION_WARNINGS`, `PORTFOLIO_STRESS_TESTS`, `PERFORMANCE_INTELLIGENCE`.

Broker snapshots remain the source for balances and positions at a point in time. Portfolio analyses are immutable derived records with disclosed inputs and timestamps.

#### Authoritative experience and learning truth

`EXPERIENCE_RECORDS`, `POST_TRADE_REVIEWS`, `HISTORICAL_ANALOGUES`, `CONFIDENCE_CALIBRATION`, `LEARNING_PROPOSALS`, `SPRINT6_WORKFLOW_OUTBOX`.

Experience records are immutable. Learning proposals are suggestions only and cannot change production parameters without governed approval.

#### Authoritative operations and reports

`SCHEDULED_JOB_RUNS`, `WORKER_HEARTBEATS`, `WORKER_SUPERVISION_RUNS`, `OPERATIONS_INCIDENTS`, `INCIDENT_LIFECYCLE`, `OPERATIONAL_EVENTS`, `FOUNDER_OPERATIONAL_REPORTS`, `TRADING_REPORTS`, `DAILY_BRIEFINGS`, `DAILY_BRIEFS`.

These tables are operational authority. A job or report that has no persisted row did not happen from the platform's evidentiary perspective.

#### Projections/read models

`PRODUCTION_RESEARCH_EVIDENCE`, `PRODUCTION_RECOMMENDATION_EVIDENCE`, `PRODUCTION_BROKER_SNAPSHOTS`, `PRODUCTION_TRADE_EVIDENCE`, `PRODUCTION_LEARNING_EVIDENCE`, `PRODUCTION_SPINE_SNAPSHOTS`, `SHADOW_TRADES`, `MARKET_DATA_GATEWAY_RUNS`.

These are query-oriented projections or run summaries. They may be rebuilt from authoritative records. They must contain source references and completeness state. They must not be used to claim activity absent source records.

#### Obsolete or duplicate production concepts

`TRADE_LIFECYCLE` duplicates `CANONICAL_TRADE_LIFECYCLE`; `DAILY_BRIEFS` overlaps `DAILY_BRIEFINGS` and `TRADING_REPORTS`; `AUTO_TRADE_EVENTS` overlaps decision, intent and broker lifecycle evidence; `BROKER_RUNTIME_STATE` and `ENGINE_CONTROL` have overlapping operational switches. These tables may remain for backward-compatible reads during cutover, but no new production authority may be written to them after callers are migrated. They should be documented as legacy projections and removed in a later controlled migration only after hosted data retention is confirmed.

#### Unknown/needs retention review

No table may remain unclassified after the cutover. The 109 declared tables above are classified. Retention periods are not consistently encoded and remain a governance concern, but lack of automated retention does not block dependable operation because records are append-oriented and small at current scale.

## Execution-path audit

### Production paths discovered

1. API manual approval: recommendation load -> `pre_execution_decision_packet` -> `InvestmentOrchestrator.evaluate_recommendation` -> broker adapter.
2. API auto-execution: eligible recommendation loop -> `pre_execution_decision_packet` -> Orchestrator -> broker adapter.
3. Worker auto-execution: worker named job -> API service auto-execution path -> same API/Orchestrator path.
4. CLI legacy execution: `ExecutionEngine.execute_proposals` -> guardrails -> broker directly.
5. Direct Orchestrator callers: tests and any future internal caller can invoke `evaluate_recommendation` without Portfolio Manager, Strategy Maturity or Sentinel because those gates currently live outside the Orchestrator.

### Governance bypasses

- `ExecutionEngine` bypasses Portfolio Manager, Strategy Maturity, Sentinel and the Orchestrator.
- The Orchestrator itself does not enforce the Sprint 6 pre-execution packet. Direct callers bypass three mandatory gates.
- API callers invoke the packet separately, producing duplicated orchestration responsibility and leaving correctness dependent on caller discipline.
- Market-data quality is optional in the pre-execution packet and can reach the Sentinel as an unknown string.

### Required cutover

The Orchestrator must own one `GovernedExecutionPipeline`. Every broker submission must originate from this pipeline. The pipeline order is Research evidence -> Recommendation -> Strategy Maturity -> Portfolio Manager -> Risk Engine/guardrails -> Sentinel -> idempotent Execution Intent -> Broker Adapter. The legacy `ExecutionEngine` must be local/test-only or delegate to that pipeline; it cannot retain broker-submit authority in hosted mode.

## Canonical lifecycle audit

### Existing stages

The repository records recommendation lifecycle, canonical lifecycle events, broker mappings, broker history, managed exits, reconciliation cases, cost records, R records, excursion records, attribution and learning. These are useful pieces, but are not one aggregate.

### Disconnections

- Proposal ID, broker order ID, broker trade ID, fill ID and logical trade ID are not universally linked by a single immutable aggregate row.
- `TRADE_LIFECYCLE` and `CANONICAL_TRADE_LIFECYCLE` compete as lifecycle concepts.
- Broker trade-history rows include orders, fills and status snapshots, so row counts are not trade counts.
- Reconciliation groups events heuristically and writes lifecycle rows, but does not maintain a complete fill ledger and quantity state.
- `INSERT OR REPLACE` can replace reconciliation state instead of preserving immutable history.
- P&L may be reconstructed within a reporting window rather than calculated from canonical matched fills.
- Original stop, intended prices and decision context are not guaranteed to follow every broker event through closure.
- Late and out-of-order events can be deduplicated, but aggregate state is not recomputed from the immutable full event set.

### Required authority

One `LOGICAL_TRADES` aggregate must carry the canonical ID from recommendation to learning. Immutable `CANONICAL_TRADE_EVENTS` and `TRADE_FILLS` must retain every source event. Aggregate state, average prices, remaining quantity, fees, gross/net P&L, reconciliation confidence and terminal state must be deterministically recomputed from those rows. Derived calculations must reference the canonical ID.

## Learning audit

### Triggers and queues

- API broker polling calls `enqueue_learning_workflow` for detected terminal outcomes.
- `SPRINT6_WORKFLOW_OUTBOX` provides an idempotent learning queue.
- The worker calls `process_learning_outbox` each cycle.
- `run_closed_loop_learning` calculates costs, R, excursions, experience, review, analogues, a learning proposal and a `learning_completed` lifecycle event.

### Failure modes

- Terminal transitions outside the API polling path do not necessarily enqueue learning.
- A terminal payload can be incomplete because canonical entry/exit fills and original decision context are not guaranteed.
- Incomplete work can be moved to manual review instead of being retried after deterministic reconciliation.
- Serial worker execution can delay learning indefinitely behind slow broker or research calls.
- Some learning evidence is projected separately, so the Founder can see no learning even when a local SQLite run exists.

### Required cutover

The canonical reconciliation transaction must enqueue terminal learning exactly once. The learning worker must load all evidence by logical trade ID from Postgres, retry incomplete-but-recoverable cases, fail visibly for irrecoverable evidence, and never require a human merely to join deterministic records. Production parameters remain immutable until explicit approval.

## Worker audit

The single background worker currently performs:

1. managed exits;
2. due scheduled research/report jobs;
3. auto-execution evaluation;
4. broker polling;
5. evidence snapshotting;
6. learning-outbox processing;
7. heartbeat and incident recording.

It is autonomous and phone-independent. However, tasks run serially in one loop. A slow Kraken call, market provider, OpenAI request, or report can postpone all later responsibilities and produce mobile timeouts. The existing heartbeat pulse helps, but does not isolate job deadlines. The cutover must preserve one paid worker while using bounded task execution, per-job timeouts, durable claims and per-job evidence so one slow responsibility cannot halt the cycle.

## API audit

The API exposes operational and Founder aggregates, but reads a mixture of:

- explicit Postgres always-on tables;
- production evidence projections;
- direct SQLite domain tables;
- in-process broker/API calls;
- derived summaries and unavailable-value explanations.

This causes large `/status` and `/autonomous-activity` payloads, slow requests, and partial/empty screens. Authoritative source endpoints must use the shared connection provider. Founder endpoints should be bounded read models derived from Postgres and return source completeness, freshness and latest successful timestamps. They must not synchronously poll brokers or run research.

## Mobile audit

Primary screens are Dashboard, Activity, Recommendations, Portfolio, Market and Learning. They consume hosted API payloads; there is no direct mobile database access. The important mapping is:

| Screen | Primary hosted source | Current risk |
|---|---|---|
| Dashboard | `/status`, operations and activity summaries | Large mixed-source status can time out. |
| Activity | `/autonomous-activity` | Projection/API timeout can hide real worker rows. |
| Recommendations | `/recommendations` and command endpoints | Recommendation source remains SQLite in hosted processes. |
| Portfolio | `/portfolio`, attribution and lifecycle summaries | Broker snapshots and portfolio analysis can come from different stores. |
| Market | intelligence/research endpoints | Fresh observations and static seeded reference data can be conflated. |
| Learning | learning update, strategy and experience endpoints | Local learning rows are invisible to the API process. |

The mobile app correctly displays unknown states rather than fabricating data. The cutover requirement is backend source unification plus smaller read endpoints, not mobile-generated activity.

## Configuration audit

### Core production variables

`DATABASE_URL` or `SUPABASE_DATABASE_URL`, `AI_TRADER_DATABASE_BACKEND`, `AI_TRADER_REQUIRE_POSTGRES_IN_HOSTED`, `AI_TRADER_PROCESS_ROLE`, `AI_TRADER_DISABLE_API_BACKGROUND_WORKERS`, `AI_TRADER_API_TOKEN`, `OPENAI_API_KEY`, `OPENAI_MODEL`, Alpaca credentials/base URLs, Kraken credentials/base URL, broker-specific auto-trading/live approval/real-order flags, research/worker/broker-poll/auto-execution intervals, risk limits and allocation limits.

### Problems

- `DATABASE_URL` and `SUPABASE_DATABASE_URL` are aliases without one canonical name.
- Auto-trading has legacy/global and broker-specific flags.
- Some broker defaults are computed in adapters while others are loaded in `Settings` or runtime tables.
- `AI_TRADER_DB_PATH` appears production-relevant even though it must become local-only.
- The default database backend can be SQLite when no URL exists; hosted validation catches some roles, but domain modules still directly open SQLite after startup.
- Render-provided identity variables and application role variables are conflated in operational diagnostics.

The cutover must centralise effective configuration, expose redacted provenance, and fail hosted startup if any domain repository would select SQLite. Runtime broker toggles belong in Postgres; environment variables are boot-time permissions and upper bounds, not mutable state.

## Architectural blockers to resolve now

1. Direct SQLite use in hosted domain modules.
2. SQLite-specific SQL unsupported by Postgres.
3. Multiple broker submission authorities.
4. Mandatory gates outside the Orchestrator.
5. Missing universal logical trade ID.
6. No immutable fill ledger/aggregate recomputation.
7. Reporting-window P&L reconstruction instead of canonical P&L.
8. Terminal learning trigger tied to one polling path.
9. Incomplete evidence becoming manual review rather than deterministic retry.
10. Serial worker head-of-line blocking.
11. Founder read models mixing stores and synchronous external work.
12. Legacy projection tables that can be mistaken for authority.
13. Duplicated configuration and silent local defaults.
14. No repository test that forbids hosted direct SQLite access or direct broker submission outside the governed pipeline.

## Completion evidence required

The programme can be declared code-complete only when repository tests prove:

- hosted connections resolve only to Postgres and fail closed;
- every production module uses the shared provider;
- only the governed pipeline calls a broker adapter submit method;
- all gates execute in the mandated order;
- canonical events and fills are idempotent and tolerate late/out-of-order delivery;
- exact trade P&L derives from canonical fills and known fees;
- terminal learning is queued and completed exactly once;
- a slow job cannot stop heartbeat and unrelated due work;
- Founder endpoints read shared source truth and report completeness.

Hosted production completion additionally requires real deployment evidence, broker acknowledgements/fills when a genuine eligible trade occurs, restart proof, and a soak period. Unit tests cannot substitute for that evidence, and no trade will be forced to manufacture it.
