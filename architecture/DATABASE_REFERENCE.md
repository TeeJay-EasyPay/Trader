# Database Reference

AI Trader uses SQLite as the primary persistent store. The default local path is `data/audit.sqlite3`; hosted deployments normally set `AI_TRADER_DB_PATH` to a file on Render persistent disk.

The schema is modular. Each subsystem initializes its own tables:

- `audit.py` initializes core audit tables.
- `api.py` initializes control and report tables.
- `foundation.py` initializes policy, due diligence, investment score, and crypto knowledge tables.
- `multi_broker.py` initializes broker runtime, recommendations, notifications, managed exits, and attribution.
- `operational.py` initializes portfolio snapshots, research runs, and crypto asset master.
- `intelligence.py` initializes company intelligence tables.
- `benchmark.py` initializes benchmark trader tables.
- `orchestrator.py` initializes orchestrator decision tables.
- `operational_truth.py` initializes canonical lifecycle, reconciliation, execution cost, R, MAE, and MFE tables.
- `market_intelligence_platform.py` initializes provider-neutral market observation and source-aware evidence tables.
- `portfolio_intelligence.py` initializes asset metadata, exposure, correlation, risk contribution, and stress-test tables.
- `experience_engine.py` initializes immutable experience records, post-trade reviews, analogues, and governed learning proposals.

## Phase 4-8 World-Class Evidence Tables

### Operational Truth

| Table | Purpose | Producer | Consumer | Retention | Indexes / Keys | Future Expansion |
|---|---|---|---|---|---|---|
| `CANONICAL_TRADE_LIFECYCLE` | Broker-neutral lifecycle event stream for Alpaca and Kraken. | Startup reconciliation, broker-history writes, future execution lifecycle hooks. | `/operational-truth`, `/world-class-evidence`, reports, learning. | Permanent append-only. | Unique `idempotency_key`; indexes on proposal, broker/symbol, stage. | Link directly to closed-trade attribution. |
| `LIFECYCLE_TRANSITION_REJECTIONS` | Rejected unknown or illegal lifecycle transitions. | Operational Truth recorder. | Operational review and Founder exception summaries. | Permanent. | `rejection_id` primary key. | Add severity and manual-resolution status. |
| `TRADE_EXECUTION_COSTS` | Intended/actual prices, slippage, fees, total costs, basis points, fee status. | Execution/reconciliation helpers. | Reports, Experience Engine. | Permanent. | `cost_id` primary key. | Add broker cost profile versions. |
| `TRADE_R_MULTIPLES` | True R calculated from initial monetary risk. | Attribution helpers. | Learning, Strategy Lab, reports. | Permanent. | `r_id` primary key. | Link to strategy/regime IDs. |
| `TRADE_EXCURSIONS` | MAE/MFE with timestamp, granularity, gaps, and confidence. | Monitoring/attribution helpers. | Learning, reports. | Permanent. | `excursion_id` primary key. | Add candle-source relationship. |
| `BROKER_RECONCILIATION_RUNS` | Startup and polling reconciliation health. | API startup and broker-history write path. | Dashboard, Portfolio, Ask AI. | Permanent or archiveable. | `reconciliation_id` primary key. | Add per-order reconciliation status. |

### Market Intelligence

