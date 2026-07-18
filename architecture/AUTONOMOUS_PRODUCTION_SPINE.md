# Autonomous Production Spine

## Objective

The Autonomous Production Spine is the control surface for proving whether AI Trader is operating as one coordinated platform.

It answers:

- Is there one shared production truth?
- Are workers alive?
- Are scheduled jobs running?
- Are incidents generated when autonomous operations degrade?
- Are database migration gaps visible instead of hidden?

## Current Implementation

The implementation lives in `src/ai_trader/production_spine.py`.

The API initializes the schema at startup and exposes:

- `GET /phase5-status`;
- `GET /status` field `phase5_status`.

The mobile Dashboard displays an `Autonomous Production Spine` card.

## Production Spine Tables

### `PRODUCTION_SPINE_SNAPSHOTS`

Records whether each critical runtime family is migrated into the shared production datastore.

### `WORKER_SUPERVISION_RUNS`

Records each worker supervision evaluation, including health score, stale worker count, duplicate worker count, late job count, backlog count, and incidents created.

### `CANONICAL_RECONCILIATION_CASES`

Stores one logical reconciliation case per broker/logical trade ID.

### `CLOSED_LOOP_LEARNING_RUNS`

Ensures closed-loop learning runs once per logical trade.

### `PORTFOLIO_MANAGER_DECISIONS`

Records the mandatory portfolio decision before an action is considered execution-ready.

### `MARKET_DATA_GATEWAY_RUNS`

Records market-data quality decisions and provenance.

### `STRATEGY_PROMOTION_DECISIONS`

Records strategy maturity promotion, hold, or demotion decisions.

## Readiness States

`production_ready` means all critical runtime families share the production database.

`partial_spine` means the system has some production evidence but not a complete shared runtime database.

In the current implementation, Always-On operations evidence can use Supabase/Postgres, while other critical runtime families remain SQLite-oriented. This is deliberately reported as partial.

## Founder Meaning

The Founder should read the production spine card as an operations truth meter.

If it says attention is needed, it does not mean AI Trader is broken. It means the system is honestly reporting that full institutional autonomy is not yet proven.

