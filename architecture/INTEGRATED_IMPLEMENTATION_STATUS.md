# Integrated Implementation Status

Living tracking document required by the Founder's approval of `FOUNDER_IMPLEMENTATION_PLAN.md` ("maintain one integrated implementation plan showing: each pillar, dependencies, current status, code affected, tests completed, hosted-production evidence, unresolved risks"). Updated throughout the programme, not just at milestones. Pillars 1–7 rows are seeded and will be filled in as that work begins (post-Phase-0, per the approved dependency-aware parallel model).

**Completion standard in force for every row below** (per the Founder's approval): a pillar/item is not "complete" merely because code exists or unit tests pass. Completion requires production wiring, real callers, verified storage, integration testing, hosted-production evidence where applicable, truthful Founder visibility, and documentation matching the implemented code.

---

## Phase 0 — Mandatory safety gate

| Item | Status | Code affected | Tests completed | Hosted-production evidence | Unresolved risks |
|---|---|---|---|---|---|
| P0-1: `LOGICAL_TRADES` schema on Postgres | Implemented, locally tested | `canonical_trades.py`, `kraken_reconciliation.py`, `api.py` | Full suite (185 tests) passes; no dedicated Postgres test (none available in this environment) | **Outstanding** — confirm tables exist on live Postgres after deploy | Whether any pre-2026-07-28 production evidence was ever written against a schema that didn't exist is unknown and unrecoverable from this repo |
| P0-2: exit-order duplicate-order protection | Implemented, locally tested | `api.py` (`monitor_managed_exits`, `force_managed_exit`), `multi_broker.py` (`release_order_intent_lock`) | 4 new tests added (happy path, duplicate-lock refusal, shared lock between automatic/forced exit, release-on-rejection retry) | **Outstanding** — real duplicate-attempt drill against deployed worker | None identified beyond the already-documented residual gap of no broker-side idempotency key for either broker (P2-2/P2-1) |
| P0-3: duplicate scheduling (cron vs. worker loop) | Implemented | `render.yaml` | Not unit-testable (deployment topology); existing scheduling tests unaffected | **Outstanding** — `SCHEDULED_JOB_RUNS` query post-deploy showing one execution per job per cadence window | None identified; the removed cron services' Render dashboard visibility is a cosmetic-only change |
| P0-4a: Kraken reconciliation connection-per-row | Implemented, locally tested (behavior-preserving) | `canonical_trades.py` (new `_connection` helper threaded through 7 functions), `kraken_reconciliation.py` (threaded through `replay_kraken_evidence` and its full call graph) | Full suite passes; `test_kraken_reconciliation.py`'s existing idempotency/duplicate/ledger tests exercise the refactored code paths unchanged | **Outstanding** — measure actual job duration and connection count after deploy | Deferred: incremental cursor for `BROKER_TRADE_HISTORY` scan (documented as an intentional, lower-risk-first sequencing decision, not an oversight) |
| P0-4b: evidence-snapshot sequential/redundant calls | Implemented, locally tested | `api.py` (`capture_production_broker_snapshots`, `_exchange_portfolio`), `broker_adapters.py` (`get_positions` account reuse) | Full suite passes; concurrency path explicitly gated to Postgres-only so SQLite test runs exercise the unchanged sequential path | **Outstanding** — measure actual job duration after deploy | None identified |
| P0-5: push notifications unreachable in production | Implemented, locally tested | `cli.py` (`_run_named_job`, worker loop, heartbeat payload) | 1 new test (job dispatch); existing push-send tests unchanged | **Outstanding** — real device receives a test notification without opening the app | None identified |

**Phase 0 exit criteria (from the Founder's approval): all of the above move from "Outstanding" to confirmed hosted-production evidence before Seven Pillars implementation work begins.**

---

## Pillar 1 — Operational Excellence

Status: the P0 items above are Pillar 1's remaining gaps as identified in the 2026-07-27 review. P1–P3 items from `CRITICAL_REMEDIATION_PLAN.md` (two independent trade-lifecycle tables, two independent P&L calculators, mobile staleness/timeline contract bugs, token rotation, etc.) are not yet started — approved for parallel work alongside the other six pillars once Phase 0 is hosted-verified, per the dependency-aware model.

## Pillars 2–7 — Trading Intelligence, Market Research, Strategy Laboratory, Learning Engine, Portfolio Intelligence, Platform Evolution

Status: assessed (see `FOUNDER_IMPLEMENTATION_PLAN.md` for the detailed current-state mapping) but not yet started. Per the Founder's approved sequencing, this work begins once Phase 0 is hosted-verified, proceeding as parallel coordinated workstreams rather than sequential pillars, prioritizing connecting the already-built-but-disconnected capability identified in the assessment (backtest/walk-forward engine, strategy promotion gate, correlation math, sector-exposure bucketing, regime 2.0) before any new capability is built.

This section will be populated with the same per-item table structure as Phase 0 once that work begins.