| Table | Purpose | Producer | Consumer | Retention | Indexes / Keys | Future Expansion |
|---|---|---|---|---|---|---|
| `MARKET_DATA_OBSERVATIONS` | Provider-neutral market observations with provenance and quality status. | Market data provider layer. | Market screen, strategy evidence. | Permanent or roll-up archive. | Symbol/timeframe/time index. | Add provider latency and adjustment lineage. |
| `MARKET_DATA_QUALITY_EVENTS` | Stale/missing/impossible/duplicate data warnings. | Market data validator. | Recommendations, Market screen. | Permanent. | Symbol/issue index. | Add review workflow. |
| `MULTI_TIMEFRAME_INTELLIGENCE` | Multi-timeframe conclusions with supporting and contradictory evidence. | Market Intelligence Engine. | Recommendations, Founder AI. | Permanent by analysis run. | `intelligence_id` primary key. | Add direct relation to proposal IDs. |
| `FUNDAMENTAL_EVIDENCE` | Normalized equity fundamental evidence. | Fundamental data provider. | Dossiers and Portfolio. | Permanent by source timestamp. | `evidence_id` primary key. | Add metric lineage and restatement handling. |
| `MACRO_EVENT_EVIDENCE` | Macro, earnings, crypto, regulatory, and event risk. | Event calendar providers. | Dossiers, Market screen. | Permanent. | `event_id` primary key. | Add event outcome tracking. |
| `NEWS_CATALYST_EVIDENCE` | Source-aware catalyst evidence with duplicate clustering. | News processor. | Dossiers, Ask AI. | Permanent. | Unique symbol/cluster/timestamp. | Add credibility scoring by source history. |
| `MARKET_REGIME_EVIDENCE` | Regime 2.0 supporting/contradictory evidence. | Regime Engine. | Dashboard and Market screen. | Permanent by run. | `regime_id` primary key. | Add benchmark regime comparison. |

### Portfolio Intelligence

| Table | Purpose | Producer | Consumer | Retention | Indexes / Keys | Future Expansion |
|---|---|---|---|---|---|---|
| `ASSET_METADATA` | Normalized source-aware asset metadata. | Metadata providers/manual seed. | Exposure, recommendations. | Latest by source plus history. | Unique symbol/source. | Add versioned confidence changes. |
| `PORTFOLIO_EXPOSURE_SNAPSHOTS` | Exposure buckets and plain-English warnings. | Portfolio Intelligence Engine. | Portfolio screen, Risk Engine. | Permanent snapshots. | Broker/created_at index. | Add position-level source rows. |
| `PORTFOLIO_CORRELATION_WARNINGS` | Sample-aware correlation warnings. | Portfolio Intelligence Engine. | Dossiers, Portfolio screen. | Permanent. | `warning_id` primary key. | Add rolling-window relationship. |
| `PORTFOLIO_RISK_CONTRIBUTIONS` | Position and marginal risk contribution. | Portfolio/Risk Engine. | Orchestrator, reports. | Permanent by decision. | `contribution_id` primary key. | Add stress scenario link. |
| `PORTFOLIO_STRESS_TESTS` | Stress scenarios with assumptions and uncertainty. | Portfolio Intelligence Engine. | Portfolio and Founder AI. | Permanent by scenario run. | `stress_id` primary key. | Add scenario library. |

### Experience Engine

| Table | Purpose | Producer | Consumer | Retention | Indexes / Keys | Future Expansion |
|---|---|---|---|---|---|---|
| `EXPERIENCE_RECORDS` | Immutable decision, execution, and result context. | Experience Engine. | Learning, analogues, Ask AI. | Permanent append-only. | Unique `immutable_hash`; symbol/strategy/regime index. | Add evidence graph IDs. |
| `POST_TRADE_REVIEWS` | Closed-trade review and decision/outcome classification. | Experience Engine. | Learning screen and reports. | Permanent. | Symbol/date index. | Add reviewer approval status. |
| `HISTORICAL_ANALOGUES` | Stored "have we seen this before" searches. | Experience Engine. | Dossiers, Ask AI. | Permanent or archiveable. | `analogue_id` primary key. | Add vector similarity when appropriate. |
| `LEARNING_PROPOSALS` | Governed, versioned learning proposals. | Experience Engine. | Founder approval process. | Permanent. | `proposal_id` primary key. | Add formal approval and rollout tables. |

## Core Audit Tables

| Table | Purpose | Producer | Consumer | Retention | Indexes / Keys | Future Expansion |
|---|---|---|---|---|---|---|
| `trade_audit` | Append-only trade/proposal audit events with AI reasoning, guardrail status, execution result, and payload JSON. | `AuditDatabase.record_trade_event`, proposal/execution flows. | Reports, audit review, recommendation history. | Permanent. | `id` primary key. | Add indexes on `proposal_id`, `created_at`, `symbol`, `event_type`. |
| `execution_events` | Append-only execution event details keyed by proposal. | Execution engine and broker flows. | Debugging and reports. | Permanent. | `id` primary key. | Add event correlation IDs. |
| `daily_briefings` | Stored daily briefing markdown and payload. | `briefing.py` / audit helpers. | Founder reports. | Permanent. | `id` primary key. | Link to `TRADING_REPORTS`. |

