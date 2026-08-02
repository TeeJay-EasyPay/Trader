# AI Trader Modularisation Architecture and Implementation Plan

**Date:** 2026-08-02  
**Source baseline:** `master`, commit `32d33a5a`  
**Primary discovery input:** `architecture/AI_TRADER_MODULARISATION_DISCOVERY_PACK_2026-08-02.md`  
**Companion input:** `architecture/CURRENT_STATE_FOR_REDESIGN_2026-08-02.md`

## 1. Purpose

Modularise the AI Trader application without changing its external behaviour, trading policy, database state, deployment behaviour, or mobile API contracts.

This is an **incremental extraction**, not a rewrite.

The primary architectural problem is the concentration of routing, orchestration, presentation, reporting, broker operations, research and execution responsibilities inside `LocalApiService` in `api.py`.

The existing domain modules should be preserved wherever possible.

## 2. Required Outcomes

1. Reduce `api.py` to HTTP routing and composition responsibilities.
2. Introduce clearly bounded application services.
3. Preserve every existing HTTP path and response shape.
4. Preserve every safety control and trading decision rule.
5. Eliminate repeated runtime schema initialisation from hot paths.
6. Add contract tests before moving mobile-consumed API handlers.
7. Keep every implementation step small, testable and independently revertible.
8. Do not perform database cleanup or remove dormant schemas during this work.

## 3. Non-Negotiable Safety Invariants

The implementation must preserve and test all of the following:

- A live order cannot be submitted while the global kill switch is active.
- Engine paused/stopped state blocks autonomous execution.
- Broker auto-trading authorisation remains broker-specific.
- Kraken reconciliation hold remains separate from founder override.
- Kraken personal holdings never enter the AI trading capital sleeve.
- Kraken order size, allocation, allowed-pair and buy-only checks remain enforced at the adapter boundary.
- Order-intent locks remain atomic and prevent duplicate order submission.
- An uncertain broker outcome must not cause an order-intent lock to be automatically released.
- Strategy maturity and entitlement remain mandatory before execution.
- Data freshness, risk, concentration and portfolio checks remain mandatory.
- Alpaca remains paper-only unless an explicitly approved future change alters that policy.
- Managed exits retain both broker-side protection and application-side monitoring.
- No extraction may alter position sizing, loss limits, trading permissions or risk calculations.

Document and test the execution-gate precedence:

```text
Global kill switch
→ engine state
→ broker auto-trading authorisation
→ reconciliation hold
→ broker/pair/order-size restrictions
→ strategy entitlement
→ data freshness
→ portfolio and risk checks
→ order-intent lock
→ broker submission
```

## 4. Target Structure

Use a small number of cohesive modules. Do not create a large collection of tiny wrapper files.

```text
src/
  api/
    router.py
    http_server.py
    auth.py
    contracts.py

  application/
    context.py
    founder_experience_service.py
    reporting_service.py
    research_service.py
    broker_service.py
    operations_service.py
    administration_service.py
    execution_service.py

  persistence/
    query_executor.py
    schema_once.py

  # Existing domain modules remain in place initially:
  orchestrator.py
  multi_broker.py
  trading_intelligence.py
  production_spine.py
  operational_truth.py
  portfolio_intelligence.py
  kraken_reconciliation.py
  production_evidence.py
  always_on.py
  foundation.py
  sprint6.py
```

### Application context

Introduce one composition root that constructs shared stateful dependencies once per process.

```python
@dataclass(frozen=True)
class ApplicationContext:
    settings: Settings
    audit: AuditDatabase
    intelligence: InvestmentIntelligenceDatabase
    benchmark: BenchmarkIntelligenceDatabase
    orchestrator: InvestmentOrchestrator
    brokers: Mapping[str, BrokerAdapter]
```

Application services should receive only the context or dependencies they require. They must not construct duplicate broker adapters, database services or orchestrators.

## 5. Dependency Rules

1. `api/*` may depend on `application/*`.
2. `application/*` may depend on existing domain modules and `persistence/*`.
3. Domain modules must not depend on `api/*` or presentation services.
4. Presentation services may read operational state but must not mutate trading state.
5. `execution_service.py` coordinates execution but must not absorb or duplicate authoritative risk, entitlement, reconciliation or broker validation logic.
6. Shared application services must not call each other cyclically. Cross-service dependencies should go through explicit domain services or the application context.
7. Preserve the existing one-directional dependency graph unless a change is separately justified and tested.

## 6. Stage 0 — Mandatory Safety and Characterisation Work

Complete this stage before moving production logic.

