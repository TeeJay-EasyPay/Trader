# Autonomous Service Inventory

Date: 2026-07-18

Scope: every autonomous process visible in source, blueprint and documentation.

## API Process

| Question | Answer |
|---|---|
| What starts it? | Render web service or local CLI. |
| Where is it started? | Dockerfile CMD, `python -m ai_trader.cli serve-api`. |
| When is it started? | On Render deploy/start/restart. |
| How often should it execute? | Continuously as HTTP server. |
| Config enables it? | `AI_TRADER_API_HOST`, `PORT`, `AI_TRADER_API_TOKEN`. |
| Evidence proves it executed? | `/healthz` 200, process logs, API responses. |
| Output stored? | SQLite/Postgres via API methods, reports output dir. |
| Founder verification | App Dashboard and `/healthz`. |

Status: Green for HTTP availability. Orange for autonomous work because the API is still carrying background threads.

## API In-Process Research Scheduler

| Question | Answer |
|---|---|
| What starts it? | `run_server()` in `src/ai_trader/api.py`. |
| Where is it started? | Inside the web API process. |
| When is it started? | At API startup if `RESEARCH_SCHEDULER_ENABLED=true`. |
| Cadence | `RESEARCH_SCHEDULER_INTERVAL_MINUTES`, default 60 minutes. |
| What it runs | `ResearchScheduler.run_once()`, which calls `service.run_analysis()`. |
| Evidence | `RESEARCH_RUNS`, `RESEARCH_FUNNELS`, notifications, operations events. |
| Current evidence | Local inspected DB has no `RESEARCH_RUNS` and no `RESEARCH_FUNNELS`. |
| Founder verification | Dashboard research fields, `/research-funnel`, `/alpaca-inactivity-diagnosis`. |

Status: Orange - Partially Working.

Reason: source path exists, but current durable evidence reviewed does not prove sustained execution.

## Managed Exit Monitor

| Question | Answer |
|---|---|
| What starts it? | `run_server()` daemon thread and `run-worker` cycle. |
| Cadence | 60 seconds in API thread. |
| What it runs | `service.monitor_managed_exits()`. |
| Evidence | managed exit rows, broker orders, notifications, operations events. |
| Current evidence | Source path exists. Hosted runtime not verified. |

Status: Orange - Partially Working.

## Broker Activity Poller

| Question | Answer |
|---|---|
| What starts it? | `run_server()` daemon thread and `run-worker` cycle. |
| Cadence | 60 seconds in API thread. |
| What it runs | `service.poll_broker_activity()`. |
| Evidence | `BROKER_TRADE_HISTORY`, canonical lifecycle records, broker notifications. |
| Current evidence | Local inspected `BROKER_TRADE_HISTORY` has 0 rows. |

Status: Orange - Partially Working.

## Auto Executor

| Question | Answer |
|---|---|
| What starts it? | `run_server()` daemon thread and `run-worker` cycle. |
| Cadence | `AUTO_EXECUTION_INTERVAL_SECONDS`, minimum 30 seconds. |
| What it runs | `service.auto_execute_recommendations()`. |
| Evidence | orchestrator decisions, broker orders, notifications, research funnel submitted count. |
| Requirements | global trading state running, broker auto enabled, paper mode, fresh proposal, guardrails, strategy entitlement, risk sentinel, broker capacity. |
| Current evidence | Local job row exists once; no local broker history. |

Status: Orange - Partially Working.

Important: auto-execution is not a trade generator. It only acts on eligible stored proposals.

## Crypto Universe Refresh

| Question | Answer |
|---|---|
| What starts it? | `run_server()` daemon thread. |
| Cadence | max of 300 seconds or research interval. |
| What it runs | `service.refresh_crypto_universe()`. |
| Evidence | crypto master/intelligence rows, operations events. |
| Current evidence | Source path exists. Hosted runtime not verified. |

Status: Orange - Partially Working.

## Push Notification Dispatcher

| Question | Answer |
|---|---|
| What starts it? | `run_server()` daemon thread. |
| Cadence | 30 seconds. |
| What it runs | `service.dispatch_pending_push_notifications()`. |
| Evidence | notification delivery state. |
| Current evidence | Source path exists. Hosted runtime not verified. |

Status: Orange - Partially Working.

## Explicit Background Worker

| Question | Answer |
|---|---|
| What starts it? | `python -m ai_trader run-worker`. |
| Where is it started? | CLI implemented in `src/ai_trader/cli.py`. |
| When should it start? | As a Render background worker service in target topology. |
| What it runs | `broker-poll`, `managed-exits`, `auto-execution`, then heartbeat. |
| Evidence | `SCHEDULED_JOB_RUNS`, `WORKER_HEARTBEATS`, `OPERATIONS_INCIDENTS`. |
| Current evidence | Local rows exist from one run; Render blueprint does not start it. |

Status: Yellow - Working locally only / Red in current Render blueprint.

## Explicit Scheduled Jobs

| Job | Command | Purpose | Status |
|---|---|---|---|
| Premarket equity | `run-job premarket-equity` | Alpaca research before market. | Implemented, not active in Render. |
| Market-open equity | `run-job market-open-equity` | Opening scan. | Implemented, not active in Render. |
| Midday equity | `run-job midday-equity` | Mid-session scan. | Implemented, not active in Render. |
| Market-close equity | `run-job market-close-equity` | Close review. | Implemented, not active in Render. |
| Overnight crypto | `run-job overnight-crypto` | Crypto analysis. | Implemented, not active in Render. |
| Daily learning | `run-job daily-learning` | Daily learning update. | Implemented, not active in Render. |
| Daily report | `run-job daily-report` | Founder report. | Implemented, not active in Render. |

Status: Yellow - Implemented locally, waiting for Render/Postgres activation.

## Shadow Trading

| Question | Answer |
|---|---|
| What creates it? | `_record_shadow_from_proposal()` from generated proposals. |
| What stores it? | `SHADOW_TRADES`. |
| What should update outcomes? | Always-On shadow outcome functions. |
| Current evidence | Local `SHADOW_TRADES` has 0 rows. |

Status: Orange - Partially Working.

## Closed-Loop Learning

| Question | Answer |
|---|---|
| What runs it? | `run_closed_loop_learning()` in `production_spine.py`. |
| What queues it? | `enqueue_learning_workflow()` in `sprint6.py`. |
| What consumes queued work? | No automatic outbox consumer found during audit. |
| Current evidence | Local outbox table missing in inspected DB; closed-loop runs table missing. |

Status: Red - Not automatic.

## Founder Reports

| Report | Generation Path | Automatic Path | Evidence |
|---|---|---|---|
| Daily trading report | API `/trading-report`, `run-job daily-report` | Cron intended, not active in blueprint | Local `TRADING_REPORTS` empty. |
| Weekly report | API report type | No active cron found | Not proven. |
| Monthly report | API report type | No active cron found | Not proven. |
| Daily learning update | API `/daily-learning-update`, `run-job daily-learning` | Cron intended, not active | Function exists, auto schedule not deployed. |
| Operational report | API `/generate-operational-report` | Manual POST path | No automatic schedule proven. |

Status: Orange - Manual/API capable, not proven automatic.