## API Control And Reports

| Table | Purpose | Producer | Consumer | Retention | Indexes / Keys | Future Expansion |
|---|---|---|---|---|---|---|
| `engine_control` | Single-row trading state control: running, paused, stopped, last command. | API control endpoints. | `/status`, Command screen, scheduler. | Latest state plus history through logs/audit. | `id` primary key constrained to 1. | Add append-only control history. |
| `TRADING_REPORTS` | Generated report metadata and markdown. | Report endpoints in `api.py`. | Mobile report buttons, `/reports/{id}`. | Permanent. | `report_id` primary key. | Add broker/date/type indexes and HTML cache path. |

## Operational Tables

| Table | Purpose | Producer | Consumer | Retention | Indexes / Keys | Future Expansion |
|---|---|---|---|---|---|---|
| `PORTFOLIO_SNAPSHOTS` | Broker portfolio snapshots: cash, value, buying power, P&L, positions count. | Broker polling and status refresh. | Command screen, reports, risk checks. | Permanent. | `snapshot_id` primary key. | Add indexes on broker/exchange/created_at. |
| `RESEARCH_RUNS` | Research cycle record: status, markets reviewed, recommendations, errors, next run. | Scheduler and manual analysis. | Intelligence screen, reports, Ask AI. | Permanent. | `research_run_id` primary key. | Add run stage details and worker heartbeat relation. |
| `CRYPTO_ASSET_MASTER` | Operational crypto universe seed table populated from public rankings. | `seed_crypto_universe`. | Crypto analysis. | Historical with active flag. | `asset_id` primary key. | Add unique symbol/category constraint and provider metadata. |

## Foundation And Governance Tables

| Table | Purpose | Producer | Consumer | Retention | Indexes / Keys | Future Expansion |
|---|---|---|---|---|---|---|
| `INVESTMENT_POLICIES` | Runtime investment policy key/value rows. | Foundation seeding. | Policy loader and orchestrator. | Active policies retained; changes should become append-only later. | Unique `policy_key`. | Add policy versioning and approval records. |
| `RISK_POLICIES` | Runtime risk policy key/value rows. | Foundation seeding. | Risk engine and orchestrator. | Active policies retained. | Unique `policy_key`. | Add immutable policy snapshots. |
| `BROKER_POLICIES` | Broker-specific policy key/value rows. | Foundation seeding. | Broker validation. | Active policies retained. | Unique `(broker, policy_key)`. | Add per-broker approval workflow. |
| `LEARNING_POLICIES` | Learning boundaries, such as whether AI can modify governance. | Foundation seeding. | Learning/reporting logic. | Active policies retained. | Unique `policy_key`. | Add learning experiment registry. |
| `CAPITAL_ALLOCATION_HISTORY` | Records requested and approved notional/quantity and risk amount for each proposal. | `calculate_capital_allocation`. | Reports, audit, risk review. | Permanent. | `allocation_id` primary key. | Add broker and account currency columns. |
| `DUE_DILIGENCE_ASSESSMENTS` | Due diligence status by proposal. | `create_due_diligence_assessment`. | Orchestrator, Recommendations UI. | Permanent by proposal. | Unique `proposal_id`. | Add evidence links per diligence dimension. |
| `INVESTMENT_SCORES` | Fundamental, technical, market, macro, behavioural, policy, risk, and overall scores. | `calculate_investment_score`. | Orchestrator, UI, reports. | Permanent by proposal. | Unique `proposal_id`. | Add model/provider version. |
| `BROKER_DECISIONS` | Broker routing and market/asset availability decision. | Orchestrator. | Reports, Ask AI. | Permanent. | `broker_decision_id` primary key. | Add adapter version and latency. |
| `EXECUTION_DECISIONS` | Execution decision and validation result. | Orchestrator. | Reports, audit. | Permanent. | `execution_decision_id` primary key. | Add explicit rule failure table. |

