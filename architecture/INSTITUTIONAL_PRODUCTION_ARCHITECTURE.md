# Institutional Production Architecture

## Architecture Principle

Every new capability must answer one of three questions:

1. Does it help AI Trader make a better investment decision?
2. Does it help the Founder make a better decision?
3. Does it help AI Trader learn to make better decisions in the future?

Sprint 6 applies this principle by making evidence and control gates mandatory before execution.

## Current Production Spine

The current runtime architecture is:

```text
Mobile Founder App
        |
        v
Hosted API on Render
        |
        v
Shared runtime database target
        |
        +--> Always-On jobs and worker records
        +--> Recommendations and trade audit
        +--> Strategy maturity registry
        +--> Decision journal
        +--> Portfolio Manager decisions
        +--> Risk Sentinel decisions
        +--> Broker event mappings
        +--> Canonical lifecycle
        +--> Experience and learning records
```

## Execution Chain

```text
Market evidence
  -> recommendation
  -> Sprint 6 decision packet
  -> Portfolio Manager authority
  -> Strategy maturity entitlement
  -> Production Risk Sentinel
  -> Investment Orchestrator
  -> Risk Engine and guardrails
  -> broker adapter
  -> broker polling
  -> canonical reconciliation
  -> learning outbox
```

## Authority Boundaries

- Mobile app: Founder interface only.
- Ask AI Trader: read-only explanation.
- Portfolio Manager: mandatory pre-execution authority.
- Strategy Maturity Registry: controls whether a strategy may execute in a mode.
- Production Risk Sentinel: blocks execution on emergency or operational risk.
- Investment Orchestrator: remains broker submission authority.
- Broker adapters: broker-specific deterministic execution.

## Database Reality

Sprint 6 installs tables that are compatible with SQLite and can migrate to Postgres/Supabase. SQLite remains suitable for local development, testing and offline demos. It is not sufficient as the final multi-process production truth for API, worker and scheduled jobs.

## Render Reality

The code exposes hosted evidence endpoints, but deployment and soak evidence must be captured from Render logs and persisted job records. Source code alone does not prove always-on production operation.

