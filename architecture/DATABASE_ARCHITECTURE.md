# Database Architecture

## Sprint 6 Additive Runtime Control Tables

Sprint 6 adds a production-control layer that is initialized at API startup and is compatible with SQLite for local testing. These tables are intended to migrate to Supabase/Postgres before multi-process hosted production claims.

New tables:

- `OPERATIONAL_EVENTS`: immutable operational evidence from research, broker polling, pre-execution, incidents and reconciliation.
- `DECISION_JOURNAL`: durable pre-execution decision packet for every manual or autonomous trade attempt that reaches Sprint 6 controls.
- `STRATEGY_MATURITY_REGISTRY`: governed strategy maturity, permitted brokers, permitted modes and suspension state.
- `STRATEGY_ENTITLEMENT_DECISIONS`: per-proposal strategy entitlement result.
- `PRODUCTION_RISK_SENTINEL_DECISIONS`: per-proposal operational risk decision.
- `KILL_SWITCH_STATE`: global production stop state used by the Risk Sentinel.
- `SPRINT6_WORKFLOW_OUTBOX`: idempotent workflow queue for closed-loop learning and future durable background tasks.
- `BROKER_EVENT_MAPPINGS`: broker-neutral mapping of raw broker events to canonical lifecycle input.
- `INCIDENT_LIFECYCLE`: deduplicated operational incidents with occurrence counts.
- `FOUNDER_OPERATIONAL_REPORTS`: persisted Sprint 6 operational reports.

SQLite remains useful for local development and tests. Postgres/Supabase remains the required target for shared API, worker and scheduled-job runtime truth.

## Current State

AI Trader remains in a controlled transition from SQLite-first local persistence to a shared production database spine.

SQLite remains supported for:

- local development;
- tests;
- offline demos;
- single-process operation.

Supabase/Postgres is the intended production database for shared runtime truth.

## Critical Runtime Families

Phase 5 defines the critical runtime families:

- Always-On operations;
- recommendations;
- broker runtime;
- canonical lifecycle;
- portfolio intelligence;
- market intelligence;
- experience and learning;
- reports.

All of these must eventually share the same production datastore before API, workers, and scheduled jobs can be treated as fully production-autonomous.

## Current Migration Status

Always-On evidence can use Postgres when configured.

The remaining families are deliberately reported as unmigrated by `production_database_spine_status`.

## API Visibility

`GET /phase5-status` exposes:

- backend type;
- migrated runtime families;
- unmigrated runtime families;
- missing local tables;
- readiness status.

## Principle

Do not duplicate runtime state between SQLite and Postgres.

Each future migration should move one schema family at a time, prove compatibility, and then switch that family to the production database.