### 6.1 Resolve safety unknowns

- Prove that `KILL_SWITCH_STATE` is consulted before every live order submission.
- Add an integration test showing an active kill switch prevents `place_bracket_order`.
- Confirm the exact behaviour of engine state, broker authorisation, reconciliation hold and strategy entitlement when multiple blocks are active.
- Confirm atomic order-intent locking under both SQLite tests and production Postgres semantics.
- Confirm whether HTTP requests and scheduled jobs can execute trading logic concurrently.

### 6.2 Fix schema initialisation risks

- Add process-level, thread-safe schema-once protection to `portfolio_intelligence.py`.
- Trace all `operational_truth.py` schema-init call sites and fix any hot-path repetition.
- Review `experience_engine.py` before terminal-trade volume begins.
- Replace duplicated `_SCHEMA_LOCK/_INITIALIZED_SCHEMA_KEYS/_schema_key` implementations with one tested helper in `persistence/schema_once.py`.
- Do not change schema definitions in this stage.

### 6.3 Capture API contracts

Create response-shape characterisation tests for every confirmed mobile-consumed endpoint, including:

- `/founder-evidence`
- `/founder-brief`
- `/intelligence/companies`
- `/intelligence/themes`
- `/trading-report`
- `/notifications`
- `/run-analysis`
- `/run-crypto-analysis`
- `/start-trading`
- `/resume-trading`
- `/stop-trading`
- `/auto-execute-recommendations`
- `/approve-and-execute`
- `/broker-auto-trading`
- `/force-managed-exit`
- `/kraken-reconciliation/replay`
- `/generate-report`
- `/ask-ai-trader`

Trace the mobile command/path lookup fully and add any additional consumed endpoints.

Tests should validate:

- top-level keys;
- nesting;
- list/object types;
- nullability;
- number/string/boolean types;
- error-envelope shape;
- required ordering where the mobile UI depends on it.

### 6.4 Add missing safety tests

Add dedicated tests for:

- Kraken buy-only enforcement;
- Kraken allowed-pair enforcement;
- Kraken capital-sleeve isolation;
- Alpaca paper-only enforcement;
- uncertain broker outcome retaining the order-intent lock;
- operational-truth reconciliation;
- portfolio-intelligence schema caching and first-trade concentration behaviour.

Diagnose or explicitly quarantine the known flaky production-spine test before using the full suite as a refactor gate.

## 7. Incremental Extraction Sequence

### Phase 1 — HTTP transport

Extract `ApiHandler` to `api/http_server.py`.

Preserve exactly:

- authentication;
- `/healthz` exemption;
- CORS;
- body parsing;
- IP lockout;
- error envelopes;
- response serialisation;
- logging behaviour.

Keep route paths and handler results unchanged.

### Phase 2 — Query execution

Extract `_connect`, `_row`, `_rows`, `_scalar` and `_count` into an injected `QueryExecutor`.

Avoid a broad inheritance mixin. Use explicit composition.

### Phase 3 — Reporting service

Move the report pipeline into `application/reporting_service.py`:

- `trading_report`
- `report_page`
- report-source refresh
- broker-learning markdown
- report writing and persistence
- report generation

Preserve `/trading-report`, `/generate-report` and `/reports/*` contracts exactly.

### Phase 4 — Founder presentation service

Move read-only founder-facing aggregation into `application/founder_experience_service.py`, including:

- founder experience payload;
- world-class evidence;
- executive summaries;
- connection readiness;
- portfolio extremes;
- positions requiring attention;
- strategy/signal summaries;
- supporting presentation helpers.

This service must not execute trades, change broker settings or mutate operational controls.

### Phase 5 — Research service

Move:

- `run_analysis`;
- `run_crypto_analysis`;
- `refresh_strategy_lab`;
- `refresh_crypto_universe`;
- research recording and enrichment;
- shared cycle bookkeeping.

Preserve separate equity and crypto entry points. Share only lifecycle helpers that are genuinely common.

### Phase 6 — Broker and operations services

Move broker panels, broker activity polling, production snapshots, operational timelines, notifications and reconciliation presentation into bounded broker/operations services.

Re-run all Kraken isolation and reconciliation tests after each move.

### Phase 7 — Administration service

Move:

- trading-state administration;
- broker auto-trading settings;
- Render API synchronisation;
- guarded lock release;
- founder reconciliation override;
- developer/diagnostic status.

Keep guarded administrative actions separate from ordinary presentation endpoints.

### Phase 8 — Execution service, last

Only after all previous phases are stable, move:

