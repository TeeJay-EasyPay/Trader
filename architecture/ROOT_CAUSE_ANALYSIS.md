# Root Cause Analysis

Date: 2026-07-18

## Primary Question

Why is AI Trader not yet behaving like a continuously operating autonomous investment platform?

## Short Answer

Because the production operating topology is not yet complete or proven.

The code contains many autonomous mechanisms, but the active Render blueprint is still a single web service using SQLite. Separate worker and cron services are intentionally not enabled. Supabase/Postgres is only partially supported for Always-On evidence and is not selected in `render.yaml`.

## Root Cause 1: Render Has Only One Active Service

Classification: Deployment / Architecture

Evidence:

- `render.yaml` declares only `type: web` service `ai-trader-api`.
- Worker and cron commands appear only as comments.
- Architecture documentation says worker/cron should wait until Postgres is active.

Impact:

- Background operations depend on API process daemon threads or manual/local CLI.
- No separate worker heartbeat can be expected from Render unless a worker service is manually configured outside the blueprint.
- No Render cron job can be expected unless manually configured outside the blueprint.

Severity: High.

## Root Cause 2: SQLite Is Still The Blueprint Runtime Backend

Classification: Database / Configuration

Evidence:

- `render.yaml` sets `AI_TRADER_DATABASE_BACKEND=sqlite`.
- `README.md`, `STATUS.md`, and `architecture/RENDER_SERVICE_TOPOLOGY.md` state that worker/cron should not be enabled until Supabase/Postgres is active.
- `architecture/KNOWN_LIMITATIONS.md` states critical runtime families remain SQLite-oriented.

Impact:

- API, worker, and cron cannot safely share one production truth if each is an independent process writing SQLite.
- Correctly, the blueprint avoids starting multiple write-owning services.
- This keeps production autonomy incomplete.

Severity: High.

## Root Cause 3: API In-Process Threads Are Not Enough Evidence

Classification: Architecture / Observability

Evidence:

- `run_server()` starts daemon threads for research, exits, polling, auto-execution, crypto refresh and push dispatch.
- These threads are inside the web process.
- Local database has no sustained research/run evidence.

Impact:

- The system may do work while the API is alive, but it is hard to prove from deployment alone.
- If the API process restarts, sleeps or fails, those loops stop.
- Daemon threads do not provide the same operational guarantee as supervised workers and persisted cron records.

Severity: High.

## Root Cause 4: Research Evidence Is Missing Or Stale

Classification: Runtime Evidence / Scheduler

Evidence:

- Local inspected `RESEARCH_RUNS`: 0 rows.
- Local inspected `RESEARCH_FUNNELS`: 0 rows.
- Old local `trade_audit` proposal rows date back to 2026-07-03.
- Previous screenshots showed recommendations remaining static and report rows missing current trade attribution.

Impact:

- The Founder cannot distinguish "nothing qualified" from "research did not run."
- Auto-execution has no fresh eligible proposals to act upon.
- Reports and learning have little current evidence.

Severity: High.

## Root Cause 5: Auto-Execution Requires Fresh Eligible Proposals

Classification: Design Choice / Correct Safety Behaviour

Evidence:

`auto_execute_recommendations()` requires:

- engine trading state `running`;
- at least one broker auto setting enabled;
- `PAPER_TRADING_ONLY=true`;
- stored `agent_proposal` rows;
- confidence above threshold;
- recommendation not expired;
- execution guardrails pre-passed;
- selected broker configured;
- broker auto enabled;
- AI-managed trade capacity available;
- Sprint 6 pre-execution approved;
- Investment Orchestrator approved.

Impact:

- Enabling auto trading does not itself create trades.
- If research is stale, no proposals exist, or pre-execution blocks a proposal, no order is submitted.

Severity: Medium.

This is mostly correct behaviour. The missing piece is better operational evidence explaining which gate stopped action.

## Root Cause 6: Kraken Live Trading Is Governance-Blocked By Strategy Maturity

Classification: Governance / Strategy Maturity

Evidence:

- `seed_default_strategy_registry()` seeds `current_recommendation_process` at stage `Paper`.
- Permitted modes are `shadow`, `paper`, and `manual`.
- `strategy_entitlement_decision()` blocks modes not in the registry.
- `architecture/KNOWN_LIMITATIONS.md` explicitly says default Sprint 6 strategy does not allow `micro_live` or production execution.

Impact:

- Kraken can be connected and still not place new live orders if the execution mode resolves to `micro_live`.
- This is intentional until strategy promotion evidence exists.

Severity: Medium.

## Root Cause 7: Closed-Loop Learning Is Not Fully Automatic

Classification: Missing Feature / Worker

Evidence:

- `enqueue_learning_workflow()` inserts pending `closed_loop_learning` work.
- `run_closed_loop_learning()` performs idempotent learning.
- No automatic outbox consumer was found by searching for `SPRINT6_WORKFLOW_OUTBOX`, `workflow_type`, and `closed_loop_learning`.
- `architecture/AUTONOMOUS_LEARNING_WORKFLOW.md` says the next step is a worker-owned outbox processor.
- `architecture/KNOWN_LIMITATIONS.md` says automatic outbox processing still needs completion.

Impact:

- Terminal trade learning may be queued but not processed automatically.
- The app may show limited or stale learning.

Severity: High.

## Root Cause 8: Market Data Gateway Is Not Yet Mandatory In Live Research

Classification: Partial Implementation

Evidence:

- `market_data_gateway_validate()` exists in `production_spine.py`.
- Tests reference it.
- Source search did not show it being called from `api.py` research or execution paths.
- Pre-execution packets record market data quality as unknown for persisted/manual recommendations.

Impact:

- Bad data validation exists as a component, but the full provider gateway is not yet the mandatory upstream route for every recommendation.
- Recommendations can still rely on older broker/research paths.

Severity: Medium.

## Root Cause 9: Reports Are Mostly Request-Driven

Classification: Scheduler / Deployment

Evidence:

- `/trading-report` creates/persists reports.
- `run-job daily-report` exists.
- No Render cron job exists in `render.yaml`.
- Local `TRADING_REPORTS`: 0 rows.

Impact:

- Reports may be generated when the app requests them.
- Automatic daily/weekly/monthly report generation is not proven.

Severity: Medium.

## Root Cause 10: Hosted Runtime Evidence Could Not Be Fully Verified

Classification: Operational Access / Unknown

Evidence:

- `/healthz` worked.
- Protected endpoints required authentication.
- Authenticated runtime checks could not connect from this environment during the audit.
- Render logs were not available.

Impact:

- The audit can prove source and blueprint state.
- It cannot prove current Render dashboard environment values, live logs, worker records or cron records.

Severity: Medium.

## Final Root Cause Classification

| Issue | Cause Type | Confidence |
|---|---|---:|
| No separate autonomous worker in blueprint | Deployment/architecture | High |
| No Render cron jobs in blueprint | Deployment/architecture | High |
| SQLite selected as runtime backend | Configuration/database | High |
| Supabase/Postgres not fully active | Configuration/database | High |
| In-process API threads relied on for background work | Architecture | High |
| No durable evidence of sustained research in inspected DB | Runtime evidence | High |
| No automatic closed-loop learning outbox consumer | Missing feature | High |
| Kraken live orders blocked by strategy maturity | Governance/design | High |
| Reports not automatically scheduled in blueprint | Deployment/scheduler | High |
| Live Render env/logs not fully inspectable | Operational access | Medium |

## Single Biggest Issue

The single biggest issue is the missing production operations spine:

> AI Trader needs a shared production database plus independently deployed worker and scheduled jobs before autonomy can be truthfully claimed.