## Crypto Knowledge Tables

| Table | Purpose | Producer | Consumer | Retention | Indexes / Keys | Future Expansion |
|---|---|---|---|---|---|---|
| `CRYPTO_MASTER` | Approved/known crypto assets by symbol/category. | Foundation and crypto universe seeding. | Universe validation. | Historical with active flag. | Unique `(symbol, category)`. | Add exchange availability mapping. |
| `CRYPTO_MARKET_DATA` | Observed crypto market prices, caps, volumes, raw payload. | Crypto universe refresh. | Crypto scoring, reports. | Permanent. | `market_data_id` primary key. | Add symbol/observed_at index. |
| `CRYPTO_DAILY_UPDATES` | Daily crypto narrative updates. | Future/partial research flows. | Knowledge and reports. | Permanent. | `update_id` primary key. | Add source reliability scoring. |
| `CRYPTO_PROJECT_ANALYSIS` | Project/use-case/team/ecosystem notes. | Future research flows. | Due diligence. | Permanent. | `analysis_id` primary key. | Add structured technology and adoption scores. |
| `CRYPTO_TOKENOMICS` | Supply, utility, emissions, concentration risk. | Future research flows. | Due diligence. | Permanent. | `tokenomics_id` primary key. | Add circulating supply snapshots. |
| `CRYPTO_ONCHAIN_METRICS` | On-chain activity metrics when provider exists. | Future provider integration. | Crypto scoring. | Permanent. | `onchain_id` primary key. | Add provider-specific index. |
| `CRYPTO_SENTIMENT` | Sentiment score and summary. | Future provider integration. | Due diligence and Ask AI. | Permanent. | `sentiment_id` primary key. | Add source weighting. |
| `CRYPTO_RISK` | Custody, liquidity, regulatory, protocol risk. | Future/partial research flows. | Risk engine and reports. | Permanent. | `risk_id` primary key. | Add risk category scoring. |
| `CRYPTO_NEWS` | Crypto news records. | Future news integration. | Due diligence and reports. | Permanent. | `news_id` primary key. | Add URL uniqueness. |
| `CRYPTO_BENCHMARK_ALIGNMENT` | Alignment with benchmark lessons. | Future learning. | Learning engine. | Permanent. | `alignment_id` primary key. | Add benchmark trader relation. |
| `CRYPTO_TRADING_HISTORY` | Crypto-specific trading history. | Foundation helpers. | Reports. | Permanent. | `history_id` primary key. | Consolidate with canonical broker trade lifecycle. |

## Multi-Broker Tables

| Table | Purpose | Producer | Consumer | Retention | Indexes / Keys | Future Expansion |
|---|---|---|---|---|---|---|
| `BROKER_AUTO_TRADING_SETTINGS` | Per-broker auto-trading flag. | Broker auto endpoints and env default sync. | Command screen, orchestrator, auto worker. | Latest state. | Broker primary key. | Add append-only setting history. |
| `BROKER_RUNTIME_STATE` | Per-broker connection/research/due diligence status and details JSON. | Pollers, analysis flows. | Command and Intelligence screens. | Latest state. | Broker primary key. | Add worker heartbeat and freshness timestamps by category. |
| `BROKER_TRADE_HISTORY` | Raw broker order/fill/trade rows. | Broker poller and managed exit close. | Trade History screen, reports. | Permanent. | Unique `(broker, external_id, status, updated_at)`. | Replace UI dependence with canonical trade lifecycle table. |
| `NOTIFICATION_EVENTS` | In-app/push notification queue and history. | Broker sync, managed exits, control endpoints. | Notifications, push worker. | Permanent or archiveable. | `notification_id` primary key. | Add read receipts by device/user. |
| `RECOMMENDATION_SETS` | Saved recommendation run metadata and proposal IDs. | Analysis flows. | Recommendations screen. | Permanent. | `set_id` primary key. | Add active pointer and run relation. |
| `CRYPTO_RESEARCH_SCORES` | Computed crypto technical/momentum/risk/confidence scores. | Crypto research. | Recommendations, due diligence, Ask AI. | Permanent. | `score_id` primary key. | Add symbol/date index and provider version. |
| `ORDER_INTENT_LOCKS` | Idempotency lock before broker submission. | Orchestrator. | Orchestrator and audit review. | Permanent. | Unique `(broker, client_order_id)`. | Add timeout/reconciliation status. |
| `MANAGED_TRADE_EXITS` | Open/closed managed exits with stop loss, take profit, trailing marks. | Kraken execution and exit worker. | Managed exit worker, Trade History, reports. | Permanent. | `managed_exit_id` primary key. | Link to canonical lifecycle and broker fills. |
| `PUSH_TOKENS` | Registered Expo push tokens. | Mobile registration endpoint. | Push worker. | Active tokens with history. | Unique `push_token`. | Add device metadata and expiration. |
| `PERFORMANCE_ATTRIBUTION` | Closed trade entry/exit/P&L attribution. | Managed exit close and reporting logic. | Reports, learning, Ask AI. | Permanent. | `attribution_id` primary key. | Expand to partial fills and fees. |
| `MECHANICAL_SEATBELT_EVENTS` | Mechanical safety events: locks, broker confirmations, blocks. | Orchestrator and broker controls. | Reports and audit. | Permanent. | `event_id` primary key. | Add severity and remediation status. |