- `approve_and_execute`;
- autonomous recommendation execution;
- managed-exit monitoring;
- forced managed exits;
- execution-specific helper checks.

`ExecutionService` is an application coordinator only. Authoritative controls remain in:

- `orchestrator.py`;
- `guardrails.py`;
- `sprint6.py`;
- `foundation.py`;
- `portfolio_intelligence.py`;
- `multi_broker.py`;
- `broker_adapters.py`;
- `kraken_reconciliation.py`.

## 8. Router End State

`LocalApiService.get()` and `.post()` should eventually become a small declarative route map or thin dispatch layer.

Example:

```python
GET_ROUTES = {
    "/status": status_service.status,
    "/portfolio": founder_service.portfolio,
    "/trading-report": reporting_service.trading_report,
}
```

Prefix and query-aware routes may retain small explicit handlers.

Do not introduce a web framework migration during this modularisation. Replacing `BaseHTTPRequestHandler` is a separate future decision.

## 9. Database and Schema Policy

During this implementation:

- do not drop tables;
- do not rename tables;
- do not migrate data;
- do not consolidate overlapping schemas;
- do not remove apparently dormant modules;
- do not alter production database state except through existing application behaviour.

Create a separate **Schema Disposition Register** classifying each questionable table as:

- active;
- future planned;
- historical/experimental;
- externally populated;
- candidate for later removal;
- unknown pending production evidence.

Runtime schema assurance and formal migration ownership should be reviewed after modularisation, not mixed into the extraction.

## 10. Mobile Follow-On Workstream

Backend extraction is the first priority.

After the backend stabilises, modularise `mobile/App.js` separately:

```text
mobile/
  api/
    client.js
    endpoints.js
  screens/
    DashboardScreen.js
    ActivityScreen.js
    RecommendationsScreen.js
    PortfolioScreen.js
    MarketScreen.js
    LearningScreen.js
  components/
  presentation/
    founderPresentation.js
```

Before changing screens:

- establish an `npm test` command;
- retain and expand pure presentation tests;
- add linting;
- trace every endpoint used by the app;
- investigate and disposition `mobile/inspect-output`;
- decide whether `mobile/dist` should be version controlled.

Do not combine the backend and mobile monolith refactors in one implementation phase.

## 11. Delivery Controls

Each phase must:

1. move one cohesive responsibility only;
2. preserve behaviour;
3. add or retain tests before deletion of the old implementation;
4. pass focused safety tests;
5. pass API contract tests;
6. pass the full stable test suite;
7. produce a small, independently revertible commit;
8. update the implementation log;
9. include a brief before/after dependency summary;
10. stop immediately if a trading, reconciliation, capital-isolation or API-contract regression appears.

Use delegation before deletion:

```text
Old LocalApiService method
→ delegates to new service
→ tests prove equivalence
→ old body removed in a later commit
```

Do not move and redesign logic simultaneously.

## 12. Acceptance Criteria

The modularisation is complete when:

- `api.py` contains only composition, route dispatch compatibility and temporary delegations;
- `ApiHandler` is isolated in the HTTP layer;
- major application responsibilities reside in bounded services;
- no safety-critical behaviour has changed;
- all mobile API contracts are protected by tests;
- schema initialisation is thread-safe and once-per-process across hot paths;
- no new circular dependency exists;
- no shared dependency is constructed more than once per application process without an explicit reason;
- the full stable Python test suite passes;
- mobile presentation tests pass;
- production smoke checks pass;
- architecture and implementation logs describe the final module ownership.

## 13. Explicitly Out of Scope

Do not perform any of the following as part of this work:

- trading-strategy redesign;
- financial-policy changes;
- broker-policy changes;
- new live-trading authorisations;
- database cleanup;
- dead-table deletion;
- web-framework migration;
- mobile visual redesign;
- TypeScript conversion;
- cloud/deployment redesign;
- replacement of Render;
- replacement of the database;
- new features.

## 14. Claude Implementation Instruction

Read both architecture discovery documents and the repository before editing.

Implement this plan sequentially, beginning with **Stage 0 only**. Do not begin code extraction until every Stage 0 safety and characterisation requirement is either completed or documented as blocked with evidence.

After Stage 0, implement one phase at a time. At the end of each phase:

- run focused tests;
- run the stable full suite;
- report files changed;
- report behaviour preserved;
- report any unresolved risk;
- commit the phase separately;
- stop for review before moving to the next phase unless explicitly authorised to continue.

The objective is not merely to split files. The objective is to create clear ownership boundaries while preserving the exact conditions under which the application may and may not place a trade.
