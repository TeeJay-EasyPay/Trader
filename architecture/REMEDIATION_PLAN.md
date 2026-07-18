# Remediation Plan

Date: 2026-07-18

Status: plan only. No implementation was performed as part of the audit.

## Ordering Principle

Do not enable more autonomous trading before the operating spine can prove what is running.

The correct dependency order is:

1. shared production truth;
2. observable worker;
3. observable scheduled jobs;
4. research freshness;
5. no-trade reason capture;
6. broker reconciliation;
7. learning outbox processing;
8. trading eligibility review.

## Priority 1: Activate Supabase/Postgres For Always-On Evidence

Complexity: Medium

Risk: Medium

Files likely affected:

- `render.yaml`
- `architecture/SUPABASE_POSTGRES_MIGRATION_PLAN.md`
- deployment documentation

Expected benefit:

- API, worker and cron can share job runs, heartbeats, research funnels, shadow trades and incidents.
- Worker/cron can be enabled without SQLite multi-process risk.

Code changes required:

- Possibly none if existing Postgres bridge is sufficient.
- Configuration and deployment verification required.

Exit evidence:

- `/operations-health` reports `database_backend.active_backend = postgres`.
- `/operations-health` reports `database_durability = supabase_postgres`.

## Priority 2: Add Render Background Worker Service

Complexity: Low to Medium

Risk: Medium

Files likely affected:

- `render.yaml`
- `architecture/RENDER_SERVICE_TOPOLOGY.md`
- `STATUS.md`
- `governance/IMPLEMENTATION_LOG.md`

Expected benefit:

- Broker polling, managed exits and auto-execution are no longer dependent on API daemon threads.

Code changes required:

- Likely no functional code changes if `run-worker` is accepted.
- Deployment configuration changes required.

Exit evidence:

- `/operations-health` shows a current healthy worker heartbeat.
- `WORKER_HEARTBEATS` updates while the mobile app is closed.

## Priority 3: Add Render Cron Jobs

Complexity: Medium

Risk: Medium

Files likely affected:

- `render.yaml`
- scheduling architecture docs

Expected benefit:

- Equity research, crypto research, daily learning and reports become time-owned jobs instead of app-triggered events.

Code changes required:

- Render configuration.
- Possibly timezone/schedule tuning.

Exit evidence:

- `SCHEDULED_JOB_RUNS` contains named jobs created by Render cron.
- `/job-runs` shows successful premarket, market-open, midday, market-close, overnight-crypto, daily-learning and daily-report rows over the expected windows.

## Priority 4: Verify Alpaca Research Funnel In Production

Complexity: Medium

Risk: Low

Files likely affected:

- possibly `src/ai_trader/api.py`;
- `architecture/ALPACA_INACTIVITY_ROOT_CAUSE_REPORT.md`.

Expected benefit:

- Founder can see why Alpaca did or did not trade.

Code changes required:

- Only if current funnel records are incomplete after cron/worker verification.

Exit evidence:

- `/alpaca-inactivity-diagnosis` shows:
  - last successful research cycle;
  - last proposal;
  - last valid strategy;
  - last eligible paper recommendation;
  - last submitted paper order or exact rejection reason.

## Priority 5: Implement Worker-Owned Learning Outbox Consumer

Complexity: Medium to High

Risk: Medium

Files likely affected:

- `src/ai_trader/cli.py`
- `src/ai_trader/sprint6.py`
- `src/ai_trader/production_spine.py`
- tests
- learning architecture docs

Expected benefit:

- Closed trades automatically create experience records, post-trade reviews and learning proposals.

Code changes required:

- Yes.

Exit evidence:

- Pending `SPRINT6_WORKFLOW_OUTBOX` rows are processed idempotently.
- `CLOSED_LOOP_LEARNING_RUNS` receives one row per terminal logical trade.
- Duplicate processing does not create duplicate learning.

## Priority 6: Make Market Data Gateway Mandatory For New Recommendations

Complexity: High

Risk: Medium

Files likely affected:

- research modules;
- `src/ai_trader/api.py`;
- `src/ai_trader/production_spine.py`;
- tests;
- market intelligence docs.

Expected benefit:

- Stale or bad market data blocks recommendations before they reach execution.

Code changes required:

- Yes.

Exit evidence:

- Every new recommendation has a market data gateway run ID or explicit unavailable reason.
- Bad candle/stale data tests block recommendations.

## Priority 7: Complete Critical Runtime Postgres Migration

Complexity: High

Risk: High

Files likely affected:

- database access layer;
- audit database;
- broker history;
- recommendations;
- lifecycle;
- reports;
- learning;
- tests;
- architecture docs.

Expected benefit:

- One production truth across API, worker and scheduled jobs.

Code changes required:

- Yes.

Exit evidence:

- `/phase5-status` reports production-ready database spine.
- SQLite remains only for local/offline/test mode.

## Priority 8: Strategy Promotion Governance For Kraken Micro-Live

Complexity: Medium

Risk: High if rushed

Files likely affected:

- strategy maturity registry tools;
- governance docs;
- UI review flow;
- tests.

Expected benefit:

- Kraken live micro-trading can proceed only when evidence supports it.

Code changes required:

- Possibly yes, mostly governed workflow and UI.

Exit evidence:

- Strategy registry shows approved stage and permitted mode.
- Decision journal records why micro-live is permitted.
- No silent promotion occurs.

## Priority 9: Report Automation

Complexity: Medium

Risk: Low

Files likely affected:

- Render cron configuration;
- report docs;
- possibly report persistence paths.

Expected benefit:

- Founder daily/weekly/monthly reports exist without opening the app.

Code changes required:

- Maybe not after cron is configured.

Exit evidence:

- `TRADING_REPORTS` contains daily reports generated by cron.
- Report links open from the app.

## Priority 10: Hosted Verification Script

Complexity: Low

Risk: Low

Files likely affected:

- scripts;
- docs.

Expected benefit:

- Repeatable proof of production autonomy.

Code changes required:

- Yes, but operational only.

Exit evidence:

- A script can verify `/healthz`, `/operations-health`, `/scheduler-status`, `/job-runs`, `/research-funnel`, `/shadow-trades`, and `/alpaca-inactivity-diagnosis` using the API token without printing secrets.

## Recommended Next Sprint

The next sprint should not focus on new trading intelligence.

Recommended next sprint:

> Production Autonomy Verification Sprint

Scope:

1. Configure Supabase/Postgres for Always-On evidence.
2. Enable Render worker.
3. Enable Render cron.
4. Verify worker heartbeat while phone is closed.
5. Verify one scheduled research job while phone is closed.
6. Verify Alpaca no-trade/trade funnel.
7. Produce evidence screenshots and persisted records.