## Intelligence Tables

| Table | Purpose | Producer | Consumer | Retention | Indexes / Keys | Future Expansion |
|---|---|---|---|---|---|---|
| `COMPANY_MASTER` | Company profile and investment thesis. | Intelligence seed/refresh. | Intelligence UI, research, Ask AI. | Current row with update timestamps. | Unique `(ticker, exchange)`. | Add external IDs and source freshness. |
| `COMPANY_FINANCIALS` | Company financial snapshots. | Intelligence seed/refresh. | Due diligence. | Historical. | `id` primary key. | Add ticker/date index. |
| `COMPANY_DAILY_UPDATES` | Daily company updates and material change flag. | Daily refresh. | Intelligence UI and reports. | Permanent. | `id` primary key. | Add uniqueness by company/date/source. |
| `INVESTMENT_WATCHLIST` | Active watchlist and priority. | Intelligence seed. | Research scheduler. | Current with active flag. | Unique `company_id`. | Add user-defined universe management. |
| `MARKET_THEMES` | Macro/market themes and risks. | Intelligence seed/refresh. | Due diligence and reports. | Current with timestamps. | Unique `theme`. | Add theme history table. |

## Benchmark Tables

| Table | Purpose | Producer | Consumer | Retention | Indexes / Keys | Future Expansion |
|---|---|---|---|---|---|---|
| `BENCHMARK_TRADERS` | Public benchmark trader profiles. | Benchmark seed. | Learning/reporting. | Current with active flag. | Unique `(trader_name, platform)`. | Add public source verification dates. |
| `BENCHMARK_DAILY_RESEARCH` | Public benchmark observations and lessons. | Benchmark seed/refresh. | Learning engine, Ask AI. | Permanent. | `id` primary key. | Add URL/source uniqueness and confidence scoring. |

## Orchestrator Tables

| Table | Purpose | Producer | Consumer | Retention | Indexes / Keys | Future Expansion |
|---|---|---|---|---|---|---|
| `ORCHESTRATOR_DECISIONS` | Final decision per recommendation: approved, rejected, manual required, submitted. | Orchestrator. | UI, reports, Ask AI. | Permanent. | `decision_id` primary key. | Add individual rule-result rows. |
| `AUTO_TRADE_EVENTS` | Auto/manual trade attempt event summary. | Orchestrator. | Reports and debugging. | Permanent. | `event_id` primary key. | Add broker response relation. |
| `DAILY_BRIEFS` | Orchestrator-level briefing rows. | Orchestrator/reporting. | Reports. | Permanent. | `brief_id` primary key. | Consolidate with `TRADING_REPORTS`. |

## Retention Policy

Default retention is permanent because the system is audit-first. Future cleanup should archive old raw broker payloads only after canonical trade lifecycle and performance attribution records are proven complete.
