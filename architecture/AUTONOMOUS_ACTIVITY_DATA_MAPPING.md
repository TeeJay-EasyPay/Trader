# Autonomous Activity Data Mapping

Date: 2026-07-19

## Read Model Contract

Each activity item returned by the backend contains:

- `activity_id`
- `event_type`
- `event_category`
- `source_table`
- `source_record_id`
- `timestamp`
- `title`
- `summary`
- `detailed_reason`
- `outcome`
- `severity`
- `component`
- `asset_or_symbol`
- `broker`
- `strategy`
- `recommendation_id`
- `order_id`
- `trade_id`
- `incident_id`
- `founder_action_required`
- `navigation_target`
- `raw_evidence_available`

## Source Tables

### `SCHEDULED_JOB_RUNS`

Mapped to system, research, execution, broker, learning, and report activity depending on `job_name`.

Examples:

- `overnight-crypto` -> Research
- `broker-poll` -> Brokers
- `auto-execution` -> Execution
- `daily-learning` -> Learning
- `daily-report`, `weekly-report`, `monthly-report` -> Reports

Counts from this table power:

- research runs;
- recommendations created;
- shadow decisions created;
- paper orders submitted;
- paper orders filled;
- job failures.

### `WORKER_HEARTBEATS`

Used by `/operations-health` and Activity status to prove whether the background worker is alive.

The UI must never equate API availability with autonomous health. Worker heartbeat freshness is the key proof.

### `RESEARCH_FUNNELS`

Mapped to Research activity and the Why No Trade funnel.

Important fields:

- `symbols_examined`
- `symbols_with_adequate_data`
- `interesting_ideas`
- `valid_strategies`
- `committee_approved`
- `portfolio_approved`
- `guardrail_approved`
- `eligible_for_paper_execution`
- `submitted`
- `filled`
- `rejected`
- `primary_reason`
- `secondary_reasons_json`

### `OPERATIONAL_EVENTS`

Mapped using `component`, `event_type`, `severity`, `summary`, `broker`, and linked IDs.

Examples:

- Production Risk Sentinel block;
- report generated;
- learning processor outcome;
- broker polling incident.

### `DECISION_JOURNAL`

Mapped to decision events.

Used to show whether a proposal was approved, rejected, blocked, or made execution-eligible.

### `PORTFOLIO_MANAGER_DECISIONS`

Mapped to Portfolio Manager decision events.

Used to show portfolio approvals, rejections, manual review requirements, and sizing decisions.

### `BROKER_TRADE_HISTORY`

Mapped to broker execution events.

Used for:

- order submission evidence;
- fills;
- partially filled records;
- closed records;
- latest broker activity by Alpaca and Kraken.

### `CANONICAL_RECONCILIATION_CASES`

Mapped to reconciliation activity.

Used to show whether broker events were matched to one logical trade and whether manual review is needed.

### `CLOSED_LOOP_LEARNING_RUNS`

Mapped to learning activity.

Used only when closed-loop learning actually recorded a completed or failed learning run.

### `FOUNDER_OPERATIONAL_REPORTS` and `TRADING_REPORTS`

Mapped to reporting activity.

The Activity screen only reports generated reports when rows exist.

### `INCIDENT_LIFECYCLE`

Mapped to incident activity and Founder attention.

Unresolved incidents become action items.

## Truthfulness Rules

- Missing tables are skipped, not invented.
- Empty tables create empty states, not fake activity.
- Old rows remain visible only if they fall inside the selected period.
- Counts are summed from source records.
- Current health is based on worker, scheduler, database, research, broker, and incident evidence, not API availability alone.

