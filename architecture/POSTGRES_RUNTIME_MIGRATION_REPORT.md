# Postgres Runtime Migration Report

## Current State

AI Trader currently supports `AI_TRADER_DATABASE_BACKEND` and `DATABASE_URL` or `SUPABASE_DATABASE_URL` in settings. Phase 5 and Sprint 6 make the database backend visible in `/status`, `/phase5-status`, and `/sprint6-status`.

## Implemented In Sprint 6

Sprint 6 adds a deterministic runtime schema for critical control records:

- Operational events.
- Decision journal.
- Strategy maturity registry.
- Strategy entitlement decisions.
- Production Risk Sentinel decisions.
- Kill switch state.
- Learning workflow outbox.
- Broker event mappings.
- Incident lifecycle.
- Founder operational reports.

## Migration Position

The schema is additive and SQLite-compatible. The next migration step is to move the critical runtime families to Supabase/Postgres with a real SQL execution layer rather than simply storing a `DATABASE_URL`.

## Critical Runtime Families

The following should be backed by Postgres before full autonomous production claims:

- Recommendations.
- Proposal state.
- Broker runtime.
- Broker history.
- Order intent locks.
- Managed exits.
- Canonical lifecycle.
- Execution costs.
- Attribution.
- R multiples.
- MAE/MFE.
- Portfolio intelligence.
- Market intelligence.
- Experience records.
- Learning proposals.
- Reports.
- Operational events.

## Founder Meaning

If `/sprint6-status.shared_runtime_truth` says SQLite is active, AI Trader is in local/test/offline mode for shared production truth. That does not mean the app is broken. It means the system should not be treated as a multi-process autonomous production database yet.

