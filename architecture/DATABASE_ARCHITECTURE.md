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

## Founder Evidence Projection

`PRODUCTION_FOUNDER_EVIDENCE_SNAPSHOTS` is the durable read projection used by all six Founder screens. It contains one row per supported period:

- `period`: stable key (`1h`, `24h`, `7d`, or `30d`);
- `generated_at`: UTC projection creation time;
- `payload_json`: evidence-derived Founder payload.

The background worker is the sole projection builder. Its existing evidence-snapshot responsibility first captures connected broker evidence and then refreshes all four periods. The API is a read-only consumer for this table. This ownership avoids request-time reconstruction and ensures the phone sees the same shared Postgres truth as the worker.

The table is a derived read model, not a duplicate system of record. Authoritative research, recommendation, broker, trade, learning, heartbeat, job, and funnel rows remain in their existing tables. A stale or absent projection is labelled explicitly and never replaced with synthetic data.

Production connections use bounded defaults: five seconds to establish a connection and eight seconds per SQL statement. Both are configurable through `AI_TRADER_DB_CONNECT_TIMEOUT_SECONDS` and `AI_TRADER_DB_STATEMENT_TIMEOUT_MS`.
