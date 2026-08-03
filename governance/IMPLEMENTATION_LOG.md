# Implementation Log

## 2026-08-02 Modularisation Phase 9 (items 1-4) — wrapper audit, helper consolidation, dead code, schema fix

Implements items 1-4 of the ChatGPT-authored Phase 9 directive (behaviour-preserving cleanup,
following Founder authorization of Stage 0 through Phase 8). Items 5-11 (verification,
git/deployment, production smoke checks, and the read-only UI investigation) are separate,
later steps in the same directive, done by the coordinating session after this work is
reviewed.

**Item 1 - Compatibility wrapper audit.** Audited all 50 thin delegate methods remaining in
`LocalApiService` (an AST-based scan of every one-line `return self._X_service.method(...)`
method body, not a manual guess) against every possible external caller: the GET/POST route
dispatch table, `run_server()`'s `IntervalWorker`/`ResearchScheduler` wiring, `cli.py`, the rest
of `src/ai_trader/`, `tests/*.py`, and patch/patch.object targets. **49 of 50 are required** -
each has a confirmed external caller in at least one of those places. **One delegate,
`_refresh_report_sources`, has zero external callers anywhere** (not the route table, not
`run_server()`, not `cli.py`, not any test, not any patch target) - removed. No delegate was
redirected merely to shrink line count; only the one genuinely dead wrapper was touched.

**Item 2 - Shared pure helpers.** Before consolidating, verified byte-for-byte that every
existing duplicate of the 7 named helpers (`_broker_label`, `_money_text`,
`_estimated_in_positions`, `_broker_trade_payload`, `_broker_trade_symbol`, `_int_or_default`,
`_csv_env`) was identical across every `application/*.py` copy - confirmed no drift anywhere.
Created `src/ai_trader/application/shared_helpers.py` (a dependency-free leaf: only stdlib and
`..operational.safe_float`, no `application/*` imports, so it introduces no circular import).
Every `application/*.py` file that previously duplicated one or more of these 7 now imports
them from `shared_helpers.py` instead - `broker_service.py` (5 of 7), `reporting_service.py` (5
of 7, `_broker_trade_side`/`_quantity`/`_price`/`_time` stayed since they were never on the
list), `founder_experience_service.py` (2 of 7), `execution_service.py`/`operations_service.py`/
`research_service.py` (`_int_or_default` each, plus `_csv_env` in `research_service.py`).
`api/__init__.py` still has its own separate copies of 4 of these 7 - deliberately **not**
touched, since the directive's item 2 explicitly scopes to "every application/*.py file," which
`api/__init__.py` is not; flagged here rather than silently left inconsistent. Two now-unused
imports (`json` in `broker_service.py` and `reporting_service.py`, `os` in `research_service.py`)
were removed as a direct consequence. Added `tests/test_shared_helpers.py` (14 tests) since none
of the 7 helpers had any direct test coverage before this (only indirect exercise through the
services that called them).

**Item 3 - Dead code.** Reconfirmed (not just trusted the Phase 6b log entry) that
`OperationsService.autonomous_activity` has zero callers anywhere - route dispatch, `cli.py`,
every test file, everywhere else in `src/ai_trader/` - and that `/autonomous-activity` genuinely
calls `production_activity` instead. Removed the method, its now-unused
`autonomous_activity_payload` import, and a stale docstring comment on `broker_panels()` in
`api/__init__.py` that named the now-deleted method as one of its callers. `_broker_panels_lookup`
(which the dead method also used) remains genuinely needed by `status()`, confirmed before
leaving it in place.

**Item 4 - Report schema-reinitialisation fix.** `record_trading_report` used to run
`REPORT_SCHEMA`'s `executescript` on every single persisted report - a known bug, documented and
deliberately left unfixed in Phase 3's log entry ("do not move and redesign logic
simultaneously"). Root cause: `initialize_schema()` (called once from `LocalApiService.__init__`,
but only when `initialize_runtime=True` - not guaranteed in the "worker owns runtime" split-
process hosted path) ran the schema script unconditionally, and `record_trading_report`
independently re-ran the identical script defensively, since it couldn't assume
`initialize_schema()` had already run for this process. Fixed by routing both through the
existing `persistence/schema_once.py` helper (`ensure_schema_once`) - `initialize_schema()` now
only runs the real `executescript` once per (backend, db_path) per process, and
`record_trading_report` now calls `self.initialize_schema()` first instead of duplicating the
inline schema statement, so the defensive guarantee is preserved (self-healing if
`initialize_schema()` was never called) while the redundant work disappears entirely after the
first call in either order. `schema_once.py` is already backend-aware (Postgres and SQLite), so
no new backend-specific logic was needed. Added
`test_record_trading_report_does_not_reinitialize_schema_on_every_call`
(`tests/test_world_class_transformation.py`): warms the schema-once cache, then proves
`QueryExecutor.connect` (the only thing `initialize_schema()`'s guarded init closure calls) is
never invoked again across two subsequent `record_trading_report` calls.

**Verification.** `python -m py_compile` clean on every touched file. Full stable suite passed
clean twice independently: 302 passed (287 + 14 new helper tests + 1 new schema-fix regression
test), 0 failed both runs. `api/__init__.py`: 2,332 -> 2,329 lines (net roughly unchanged - one
delegate removed, one stale comment shortened, offset by nothing added). `broker_service.py`:
990 -> 943 (-47). `reporting_service.py`: 903 -> 872 (-31, partially offset by the schema-fix
comments). `founder_experience_service.py`: 649 -> 623 (-26). `execution_service.py`: 711 -> 706
(-5). `operations_service.py`: 389 -> 364 (-25). `research_service.py`: 933 -> 914 (-19). New
`shared_helpers.py`: 74 lines.

**Not committed yet** by this work - left in the working tree for the coordinating session's own
independent verification (items 5-7 of the directive) before committing, matching the process
established since an earlier phase's fork committed without waiting for review.

**Next.** Items 5-7 (final architecture review, safety verification, full validation against the
cumulative diff), then item 8 (git commit and push), item 9 (production smoke verification),
item 10 (documentation/Founder briefing), and item 11 (the read-only UI data freshness
investigation) proceed as separate steps.

## 2026-08-02 Modularisation Phase 8 — execution service extraction (final extraction phase)

Implements Phase 8 of `architecture/AI_TRADER_MODULARISATION_ARCHITECTURE_2026-08-02.md`
("Execution service, last... approve_and_execute; autonomous recommendation execution;
managed-exit monitoring; forced managed exits; execution-specific helper checks. ExecutionService
is an application coordinator only."), per a detailed ChatGPT-authored directive reviewed and
authorized by the Founder on 2026-08-02, following a prerequisite boundary audit of
`broker_service.py`/`operations_service.py` (see that audit's own record below) that found no
violations, clearing this phase to proceed.

**Prerequisite boundary audit (no violations found).** Read every method in `broker_service.py`
and `operations_service.py`, grepped both files exhaustively for raw SQL writes and for calls to
any order-submission/authorization/lock/reconciliation-hold-mutating function, and traced
`reconciliation_control`/`broker_auto_settings` to confirm both are genuinely read-only despite
their names. Everything in both files is either read-only or writes only observational/audit
records (trade history, snapshots, canonical lifecycle events, notifications, push tokens) -
never trading authorization, execution permission, locks, or the reconciliation hold/control
state. This matches Phase 6's own scope description ("broker activity polling... reconciliation
presentation"), confirmed by tracing `normalize_broker_events`/`reconcile_canonical_broker_event`
directly: they record observed broker fills into the canonical trade lifecycle, they never write
`KRAKEN_RECONCILIATION_CONTROL.hold_new_entries` or any authorization flag.

**New `src/ai_trader/application/execution_service.py`** (711 lines): `ExecutionService` holding
10 methods moved verbatim from `LocalApiService` - `approve_and_execute`,
`_proposal_with_manual_amount`, `_manual_approval_auto_config`, `_auto_config_for_broker`,
`auto_execute_recommendations`, `auto_execute_recommendations_alpaca`,
`auto_execute_recommendations_kraken`, `monitor_managed_exits`, `force_managed_exit`,
`_proposal_already_executed` - plus 7 exclusive helper functions (`_int_or_default`,
`_parse_datetime`, `_recommendation_freshness`, `_validation_payload`, `_validation_failures`,
`_format_guardrail_failures`, `_json_loads_safe`), all duplicated per the established convention
since each still has external callers in not-yet-extracted presentation code
(`recommendations()`). Every moved method and helper was verified byte-for-byte identical to its
original (via an AST-based comparison script, not eyeballing) before `api/__init__.py` was
touched at all, confirming an accurate move with only the known, deliberate call-site
substitutions for injected dependencies.

**`ExecutionService` is a coordinator only, per the plan's explicit requirement.** Every
authoritative safety decision stays exactly where it already was and is called directly, never
reimplemented: Strategy/Portfolio/Risk/Sentinel governance and the kill switch
(`orchestrator.evaluate_recommendation`, unchanged), order-intent locking
(`acquire_order_intent_lock`/`complete_order_intent_lock`/`release_order_intent_lock` in
`multi_broker.py`, unchanged - a lock is only ever released here after a definite, synchronous
"no order was placed" broker answer; an exception or an ambiguous result leaves it locked), the
Kraken reconciliation hold (consulted inside `orchestrator.evaluate_recommendation` itself, not
duplicated here), broker-adapter order validation (`broker_adapters.KrakenAdapter`, unchanged),
and canonical trade lifecycle recording. Managed-exit *registration* specifically (as opposed to
*monitoring*, which did move) was traced and confirmed to already live entirely inside
`orchestrator.py` (`record_managed_trade_exit`, called only for Kraken fills) - nothing in
`LocalApiService` ever performed it, so there was nothing to extract for that specific plan
bullet; this is recorded here so it doesn't look like an oversight.

**Four narrow injected dependencies, not a reference to LocalApiService**: `account_context_lookup`
(carries the Kraken AI capital-sleeve isolation logic - deliberately injected, not duplicated, so
it keeps exactly one implementation anywhere in the codebase, the same discipline Phases 5 and 6a
already established for this exact function), `control_state_lookup`, `broker_managed_trade_capacity_lookup`
(the `BrokerService` method from Phase 6a), and `portfolio_lookup`. All four wired as call-time
lambdas in `LocalApiService.__init__`, matching every prior phase's pattern.

**Two methods verified exclusively execution-scope via call-graph, not proximity** (the plan's own
warning: "do not move methods merely because they are adjacent in the file"): `_auto_config_for_broker`
looked purely execution-adjacent by name and was confirmed to have exactly two callers, both
moving, so it moved too (with no delegate needed - zero external callers, including tests).
Conversely, `_proposal_broker` sits physically between `_proposal_already_executed` and
`broker_decisions` and looked execution-adjacent by proximity, but its only caller anywhere in the
codebase is `recommendations()` (presentation, not execution) - correctly **not** moved, staying in
`api/__init__.py`. `_apply_env_broker_auto_defaults`/`_apply_founder_kraken_live_authorization`
were also considered and correctly excluded: both run once at process startup from `__init__`,
not from any execution request path, so they are startup bootstrap, not part of this cluster.

**New safety characterization test, one genuine gap found and filled.** Checked existing coverage
first against the directive's six safety categories before writing anything new - Category 3
(order-intent locking: acquired before submission, no duplicate on success, definite failure
releases, ambiguous/crash retains, retained lock prevents blind resubmission) and Category 4
(kill switch, strategy entitlement, portfolio/risk rejection) were already extremely well covered
by existing tests (`test_ambiguous_broker_outcome_does_not_release_the_lock`,
`test_monitor_managed_exits_refuses_to_resubmit_while_a_prior_attempt_is_still_locked`,
`test_active_kill_switch_prevents_order_placement_end_to_end`, etc.) - no duplicate tests added.
Category 2 ("respects the reconciliation hold where applicable") had a real gap: nothing proved
`orchestrator.evaluate_recommendation` actually consults the Kraken reconciliation hold for a
Kraken proposal specifically, only that the reconciliation-control module itself defaults to
holding. Added `test_kraken_reconciliation_hold_blocks_new_entries_end_to_end`
(`tests/test_orchestrator.py`), which incidentally also confirmed a genuine safety-positive
finding worth recording: `KRAKEN_RECONCILIATION_CONTROL.hold_new_entries` defaults to `True`
(fail-closed) on a fresh database, matching the existing
`test_default_control_pauses_entries_and_failed_verification_cannot_resume` test in
`tests/test_kraken_reconciliation.py`. Category 1's "creates managed-exit monitoring where
required" for Alpaca was verified by direct code trace rather than a new heavy integration test
(see the coordinator-service note above: registration is Kraken-only and lives entirely in
`orchestrator.py`, which Phase 8 does not touch), a proportionate choice given a full new
end-to-end submission test would exercise domain logic outside this phase's actual change surface.

**No bug found this phase requiring a fix.**

**Verification.** `python -m py_compile` clean on both files. Grepped every one of the 10 moved
methods plus the removed-not-delegated `_proposal_with_manual_amount`/`_manual_approval_auto_config`/
`_auto_config_for_broker` across `api/__init__.py` post-edit - zero dangling references. Removed 8
now-fully-unused imports (`OrderRequest`, `acquire_order_intent_lock`, `complete_order_intent_lock`,
`release_order_intent_lock`, `mark_managed_exit_submitted`, `update_broker_runtime`,
`update_trailing_water_marks`, `register_kraken_order_ownership`) whose only remaining call sites
moved with the code. Full stable suite passed clean twice independently: 287 passed (286 + 1 new),
0 failed both runs. The two safety-critical test files (`test_orchestrator.py`,
`test_multi_broker_platform.py`, 60 tests) and all 20 API contract characterization tests
(including `/approve-and-execute`, `/auto-execute-recommendations`, `/force-managed-exit`) were
additionally re-run individually with verbose output for extra confidence, all unchanged.
`api/__init__.py`: 2,828 -> 2,332 lines (-496). No production runtime behaviour changed. No real
Kraken order was submitted in any test (all tests use `FakeKrakenAdapter`/`FakeAlpacaClient` or
equivalent controlled fakes, consistent with every prior phase's tests).

**Not committed** by the fork that did this work, per this session's established process (one
earlier phase's fork committed without waiting for review; every phase since has left work
uncommitted for the coordinating session to verify independently first).

**Next.** All 8 extraction phases plus Stage 0 are now complete. Per the ChatGPT-authored Phase 8
directive's own instruction ("Pause after Phase 8 and the proposed Phase 9 cleanup plan so the
Founder and ChatGPT can review the complete modularised code before push, merge or deployment"),
this is a deliberate stop: no push, no merge, no deploy. A Phase 9 cleanup *plan* (proposal only,
not executed) follows this entry; a Phase 8 Founder briefing has been produced separately for
this specific checkpoint.

## 2026-08-02 Modularisation Phase 7 — administration service extraction (+ Phase 6a scope correction)

Implements Phase 7 of `architecture/AI_TRADER_MODULARISATION_ARCHITECTURE_2026-08-02.md`
Section 7 ("Move trading-state administration, broker auto-trading settings, Render API
synchronisation, guarded lock release, founder reconciliation override, developer/diagnostic
status. Keep guarded administrative actions separate from ordinary presentation endpoints."),
plus a correction to Phase 6a found while scoping this phase.

**The correction, found and fixed before any new Phase 7 work.** Phase 6a's fork instructions
were written from Phase 6's one-sentence plan description alone, without cross-checking Phase
7's explicit list. As a result four methods that genuinely *mutate* state ended up inside
`application/broker_service.py`, which the plan's Section 5 dependency rule 4 requires to stay
presentation-only ("may read operational state but must not mutate trading state"):
`set_broker_auto_trading` (writes to the DB, triggers a Render deploy), `_render_api_json` and
`_sync_broker_auto_trading_to_render` (the Render API call that performs), and
`release_order_intent_lock_for` (manually releases a safety lock - explicitly a "guarded"
action per its own docstring, and per this exact plan section's wording). Moved a second time,
from `broker_service.py` (not from `api/__init__.py` - they no longer lived there), into the
new `application/administration_service.py`, along with `BROKER_AUTO_TRADING_ENV_VARS` (only
used by `_sync_broker_auto_trading_to_render`). `broker_service.py`'s `order_intent_locks`
(the read-only lock listing, correctly presentation, unmoved) now cross-references where the
guarded release action actually lives. `LocalApiService`'s delegates for `set_broker_auto_trading`
and `release_order_intent_lock_for` were repointed from `self._broker_service.*` to
`self._administration_service.*`; a stale test patch target in
`tests/test_multi_broker_platform.py` (`patch.object(BrokerService, "_render_api_json", ...)`)
was found by running the suite and retargeted to `AdministrationService`.

**New Phase 7 scope**: `set_trading_state` moved from `api/__init__.py` into
`AdministrationService` the normal way (AST-verified exclusive, delegated, "delegation before
deletion").

**`AdministrationService` needs zero injected dependencies** - unlike every other application
service extracted so far, all six of its methods only need `settings`, `audit`, and
`query_executor`, no not-yet-extracted `LocalApiService` state.

**Two deliberate non-moves, decided and documented rather than assumed:**
- `founder_override_kraken_hold` ("founder reconciliation override" in the plan's list) is
  already a bare domain-level function (from `kraken_reconciliation.py`) called directly inline
  in the POST route dispatch table - there is no existing `LocalApiService` method wrapping it.
  Left exactly as-is: a route calling a domain function directly is already clean, and inventing
  a wrapper method purely to match a plan bullet point would be redesign, not extraction, which
  the plan explicitly warns against ("do not move and redesign logic simultaneously").
- `developer_status` ("developer/diagnostic status" in the plan's list) was already moved into
  `OperationsService` during Phase 6b. Verified its body is 100% read-only (SELECT counts and
  system diagnostics, zero writes) - it does not violate dependency rule 4, unlike the four
  methods corrected above. Left in `OperationsService`; moving it again would be pure churn
  with no rule-compliance benefit, even though it doesn't match the plan's phase-label grouping
  exactly.

**No bug found this phase requiring a fix.**

**Verification.** `python -m py_compile` clean on all three touched/new files. Confirmed no
circular import at runtime (`from ai_trader.api import LocalApiService, AdministrationService`).
Grepped every corrected/moved name across `broker_service.py` and `api/__init__.py` post-edit -
zero dangling references (one intentional docstring cross-reference in `order_intent_locks`
pointing to the new location, not a code reference). Full stable suite passed clean twice
independently: 286 passed, 0 failed both runs, including the retargeted broker-auto-trading
Render-sync test. `api/__init__.py`: 2,828 lines (net roughly unchanged - `set_trading_state`'s
body shrank to a delegate but the new service's construction and three corrected delegates
added lines back). `broker_service.py`: 1,133 -> 990 lines (-143, the correction). New
`administration_service.py`: 212 lines. No production runtime behaviour changed.

**Note on how this entry was produced.** The fork that started this phase was terminated
mid-task by a session usage limit after completing the code moves (both files) but before
wiring `AdministrationService` into `api/__init__.py`'s constructor/imports/delegates or
writing this log entry - the working tree was left in a genuinely broken intermediate state
(delegates pointing at methods that no longer existed on `BrokerService`). The coordinating
session completed the wiring, found and fixed the one resulting test failure, ran full
verification, and wrote this entry directly.

**Did not run `git commit`** during the fork's portion; the coordinating session reviewed and
completed this phase itself before committing.

**Next.** Phase 7 complete - this was the last phase before the Founder/Claude/ChatGPT review
checkpoint agreed 2026-08-02. Stopping here. Phase 8 (execution service) does not begin until
that review happens.

## 2026-08-02 Modularisation Phase 6b — operations service extraction

Implements the operations half of Phase 6 of `architecture/AI_TRADER_MODULARISATION_ARCHITECTURE_2026-08-02.md`
Section 7 ("Move broker panels, broker activity polling, production snapshots, operational
timelines, notifications and reconciliation presentation into bounded broker/operations
services. Re-run all Kraken isolation and reconciliation tests after each move."). The broker
half (Phase 6a, `application/broker_service.py`) is already done and committed (`b5f13c2b`).

**New `src/ai_trader/application/operations_service.py`** (389 lines): `OperationsService`
holding 13 methods moved verbatim from `LocalApiService` - `notifications`,
`ack_notifications`, `register_push_token_endpoint`, `dispatch_pending_push_notifications`,
`status` (the single dashboard aggregator the whole app is built around), `operations_health`,
`phase5_status`, `sprint6_status`, `autonomous_activity`, `production_activity`,
`_filtered_production_timeline`, `operational_events`, `decision_journal`,
`developer_status` - plus four exclusive module-level helpers (`_component`, `_port_open`,
`_research_status`, `_research_assets_reviewed`) and two generic query-param helpers
(`_first`, `_int_or_default`) duplicated verbatim per the established convention (still used
44 times elsewhere in `api/__init__.py`'s route dispatch).

**`reconcile_on_startup` deliberately excluded, staying in `api/__init__.py`.** Despite its
operations-adjacent name, its body calls `reconcile_broker_trade_rows` (writes lifecycle
events) and `record_notification` (writes a notification row) - it performs real
reconciliation actions at process startup, not read-only presentation. Per the plan's Section
5 dependency rule 4 ("presentation services may read operational state but must not mutate
trading state") and matching Phase 6a's precedent of excluding two genuinely mutating
methods from `BrokerService`, this stays out of `OperationsService`.

**`autonomous_activity` found to be dead code**, unrelated to this extraction. Grepped every
call site in `api/__init__.py`'s GET/POST route dispatch, every test file, and the rest of the
codebase: zero callers anywhere. The `/autonomous-activity` route calls `production_activity`
instead - `autonomous_activity` appears to be an orphaned method that predates this phase.
Moved as-is (not removed, not fixed) to keep this phase a pure relocation with zero behaviour
change; it now has no delegate wrapper in `api/__init__.py` since nothing calls it there
either, matching the established convention for zero-caller methods.

**Thirteen narrow injected dependencies** - the largest injection surface of any phase so far,
because `status()` alone touches nearly every other application service already extracted:
`recommendations`, `broker_panels` (`BrokerService`), `executive_summary`,
`founder_executive_summary`, `connection_readiness`, `founder_experience_payload`,
`world_class_evidence` (all `FounderExperienceService`), `_active_broker_names`
(`BrokerService`), `_continuous_research_status`, `_due_diligence_status`, `_control_state`,
`_latest_daily_brief` (all still un-extracted `LocalApiService` methods). All thirteen are
wired as call-time lambdas in `LocalApiService.__init__`, per the pattern every phase from 4
onward established.

**Zero fix-cycle this phase.** Unlike Phases 4-6a, every test passed on the first run: the
Kraken/operations-focused test files individually (`test_multi_broker_platform.py`,
`test_always_on_operations.py`, `test_sprint6_institutional_spine.py`,
`test_phase5_production_spine.py`, `test_developer_experience.py` - 119 passed), then the full
suite (286 passed) twice. No test file needed changes. Verified every SQL string moved into
the new file byte-for-byte against the original before running anything (programmatic
substring match across all triple-quoted `SELECT` blocks in both files), and diffed all six
duplicated/moved helper functions (`_component`, `_port_open`, `_research_status`,
`_research_assets_reviewed`, `_first`, `_int_or_default`) for exact equality - all identical.

**Verification.** `python -m py_compile` clean on both files. Confirmed no circular import at
runtime. Grepped all 17 moved names (13 methods + 4 module-level helpers) across
`api/__init__.py` post-edit - zero dangling references. Removed 12 now-fully-unused imports
(`operations_health`, `phase5_status`, `sprint6_status`, `autonomous_activity_payload`,
`load_trading_policy`, `latest_research_run`, and the six `multi_broker` notification
functions) plus the now-dead `socket`/`sys` module imports (both only used by the two
module-level helpers that moved). `api/__init__.py`: 3,053 -> 2,828 lines (-225). No
production runtime behaviour changed.

**Did not run `git commit`** - left in the working tree for the coordinating session to
review and commit, per the process established after an earlier phase's fork committed
without waiting for review.

**Next.** Continuing to Phase 7 (Administration service) - the last phase before the
2026-08-02 Founder/Claude/ChatGPT review checkpoint.

## 2026-08-02 Modularisation Phase 6a — broker service extraction

Implements the broker half of Phase 6 of `architecture/AI_TRADER_MODULARISATION_ARCHITECTURE_2026-08-02.md`
Section 7 ("Move broker panels, broker activity polling, production snapshots, ...
reconciliation presentation into bounded broker/operations services. Re-run all Kraken
isolation and reconciliation tests after each move."). The operations half (notifications,
operational timelines, status/dashboard aggregation) is a separate Phase 6b, not done here.

**New `src/ai_trader/application/broker_service.py`** (1,133 lines): `BrokerService` holding
23 methods moved verbatim from `LocalApiService` - `broker_panels`, `poll_broker_activity`
(+ `_alpaca`/`_kraken` variants), `capture_production_broker_snapshots`,
`set_broker_auto_trading`, `_sync_broker_auto_trading_to_render`, `_render_api_json`,
`_broker_trade_rows`, `_managed_exit_rows`, `_broker_trading_permissions`,
`_ai_managed_open_trade_count`, `_kraken_ai_capital_ledger`, `_broker_managed_trade_capacity`,
`_active_broker_names`, `_latest_snapshot_summary`, `_unconfigured_exchange_portfolio`,
`_exchange_portfolio`, `_alpaca_panel_portfolio`, `_live_alpaca_portfolio`, `broker_decisions`,
`order_intent_locks`, `release_order_intent_lock_for` - plus `BROKER_AUTO_TRADING_ENV_VARS`
and 10 exclusive module-level helpers.

**Four methods deliberately excluded, staying in `api/__init__.py`** - all four looked
broker-adjacent by name but failed a "presentation only" scope check on inspection:
- `_adapters` - called during `LocalApiService.__init__` itself (`self.orchestrator =
  InvestmentOrchestrator(adapters=self._adapters(), ...)`), before any application service
  can exist. Moving it would create a construction-order deadlock.
- `_auto_config_for_broker` - its only callers (`_manual_approval_auto_config`,
  `auto_execute_recommendations`) are execution territory (Phase 8), not broker
  presentation; nothing in the broker cluster calls it.
- `_apply_env_broker_auto_defaults` and `_apply_founder_kraken_live_authorization` - both
  called once from `__init__`, both **mutate trading-state authorization**
  (`apply_founder_strategy_authorization`, `set_broker_auto_trading`), not read it. The
  plan's Section 5 dependency rule 4 restricts presentation services from mutating trading
  state; `_apply_founder_kraken_live_authorization` specifically controls whether autonomous
  Kraken execution can cross into real-money mode. This is Phase 7 (Administration service,
  "trading-state administration") territory, not Phase 6.

**The Kraken wallet-pricing subsystem was deliberately left completely untouched.**
`_kraken_balance_summary`/`_kraken_gbp_cash`/`_kraken_asset_gbp_price`/`_kraken_usd_to_gbp`/
`_kraken_pair_price`/`_kraken_asset_symbol`/`_kraken_trading_allocation_gbp` all stay in
`api/__init__.py`. `_kraken_trading_allocation_gbp` is the same safety-critical Kraken AI
capital-sleeve isolation function Phase 5 already established must keep exactly one
implementation anywhere in the codebase (`_account_context_for_broker`, which also stays,
calls it directly). Since `_kraken_balance_summary` calls `_kraken_trading_allocation_gbp`
and the moved `_exchange_portfolio` needs `_kraken_balance_summary`, the entire pricing
pipeline is injected as one `kraken_balance_summary_lookup: Callable` rather than partially
extracted or duplicated - the safest option given this phase's explicit "re-run Kraken
isolation tests after each move" instruction.

**Two narrow injected dependencies**: `broker_factory` (constructs an `AlpacaPaperClient`,
same pattern Phase 5 established) and `kraken_balance_summary_lookup`, both wired as
call-time lambdas in `LocalApiService.__init__`.

**Own bugs caught via automated AST diff before touching `api/__init__.py` at all** (the
Phase 3/5 discipline: compare every moved function's source against the original
byte-for-byte before running any test): a first-draft reconstruction of `_float_env`/
`_int_env` used invented logic instead of the original's `float(os.getenv(key,
str(default)))`/try-except pattern; `_broker_trade_payload` used a different (wrong)
type-check branch than the original; `_sum_balances` was restructured (behaviourally
identical, but rewritten rather than copied) - all three found and fixed before any test ran.

**Extensive test fixes required - all expected consequences of the move, not behaviour
changes**: six `patch("ai_trader.api.X", ...)` targets updated to
`ai_trader.application.broker_service.X` (`kraken_capital_ledger_summary`,
`record_broker_snapshot`, `record_broker_trade_history`, `record_trade_evidence_batch`,
`normalize_broker_events`, `replay_kraken_evidence`) across `tests/test_multi_broker_platform.py`
and `tests/test_production_completion.py`. One `patch.object(LocalApiService,
"_render_api_json", ...)` changed to `patch.object(BrokerService, "_render_api_json", ...)`,
since that method has no delegate. One import (`from ai_trader.api import
_recent_unique_broker_events`) changed to import from `ai_trader.application.broker_service`
instead, since it moved and is no longer defined in `api/__init__.py`.

**A real gap found in four hand-built `LocalApiService.__new__(LocalApiService)` test
doubles** (`tests/test_production_completion.py`) that bypass `__init__` entirely and
manually set only `service.settings`/`service.orchestrator` - these never got a
`_broker_service` constructed, so the delegate methods would raise `AttributeError`. Fixed by
constructing `BrokerService.__new__(BrokerService)` alongside each and wiring only the
attributes each test actually needs (mirroring exactly what the test already did for
`service.settings`/`service.orchestrator`). Three more tests (one in
`test_multi_broker_platform.py`, two in `test_production_completion.py`) monkeypatched
`service._live_alpaca_portfolio`/`service._exchange_portfolio` directly on a *fully
constructed* `LocalApiService` instance - after the move, `capture_production_broker_snapshots`
(now on `BrokerService`) calls `self._live_alpaca_portfolio()` on the `BrokerService`
instance, not the `LocalApiService` delegate, so these monkeypatches had gone silently inert.
Fixed by retargeting them to `service._broker_service._live_alpaca_portfolio`/
`._exchange_portfolio`. None of this was caught by AST analysis of `api/__init__.py`'s own
call graph (the established Phase 5 gap: it cannot see test-file monkeypatch targets) - only
by actually running the suite and reading each failure.

**Verification.** `python -m py_compile` clean on both files. Confirmed no circular import at
runtime. Grepped every one of the 34 moved names (23 methods + 11 module-level items) across
`api/__init__.py` post-edit - zero dangling references, including bare-name (not just
call-site) greps to catch non-call references. Ran the Kraken/broker-focused test files
individually first (`test_multi_broker_platform.py`: 37 passed; `test_production_completion.py`:
14 passed) before the full suite, per this phase's explicit re-test instruction. Full stable
suite passed clean twice independently: 286 passed, 0 failed both runs. `api/__init__.py`:
3,982 -> 3,053 lines (-929). No production runtime behaviour changed.

**Did not run `git commit`** - left in the working tree for the coordinating session to
review and commit, per the process established after an earlier phase's fork committed
without waiting for review.

**Next.** Continuing to Phase 6b (Operations service). No checkpoint until Phase 7 completes,
per the 2026-08-02 Founder/Claude agreement on phase batching.

## 2026-08-02 Modularisation Phase 5 — research service extraction

Implements Phase 5 of `architecture/AI_TRADER_MODULARISATION_ARCHITECTURE_2026-08-02.md`
Section 7 ("Move run_analysis, run_crypto_analysis, refresh_strategy_lab,
refresh_crypto_universe, research recording and enrichment, shared cycle bookkeeping.
Preserve separate equity and crypto entry points. Share only lifecycle helpers that are
genuinely common.").

**New `src/ai_trader/application/research_service.py`** (933 lines): `ResearchService`
holding `run_analysis`, `run_crypto_analysis`, `refresh_strategy_lab`,
`refresh_crypto_universe`, `_refresh_asset_metadata_from_company_master`,
`_record_production_research`, `_enrich_production_recommendations`,
`_bootstrap_crypto_universe_from_kraken_permissions`, `_record_research_from_result`,
`_record_research_funnel_from_result`, `_record_shadow_from_proposal`, plus three exclusive
module-level helpers (`_symbol_from_kraken_pair`, `_crypto_display_name`,
`_proposal_expected_r`). `run_analysis` and `run_crypto_analysis` remain two separate
methods, not merged, per the plan's explicit instruction.

**AST-based caller analysis excluded `_continuous_research_status`** from this phase despite
its name and the plan's "shared cycle bookkeeping" wording suggesting otherwise: its only
caller anywhere in `api/__init__.py` is `status()` (the `/status` dashboard aggregator), never
any research method. It computes a status summary for display, not bookkeeping that happens
during a research cycle - left in place, correctly out of scope.

**Four narrow injected dependencies, not a reference to LocalApiService.**
`_account_context_for_broker` (Kraken AI capital-sleeve isolation logic -
`_kraken_trading_allocation_gbp` - deliberately injected rather than duplicated, so that
safety-critical logic keeps exactly one implementation anywhere in the codebase),
`recommendations` (used by several not-yet-extracted callers), `auto_execute_recommendations`
(execution territory, Phase 6/8), and a broker-client factory (`_broker`, still needed
elsewhere in `api/__init__.py` too) are all injected as `Callable`s per the plan's Section 5
dependency rule 6.

**Design flaw found via test failures, not caught before running tests - corrected.** The
first pass wired `recommendations_lookup=self.recommendations` and (for the broker factory)
duplicated `_broker()` as ResearchService's own method, both captured/defined once. Running
the full suite (not py_compile, not manual review) surfaced two real failures:
`tests/test_strategy_lab.py` monkeypatches `service._broker = lambda: FakeAlpacaBars(...)`
*after* `LocalApiService(settings)` has already constructed `ResearchService`, and
`tests/test_production_evidence.py` does the same via `patch.object(service, "recommendations",
...)`. A directly-captured bound method or a duplicated method neither one sees a later
instance-attribute monkeypatch. Fixed by wiring all four injected dependencies as lambdas that
read the LocalApiService instance's method at call time
(`lambda limit: self.recommendations(limit)`, not `self.recommendations`) - the same
live-reading pattern Phase 4 already established for `hosted_read_only`/`api_token_configured`
for the identical reason, now applied consistently across all four here rather than only the
two a test happened to catch.

**Two more methods needed delegates, not full removal - also found via test failures.**
`_refresh_asset_metadata_from_company_master` and `_record_production_research` had no
internal caller left inside `api/__init__.py` after their one call site moved with them, so
the first pass removed both outright - but `tests/test_asset_metadata_refresh.py` and
`tests/test_production_evidence.py` call both directly on the `LocalApiService` instance as
external callers. AST analysis of *this file's* call graph correctly found zero internal
callers; it does not see test-file callers, which is a real gap in the method, not just this
run of it - noted here so a future phase's exclusivity check greps `tests/` too, not only
`api/__init__.py`. Fixed by adding both back as one-line delegates.

**One test patch target updated to match the new call site.**
`tests/test_production_evidence.py` patched `ai_trader.api.record_research_evidence` -
`_record_production_research` now imports `record_research_evidence` independently into
`research_service.py`, so the patch target changed to
`ai_trader.application.research_service.record_research_evidence`. Same function object, same
observable behaviour; only the module-qualified name the test patches moved, which is an
expected consequence of relocating the implementation, not a behaviour change.

**Small helpers duplicated**: `_csv_env` and `_int_or_default` are still used elsewhere in
`api/__init__.py`, duplicated verbatim per the established Phase 3/4 convention. Caught myself
using `_int_or_default(body.get("limit"), 10)`'s inline-`int()` near-equivalent in a first
draft, which is not behaviourally identical (it raises on a non-numeric string instead of
falling back to the default) - fixed before running any tests, by an automated diff of every
moved method against the original rather than eyeballing it.

**Verification.** Automated a byte-for-byte diff (after normalizing only the known
lookup/query-executor substitutions) of every moved method and function against its original
before touching `api/__init__.py` at all - this is what caught the `_int_or_default` and
`_csv_env`-inline-import deviations before any test run. Grepped every moved name across
`api/__init__.py` post-edit - zero dangling references. `python -m py_compile` clean. Full
stable suite passed clean three times independently across the fix cycle: 286 passed, 0 failed
every run, including both `/run-analysis` and `/run-crypto-analysis` characterization tests
re-run individually by name. `api/__init__.py`: 4,747 -> 3,982 lines (-765).

**Did not run `git commit`** - the previous phase's fork committed without waiting for review,
which was flagged to the Founder as a process violation; this phase deliberately left
everything in the working tree for the coordinating session to review and commit.

**Next.** Continuing to Phase 6 (Broker and operations services). No checkpoint until Phase 7
completes, per the 2026-08-02 Founder/Claude agreement on phase batching.

## 2026-08-02 Modularisation Phase 4 — founder presentation service extraction

Implements Phase 4 of `architecture/AI_TRADER_MODULARISATION_ARCHITECTURE_2026-08-02.md`
Section 7 ("Move read-only founder-facing aggregation into `application/founder_experience_service.py`:
founder experience payload, world-class evidence, executive summaries, connection readiness,
portfolio extremes, positions requiring attention, strategy/signal summaries, supporting
presentation helpers. This service must not execute trades, change broker settings or mutate
operational controls.").

**New `src/ai_trader/application/founder_experience_service.py`** (649 lines): `FounderExperienceService`
holding 15 methods moved verbatim from `LocalApiService` - `founder_experience_payload`,
`world_class_evidence`, `executive_summary`, `founder_executive_summary`, `connection_readiness`,
plus 10 exclusive supporting helpers (`_latest_strategy_performance_rows`, `_portfolio_extremes`,
`_positions_requiring_attention`, `_crypto_health_summary`, `_strategy_validation_summary`,
`_signal_rankings`, `_portfolio_intelligence_summary`, `_future_broker_status`,
`_data_availability_unknowns`, `_executive_first_conclusion`, `_latest_broker_trade_any`,
`_plain_learning_status` - 12 in total), and 6 module-level formatting helper functions
(`_average_numeric`, `_committee_numeric_confidence`, `_plain_confidence`, `_plain_regime`,
`_plain_market_health`, `_portfolio_rebalancing_suggestions`) used only by this cluster.
Verified via grep-based call-site analysis (every candidate helper checked for call sites
outside its own containing method before being classified as exclusive) - confirmed zero
dangling references after the move.

**Confirmed read-only**, per the plan's explicit constraint: grepped the new file for
`INSERT INTO`/`UPDATE`/`DELETE FROM`/`place_order`/`place_bracket`/`set_kill_switch`/
`record_notification` - zero matches. Every method is aggregation over already-recorded data
or `SELECT`-only queries.

**One caught-in-review design mistake, fixed before this entry was written.** The first
extraction pass used a single blind line-range replacement (1072-1493) covering the entire
founder-presentation cluster, not noticing that `portfolio()`, `founder_brief()`, and
`operational_truth_status()` - three unrelated, out-of-scope `LocalApiService` methods - sit
physically interspersed between `_signal_rankings` and `world_class_evidence` in the original
file. That pass silently deleted all three. Caught immediately by grepping for their
definitions post-edit and finding none; fixed by reverting the file to the last commit
(`git checkout`) and redoing the extraction as separate, precisely-bounded blocks that
verified the preserved methods survived before proceeding. No broken state was ever tested,
committed, or left in place - this is recorded here as the plan's Section 11 delivery
controls call for honest accounting of what verification actually caught, not to imply the
error reached a committed state.

**Eight narrow injected dependencies, not a reference to LocalApiService.** This cluster reads
more not-yet-extracted `LocalApiService` state than Phase 3's reporting pipeline did:
`broker_panels()` and `recommendations()` (Phase 6/5 territory), `daily_learning_update()`
(Phase 5 territory), `operational_truth_status()`, `themes()`, and `companies()` (each has its
own separate route contract, out of this phase's scope to move), plus `hosted_read_only` and
`api_token_configured`. The last two are **not** captured as plain bool parameters: both are
reassigned on the `LocalApiService` instance *after* `__init__` runs (by `run_server()`, and
by `tests/test_developer_experience.py::test_connection_readiness_shows_hosted_control_lock`,
which sets `service.hosted_read_only = True` post-construction and expects
`connection_readiness()` to reflect it) - so both are wired as `lambda: self.hosted_read_only`
/ `lambda: self.api_token_configured`, reading live state off the instance at call time, not a
value snapshotted at construction. All eight follow the same `Callable` injection pattern
established in Phase 3, per the plan's Section 5 dependency rule 6.

**Two small pure formatting helpers duplicated again**, not imported: `_broker_label` and
`_money_text` are still needed by other not-yet-extracted parts of `api/__init__.py` (broker
panels and permissions summaries - Phase 6 territory) and were already duplicated once into
`application/reporting_service.py` for the same reason in Phase 3. Per this codebase's now-
established convention, each `application/*` module stays self-contained rather than importing
from a peer service, so they are duplicated a second time here rather than imported from
`reporting_service.py`.

**Delegation before deletion.** The 5 top-level methods (`founder_experience_payload`,
`world_class_evidence`, `executive_summary`, `founder_executive_summary`, `connection_readiness`)
stayed in place as one-line delegates to `self._founder_experience_service.*`, constructed via
composition in `__init__` alongside `self._query_executor` and `self._reporting_service`. The
GET/POST route dispatch table and the large `/founder-evidence` aggregator function (which
calls all 5) needed zero changes. The 12 exclusive supporting helpers had no other internal
callers and were fully removed rather than delegated, matching Phase 3's precedent for methods
with a single containing caller.

**No bug found this phase.** Unlike Phase 3 (`record_trading_report`'s schema-reinit-per-call),
nothing in this cluster showed the same pattern - none of these methods call any
`initialize_*_schema` function.

**Verification.** `python -m py_compile` clean on both files. Confirmed no circular import at
runtime. Grepped every moved function/method name across `api/__init__.py` post-edit -
zero dangling references. Full stable suite passed clean twice independently: 286 passed, 0
failed both runs, including `test_connection_readiness_shows_hosted_control_lock` (the direct
proof the live-state injection design works) and `test_founder_evidence_top_level_shape`
(the direct proof the `/founder-evidence` contract didn't shift), both re-run individually
by name for extra confidence. `api/__init__.py`: 5,261 -> 4,747 lines (-514). Removed two now-
unused imports (`calculate_portfolio_exposure`, `calculate_performance_metrics` - both moved
into the new file). No production runtime behaviour changed.

**Next.** Continuing to Phase 5 (Research service). No checkpoint until Phase 7 completes, per
the 2026-08-02 Founder/Claude agreement on phase batching.

## 2026-08-02 Modularisation Phase 3 — reporting service extraction

Implements Phase 3 of `architecture/AI_TRADER_MODULARISATION_ARCHITECTURE_2026-08-02.md`
Section 7 ("Move the report pipeline into `application/reporting_service.py`: trading_report /
report_page / report-source refresh / broker-learning markdown / report writing and
persistence / report generation. Preserve `/trading-report`, `/generate-report` and
`/reports/*` contracts exactly.").

**New `src/ai_trader/application/reporting_service.py`** (903 lines): `ReportingService`,
holding the entire report pipeline moved verbatim from `LocalApiService` - `generate_report`,
`trading_report`, `report_page`, `refresh_report_sources`, `broker_learning_report_markdown`,
`write_trading_report`, `record_trading_report`, `initialize_schema`, plus 20 module-level
formatting/reconstruction helper functions (`_report_period`, `_reconstruct_broker_fill_pnl`,
`_period_lessons`, etc.) that only the report pipeline used, and the `REPORT_SCHEMA` constant.
Verified via AST call-graph analysis (not just grep) which helpers were reporting-exclusive
versus shared with other, not-yet-extracted parts of `api/__init__.py` before moving anything -
this caught `_kraken_trade_status_lines` looking reporting-adjacent by proximity but actually
belonging entirely to the separate Ask AI Trader feature, which stayed put correctly.

**Two narrow injected dependencies, not a reference to LocalApiService.** `refresh_report_sources`
needs `portfolio()` (Phase 6 broker/operations territory) and `broker_learning_report_markdown`
needs `daily_learning_update()` (research/learning territory) - both still live on
`LocalApiService` and are out of this phase's scope to move. Per the plan's Section 5
dependency rule 6 ("cross-service dependencies should go through explicit domain services or
the application context," not the whole service object), `ReportingService.__init__` takes
`portfolio_lookup` and `daily_learning_lookup` as explicit `Callable` parameters, wired by
`LocalApiService` as `portfolio_lookup=self.portfolio, daily_learning_lookup=self.daily_learning_update`
(ordinary bound-method references).

**Five small pure formatting helpers duplicated, not imported.** `_human_time`, `_money_text`,
`_list_or_none`, `_broker_label`, `_estimated_in_positions`, plus the tightly-coupled
`_broker_trade_payload`/`_broker_trade_symbol` pair, are still used by other not-yet-extracted
parts of `api/__init__.py` (broker panels, executive summaries - Phase 4/6 territory) and by
`_broker_trade_rows` specifically. Importing them into `reporting_service.py` from `..api`
would create a circular import (api/__init__.py imports `ReportingService` at module load
time, before its own later-defined functions exist yet). Rather than introduce a lazy/deferred
import pattern this codebase doesn't otherwise use, these seven small stateless functions are
duplicated verbatim with a comment explaining why, pending consolidation once their other call
sites are extracted in a later phase.

**Delegation before deletion.** All eight `LocalApiService` methods stayed in place as one-line
delegates to `self._reporting_service.*` (constructed via composition in `__init__`, alongside
the existing `self._query_executor`), so the GET/POST route dispatch table needed zero changes.
`_write_trading_report`, `_record_trading_report`, and `_broker_learning_report_markdown` had no
other internal callers, so no delegate wrapper was needed for those three specifically -
verified by grep before removing them.

**Bug found, not fixed.** `record_trading_report` re-runs `REPORT_SCHEMA`'s `executescript` on
every persisted report - the same "schema re-init mistaken for slow work" pattern already fixed
elsewhere this session via `persistence/schema_once.py`. Left as a code comment for a future
fix; not touched here per "do not move and redesign logic simultaneously."

**Own bug caught and fixed before verification.** The first draft of `refresh_report_sources`
silently dropped the `logger.exception(...)` call the original `_refresh_report_sources` made
on a broker-refresh failure. Caught by diffing removed lines for any `logger.` calls before
declaring the move complete, not by a test (no existing test exercised the failure path) -
fixed by adding a `logger = logging.getLogger("ai_trader.api")` (same logger name, same log
output) to `reporting_service.py` and restoring the call.

**Verification.** `python -m py_compile` clean. Confirmed no circular import at runtime.
Grepped every moved function name across `api/__init__.py` post-edit to confirm zero dangling
references. Smoke-tested all three endpoints end-to-end against a real temp SQLite database
(`/trading-report`, `/generate-report`, `/reports/{id}`) - genuine report generation,
persistence, and HTML rendering, not just import resolution. Full stable suite passed clean
twice independently: 286 passed, 0 failed both runs, including both existing characterization
tests for `/trading-report` and `/generate-report` unchanged. `api/__init__.py`: 6,021 -> 5,261
lines (-760). Removed `import html` (its only use moved). No production runtime behaviour
changed except restoring the logging call above to match the original exactly.

**Next.** Continuing to Phase 4 (Founder presentation service). Per 2026-08-02 agreement with
the Founder, phases 3-7 proceed without a stop-for-review checkpoint between each one (to
preserve momentum on the rearchitecture); the next checkpoint is after Phase 7 completes, for
joint Founder/Claude/ChatGPT review of this log before Phase 8 (execution service - the
highest-risk phase, sequenced last for that reason) begins.

## 2026-08-02 Modularisation Phase 2 — query execution extraction

Implements Phase 2 of `architecture/AI_TRADER_MODULARISATION_ARCHITECTURE_2026-08-02.md`
Section 7 ("Extract `_connect`, `_row`, `_rows`, `_scalar` and `_count` into an injected
`QueryExecutor`. Avoid a broad inheritance mixin. Use explicit composition.").

**New `src/ai_trader/persistence/query_executor.py`**: `QueryExecutor`, constructed with a
`db_path`, holding `connect`/`row`/`rows`/`scalar`/`count` - the same logic these five
`LocalApiService` methods held, moved verbatim (including the `count` table allowlist and its
`ValueError` message). `LocalApiService.__init__` now constructs `self._query_executor =
QueryExecutor(settings.db_path)` (composition, not inheritance - matches the plan's explicit
"avoid a broad inheritance mixin" instruction).

**Delegation before deletion.** `LocalApiService._connect/_row/_rows/_scalar/_count` were not
deleted - they're now one-line delegates to `self._query_executor.*`, so the 73 existing call
sites elsewhere in the file (`self._row(...)`, `self._rows(...)`, etc.) needed zero changes.
Per the plan's Section 11 delivery controls: "Old method → delegates to new service → tests
prove equivalence → old body removed in a later commit. Do not move and redesign logic
simultaneously." Removing the now-redundant wrapper methods and pointing all 73 call sites at
`self._query_executor` directly is left for a later cleanup pass, not this phase.

**New tests.** `tests/test_query_executor.py` (9 tests) exercises `QueryExecutor` directly and
in isolation from `LocalApiService` for the first time: connection row-factory behaviour, `row`/
`rows`/`scalar` on matches and on no-match, and `count`'s table allowlist including the
rejection path.

**Verification.** `python -m py_compile` clean. Confirmed no circular import. Full stable suite
passed clean twice independently: 286 passed (277 + 9 new), 0 failed both runs. No production
runtime behaviour changed - `QueryExecutor`'s methods are the exact same SQL and control flow
that `LocalApiService`'s methods already ran.

**Next.** Stopping here for review before Phase 3 (reporting service extraction), per the
plan's per-phase review cadence.

## 2026-08-02 Modularisation Phase 1 — HTTP transport extraction

Implements Phase 1 of `architecture/AI_TRADER_MODULARISATION_ARCHITECTURE_2026-08-02.md`
Section 7 ("Extract `ApiHandler` to `api/http_server.py`. Preserve exactly: authentication;
`/healthz` exemption; CORS; body parsing; IP lockout; error envelopes; response serialisation;
logging behaviour. Keep route paths and handler results unchanged.").

**Mechanical move, not a redesign.** `src/ai_trader/api.py` (6,152 lines) converted into a
package: `git mv` to `src/ai_trader/api/__init__.py`, then the `ApiHandler` class (transport
only: `do_GET`/`do_POST`/`do_OPTIONS`, auth-token + IP-lockout check, JSON/HTML response
serialization, CORS headers, error envelopes) moved verbatim into the new
`src/ai_trader/api/http_server.py`, which now has zero dependency on any other `ai_trader`
module - only stdlib. `__init__.py` re-imports it (`from .http_server import ApiHandler`), so
every existing call site continues to resolve identically: `from ai_trader.api import
ApiHandler, LocalApiService, run_server` (cli.py, most tests) and every `patch("ai_trader.api.X")`
mock target (`kraken_capital_ledger_summary`, `record_broker_snapshot`,
`OpenAIReadOnlyExplainer`, `AuditDatabase`, etc.) still hang off the same `ai_trader.api`
namespace, since `LocalApiService` and everything else stayed in `__init__.py` untouched -
only `ApiHandler` moved.

**Before/after dependency summary.** Before: one 6,152-line module mixing HTTP transport,
service orchestration (`LocalApiService`, ~150 methods), and ~70 module-level helper
functions, with 28 single-dot relative imports of sibling domain modules. After: `api/http_server.py`
(143 lines, stdlib-only) owns transport; `api/__init__.py` (6,021 lines, unchanged content
otherwise) still owns everything else pending Phases 2-8, with its 28 sibling imports promoted
to double-dot (`..database`, `..agent`, etc., since it is now one directory deeper) and six
imports removed that only `ApiHandler` had used (`hmac`, `deque`, `BaseHTTPRequestHandler`,
`Lock`, `parse_qs`, `urlparse`).

**Verification.** `python -m py_compile` clean on both files. Confirmed no circular import
(`http_server.py` imports nothing from the `api` package). Confirmed no deployment config
(`Dockerfile`, `render.yaml`) or packaging metadata hardcodes the old `api.py` file path.
Full stable suite passed clean twice independently: 277 passed, 0 failed both runs. No
production runtime behaviour changed - this is a pure code-location move.

**Committed separately from Stage 0 below**, per the plan's "small, independently revertible
commit" delivery control. Files changed: `src/ai_trader/api.py` → `src/ai_trader/api/__init__.py`
(renamed, ~195 lines changed), `src/ai_trader/api/http_server.py` (new, 143 lines).

**Next.** Continuing to Phase 2 (query execution: extracting `_connect`, `_row`, `_rows`,
`_scalar`, `_count` into an injected `QueryExecutor`).

## 2026-08-02 Modularisation Stage 0 (safety/characterization) complete

Implements Stage 0 of `architecture/AI_TRADER_MODULARISATION_ARCHITECTURE_2026-08-02.md`
(ChatGPT-authored plan, produced from `architecture/AI_TRADER_MODULARISATION_DISCOVERY_PACK_2026-08-02.md`).
Per the plan's own Section 14 instruction, Stage 0 is mandatory safety/characterization work
that must complete and be reviewed before any Phase (actual code extraction) begins. **No
extraction Phase has started.** No behaviour was intentionally changed; this stage only adds
tests and collapses redundant schema-initialization work.

**0.1 - Resolved two flagged safety unknowns** (the discovery pack could not confirm either
from static reading alone):
- Kill switch consultation: proved by code trace and a new end-to-end test
  (`test_active_kill_switch_prevents_order_placement_end_to_end`, `tests/test_orchestrator.py`)
  that `KILL_SWITCH_STATE` is genuinely read on the live order path
  (`sprint6.production_risk_sentinel_decision` -> `pre_execution_decision_packet` ->
  `orchestrator.evaluate_recommendation`), not only displayed on a status endpoint.
- Order-intent lock atomicity under Postgres: proved by code trace that
  `database.PostgresConnection.execute()` re-raises `psycopg.IntegrityError` as
  `sqlite3.IntegrityError`, which `acquire_order_intent_lock`'s existing exception handler
  already catches correctly on both backends. No bug found.

**0.2 - Fixed the remaining schema-reinit-per-call bug** (the same class of bug fixed in 7
other modules on 2026-08-01, where `initialize_*_schema` ran its full `CREATE TABLE`/`ALTER`/
seed sequence unconditionally on every call instead of once per process). Added a shared
`src/ai_trader/persistence/schema_once.py` helper (`ensure_schema_once`, process-wide,
thread-safe, backend/db_path-scoped cache key; 5 tests in `tests/test_schema_once.py`) and
applied it to the three modules confirmed to sit in a real hot loop:
- `portfolio_intelligence.py` - runs on every candidate `evaluate_recommendation` call via
  the portfolio-manager governance step.
- `operational_truth.py` and `experience_engine.py` - `sprint6.process_learning_outbox`
  claims and loops over up to 10 pending learning workflows per worker invocation, each of
  which independently called these modules' schema-init functions up to ~4 times.
- Deferred: migrating the 8 already-fixed modules' hand-rolled equivalents onto the shared
  helper. They are already correct and tested; this is pure code-hygiene cleanup with no bug
  to fix, left for a later phase to avoid unnecessary re-test surface during Stage 0.

**0.3 - API contract characterization tests.** Added `tests/test_api_contract_characterization.py`
(21 tests) pinning current authorization and top-level response shape for all 17 named
mobile-consumed endpoints ahead of any future extraction of `api.py` routing/handlers. Cross-
checked `mobile/App.js`'s actual call sites (not static grep): confirmed mobile calls all 17,
found one endpoint outside the named list that mobile also calls
(`/benchmark-daily-brief`, fetched best-effort like the other secondary screens), and
confirmed which GET endpoints mobile does not call at all (everything founder-facing screens
need is nested inside `/founder-evidence` instead).

**0.4 - Added the remaining missing safety tests** named in the plan's Section 3 invariants,
after checking existing coverage to avoid duplicates: Kraken allowed-pair rejection, Kraken
capital-sleeve isolation at the real `_account_context_for_broker` integration point (a large
pre-existing personal BTC holding must never inflate the AI's isolated equity), the
`_snapshot_equity_basis_matches_context` equity-basis guard directly, Alpaca paper-only
rejection on the live-account path, an ambiguous (exception-raising) broker outcome
retaining its order-intent lock, `operational_truth` reconciliation flagging missing data for
manual review instead of fabricating a symbol, and a regression test proving the 0.2 schema-
once fix still initializes correctly across multiple fresh `db_path` values in one process.
Kraken buy-only enforcement was already covered and was not duplicated.

**Flaky test diagnosed and fixed.** `test_phase5_production_spine.py::test_phase5_status_reports_attention_until_production_database_ready`
intermittently failed only in full-suite runs. Root cause: `production_spine.supervise_workers`
classifies heartbeat staleness against a live, non-injectable `datetime.now(timezone.utc)`
read against a fixed 240-second threshold - a genuine wall-clock race on this environment, not
a logic bug (schema-cache key collision and cross-test global state were both ruled out by
direct code trace). Fixed the test, not production code: it now asserts the healthy path
strictly, and on the rare stale-clock path asserts the failure is genuinely isolated to clock
staleness on the one just-heartbeated worker (no duplicate worker types, no late jobs, no
backlog) - still fails on a real classification bug if one exists.

**Verification.** Full stable suite: 277 passed, 0 failed, run clean twice independently
(including the previously-flaky test). No production runtime behaviour was intentionally
changed - all `src/` edits only collapse repeated idempotent schema setup into a single
process-lifetime call, per module. No broker permission, risk limit, strategy gate,
allocation limit, stop, target, capital-isolation boundary, or governance threshold was
weakened.

**Committed separately from Phase 1 above**, per the plan's "small, independently revertible
commit" delivery control. Files changed: `src/ai_trader/portfolio_intelligence.py`,
`src/ai_trader/operational_truth.py`, `src/ai_trader/experience_engine.py`,
`src/ai_trader/persistence/__init__.py` (new), `src/ai_trader/persistence/schema_once.py` (new),
`tests/test_schema_once.py` (new), `tests/test_api_contract_characterization.py` (new),
`tests/test_orchestrator.py`, `tests/test_guardrails.py`, `tests/test_multi_broker_platform.py`,
`tests/test_phase5_production_spine.py`, `tests/test_world_class_transformation.py`.

**Next.** Per the plan's Section 14 instruction, stopping here for review before Phase 1
(HTTP transport extraction) begins.

## 2026-07-31 AT-ED-003 UI pass completed - Activity, Recommendations, Portfolio, Learning

Continuation of the same day's Command-screen truth/declutter session. Commit `7969d1d2`,
merged `5656e7bc`, pushed to master (Render backend redeploy triggered by the additive
`production_evidence.py` change; the mobile `App.js`/`lib/` changes require a separate
EAS Update - see "Mobile deployment" below, not automatic from a git push).

**New shared module** `mobile/lib/founderPresentation.js` - pure, dependency-free functions
(no React/RN imports) so they're unit-testable without a bundler: `operationalRollup`,
`operationalLevelTone`, `brokerOverallReadiness` (moved out of `App.js` so Command, Activity,
and Portfolio all call the same broker-status computation instead of each maintaining their
own copy), `activityCategoryFor`/`groupActivity`, `recommendationLifecycle`,
`positionOwnership`, `learningSummary`. 24 assert-based tests in
`mobile/lib/founderPresentation.test.js`, run with `node mobile/lib/founderPresentation.test.js`
- no test framework was installed; this is Node's built-in `assert`.

**Activity screen.** Raw timeline items (`_timeline()` in `production_evidence.py`, which only
carries four raw categories - Research/Execution/Learning/System, with job identity folded into
the title string) are now grouped client-side into the nine Founder-facing categories via
job-name pattern matching, with repeated identical events (e.g.
`auto-execution-alpaca completed_no_action` firing every cycle) collapsed into one line with a
count and latest-occurrence timestamp. Each event states what happened, why it matters, the
outcome, and whether Founder action is required. Raw per-event detail is retained in full behind
a "Technical Details" section - nothing is deleted, only reordered. Removed a "Broker Activity"
section whose own broker-status computation (`row.payload?.auto_trading_enabled ? 'Enabled' :
'Disabled or not evidenced'`) used the exact true/false-only coercion the rest of the app had
already moved away from; rather than fix a component nothing else needed, it and its backing
computation were removed so it can't resurface later as a second, disagreeing source. Also
removed "Founder Attention" and "Latest Completed Actions", which duplicated the same evidence
now shown in the grouped view (the former's `items` array was always hardcoded empty).

**Recommendations screen.** Added a `recommendationLifecycle()` stage - Executed / Expired /
Blocked / No Action / Under Review - computed only from fields already in the
`/founder-evidence` recommendation payload (`freshness_status`, `guardrails_passed`,
`guardrail_failures`, `confidence`). "Executed" additionally requires a best-effort match
against trade evidence (same broker, same symbol, fill observed within the recommendation's
`created_at`..`expires_at` window plus a 24h grace period) - there is no persisted foreign key
from a recommendation to a specific fill in the current evidence model, so the reason text says
"matched by broker/symbol/timing, not a direct database link" rather than overclaiming certainty.
"Generated" (always true - `created_at` is always present), "Approved", and "Rejected" are
**not** separately derivable from current evidence - there is no persisted per-recommendation
orchestrator-decision record to read - and the module says so in its own docstring rather than
faking a sixth/seventh/eighth stage. The ~50-field technical dossier per recommendation moved
behind a collapsible "Full Evidence Dossier"; the lifecycle stage and reason now lead the card.

**Portfolio screen.** Reordered to lead with portfolio value/cash/deployed capital/day P&L/open
positions/positions-at-a-loss; broker diagnostics and exposure/operational detail moved into
collapsible sections. Added a new "AI-Managed Positions" section fed by a **new backend field**
(see below) - `positionOwnership()` only ever labels a position AI-managed when a real, open
`MANAGED_TRADE_EXITS` row exists for that symbol; every other holding (including any manual
Kraken holdings) renders as a plain position, never guessed to be AI-managed. Each AI-managed
position shows its originating recommendation (`proposal_id`, cross-referenced against the
recommendations list for strategy name), broker, entry time, current state, and unrealised
result; learning state correctly reads "not available yet" since learning only ever follows a
closed, reconciled trade and these positions are by definition still open.

**Learning screen.** Replaced three sections that were *always* empty under the current evidence
model (Strategy Rankings, Signal Rankings, Institutional Tests - all backed by
`founder_experience.learning_lab` fields hardcoded to `[]`/`null` in `statusFromFounderEvidence`)
with one concise summary card: completed trades reviewed, distinct strategies evaluated (from
recommendations grouped by `strategy_id`), latest lesson, and a single "why learning hasn't
progressed further" explanation instead of repeated "Not available" rows. Latest
strategy-change-proposal approval status reads "not yet exposed in this evidence projection" -
genuinely true; no strategy-promotion record is included in `/founder-evidence` today.

**Backend addition (`production_evidence.py`).** Added `managed_exits` (open
`MANAGED_TRADE_EXITS` rows, via the already-existing `open_managed_exits()`) to each broker in
the founder-evidence payload. Read-only and additive - no governance, guardrail, kill-switch,
allocation, reconciliation, or duplicate-order logic touched. This was the only way to correctly
satisfy "do not label manual Kraken holdings as AI-managed": without it, the mobile app had zero
signal to distinguish an AI-opened position from a personal holding. New test:
`test_founder_evidence_exposes_managed_exits_distinct_from_raw_positions`.

**Cross-screen consistency.** Confirmed Command, Portfolio, and the Dashboard tab all render
broker status through the same `BrokerPanel` component fed by the same `status.brokers` array
computed once per refresh in `statusFromFounderEvidence` - structurally, one broker cannot read
"Enabled" on one screen and "Disabled" on another because there is only one computation, not
several. The one live inconsistency risk found (the Activity screen's now-removed
`broker_activity` computation) is documented above.

**Validation performed:** full backend suite (234/234), 24 assert-based JS tests for the new
module, a full-file babel parse (`babel-preset-expo`) after every edit, manual review of every
modified JSX block and its data mapping, and repo-wide greps for remaining user-visible SQLite
wording (none beyond the intentionally-conditional sprint6/always_on self-diagnostic strings
already reviewed in the original AT-ED-003 session) and for independently-computed broker-status
logic (one instance found and removed).

**Not verified - requires the Founder:** on-device rendering, narrow/foldable Android layout,
loading/error states under real network conditions, and an actual EAS Update/build. There is
still no lint/typecheck/build tooling in `mobile/package.json` beyond the syntax-only babel
parse used here.

**Mobile deployment.** The `git push` above deploys the *backend* change only (Render). The
`mobile/App.js`/`mobile/lib/` changes need a separate EAS Update to reach installed test
builds, since this is a pure-JS change (no native code) under `runtimeVersion.policy:
"appVersion"`. This environment has no Expo/EAS credentials to run it. Exact command for the
Founder to run (from `mobile/`, after `eas login` with access to project
`58ca35af-2cf4-44a0-8da4-7f02563b635f`):

```
cd mobile
eas update --branch preview --message "AT-ED-003 UI pass: Activity/Recommendations/Portfolio/Learning"
```

Replace `preview` with whichever channel (`preview` / `hosted-preview` / other) the Founder's
actual test device build is currently pointed at - `eas.json` defines both `preview` and
`hosted-preview` build profiles with no way to tell from the repo alone which one is installed
on the Founder's device.

## 2026-07-31 Research batching/timeout fix + Command screen truth/declutter (partial)

Two coordinated changes, each on its own feature branch, merged to master and deployed:

**1. `fix/research-batching-and-timeout` (commit `fd9575b3`, merged `12040272`).**
Root cause of auto-execution never seeing fresh candidates: `run_analysis` called
`propose_trades` once per symbol, making up to 60 separate Alpaca `get_latest_bars`/`get_news`
HTTP round trips for a 30-symbol watchlist (both are genuine batch endpoints), plus one OpenAI
call per symbol, all sharing the fixed per-job subprocess overhead already confirmed to consume
most of the generic 180s worker job timeout. Fixed: `propose_trades` now fetches market/news once
per batch with per-symbol try/except preserving fault isolation; `run_analysis` calls it once;
`premarket-equity`/`market-open-equity`/`market-close-equity`/`overnight-crypto` get their own
timeout via `AI_TRADER_RESEARCH_JOB_TIMEOUT_SECONDS` (default 300s) instead of the shared 180s.
No trading/risk/governance/broker-permission/kill-switch/allocation/reconciliation/duplicate-order
logic touched. Local suite: 233/233. **Hosted verification not yet performed** - requires a Render
log pull spanning at least one `market-open-equity`/`overnight-crypto` firing (hourly buckets);
see `architecture/` for the prior evidence-snapshot-timeout fix this follows the same pattern as.

**2. `feat/command-screen-truth-and-declutter` (commit `3dc2bef8`, merged `26802923`) - PARTIAL.**
Scoped to what could be verified without new test infrastructure. Delivered: one true
Normal/Degraded/Blocked/Critical rollup (`operationalRollup`) replacing four independently-computed
"is everything OK" signals that could disagree with each other on the same screen; a
`CollapsibleSection` primitive so Command-screen detail is collapsed by default instead of ~15 flat
always-open sections, grouped into Research / Recommendations & Decisions / Broker Operations /
Trading & Portfolio / Learning / System Health; removed a full inline duplicate of `BrokerPanel`'s
JSX inside `CommandCentre` (now reuses the shared component) and a dead `{false && ...}`
notifications block; added explicit "New Entries Allowed", "Overall Readiness", "Latest Successful
Poll", and "Latest Confirmed Trade" per broker; fixed the one remaining genuinely user-facing
SQLite-wording string (`api.py` `report_page()`'s file_path fallback).

**Not attempted this session** (explicitly deferred, not silently dropped): Activity screen
grouping/collapsing/filters, Recommendations lifecycle wording, Portfolio screen declutter,
Learning screen concise empty-state, the cross-screen data-consistency audit beyond the Command
screen, and all new test-infrastructure work. `mobile/App.js` is a single ~3,800-line file with no
test/lint/typecheck/build tooling in `mobile/package.json` (no jest, no eslint, no tsconfig, no
build script) - verified only with a one-off babel parse (`babel-preset-expo`), which confirms
syntax only, not runtime behavior, rendering, or layout. On-device / narrow / foldable Android
layout was not verified; no EAS build or update was run (no Expo/EAS credentials available in this
environment).

## 2026-07-30 AT-ED-003 implementation session - operational job splitting, broker status data contract, SQLite wording audit

Executes `engineering-directives/implementation/AT-ED-003_OPERATIONAL_UI_CLEANUP_AND_REMEDIATION.md.txt`
Sections 1, 3, 5, and a scoped portion of Section 2. Sections 2 (remaining), 4, 6, and 7
(the full Command-screen operations-health redesign, Activity-screen regrouping, cross-screen
recommendation/decision/trade/portfolio/learning ID linking, and broader mobile UI polish) were
not attempted this session - see "Deferred" below.

**Section 1 - operational fixes.**
- Split `broker-poll` into `broker-poll-alpaca` / `broker-poll-kraken` and `auto-execution` into
  `auto-execution-alpaca` / `auto-execution-kraken`, each with its own scheduled-job name (own
  claim/idempotency/run-history row), so one broker's slow API or a transient failure cannot delay
  or starve the other broker's cycle. The worker loop's automatic scheduling now calls only the
  four new names; the old combined names remain dispatchable via `run-job` for manual/debug use
  only, so there is no duplicate scheduling and no duplicate execution.
- `poll_broker_activity(broker_filter=...)` and `auto_execute_recommendations(broker_filter=...)`
  gained a broker filter. In auto-execution, the filter is applied in Python immediately after each
  candidate's broker is resolved (before any governance-chain work), because `trade_audit` has no
  broker/asset_type column to filter on in SQL. The full guardrail / kill-switch / strategy-
  entitlement / Kraken-reconciliation-hold / order-intent-lock / duplicate-order chain is otherwise
  completely unchanged - reviewed line-by-line, not weakened.
- Added `record_trade_evidence_batch()`: one connection/transaction per broker-poll cycle instead
  of one connection per broker event, with identical per-row idempotent ON CONFLICT semantics.
- Evidence at deploy time: the previously-recorded `broker-poll` (combined) job had timed out on
  three consecutive cycles immediately before this deploy (`SCHEDULED_JOB_RUNS`, 23:40/23:50/00:10
  UTC on 2026-07-30) - direct confirmation the split was addressing a real, active production
  problem, not a hypothetical one.

**Section 3 - broker auto-trading status data contract.**
- Root cause confirmed: `PRODUCTION_BROKER_SNAPSHOTS.payload_json` was never selected into the
  Founder evidence projection, and the snapshot `panel` dict written by
  `capture_production_broker_snapshots()` never carried `auto_trading_enabled` /
  `trading_permissions` in the first place - so the mobile app's existing (already-written)
  consumption code always saw `undefined` and coerced it to "Disabled", regardless of the true
  DB-backed setting.
- `capture_production_broker_snapshots()` now computes the same governance
  (`_broker_trading_permissions()`) already used by the live `/brokers` endpoint and persists
  `auto_trading_enabled`, `auto_trading_status`, `trading_permissions`, and a new
  `block_reason` (plain-language, mirrors the exact gate that is blocking new entries) into every
  snapshot. `_load_founder_evidence_rows()` now selects `payload_json`; `_assemble_founder_evidence_payload()`
  lifts these fields to the top level of each broker row, defaulting to `None`/"Unknown" - never a
  silent `false`/"Disabled" - when a snapshot has not captured them yet.
- Mobile: `statusFromFounderEvidence()`'s broker-panel mapping, `BrokerPanel`, and
  `ConnectionReadinessCard` now treat `auto_trading_enabled` as a true tri-state and render
  `auto_trading_status` / a new "Block Reason" metric instead of coercing missing data to
  "Disabled".

**Section 5 - SQLite wording audit.**
- Reviewed every user-facing string containing "SQLite" across the backend and mobile app.
  Fixed three that named SQLite even though production runs Postgres and would have shown the
  wrong storage technology to the Founder: the benchmark-brief unavailable-reason, the equity
  research "no symbols" message, and the Recommendation History screen's description line.
- Left the `sprint6`/`always_on` self-diagnostic strings ("SQLite is active; acceptable for
  local/test/offline use...") unchanged - these are genuinely conditional on the active backend and
  only ever say "SQLite" when that is true, which is the correct, honest behavior the directive
  requires, not a defect.

**Section 2 - scoped addition (24-Hour Operations).**
- Added `_job_health_summary()`: backend classification of every scheduled job using the exact
  Founder-facing vocabulary the directive specifies (Healthy / Delayed / Timed Out / Blocked / No
  Eligible Action / Awaiting First Run / Disabled by Founder / Enabled but Blocked), computed from
  each job's own `SCHEDULED_JOB_RUNS` history and the broker's true auto-trading setting - never
  "Healthy" merely because a process exists. Exposed at
  `founder-evidence.summary.operations.job_health` and rendered as a new "24-Hour Operations" card
  on the Command screen.

**Testing.**
- Added/updated: `test_production_completion.py` (batched evidence-write contract, broker-filtered
  poll isolation, broker-snapshot governance-field contract, a positive-path auto-trading-enabled/
  disabled data-contract test), `test_multi_broker_platform.py` (auto-execution broker-filter
  candidate isolation, updated the delegated-execution message assertion),
  `test_production_evidence.py` (job-health vocabulary classification, including the
  Disabled-by-Founder-takes-precedence-over-Delayed case and the Blocked-vs-No-Eligible-Action
  distinction).
- Full Python suite: 218 passed (2 pre-existing `test_cli_startup.py` failures are a local Windows
  temp-directory permission error in the pytest fixture itself, unrelated to any file this session
  touched, and unaffected by this diff).
- Mobile: no test/lint/typecheck tooling exists in this project (`mobile/package.json` has no
  test/lint scripts, no Jest, no ESLint, no TypeScript config) - not introduced this session, since
  that is a larger tooling decision outside this directive's scope. Verified instead by parsing the
  full `App.js` with `@babel/preset-react` after every edit (confirms valid JSX/syntax, not runtime
  correctness).

**Deployment.**
- Branch `feature/at-ed-003-operational-ui-remediation`, fast-forward merged to `master` at
  `27bc1d81`, pushed. Render redeployed; `/healthz` returned 200 after the push.
- Mobile: `npx eas update --branch preview` published, commit `27bc1d81` (matches the deployed
  backend commit), runtime version 1.0.3.
- Post-deployment read-only verification used the locally configured `AI_TRADER_API_TOKEN`
  (already present in `.env`/`mobile/.env.local` from prior sessions) against the hosted
  `/founder-evidence` and `/job-runs` endpoints. Confirmed `broker-poll-alpaca` appearing in
  `SCHEDULED_JOB_RUNS` for the first time immediately after deploy. Full confirmation that the
  persisted founder-evidence snapshot reflects the new payload shape (`job_health` present,
  `auto_trading_status` populated) was pending the next `evidence-snapshot` job cycle (~5 minute
  cadence) at the time of writing - see the Founder briefing for the final result.

**Deferred (not implemented this session) - AT-ED-003 Sections 2 (remainder), 4, 6, 7.**
- Command screen: Command Summary card (single overall Normal/Degraded/Blocked/Critical state with
  deployed-commit and heartbeat-freshness) is not built; the 24-Hour Operations card above is real
  but partial.
- Activity screen: the two-level (Founder view / Technical Detail view) redesign, duplicate/
  heartbeat collapsing with counts, and category/broker/severity/date filtering are not built - the
  existing Activity screen is unchanged.
- Cross-screen lifecycle linking: recommendation/decision/trade/portfolio/learning ID propagation
  and in-app navigation between them are not built, beyond what the existing data model already
  carries (`proposal_id`, `broker`, `strategy_id` are already present on recommendation rows).
- Broader UI polish (collapsible sections summary-first by default, empty/error/loading state
  review across all six screens) is not attempted.
- Reason: implementing a full rewrite of the Activity screen and cross-screen navigation in a
  single-file, 3,600+ line, untested production mobile app carries real regression risk that this
  session's time did not allow validating safely (no test/lint infrastructure exists to catch a
  mistake before it reaches the Founder's phone). Next action: a follow-up, narrowly-scoped session
  per remaining sub-section, each landed and verified independently rather than as one large
  Activity-screen rewrite.
- No trading, risk, governance, capital-allocation, kill-switch, strategy-maturity,
  order-intent-lock, or duplicate-order control was touched, weakened, or bypassed. The Kraken
  reconciliation hold was not cleared. No live Kraken order was submitted.

## 2026-07-29 AT-ED-002 v2.0 implementation session - restore continuous autonomous operation

Executes `engineering-directives/implementation/AT-ED-002_v2.0_INSTITUTIONAL_EDITION.md.txt`,
scoped per the Founder's explicit clarification to: restore/verify continuous operation, Alpaca
paper trading, and Kraken governed live trading; keep market data/research/opportunity
evaluation/learning/persistence/reporting running continuously; preserve every existing
capability; expand evidence quality where safe and low-risk. Explicitly out of scope this session
(per Founder instruction): the Knowledge Graph, Investment Committee workflow, Monte Carlo
infrastructure, and the `investment-governance/` documentation set - these remain long-term-vision
items, not attempted, and are not placeholder-implemented.

**Critical finding #1 - autonomous execution was fully disabled in the hosted config.**
`render.yaml` had `AUTO_PAPER_TRADING`, `ALPACA_AUTO_TRADING`, `KRAKEN_AUTO_TRADING`,
`KRAKEN_TRADING_ENABLED`, `KRAKEN_LIVE_TRADING_APPROVED`, and `KRAKEN_SUBMIT_REAL_ORDERS` all set
to `"false"`. Flagged to the Founder directly (not assumed) before changing anything, since Kraken
enablement is a real-money decision. The Founder explicitly authorized enabling autonomous trading
for both brokers, with Kraken's existing size/count/allocation guardrails
(`KRAKEN_MAX_ORDER_GBP=5`, `KRAKEN_MIN_ORDER_GBP=1`, `KRAKEN_MAX_OPEN_TRADES=1`,
`KRAKEN_TRADING_ALLOCATION_GBP=100`, `KRAKEN_ALLOWED_PAIRS`) explicitly preserved unchanged.
Flipped exactly those six flags to `"true"` in `render.yaml`; verified via `git diff` that no
other value changed. `KRAKEN_SANDBOX_MODE` was found to be dead configuration (referenced in
`.env.example`/`ENVIRONMENT_VARIABLE_AUDIT.md` as an active safety guard but never read by any
Python code) - left untouched, documented as a doc-vs-code drift for correction.

**Critical finding #2 - flipping the flags alone would not have produced a single real Kraken
order.** Traced the full autonomous-execution path and found `orchestrator.py` routes every
non-Alpaca broker through `pre_execution_decision_packet()` with `mode="micro_live"`, but every
strategy in `STRATEGY_MATURITY_REGISTRY` is deliberately capped at paper/shadow/manual
entitlement (the Phase 1 promotion safety gate - see 2026-07-29 Phase 1 entry below). Verified
empirically (not just by reading code) that `strategy_entitlement_decision()` returned `blocked`,
`"Strategy is not permitted for micro_live execution"`, for the crypto strategy Kraken actually
uses, before any fix. This is not a regression from Phase 1 - the same block existed identically
before it, just never exercised because auto-trading was off and the one real Kraken strategy
traded exclusively via founder-triggered "manual" mode. Added
`sprint6.apply_founder_strategy_authorization()`: a direct, explicit, human-authorization path
distinct from the evidence-based `refresh_strategy_maturity()` (which is deliberately capped below
real-capital stages, per Phase 1). Applied it to exactly one strategy -
`crypto_trend_following_2r`, the only strategy `trading_intelligence.STRATEGIES` itself already
labels `production_status="founder_controlled_live_kraken"` - raising it to "Micro Live" with
`micro_live` added to its permitted modes. Every other crypto-eligible strategy (8 others,
including `crypto_infrastructure_trend`, `momentum`, `breakout`, etc.) is explicitly
`production_status="research_only"` in its own definition and was deliberately left untouched: if
the scoring engine selects one of them for a given Kraken proposal, that proposal is still
correctly blocked from real-money execution. Wired the authorization to apply automatically and
idempotently at API startup (`LocalApiService._apply_founder_kraken_live_authorization()`),
alongside the existing `_apply_env_broker_auto_defaults()`, gated on `KRAKEN_AUTO_TRADING` being
on - so it self-applies on the hosted database on next deploy, the same pattern already used for
syncing broker auto-trading state from environment.

**Verification performed (not just claimed):**
- Continuous runtime: traced `cli.py run-worker`'s loop - runs `managed-exits`, `broker-poll`,
  `auto-execution`, `push-dispatch` every cycle (~60s), plus all `_due_worker_jobs`-scheduled
  research jobs, processes the learning outbox, records a heartbeat, and degrades gracefully
  (records an incident, does not crash) on any exception.
- Market data / research: `overnight-crypto` runs hourly regardless of weekday;
  premarket/market-open/market-close-equity run during market hours; `strategy-lab-refresh`
  (Phase 1) runs daily after close. `AI_TRADER_WORKER_RESEARCH_ENABLED=true` already in
  `render.yaml`, unaffected by this session.
- Learning: `enqueue_learning_workflow()` is called from real trade-closing reconciliation
  (`kraken_reconciliation.py`, `sprint6.py`); `process_learning_outbox()` claims and processes
  pending entries every worker cycle via `run_closed_loop_learning()`.
- Alpaca: confirmed empirically (not just by reading code) that `strategy_entitlement_decision()`
  approves `mode="paper"` for a representative strategy with no equivalent blocker.
- Kraken: added an end-to-end orchestrator-level test
  (`test_kraken_autonomous_execution_requires_founder_authorization_end_to_end`) proving the
  specific `"not permitted for micro_live execution"` failure is present before authorization and
  absent after it, using the real `InvestmentOrchestrator.evaluate_recommendation()` path with the
  same three env vars `render.yaml` now sets.
- Reporting: confirmed `daily_learning_update()` (performance attribution, win/loss, orchestrator
  decisions, benchmark comparison) and `generate_founder_operational_report()` (events, decision
  journal, incidents) both already scheduled and produce real content, not placeholders.

**Evidence-quality expansion:** audited what already exists rather than adding new external
provider integrations blind. ATR-based volatility, regime classification, and cross-market
correlation (`load_return_series`, Phase 1) are already real, tested, non-placeholder capability
feeding research and portfolio decisions. Genuinely new evidence sources requested in
AT-ED-002 Part 2 (macroeconomic/central-bank data, funding rates, order-book depth, sentiment,
academic literature) all require new external provider integrations that cannot be safely built
and tested without credentials this environment does not have - deferred as explicit
recommendations below rather than built untested, consistent with the same judgment applied to
Kraken historical-candle ingestion in Phase 1.

**Testing:** full suite grew from 210 to 215 tests, all passing. New tests specifically prove: the
Kraken entitlement gap (blocked before, unblocked after, for the authorized strategy only, with a
research-only strategy remaining correctly blocked); the API-startup wiring applies the
authorization only when `KRAKEN_AUTO_TRADING` is on; idempotency of the authorization; and the
full orchestrator-level path.

**Files changed:** `render.yaml`, `src/ai_trader/sprint6.py`, `src/ai_trader/api.py`,
`tests/test_sprint6_institutional_spine.py`, `tests/test_orchestrator.py`.

## 2026-07-29 Backend-selection hardening (pre-Phase-1-commit)

Requested by the Founder before committing Phase 1, following the architectural clarification on
SQLite presence given earlier the same day. That clarification surfaced a real inconsistency:
`database.py:selected_backend()` correctly treats a configured `DATABASE_URL`/`SUPABASE_DATABASE_URL`
as sufficient to select Postgres when `AI_TRADER_DATABASE_BACKEND` is unset, but
`always_on.py:_use_postgres()` independently reimplemented the same decision and defaulted to
`"sqlite"` in that exact case instead. In the currently deployed `render.yaml` this never
manifested (every hosted service sets `AI_TRADER_DATABASE_BACKEND=postgres` explicitly), but it
was a live risk for any future or ad-hoc environment that configured only `DATABASE_URL`.

**Consolidation, `database.py` is now the single authoritative implementation:**

- Split `selected_backend()`'s precedence logic out into a new `requested_backend()` - the one
  place "what backend does this environment ask for" is decided (explicit
  `AI_TRADER_DATABASE_BACKEND` wins; otherwise `DATABASE_URL`/`SUPABASE_DATABASE_URL` presence
  implies Postgres). `selected_backend()` is now `requested_backend()` plus validation (raises if
  hosted-and-not-postgres, or postgres-requested-without-a-url) - unchanged behaviour, just
  factored so the precedence logic isn't duplicated inside it.
- Added `database.uses_postgres() -> bool`: the same precedence logic, non-raising, for
  status/diagnostic reporting and internal SQL-dialect branching.
- **`always_on.py`**: deleted its independent `_database_url()` and `_use_postgres()`
  implementations entirely. Now imports `database_url`, `requested_backend`, and `uses_postgres`
  directly from `database.py` - `always_on.uses_postgres` is the literal same function object
  other modules already import via `from .always_on import uses_postgres`
  (`sprint6.py`, `production_evidence.py`), so those call sites now transitively use the
  authoritative implementation with no import-path changes required. All ~20 internal
  `if _use_postgres():` / dialect-branching call sites updated to call the imported
  `uses_postgres()`. `database_backend_status()` (the Founder-facing diagnostic used by
  `always_on_status()`) now reports `requested_backend` from `requested_backend()` instead of a
  third independent raw `os.getenv("AI_TRADER_DATABASE_BACKEND", "sqlite")` read - it now
  correctly reports `"postgres"` when only `DATABASE_URL` is set, consistent with
  `active_backend`, instead of the previous self-contradictory `requested_backend: "sqlite"`,
  `active_backend` potentially disagreeing.
- **`config.py`**: `Settings.is_hosted_runtime` now ORs its existing `process_role` check with
  `database.is_hosted_runtime()` instead of re-listing the three Render env vars inline.
  `Settings.uses_postgres` now checks against the imported `database.POSTGRES_BACKENDS` constant
  instead of a separately-written literal set. `Settings` remains a resolved-at-load-time
  snapshot (it does not re-read env vars live), which is a legitimate, deliberately different
  layer from `database.py`'s live resolution - not consolidated further than this.
- **`production_spine.py`, `sprint6.py`**: both had a `database_backend in {"postgres", "postgresql", "supabase"}`
  literal (checking an already-resolved string parameter, not re-reading env) duplicated from
  `database.py:POSTGRES_BACKENDS`. Replaced with the imported constant so the set of Postgres
  backend aliases is defined in exactly one place repository-wide.

**Found but deliberately not touched (out of the "small" scope requested):**
`always_on.py` also has its own parallel `_postgres_connection()`/`postgres_connection()` (a raw
`psycopg.connect()`, separate from `database.py`'s `PostgresConnection`/`connect()` wrapper), and
hand-writes dual-dialect SQL throughout (`"%s" if uses_postgres() else "?"`) instead of using the
`?`-placeholder abstraction every other module uses via `connect()`. This is a real, separate
architectural duplication - a second database-access pattern, not just a second backend-selection
check - but consolidating it means rewriting ~20 call sites in safety-critical worker/scheduling
code (job locking, heartbeats, incidents). That is a materially larger and riskier change than the
backend-*selection* hardening requested here and was not attempted.

**Deleted:** the untracked root-level `unused.sqlite3` artifact (a confirmed local `pytest` side
effect from `test_production_completion.py`, already documented as such in
`architecture/CRITICAL_REMEDIATION_PLAN.md`; not read by any production code path).

**Testing:** new `tests/test_database.py` (8 tests) covers `database.py` directly: explicit
Postgres backend, Postgres selected from `DATABASE_URL` alone (the exact bug fixed), Postgres
selected from `SUPABASE_DATABASE_URL` alone, local SQLite with nothing configured, hosted runtime
refusing SQLite, hosted runtime succeeding with Postgres configured, Postgres requested without a
URL raising even when not hosted, and `postgresql`/`supabase` aliases normalizing to `"postgres"`.
Added one test to `tests/test_always_on_operations.py` proving `database_backend_status()` now
agrees with `database.py` when only `DATABASE_URL` is set. Full suite: 210 tests passing (up from
201), no regressions. Nothing committed - working tree only, per standing instruction.

## 2026-07-29 Phase 1 - Connect What Already Exists (integrated autonomous intelligence)

Executes `engineering-directives/implementation/PHASE_1_INTEGRATED_AUTONOMOUS_INTELLIGENCE.md`,
scoped to the eight-item "Phase 1" list in `architecture/FOUNDER_IMPLEMENTATION_PLAN.md`'s
Proposed Implementation Order (items a-h), approved by the Founder 2026-07-28 alongside Phase 0.
Plan document: `architecture/PHASE_1_INTEGRATED_IMPLEMENTATION_PLAN.md`.

**Known risk carried into this session:** per `architecture/INTEGRATED_IMPLEMENTATION_STATUS.md`,
Phase 0's five P0 items remained hosted-production-evidence outstanding as of 2026-07-28 - none of
them have been hosted-verified from this environment (no Postgres/Render access). The Founder
explicitly directed this session to proceed regardless, treating the gap as a tracked risk rather
than a blocker. It is unchanged by this session and still needs closing.

- **(a) `TradeProposal.strategy_id`.** The 14-strategy scoring engine's winning `strategy_id` never
  reached the top-level `TradeProposal` the governance layer reads, so `sprint6._strategy_id()`
  always fell back to a single generic bucket regardless of which strategy was actually selected.
  Added `strategy_id: str = ""` to `TradeProposal` (`models.py`), populated from
  `IntelligencePacket.strategy["strategy_id"]` in both proposal-construction paths in `agent.py`.
- **(b) `STRATEGY_MATURITY_REGISTRY` per-strategy seeding.** Discovered while implementing (a):
  shipping (a) alone without this would have made every real trade proposal blocked, because
  `strategy_entitlement_decision()` returns `blocked` for any `strategy_id` with no registry row,
  and the registry had exactly one row (`current_recommendation_process`). `seed_default_strategy_registry`
  (`sprint6.py`) now seeds one row per strategy in `trading_intelligence.STRATEGIES`, each with the
  exact same paper/shadow/manual entitlement scope the single generic bucket previously granted -
  differentiates the registry without loosening or tightening current behaviour.
- **(c) Historical-candle ingestion.** `record_historical_candle()` existed but was never called in
  production, so `HISTORICAL_CANDLES` was permanently empty. Added `AlpacaPaperClient.get_daily_bars()`
  (`alpaca.py`) - genuinely new integration, Alpaca's `/v2/stocks/{symbol}/bars` endpoint, not
  previously wrapped - and `LocalApiService.refresh_strategy_lab()` (`api.py`), which ingests daily
  bars for the COMPANY_MASTER equity universe. Equity-only: Kraken has no equivalent OHLC client
  yet, and building one untested in the same session was judged higher-risk than the value of
  including it now; tracked as a near-term follow-up, not an oversight.
- **(d) Backtest + walk-forward scheduling.** `run_strategy_backtest`/`run_walk_forward_validation`
  (`trading_intelligence.py`) existed, were unit-tested, and had zero production callers.
  `refresh_strategy_lab()` now runs both for every stock-eligible named strategy against the
  ingested candle history. Registered as worker job `strategy-lab-refresh`, scheduled once daily
  after equity market close (`cli.py`).
- **(e) `strategy_promotion_decision` scheduling + registry write-back, with a safety gate.**
  `strategy_promotion_decision()` (`production_spine.py`) had no caller and the registry had no
  write-back path. Added `refresh_strategy_maturity()` (`sprint6.py`), called per strategy from
  `refresh_strategy_lab()` with backtest evidence (sample size, expectancy, profit factor, max
  drawdown) plus real calibration evidence from `calculate_calibration_metrics()`. **Judgment call,
  not in the original plan text:** demotions (including suspension) always apply automatically
  since reducing entitlement never increases risk; promotions apply automatically only up to and
  including "Paper" stage. A promotion that would cross into "Micro Live" or "Production" - real
  capital entitlement - is fully logged in `STRATEGY_PROMOTION_DECISIONS` for visibility but is
  **not** applied to the registry; it is surfaced as pending Founder approval instead. Reason: the
  evidence feeding this job is backtest simulation, not a live trading track record, and the one
  strategy already trading real capital (`crypto_trend_following_2r`) is explicitly documented as
  founder-controlled, not self-promoting. Mirrors the Founder-approval pattern the Pillar 5
  assessment already called for on learning proposals.
- **(f) Portfolio correlation `return_series`.** `correlation_warning()` (`portfolio_intelligence.py`)
  was real but always received `return_series={}` from `portfolio_manager_decision()`, so it could
  only ever report `insufficient_history`. Added `load_return_series()` (`trading_intelligence.py`),
  reading simple period-over-period returns from `HISTORICAL_CANDLES`; wired into
  `pre_execution_decision_packet()` (`sprint6.py`). Activates automatically as (c) accumulates
  history - does not change how correlation affects the decision (still logged only, per
  `FOUNDER_IMPLEMENTATION_PLAN.md`'s explicit Phase 2 deferral of that design work).
- **(g) `upsert_asset_metadata` wiring.** Sector/country/theme exposure bucketing
  (`portfolio_intelligence.py:155-203`) always fell back to "Unknown" because nothing called
  `upsert_asset_metadata()` outside tests, despite the source data already sitting in
  `COMPANY_MASTER`. Added `LocalApiService._refresh_asset_metadata_from_company_master()`
  (`api.py`), called from the existing equity research cycle (`run_analysis`) once symbols are
  resolved. No new data source.
- **(h) Broker governance capability flag.** `orchestrator.py:202` gated the entire production
  governance chain (Strategy Entitlement -> Portfolio Manager -> Risk Sentinel) behind a hardcoded
  `{"alpaca", "kraken"}` name allowlist - a correctly implemented new `BrokerAdapter` would
  silently bypass governance unless a human separately remembered to edit that line. Added
  `requires_production_governance: bool` to the `BrokerAdapter` Protocol (`broker_adapters.py`),
  defaulted `True` on every concrete adapter (including placeholders); `orchestrator.py` now reads
  the flag via `getattr(selected, "requires_production_governance", True)` instead of the name set.
  Two pre-existing test-only `FakeAdapter` fixtures (`test_orchestrator.py`, `test_foundation_sprint.py`)
  explicitly opted out (`requires_production_governance = False`) since they predate and are
  orthogonal to the production governance chain; this was verified, not assumed, by running the
  full suite and fixing the two fixtures the change correctly broke.

**Testing:** full local suite grew from 185 to 201 tests, all passing (`pytest tests/`, this
environment's `.venv`). New tests specifically prove: (a)+(b) shipped together safely (every named
strategy is registered and entitled, not just the generic bucket); (e)'s safety gate holds under
both thin and strong synthetic evidence, including that an applied stage change never lands on
Micro Live/Production; (f) correlation status flips from `insufficient_history` to `complete` once
candle history exists; (g) portfolio exposure stops defaulting to "Unknown" once metadata is
refreshed; (h) a hypothetical new broker with no explicit governance opt-out is still routed
through governance and correctly rejected as an unpermitted broker. No Postgres access in this
environment - schema-affecting changes are written to run identically against both backends but
are not hosted-verified from here.

**Documentation:** added `architecture/PHASE_1_INTEGRATED_IMPLEMENTATION_PLAN.md` (the directive's
required First Deliverable); corrected `architecture/MARKET_INTELLIGENCE_PLATFORM.md`, which
described the still-disconnected Regime 2.0/multi-timeframe engine as live capability (that
connection remains out of scope for this session - not in the approved Phase 1 item list).

**Scope not attempted this session (Phase 2/3, per `FOUNDER_IMPLEMENTATION_PLAN.md`):** fitted/
calibrated strategy weights; the Founder-facing learning-proposal approval mechanism; regime-aware,
correlation-influenced portfolio decisioning; AI-provider abstraction; the hardcoded US-equity
market-hours gate; Kraken/crypto historical-candle ingestion; sector-rotation/macro/earnings data
ingestion; cross-broker capital view. All assessed and already described in
`FOUNDER_IMPLEMENTATION_PLAN.md`; none were part of the approved Phase 1 scope.

## 2026-07-29 Engineering Directives structure created

- Added a permanent, version-controlled `engineering-directives/` folder to
  hold lengthy prompts and governing AI engineering instructions for Claude
  Code, Codex, and future AI engineering agents, replacing long clipboard
  prompts wherever practical.
- Structure: `README.md`; `implementation/`, `architecture/`, `operations/`,
  `reviews/`, and `templates/` subfolders; reusable
  `IMPLEMENTATION_TEMPLATE.md` and `REVIEW_TEMPLATE.md`.
- Placed the Phase 1 "Integrated Autonomous Intelligence" directive at
  `engineering-directives/implementation/PHASE_1_INTEGRATED_AUTONOMOUS_INTELLIGENCE.md`
  for future execution. This entry records creation only; the directive has
  not been executed.
- Documentation-only change. No application code, tests, schema, or
  production behaviour was modified.

## 2026-07-28 Founder Implementation Programme - Phase 0 (mandatory safety gate)

Implements the five P0 items in `architecture/CRITICAL_REMEDIATION_PLAN.md`, approved by
the Founder as the mandatory gate before Seven Pillars work begins (see
`architecture/FOUNDER_IMPLEMENTATION_PLAN.md`). All five originate from the 2026-07-27
independent architecture review (`architecture/CLAUDE_INDEPENDENT_ARCHITECTURE_REVIEW.md`).

- **P0-1 - `LOGICAL_TRADES` schema never created on Postgres.** `canonical_trades.py` and
  `kraken_reconciliation.py` both skipped canonical-trade schema creation whenever
  `uses_postgres()` was true, and no other code path created it there either. Removed the
  skip; schema creation is now unconditional on both backends and cached once per process
  (the same `_INITIALIZED_SCHEMA_KEYS` pattern already used by `always_on.py` and
  `production_evidence.py`) so the fix does not reintroduce per-call connection overhead.
  Wired `initialize_canonical_trade_schema` into `LocalApiService.__init__`'s startup
  sequence in `api.py`.
- **P0-2 - exit orders had no duplicate-submission protection.** `monitor_managed_exits`
  and `force_managed_exit` in `api.py` now acquire the same DB-level
  `acquire_order_intent_lock` entries already use, before calling the broker, sharing one
  lock key per managed position so an automatic exit and a founder-forced exit can never
  both submit an order for the same position. Added `release_order_intent_lock` to
  `multi_broker.py`, called only on a definite, synchronous broker rejection, so a
  legitimate retry remains possible without ever auto-retrying an ambiguous outcome
  (process killed mid-flight).
- **P0-3 - duplicate scheduling between Render cron and the always-on worker.** Confirmed
  the worker's own `_due_worker_jobs` already independently schedules
  `premarket-equity`, `overnight-crypto`, `market-open-equity`, `market-close-equity`, and
  `daily-report` on its own cadence, and the two schedulers' idempotency keys never
  collide. Removed the six overlapping Render cron services from `render.yaml` (including
  `midday-equity`, whose window is already covered by the worker's hourly
  `market-open-equity` cadence); kept `daily-learning`, `weekly-report`, `monthly-report`,
  which the worker loop does not schedule.
- **P0-4 - timeout root causes.** (a) `kraken_reconciliation.replay_kraken_evidence` and
  its full call graph (including the shared `canonical_trades.py` reconciliation
  functions) now thread one shared database connection through an entire replay batch
  instead of opening a fresh connection per row per helper -- the confirmed dominant cost
  of the Kraken startup reconciliation timeout. (b) `capture_production_broker_snapshots`
  now fetches the Alpaca and Kraken portfolios concurrently (Postgres only, to avoid
  SQLite lock contention in local/test runs) instead of sequentially, and Kraken's
  `get_positions()` no longer makes a redundant second `get_account()` call.
- **P0-5 - push notifications structurally unreachable in production.** Added a
  `push-dispatch` named job (`cli.py:_run_named_job`) and scheduled it every 30s inside
  the always-on worker's own job loop, alongside `managed-exits`/`broker-poll`. Previously
  `dispatch_pending_push_notifications` was only registered inside the API service's
  background-worker set, which `AI_TRADER_DISABLE_API_BACKGROUND_WORKERS=true` (set on
  every Render service) disables in production -- no incident or trade notification the
  system recorded ever actually reached the Founder's phone.

**Testing:** full local suite passes (185 tests, including 5 new tests added for this
work covering P0-2's duplicate-lock behaviour on both the automatic and founder-forced
exit paths, the lock-release-on-definite-rejection retry path, and P0-5's job wiring).
Compiled all modified files with no errors. One unrelated, pre-existing, non-reproducible
flaky test (`test_phase5_production_spine.py`, worker-supervision heartbeat timing) was
observed once in five full-suite runs and confirmed unaffected by this change (same
result on unmodified code; passes in isolation and when bisected).

**Not verified by this work, and explicitly required before Phase 0 is considered
complete per the Founder's completion standard:** hosted-production evidence. This
environment has no Postgres/Docker access, so P0-1's Postgres-specific behaviour and
P0-4's connection-count reduction could not be measured against a real deployment.
Deploy this commit and confirm, from hosted evidence, before proceeding to Seven Pillars
work: (1) `LOGICAL_TRADES`/`LOGICAL_TRADE_EVENTS`/`LOGICAL_TRADE_FILLS` exist on the live
Postgres database; (2) `SCHEDULED_JOB_RUNS` shows no more double-triggering of the six
removed-cron job names; (3) `premarket-equity`, `overnight-crypto`, `evidence-snapshot`,
and Kraken startup reconciliation complete within their 180s boundary across several
consecutive cycles; (4) a test notification reaches the Founder's phone without opening
the app; (5) a deliberately-simulated duplicate exit attempt is refused.

## 2026-07-23 - Worker operational-priority recovery

- Confirmed from hosted job evidence that the final worker was healthy but
  sequential crypto and equity research jobs consumed their three-minute
  limits before broker polling and Founder evidence publication.
- Reordered the worker cycle so managed exits, broker polling, evidence
  snapshots and automatic execution evaluation run before scheduled research.
- Preserved every research, strategy-maturity, portfolio, risk and broker
  execution gate.
- Added a regression test that keeps evidence snapshots out of the deferred
  research queue.

## 2026-07-23 - Render web-service environment compatibility recovery

- Investigated repeated Render failures after both the Dockerfile command and
  explicit `python -m ai_trader.cli serve-api` command produced no open port.
- Root cause: the deployed web service used
  `AI_TRADER_DISABLE_BACKGROUND_WORKERS=true`, but runtime configuration read
  `AI_TRADER_DISABLE_API_BACKGROUND_WORKERS`. The API therefore incorrectly
  assumed it owned schema initialization and background loops.
- Added backward-compatible handling for the legacy environment-variable name.
- Changed API startup ordering so `ThreadingHTTPServer` binds before
  database-backed service initialization.
- Corrected the inconsistent variable name in the production architecture
  audit.
- Added tests proving:
  - the legacy variable safely disables API background workers;
  - the API socket binds before `LocalApiService` initialization.
- Operational action still required: set the canonical
  `AI_TRADER_DISABLE_API_BACKGROUND_WORKERS=true` on the Render web service and
  deploy the resulting commit.

## 2026-07-23 Render API Port-Binding Recovery

- Reviewed the failed `511207c2` Render deployment logs.
- Confirmed Render built the image successfully but detected no open port before
  timing out.
- Traced startup to eager `AuditDatabase` construction in `cli.main()` before
  the `serve-api` branch dispatched to `run_server`.
- Moved audit initialization into only the CLI commands that consume it:
  `propose`, `execute`, `run-once`, and `briefing`.
- Added regression coverage proving `serve-api` and `config` do not initialize
  the audit database before dispatch.
- Restored the intended production boundary: the API binds promptly; the worker
  owns production schema/bootstrap writes and Founder snapshot generation.

## 2026-07-19 Production Evidence Activation Sprint

- Audited the paid Render worker, research ownership, shared database boundaries and six Founder screens before implementation.
- Confirmed the principal production gap: the worker was alive but did not own recurring research, while most useful screen data remained process-local SQLite evidence.
- Added `production_evidence.py` with additive shared tables for research, recommendations, broker snapshots, broker trade/fill observations and learning outcomes.
- Added authenticated bounded Founder evidence and trade APIs.
- Extended the worker with durable crypto research, market-aware equity research and periodic production broker snapshots while preserving idempotent job locking.
- Preserved all Investment Orchestrator, Portfolio Manager, Risk Engine, Alpaca paper and Kraken live safety authorities.
- Reworked mobile startup to hydrate from cached evidence and refresh once from the shared Founder endpoint; removed `/status` as a blocking startup dependency.
- Updated Dashboard, Activity, Recommendations, Portfolio, Market and Learning mappings to use the same persisted production truth.
- Removed long phase-oriented diagnostic cards that obscured operating outcomes.
- Added focused production evidence tests and passed the complete 148-test Python suite, Python compilation, Expo Doctor 17/17 and Android Expo export.
- Recorded the live deployment checklist separately; no hosted order or P&L result is claimed before deployed broker evidence confirms it.
- During hosted verification, found the first worker crypto research cycle failing with Kraken `EQuery:Unknown asset pair`. Corrected autonomous symbol selection to use Founder-approved Kraken pairs and isolated per-pair quote failures so one unsupported pair creates a no-trade record instead of aborting the cycle.
- Proved the shared Founder endpoint against Render: Postgres evidence included research, recommendations, broker snapshots, trade rows and learning evidence. A governed Kraken analysis reviewed nine approved symbols and produced six proposals without submitting an order.
- Found slow broker polling could make an active worker heartbeat appear stale. Added an independent heartbeat pulse, prioritised managed exits and due research ahead of polling, and placed expensive broker polls in durable ten-minute idempotency buckets.

## 2026-07-19 Mobile Autonomous Activity Startup Hardening

- Reviewed installed-app screenshots showing that the Dashboard and Activity screen were still degraded because `/status` and `/autonomous-activity` could exceed the mobile timeout.
- Updated `mobile/App.js` so first paint no longer depends on those heavyweight endpoints.
- Primary refresh now uses lightweight persisted evidence:
  - `/operations-health`
  - `/activity/summary`
  - `/activity/why-no-trade`
  - `/portfolio`
  - `/recommendations`
- Added a mobile-side operations-derived status payload so the Dashboard can show worker, database and job evidence while full broker/status detail is still loading.
- Moved full `/status` and `/autonomous-activity` into background hydration with a longer timeout.
- Preserved truthfulness:
  - no mock activity;
  - no synthetic counts;
  - no false trading claims;
  - unavailable data still explains why it is unavailable.
- Verification:
  - `npx expo-doctor` passed.
  - `git diff --check` passed.
- Known limitation:
  - if the lightweight hosted endpoints themselves become slow, the app will still show a degraded evidence message; the backend endpoint or database query path would then need server-side optimisation.

## 2026-07-18 Sprint 6 - Institutional Production Control Layer

- Reviewed Sprint 6 requirements and current Phase 5, Always-On, Operational Truth, Portfolio Intelligence, Market Intelligence, Experience Engine, API and mobile Dashboard integration points.
- Added `src/ai_trader/sprint6.py`.
- Added Sprint 6 schema tables:
  - `OPERATIONAL_EVENTS`
  - `DECISION_JOURNAL`
  - `STRATEGY_MATURITY_REGISTRY`
  - `STRATEGY_ENTITLEMENT_DECISIONS`
  - `PRODUCTION_RISK_SENTINEL_DECISIONS`
  - `KILL_SWITCH_STATE`
  - `SPRINT6_WORKFLOW_OUTBOX`
  - `BROKER_EVENT_MAPPINGS`
  - `INCIDENT_LIFECYCLE`
  - `FOUNDER_OPERATIONAL_REPORTS`
- Seeded a conservative default strategy registry entry:
  - strategy ID: `current_recommendation_process`
  - stage: `Paper`
  - permitted modes: `shadow`, `paper`, `manual`
  - not permitted by default: `micro_live`, `production`
- Wired mandatory Sprint 6 pre-execution decision packets into:
  - `approve_and_execute`
  - `auto_execute_recommendations`
- The pre-execution packet records:
  - Portfolio Manager decision
  - strategy entitlement decision
  - Production Risk Sentinel decision
  - strongest argument for
  - strongest argument against
  - market data quality label
  - final eligibility
- Broker polling now:
  - records broker polling incidents on failure;
  - normalizes broker events into `BROKER_EVENT_MAPPINGS`;
  - passes normalized rows into canonical reconciliation;
  - queues terminal rows into the closed-loop learning outbox idempotently.
- Research cycles now record Sprint 6 operational events.
- Added API endpoints:
  - `GET /sprint6-status`
  - `GET /operational-events`
  - `GET /decision-journal`
  - `POST /generate-operational-report`
- Added `sprint6_status` to `/status`.
- Added the mobile Dashboard `Sprint 6 Production Control` card.
- Added focused tests in `tests/test_sprint6_institutional_spine.py`.
- Created Sprint 6 architecture documents:
  - `architecture/SPRINT_6_IMPLEMENTATION_REPORT.md`
  - `architecture/INSTITUTIONAL_PRODUCTION_ARCHITECTURE.md`
  - `architecture/POSTGRES_RUNTIME_MIGRATION_REPORT.md`
  - `architecture/BROKER_RECONCILIATION_STANDARD.md`
  - `architecture/ALPACA_RECONCILIATION_CONTRACT.md`
  - `architecture/KRAKEN_RECONCILIATION_CONTRACT.md`
  - `architecture/STRATEGY_MATURITY_AND_ENTITLEMENT.md`
  - `architecture/PRODUCTION_RISK_SENTINEL.md`
  - `architecture/MARKET_DATA_AND_RESEARCH_FRESHNESS_STANDARD.md`
  - `architecture/AUTONOMOUS_LEARNING_WORKFLOW.md`
  - `architecture/RENDER_PRODUCTION_VERIFICATION.md`
  - `architecture/AUTONOMOUS_QUALIFICATION_REPORT.md`
  - `architecture/NEXT_STAGE_RECOMMENDATIONS.md`
  - `architecture/FOUNDER_BRIEFING_SPRINT_6.md`
- Verification completed so far:
  - `python -m compileall src` passed.
  - `python -m unittest tests.test_sprint6_institutional_spine` passed.
  - `python -m unittest discover -s tests` passed.
  - `npx expo-doctor` passed.
- Safety note: Sprint 6 does not increase capital, promote strategies, bypass the Investment Orchestrator, bypass the Risk Engine, weaken Kraken controls, or allow Ask AI Trader to trade.

## 2026-07-18 Phase 5 - Autonomous Production Spine and Closed-Loop Learning Foundation

- Reviewed the current governance, architecture, implementation history, Operational Truth, Experience Engine, Portfolio Intelligence, Market Intelligence, and Always-On Operations implementation before changing code.
- Added `src/ai_trader/production_spine.py`.
- Added Phase 5 schema tables:
  - `PRODUCTION_SPINE_SNAPSHOTS`
  - `WORKER_SUPERVISION_RUNS`
  - `CANONICAL_RECONCILIATION_CASES`
  - `CLOSED_LOOP_LEARNING_RUNS`
  - `PORTFOLIO_MANAGER_DECISIONS`
  - `MARKET_DATA_GATEWAY_RUNS`
  - `STRATEGY_PROMOTION_DECISIONS`
- Added deterministic functions for:
  - production database spine readiness;
  - worker supervision and stale-worker incident creation;
  - idempotent broker event reconciliation into logical trades;
  - idempotent closed-loop learning;
  - Portfolio Manager approve/approve-smaller/wait/reject/manual-review decisions;
  - Market Data Gateway quality blocking;
  - strategy promotion and demotion evidence gates.
- Added API support:
  - `GET /phase5-status`
  - `phase5_status` inside `GET /status`
- Added the mobile Dashboard `Autonomous Production Spine` card.
- Added focused tests in `tests/test_phase5_production_spine.py`.
- Created Phase 5 architecture documents:
  - `architecture/PHASE_5_IMPLEMENTATION_REPORT.md`
  - `architecture/AUTONOMOUS_PRODUCTION_SPINE.md`
  - `architecture/CANONICAL_RECONCILIATION_DESIGN.md`
  - `architecture/CLOSED_LOOP_LEARNING_ARCHITECTURE.md`
  - `architecture/DATABASE_ARCHITECTURE.md`
  - `architecture/TEST_RESULTS.md`
  - `architecture/KNOWN_LIMITATIONS.md`
  - `architecture/NEXT_PHASE_RECOMMENDATIONS.md`
  - `architecture/FOUNDER_BRIEFING.md`
- Verification:
  - `python -m compileall src` passed.
  - `python -m unittest tests.test_phase5_production_spine` passed.
  - `python -m unittest tests.test_always_on_operations` passed.
- Safety note: this phase does not enable trading, weaken guardrails, change broker permissions, or silently promote strategies. It adds evidence gates and readiness visibility.

## 2026-07-02

- Reviewed repository contents.
- No existing project governance documents were present.
- Created governance baseline before implementation:
  - Architecture Design Document
  - Implementation Plan
  - Decision Register
  - Implementation Log
- Began Version 1 implementation using a compact Python command-line architecture.
- Implemented shared trade proposal models, guardrail validation, SQLite audit storage, Alpaca paper client, optional OpenAI proposal analyzer, AI Trading Agent, Execution Engine, CLI, daily briefing generator, and unit tests.
- Added local mock end-to-end demonstration path using `--demo`.
- Attempted to run `python -m unittest discover -s tests`, but the local Windows Python shim failed to launch with: "A specified logon session does not exist. It may already have been terminated." No callable `py`, `pip`, or `uv` runtime was available in this environment.
- Ran `git diff --check` successfully.
- Added `governance/TRADING_LOG.md` as the append-only human-readable trading ledger.
- Updated audit writes so trade proposal and execution lifecycle events append to the trading log when `AI_TRADER_TRADING_LOG_PATH` is configured.

## 2026-07-02 Validation Sprint

- Installed Python 3.12.10 because the machine only exposed a broken Microsoft Store Python launcher shim.
- Installed missing `tzdata==2026.2` dependency required for `zoneinfo` on Windows.
- Added `tzdata>=2026.2` to `pyproject.toml`.
- Ran unit tests; initial run failed because SQLite database files were still held open on Windows during temporary directory cleanup.
- Fixed `AuditDatabase` to explicitly close SQLite connections.
- Re-ran unit tests successfully: 4 tests passed.
- Verified `.env` was present but not loaded by the application.
- Added standard-library `.env` loading in `src/ai_trader/config.py`.
- Verified safe config output reported Alpaca credentials present.
- Connected to Alpaca Paper Trading successfully.
- Retrieved account information successfully: status `ACTIVE`, currency `USD`, equity `100000`, buying power `400000`.
- Retrieved current positions successfully: 0 open positions.
- Attempted to generate one real AI trade proposal.
- Validation stopped at proposal generation because the OpenAI Responses API returned HTTP 401 Unauthorized for the configured `OPENAI_API_KEY`.
- Created validation report: `governance/VALIDATION_REPORT_2026-07-02.md`.
- Updated project status: `STATUS.md`.

## 2026-07-02 Validation Sprint Resume

- Confirmed updated OpenAI API key worked against the OpenAI Responses API using `OPENAI_MODEL=gpt-4.1-mini`.
- Resumed validation from step 9 instead of rerunning completed setup, unit, config, and Alpaca connectivity checks.
- First resumed AI proposal was generated but correctly rejected by guardrails because `confidence_score` was below `MIN_CONFIDENCE_SCORE=0.85` and `risk_percentage` was returned as `1.0` instead of decimal `0.01`.
- Root cause: the OpenAI proposal prompt did not include the configured guardrail thresholds or the decimal risk contract.
- Fixed only that issue by passing `GuardrailConfig` into `OpenAIProposalAnalyzer` and adding the configured confidence, risk, open-position, and stop/take-profit constraints to the prompt.
- Re-ran the failed step onward and generated a valid AAPL proposal:
  - Proposal ID: `581de766-62ff-4d16-9e7e-6b27407c29b0`
  - Entry: `298.96`
  - Stop loss: `296.96`
  - Take profit: `305.96`
  - Position size: `333`
  - Risk percentage: `0.01`
  - Confidence score: `0.87`
- Execution Engine independently validated the proposal successfully.
- Submitted an Alpaca Paper Trading bracket order successfully.
- Confirmed Alpaca parent order `94de407a-8a6d-42ab-a991-de938ef27e6e` appeared and filled; bracket exit orders were present.
- Confirmed SQLite audit rows for `agent_proposal` and `execution_approved`.
- Confirmed `governance/TRADING_LOG.md` contains the successful proposal and execution entries.
- Generated Founder Brief: `data/founder_briefing_2026-07-02.md`.
- Updated project status and validation report with final passed results.

## 2026-07-02 Sprint 2 - Investment Intelligence Engine

- Treated Version 1.0 trading architecture as frozen.
- Did not redesign the AI Trading Agent.
- Did not redesign the Execution Engine.
- Did not modify the trading pipeline or Trading Journal.
- Continued using the existing local SQLite master database.
- Added `src/ai_trader/intelligence.py` with schema management, initial seeding, append-only daily refresh, and report generation.
- Added `src/ai_trader/intelligence_data.py` with an initial curated watchlist and market themes based on publicly available company/theme information.
- Created SQLite tables:
  - `COMPANY_MASTER`
  - `COMPANY_FINANCIALS`
  - `COMPANY_DAILY_UPDATES`
  - `INVESTMENT_WATCHLIST`
  - `MARKET_THEMES`
- Seeded 31 watchlist companies across precious metals, gold, silver, copper, mining, infrastructure, construction, utilities, clean energy, healthcare, airlines, and sports.
- Prioritised the United Kingdom, Europe, Asia, and Africa; avoided North American companies in the initial seed.
- Seeded 10 market themes:
  - Gold
  - Silver
  - Copper
  - Rare Earths
  - Construction
  - Clean Energy
  - Healthcare
  - Airlines
  - Infrastructure
  - Utilities
- Left unverified financial metrics as `NULL` placeholders rather than fabricating data.
- Added CLI commands:
  - `intelligence-init`
  - `intelligence-refresh`
  - `intelligence-report`
- Added local scheduled refresh helpers:
  - `scripts/run_daily_intelligence_refresh.ps1`
  - `scripts/register_daily_intelligence_refresh.ps1`
- Added schema documentation: `governance/INVESTMENT_INTELLIGENCE_SCHEMA.md`.
- Added Knowledge Engine Report: `governance/KNOWLEDGE_ENGINE_REPORT.md`.
- Generated data report: `data/INVESTMENT_INTELLIGENCE_ENGINE_REPORT.md`.
- Updated `README.md` with a short Investment Intelligence Engine section.
- Updated `STATUS.md` with Sprint 2 results.
- Added intelligence tests for initial seeding and append-only refresh behavior.
- Ran unit tests successfully: 6 tests passed.

## 2026-07-02 Sprint 3 - Mobile App and Benchmark Intelligence

- Treated Version 1.0 trading architecture, Execution Engine, guardrails, and SQLite storage as frozen.
- Added benchmark intelligence schema management in `src/ai_trader/benchmark.py`.
- Added public-information-only benchmark seed data in `src/ai_trader/benchmark_data.py`.
- Created SQLite tables:
  - `BENCHMARK_TRADERS`
  - `BENCHMARK_DAILY_RESEARCH`
- Left unavailable performance notes, drawdown notes, and consistency scores as `NULL`.
- Added benchmark schema documentation: `governance/BENCHMARK_INTELLIGENCE_SCHEMA.md`.
- Added benchmark initialization command: `benchmark-init`.
- Added small local HTTP API in `src/ai_trader/api.py`.
- Added API command: `serve-api`.
- Added local engine control state table for pause/resume/stop commands.
- Added guarded `approve-and-execute` endpoint that uses stored SQLite proposals and the existing Execution Engine.
- Added Expo app under `mobile/` with exactly three screens:
  - Trading Command Centre
  - AI Recommendations
  - Market Intelligence
- Added API/mobile run instructions to `README.md`.
- Added local run helpers: `scripts/start_local_api.ps1` and `scripts/start_mobile_app.ps1`.
- Added tests for benchmark seeding and API missing-data behavior.
- Ran unit tests successfully with installed Python 3.12 interpreter: 8 tests passed.
- Ran `benchmark-init --report`, seeding 4 monitored benchmark traders and 4 append-only research rows.
- Smoke-checked the local API service object: `/status` returned `running` and `/benchmark-traders` returned 4 rows.

## 2026-07-02 Sprint 3.1 - Developer Experience

- Investigated the broken `python` command.
- Confirmed `python` resolved to the Windows Store app execution alias at `C:\Users\t_jeh\AppData\Local\Microsoft\WindowsApps\python.exe`.
- Confirmed `py` was not available on PATH.
- Confirmed the real working interpreter is Python 3.12.10 at `C:\Users\t_jeh\AppData\Local\Programs\Python\Python312\python.exe`.
- Created local `.venv`.
- Installed the project into `.venv` with editable packaging and `tzdata`.
- Added VS Code workspace settings to select `.venv\Scripts\python.exe` automatically.
- Added VS Code tasks for project startup and Python tests.
- Added `start_project.ps1` for one-command startup.
- Updated `scripts/start_local_api.ps1` to use `.venv` and display API/dashboard URLs.
- Updated `scripts/start_mobile_app.ps1` to check Node/npm, install missing dependencies, check API availability, and start Expo with QR code output.
- Added `scripts/browse_database.ps1`.
- Added `src/ai_trader/db_browser.py`, a read-only local browser-based SQLite viewer with table listing, search, sorting, and record viewing.
- Added API Developer Dashboard endpoints:
  - `/developer-dashboard`
  - `/developer-status`
- Added root `developer_dashboard.html` launcher.
- Added `mobile/node_modules/` to `.gitignore`.
- Verified `.venv\Scripts\python.exe --version`: Python 3.12.10.
- Verified activated venv makes plain `python --version` return Python 3.12.10.
- Added developer experience tests for dashboard status and read-only database browsing.
- Ran tests in `.venv`: 10/10 passing.
- Verified CLI config runs in `.venv`.
- Verified Developer Dashboard status generation reports Python as Healthy.
- Verified read-only SQLite browser can list 11 tables.

## 2026-07-02 Hosted Backend Path

- Kept trading engine, execution engine, knowledge engine, and mobile UI logic intact.
- Added optional API-token authorization to the Python API for hosted deployment.
- Added unauthenticated `/healthz` for cloud health checks.
- Added Docker packaging for the existing Python backend.
- Added Render blueprint with persistent `/data` disk for SQLite.
- Added `cloud.env.example` for hosted environment variables.
- Added `scripts/test_hosted_api.ps1` to verify hosted API status, Paper mode, watchlist, themes, and benchmark trader counts.
- Updated the mobile app to send `Authorization: Bearer <token>` when `EXPO_PUBLIC_AI_TRADER_API_TOKEN` is configured.
- Added `hosted-preview` EAS build profile.
- Updated README and STATUS with hosted backend deployment instructions.
- Added tests for `/healthz` and API token authorization.
- Ran tests in `.venv`: 12/12 passing.
- Verified local token-auth smoke test: health check public, protected API rejects missing token, bearer token succeeds.
- Docker CLI was not available locally, so container build verification remains for the cloud host or a machine with Docker installed.

## 2026-07-02 Sprint 3.2 - Mobile Trading Usability

- Kept the trading engine, execution engine, knowledge engine, SQLite storage, and three-screen mobile structure intact.
- Added recommendation freshness metadata to the API:
  - `created_at`
  - `expires_at`
  - `freshness_status`
  - `freshness_note`
- Added expiry rules:
  - 85%+ confidence: 4-hour trade idea lifetime.
  - 75%-84% confidence: 12-hour trade idea lifetime.
  - Lower confidence: 24-hour trade idea lifetime.
- Blocked manual execution when a recommendation has expired.
- Added paper-only auto execution endpoint: `POST /auto-execute-recommendations`.
- Auto execution only considers recommendations at or above 85% confidence and still sends every proposal through the existing Execution Engine guardrails.
- Added `POST /start-trading` as the simpler mobile control while keeping existing pause/resume endpoints for compatibility.
- Enriched `/status` with recent transactions and recommendation summary counts.
- Enriched `/portfolio` with recent Alpaca orders and fill activities when Alpaca credentials are configured.
- Updated mobile Command Centre:
  - Start Trading and Stop Trading controls.
  - Recent Transactions section.
  - Active/expired recommendation counts.
  - Auto Trade Mode.
- Updated mobile Recommendations:
  - Refresh button.
  - Run New Analysis button.
  - Auto Execute 85%+ button.
  - Freshness, generated time, expiry time, and auto eligibility display.
  - Expired recommendations show as blocked.
- Updated mobile Market Intelligence to show theme definitions, key drivers, and key risks from SQLite.
- Added tests for recommendation freshness metadata and expired-recommendation execution blocking.
- Ran tests in `.venv`: 14/14 passing.

## 2026-07-02 Sprint 3.2 - EAS OTA Update

- Ran `npx eas update --branch preview --message "Sprint 3.2 mobile trading usability"`.
- EAS installed and configured `expo-updates`.
- EAS configured `updates.url` to `https://u.expo.dev/58ca35af-2cf4-44a0-8da4-7f02563b635f`.
- EAS configured `runtimeVersion` with the `appVersion` policy.
- Published update group `0727fd0a-4216-413c-affa-5c712cbc1155`.
- Published Android update `019f2473-739d-78e5-849e-99092758dd78`.
- EAS dashboard: `https://expo.dev/accounts/nexuspay/projects/ai-trader-mobile/updates/0727fd0a-4216-413c-affa-5c712cbc1155`.
- Added `mobile/dist/` to `.gitignore` because EAS Update creates it during export.
- Verified Expo Doctor after the OTA configuration: 17/17 checks passed.
- Note: the previously installed APK may not receive OTA updates because `expo-updates` was configured during this publish. Builds made after this configuration are eligible for EAS Updates.
- Added `channel: preview` to the EAS `preview` and `hosted-preview` build profiles.
- Built a fresh Android preview APK after OTA channel configuration.
- Build ID: `d5ff21b3-6685-4940-a2d4-550cd0d9e984`.
- APK: `https://expo.dev/artifacts/eas/c3aEW5gWWhVHVim0Mk2fwTGnRl7aCKosQkpYnC6n9VQ.apk`.

## 2026-07-03 Mobile UX Follow-Up

- Confirmed the installed APK had the new UI but was calling a stale local API process.
- Restarted the local API so `/start-trading` and `/auto-execute-recommendations` are available.
- Verified `/start-trading` returns `running`.
- Verified `/auto-execute-recommendations` no longer returns `not_found`.
- Confirmed `0.87` confidence means 87%; auto-trade was skipped because execution guardrails did not pass, not because of decimal confidence format.
- Added `auto_trade_reason` to recommendation API rows.
- Updated mobile cards to show:
  - readable generated/expiry timestamps,
  - confidence as percentages,
  - guardrail pass status,
  - auto-trade eligibility reason.
- Added pull-to-refresh to the main scroll view so each screen can be refreshed by dragging down.
- Improved recent transaction wording for non-technical users.
- Added fallback from `/start-trading` to `/resume-trading` for older API processes.
- Published EAS OTA update:
  - Branch: `preview`.
  - Update group ID: `c4e78a76-6233-48aa-a2ee-85ce3223007e`.
  - Android update ID: `019f2657-bc70-7c6f-9e33-91ef6e217fc1`.
  - Dashboard: `https://expo.dev/accounts/nexuspay/projects/ai-trader-mobile/updates/c4e78a76-6233-48aa-a2ee-85ce3223007e`.
- Verification:
  - Python tests: 14/14 passing.
  - Python compile check passed.
  - Expo Doctor: 17/17 checks passed.

## 2026-07-03 Hosted APK Build

- Separated `hosted-preview` from the laptop `preview` OTA channel.
- Removed the placeholder public API token from the hosted mobile build profile.
- Built hosted Android APK with initial backend URL `https://ai-trader-api.onrender.com`.
- Build ID: `7e6b53a3-d492-4594-af36-4e56199878d4`.
- APK: `https://expo.dev/artifacts/eas/s2G1DWe4aWyNiBCH7S1bJgXYmhoq8f8gSE3D6UQfe5U.apk`.
- Published hosted OTA update to branch `hosted-preview`.
- Hosted OTA update group ID: `f9a4c794-8305-47d2-83a1-99fb5b777057`.
- Hosted Android update ID: `019f2669-3a99-765d-99f1-d747aff4f9db`.
- User created Render service at `https://trader-no0f.onrender.com`.
- Updated hosted mobile build config to use `https://trader-no0f.onrender.com`.
- Verified Render `/healthz`, `/status`, `/portfolio`, `/recommendations`, and `/intelligence/themes`.
- Published hosted OTA update to point the installed hosted app at `https://trader-no0f.onrender.com`.
- Hosted OTA update group ID: `bc319f3f-0bba-48fd-992a-30601f92c2d5`.
- Hosted Android update ID: `019f27ac-1393-79d5-b822-fa82ee3cfe37`.
- Render recommendations currently return an empty list because the cloud SQLite database has no generated proposals yet.

## 2026-07-03 Remove Laptop API URL From Preview Channels

- Updated `mobile/eas.json` so the `preview` build profile also uses `https://trader-no0f.onrender.com`.
- Updated mobile error copy from "Local API unavailable" to "Backend unavailable" and included the active API URL in the alert.
- Updated the app header fallback text to show the backend host.
- Published OTA to `preview`:
  - Update group ID: `dd05b9df-40bd-43c9-99eb-7dd3d129e24b`.
  - Android update ID: `019f27b7-de37-7fb0-97b6-d397fe7d2058`.
- Published OTA to `hosted-preview`:
  - Update group ID: `895a6212-1e33-404f-8437-61ddf553adab`.
  - Android update ID: `019f27b8-c67a-797e-8feb-19d810b71283`.
- Verified `https://trader-no0f.onrender.com/healthz` returned 200 before publishing.

## 2026-07-03 Hosted Analysis and Activity Follow-Up

- Fixed mobile JSON parsing so empty or non-JSON backend responses produce a readable app error instead of `JSON Parse error`.
- Changed mobile Run Analysis to request the 30-company watchlist scan.
- Added clearer mobile messaging when analysis completes but no safe recommendations are generated.
- Added Alpaca broker orders/fills from `/portfolio` into the mobile Command Centre Recent Transactions section.
- Changed backend `/run-analysis` to scan symbols independently so one broker-rejected symbol does not fail the full analysis.
- Added `skipped_symbols` to the analysis response.
- Added `analysis_completed` events so the app can show that an analysis ran even if no recommendation was created.
- Verified Render `/run-analysis` with `AAPL` succeeds.
- Verified Render `/run-analysis` with `AAPL` and `NOVO-B` returns 200 and lists `NOVO-B` in `skipped_symbols`.
- Published OTA to `preview`: `da0f2e4d-8ecc-4fff-b026-1693ca3ca139`.
- Published OTA to `hosted-preview`: `b6ae021d-9936-4003-972f-b719f79fb4b1`.

## 2026-07-03 Guardrail Positives Follow-Up

- Added a backend `guardrail_checks` checklist to each recommendation so the app can show passed checks and failed checks from the same validation result.
- Added `guardrail_passes` to recommendation API rows for a simple positive guardrail summary.
- Updated mobile recommendation cards to show:
  - overall guardrail result,
  - passed guardrails,
  - failed guardrails.
- Kept the trading engine, execution engine, guardrail logic, and SQLite storage unchanged.
- Verified Python tests: 16/16 passing.
- Published OTA to `preview`: `bd26298e-5373-4c20-8319-b18f52135adc`.
- Published OTA to `hosted-preview`: `2b920796-6648-4c8f-acb7-e2088213c4f0`.

## 2026-07-03 Recommendation Persistence Follow-Up

- Kept the trading engine, execution engine, guardrail logic, and SQLite storage unchanged.
- Changed the recommendation API to return a larger saved SQLite recommendation history.
- Sorted saved recommendations by highest confidence first, then newest.
- Improved auto-execute responses with per-symbol skipped reasons so high-confidence but guardrail-failed cards are understandable.
- Updated Market Intelligence to load monitored companies from `/intelligence/companies` and show company names alongside theme definitions.
- Added tests for saved recommendation ordering and auto-execute skip explanations.
- Verified Python tests: 18/18 passing.
- Verified Expo Doctor: 17/17 passing.
- Published OTA to `preview`: `55d45b77-db90-4f57-b411-38d067ef6382`.
- Published OTA to `hosted-preview`: `93fa34c0-db77-4e8b-a198-6e85ac2e393f`.

## 2026-07-03 Unsupported Broker Symbol Follow-Up

- Fixed Run Analysis failure caused by Alpaca returning `asset not found` for an unsupported watchlist symbol.
- Updated the Alpaca data client to return empty market/news payloads for missing assets instead of raising a fatal error.
- Updated the AI Trading Agent to record a no-trade event when no latest market bar is available for a symbol.
- Updated OpenAI proposal parsing so empty JSON objects are treated as no-trade results instead of constructor errors.
- Kept the trading engine, execution engine, guardrails, mobile app structure, and SQLite storage unchanged.
- Verified Python tests: 21/21 passing.
- Verified Expo Doctor: 17/17 passing.

## 2026-07-03 Sprint 4 Investment Orchestrator

- Implemented `AutoTradeConfig` and added Sprint 4 environment variables.
- Added broker adapter interface in `src/ai_trader/broker_adapters.py`.
- Wrapped existing Alpaca paper integration as `AlpacaBrokerAdapter`.
- Added placeholder `InteractiveBrokersAdapter`, `SaxoAdapter`, and `KrakenAdapter` with not-configured responses only.
- Implemented `InvestmentOrchestrator` in `src/ai_trader/orchestrator.py`.
- Added append-only SQLite tables:
  - `ORCHESTRATOR_DECISIONS`
  - `AUTO_TRADE_EVENTS`
  - `DAILY_BRIEFS`
- Routed API auto-execution through the Investment Orchestrator.
- Kept manual approve-and-execute path on the existing Execution Engine.
- Added `AUTO_PAPER_TRADING=false` default behavior so recommendations require manual approval unless explicitly enabled.
- Added morning and evening brief generation with Markdown output and SQLite persistence.
- Added `ResearchScheduler` and `research-once` CLI command for safe local or Render scheduled research.
- Wired the Render Docker web process to start hourly background research when `RESEARCH_SCHEDULER_ENABLED=true`.
- Updated `render.yaml` with Sprint 4 auto-trade and scheduler environment variables while keeping `AUTO_PAPER_TRADING=false`.
- Updated `cloud.env.example` and recreated `.env.example` with Sprint 4 variables.
- Updated only the three existing mobile screens:
  - Trading Command Centre
  - AI Recommendations
  - Market Intelligence
- Added tests for orchestrator routing, Alpaca adapter compatibility, market closed rejection, unavailable asset rejection, confidence rejection, missing stop loss rejection, max stop-loss rejection, auto mode enabled/disabled, morning brief generation, evening brief generation, and scheduler cycle execution.
- Verified Python tests: 33/33 passing.
- Committed Sprint 4 Render-ready changes as `cfcd023`.
- Pushed `master` to `origin` so Render can auto-deploy if auto-deploy is enabled.
- Attempted hosted health checks after push; `https://trader-no0f.onrender.com` was not accepting connections from this environment at that moment.

## 2026-07-04 Sprint 5 Operational Clarity and Crypto Preparation

- Added `src/ai_trader/operational.py` for robust score parsing, portfolio snapshots, research runs, and crypto universe schema.
- Fixed qualitative values such as `Good`, `Medium`, `High`, `Low`, `Cautious`, and `Positive` so recommendations no longer crash on numeric conversion.
- Added `PORTFOLIO_SNAPSHOTS`, `RESEARCH_RUNS`, and `CRYPTO_ASSET_MASTER` tables.
- Portfolio dashboard refresh now records an Alpaca snapshot and returns explicit `Not available - reason` values when data cannot be calculated.
- Research analysis now records auditable research run rows.
- Benchmark daily brief now falls back to the latest seeded benchmark research with an explicit reason when today's data is unavailable.
- Updated Command screen with executive summary and exchange selector for All, Alpaca, Kraken, and Coinbase.
- Renamed visible trade history to exchange-specific wording such as Alpaca Trade History.
- Added Kraken and Coinbase adapter preparation with trading disabled by default.
- Added crypto-specific auto-trade guardrail environment variables.
- Updated Render and cloud environment documentation for Sprint 5.
- Added Sprint 5 tests for qualitative parsing, P&L unavailable reasons, snapshots, research run tracking, benchmark fallback, exchange selector not-configured states, Kraken/Coinbase not configured, crypto universe table creation, and safe crypto auto-trade rejection.
- Verified Python tests: 42/42 passing.

## 2026-07-04 Foundation Sprint - Autonomous Investment Platform

- Reviewed governance documents, `STATUS.md`, `IMPLEMENTATION_LOG.md`, `README.md`, Render configuration, broker implementations, Investment Intelligence Engine, and mobile app.
- Created Founder-governed constitutional documents:
  - `INVESTMENT_POLICY_STATEMENT.md`
  - `RISK_MANAGEMENT_POLICY.md`
  - `BROKER_EXECUTION_POLICY.md`
  - `AI_LEARNING_POLICY.md`
  - `INVESTMENT_UNIVERSE.md`
- Added `src/ai_trader/foundation.py`.
- Added configurable SQLite policy tables:
  - `INVESTMENT_POLICIES`
  - `RISK_POLICIES`
  - `BROKER_POLICIES`
  - `LEARNING_POLICIES`
- Added permanent decision and audit tables:
  - `CAPITAL_ALLOCATION_HISTORY`
  - `DUE_DILIGENCE_ASSESSMENTS`
  - `INVESTMENT_SCORES`
  - `BROKER_DECISIONS`
  - `EXECUTION_DECISIONS`
- Added crypto knowledge tables:
  - `CRYPTO_MASTER`
  - `CRYPTO_MARKET_DATA`
  - `CRYPTO_DAILY_UPDATES`
  - `CRYPTO_PROJECT_ANALYSIS`
  - `CRYPTO_TOKENOMICS`
  - `CRYPTO_ONCHAIN_METRICS`
  - `CRYPTO_SENTIMENT`
  - `CRYPTO_RISK`
  - `CRYPTO_NEWS`
  - `CRYPTO_BENCHMARK_ALIGNMENT`
  - `CRYPTO_TRADING_HISTORY`
- Updated the Investment Orchestrator so autonomous execution now validates governance policy, due diligence, investment scores, investment universe, broker state, market state, risk, and capital allocation.
- Updated API recommendations and status payloads with due diligence status, crypto projects reviewed, trading policy snapshot, and structured investment score fields.
- Updated mobile app without adding screens:
  - Command screen broker panels for Alpaca and Kraken.
  - Recommendation cards show due diligence and Investment Score fields.
  - Intelligence screen shows Alpaca and Kraken intelligence sections.
- Updated Kraken adapter to support Render `KRAKEN_PRIVATE_KEY` while preserving `KRAKEN_API_SECRET` compatibility and disabled-by-default trading.
- Updated `.env.example`, `cloud.env.example`, and `render.yaml`.
- Added foundation tests for policy seeding, due diligence, investment scores, capital allocation, orchestrator decision recording, emergency shutdown, and Kraken credential naming.
- Verified Python tests: 48/48 passing.

## 2026-07-04 Multi-Broker Autonomous Platform Sprint

- Added `src/ai_trader/multi_broker.py`.
- Added broker-specific auto-trading settings with SQLite persistence.
- Added broker runtime state so every broker can report connection, research, due diligence, current asset, current stage, queue, freshness, and last trade independently.
- Added broker trade history persistence for accepted, pending, filled, cancelled, closed, and other broker statuses.
- Added notification event queue for research, broker control, trade submission, and future push notification delivery.
- Added recommendation set persistence so the latest analysis run remains auditable and can be made active.
- Added crypto research score table for technical trend, momentum, RSI, moving average position, MACD, volume trend, volatility, liquidity, market structure, sentiment, news, on-chain activity, risk, due diligence, and confidence.
- Added broker-specific environment flags:
  - `ALPACA_AUTO_TRADING`
  - `KRAKEN_AUTO_TRADING`
  - `COINBASE_AUTO_TRADING`
  - `BINANCE_AUTO_TRADING`
  - `IBKR_AUTO_TRADING`
- Updated the API:
  - `GET /status` now includes broker panels, continuous research state, and broker-specific auto-trading state.
  - `GET /brokers` returns broker panels.
  - `POST /broker-auto-trading` enables or disables new autonomous entries for one broker only.
  - `POST /auto-execute-recommendations` no longer reports `AUTO_PAPER_TRADING is false`; it reports broker-specific enablement.
- Completed Kraken read adapter surface:
  - Authenticated balance check.
  - Holdings from balances.
  - Open orders.
  - Closed orders.
  - Trade history.
  - Current prices through public ticker helper.
  - Authentication failures are returned with reasons when credentials exist.
- Kept Kraken order submission disabled pending final Founder-approved execution method.
- Updated mobile app without adding screens:
  - Broker panels are generated from backend brokers.
  - Enable/Disable Auto Trading buttons control one broker only.
  - Recommendations are grouped by broker, collapsed by default, sorted by confidence, and filterable.
  - Intelligence displays broader continuous research state.
- Updated `.env.example`, `cloud.env.example`, `render.yaml`, `README.md`, `STATUS.md`, and `governance/FOUNDER_BRIEF.md`.
- Added tests for independent broker auto-trading, API broker control, recommendation set persistence, crypto research score storage, and legacy auto flag compatibility.
- Verified Python tests: 53/53 passing.

## 2026-07-04 Kraken Controlled Live Micro-Trading Seatbelts

- Added explicit live Kraken approval switches:
  - `KRAKEN_LIVE_TRADING_APPROVED`
  - `KRAKEN_SUBMIT_REAL_ORDERS`
  - `KRAKEN_MAX_ORDER_GBP`
  - `KRAKEN_MIN_ORDER_GBP`
  - `KRAKEN_MAX_OPEN_TRADES`
  - `KRAKEN_ALLOWED_PAIRS`
- Implemented Kraken `AddOrder` market order submission behind broker-specific auto trading, live approval, and hard mechanical checks.
- Added duplicate order intent locks before broker submission.
- Added managed exit records after accepted Kraken entries.
- Added protective exit monitoring through `POST /monitor-managed-exits`.
- Added SQLite tables:
  - `ORDER_INTENT_LOCKS`
  - `MANAGED_TRADE_EXITS`
  - `MECHANICAL_SEATBELT_EVENTS`
- Added queued notifications for trade accepted, stop loss, take profit, and exit submission.
- Added mobile recommendation cache using AsyncStorage so recommendation history survives app restarts and backend/network gaps.
- Added Intelligence-to-Recommendations linking: monitored company names link to matching recommendation cards and open the selected card.
- Added tests for Kraken live micro-order rejection and validation-mode submission.
- Verified Python tests: 55/55 passing.

## 2026-07-07 Autonomous Trading Readiness Sprint

Implemented the Go-Live Readiness Review's findings. Full detail in `STATUS.md`; summary below.

- **Broker execution is now orchestrator-only.** `approve_and_execute` (manual approval) now
  calls `InvestmentOrchestrator.evaluate_recommendation` instead of the legacy
  `ExecutionEngine` directly - it now gets due diligence, investment scoring, capital
  allocation, and the `ORDER_INTENT_LOCKS` duplicate-order lock for free.
- **Kraken safety defaults fixed.** `KRAKEN_SUBMIT_REAL_ORDERS` now defaults to validate/
  dry-run mode when unset (previously defaulted to submitting real orders).
- **Risk limits actually enforced.** Daily/weekly/monthly loss limits, a new max-drawdown
  check, and portfolio-level exposure/concentration limits are now checked against real
  `PORTFOLIO_SNAPSHOTS` history inside `InvestmentOrchestrator.evaluate_recommendation`
  (previously the daily-loss check was fed a hardcoded `0.0` and the exposure/drawdown
  checks did not exist).
- **Continuous monitoring, not manual-only.** Kraken's stop-loss/take-profit monitor and a
  new broker order/fill poller now run on background `IntervalWorker` loops (60s cadence)
  started from `run_server`, independent of whether research scheduling is enabled.
  Previously both only ran if something manually called `/monitor-managed-exits`.
- **Resilience.** `ResearchScheduler` and the new `IntervalWorker` loops catch and log any
  exception and keep running (a `research_failure`/`broker_failure` notification is fired),
  instead of the background thread dying silently. Added a startup reconciliation pass
  (`reconcile_on_startup`) that flags stuck order-intent locks left over from a prior crash.
- **Trailing stops.** Added a governed `trailing_stop_pct` risk policy and high/low
  water-mark tracking on `MANAGED_TRADE_EXITS`; `monitor_managed_exits` ratchets the
  effective stop as price moves favorably when enabled.
- **Due diligence is evidence-based, not floored.** Removed the hardcoded 0.70/0.75 score
  floors in `calculate_investment_score`; macro/behavioural factors and due-diligence
  statuses now reflect real backing data (a matching market theme, a same-day benchmark
  trader research entry, or a crypto research score) or are honestly marked
  `insufficient_data`/scored `0.0`.
- **Live crypto knowledge engine.** `seed_crypto_universe` now fetches CoinGecko's actual
  market-cap/AI/privacy-coin category endpoints (previously keyword-matched a single
  market-cap page) and populates `CRYPTO_MASTER` (previously never populated, which
  silently blocked every crypto proposal) and `CRYPTO_MARKET_DATA`, with genuine
  technical/momentum/volatility/liquidity scores computed from live price data.
  On-chain/sentiment/news remain explicitly `insufficient_data` - no fabricated scores.
- **Crypto can now actually trade autonomously.** Added `propose_crypto_trades` (in
  `agent.py`) - previously nothing in the codebase ever generated a crypto trade proposal,
  so Kraken's entire autonomous-entry path was unreachable regardless of configuration.
  While verifying this end to end (not just via unit tests), found and fixed three real
  bugs that would have silently blocked every Kraken trade: the equity trading-hours
  guardrail was wrongly applied to 24/7 crypto, `risk_percentage` was computed from the
  stop-loss distance instead of capital-at-risk, and `paper_trading_only` incorrectly
  rejected Kraken's genuinely non-paper account.
- **Performance attribution.** Added `PERFORMANCE_ATTRIBUTION` table populated atomically
  when a managed exit closes: entry/exit price, P&L, holding period, entry/exit reason,
  and the investment-score reasoning that justified entry.
- **Notifications.** Added `GET /notifications`, `POST /notifications/ack`, and best-effort
  Expo push delivery (`POST /register-push-token`, a `PUSH_TOKENS` table, and a background
  dispatcher) for high-priority events. Mobile push delivery is implemented server-side and
  unit-tested, but not end-to-end verified - that requires a rebuilt app on a physical device.
- **Security.** Hosted API startup now fails closed for trading/control actions: when
  started on a non-loopback host with no `AI_TRADER_API_TOKEN`, the service enters
  read-only mode and rejects all POST commands until the token is configured. Token
  comparison uses `hmac.compare_digest`. Added a per-IP lockout after repeated auth failures.
- **Mobile.** Added an in-app notification center with unread badge, a Risk Limits section
  surfacing the policy the orchestrator enforces, and clarified that Stop Trading halts new
  entries/approvals but does not disable already-running managed-exit protection.
- **Consolidated duplicated logic.** Kraken pair-formatting/last-price parsing existed
  independently in `api.py` and would have existed a third time in the new crypto proposal
  code; moved the canonical implementation into `broker_adapters.py` and had all three call
  sites use it.
- Added 11 new tests (55 -> 66 passing) covering every behavior change above, including
  regression tests for the three crypto guardrail bugs and the P&L sign-correctness fix.
- **Explicitly out of scope this sprint:** the `api.py` god-file / broker-addition-touches-
  many-files architecture findings (Amber, not safety-blocking - flagged as a fast-follow);
  native mobile push client integration (`expo-notifications`) was not added, since it
  requires a rebuild I cannot verify from this environment - the backend is ready for it.
  No live-trading enablement switches (`KRAKEN_AUTO_TRADING`, `KRAKEN_LIVE_TRADING_APPROVED`,
  `INVESTMENT_POLICIES.crypto_enabled`) were changed - that remains a deliberate Founder
  action. The `.env` file's live keys were left untouched (rotation is a Founder action in
  the Alpaca/OpenAI dashboards, not something this sprint could safely do on its own).
- Verified Python tests: 66/66 passing.

## 2026-07-07 Principal Review and Release Management Pass

- Reviewed the Autonomous Trading Readiness Sprint as release manager.
- Added formal governance review artefacts:
  - `governance/ENGINEERING_REVIEW_REPORT.md`
  - `governance/ARCHITECTURE_ASSESSMENT.md`
  - `governance/SAFETY_ASSESSMENT.md`
  - `governance/REMAINING_RISKS.md`
  - `governance/FOUNDER_RELEASE_BRIEF.md`
- Corrected the mobile Command Centre wording so broker-specific Enable/Disable Auto
  Trading remains the normal broker control path, while the global buttons are clearly
  labelled as Resume All Trading and Emergency Stop All.
- Added a deployment hotfix after Render verification showed the hosted service could not
  remain healthy without `AI_TRADER_API_TOKEN`: the API now starts in hosted read-only mode
  and rejects POST trading/control commands until the token is set, preserving safety without
  taking status/recommendation views offline.
- Updated README and STATUS to match the broker-independent operating model.
- Verification completed:
  - Python compile check passed.
  - Python unit test suite passed: 66/66.
  - `git diff --check` passed.
  - `npx expo-doctor` passed: 17/17 checks.
- Deployment verification:
  - GitHub push completed and Render served the new expanded `/status` payload.
  - Render `/healthz` and `/status` returned HTTP 200 after deployment.
  - `/notifications`, `/performance-attribution`, and an unauthenticated POST check were
    unstable from external verification and require Render log review before declaring the
    hosted backend fully green.

## 2026-07-07 Trading Learning and Kraken Allocation Follow-Up

- Added `KRAKEN_TRADING_ALLOCATION_GBP` with a default of GBP 100 to local, cloud, and Render configuration.
- Updated Kraken account context so trading/risk sizing uses the AI trading allocation instead of the full Kraken account balance.
- Updated Kraken broker panels to separate:
  - full estimated account balance,
  - GBP cash,
  - AI trading allocation,
  - valuation notes for unpriced assets.
- Added `GET /daily-learning-update`, combining closed trade attribution, orchestrator decisions, portfolio snapshots, and public benchmark trader learning into one Founder-facing daily update.
- Added mobile Intelligence screen rendering for the Daily Trading Learning Update.
- Added mobile collapsible trade history rows so trade detail is available on tap without overwhelming the Command Centre.
- Added Kraken/Coinbase broker trade-history rows and `PERFORMANCE_ATTRIBUTION` rows into the Command Centre trade history feed.
- Added tests for Kraken balance/allocation separation and the daily learning update.
- Verification completed:
  - Python compile check passed.
  - Python unit test suite passed: 69/69.
  - `git diff --check` passed.
  - `npx expo-doctor` passed: 17/17 checks.
- Committed and pushed backend/mobile changes as `79df559`.
- Published EAS OTA updates for runtime `1.0.1`:
  - `preview`: update group `854ca353-8bd3-4590-8153-dd7b1d4a0c7d`.
  - `hosted-preview`: update group `3388fe5e-18ee-4a19-8ee8-11b1049a4fbb`.
- Hosted verification after push:
  - `/healthz` returned 200.
  - `/status` returned 200.
  - `/recommendations` returned 200.
  - `/daily-learning-update` and `/performance-attribution` were not reachable from this environment; this matches the previously observed hosted instability around attribution endpoints and should be checked in Render logs if it persists.

## 2026-07-07 On-Demand Trading Reports Follow-Up

- Added `GET /trading-report` for read-only report retrieval.
- Added `POST /generate-report` for app-triggered daily, morning, and evening report generation.
- Report generation now combines:
  - portfolio snapshots,
  - closed trade performance attribution,
  - broker trade history,
  - orchestrator decisions and rejections,
  - daily learning update lessons,
  - benchmark/successful-trader learning notes.
- Mobile Command Centre now includes a Reports section with Today Report, Yesterday Report, Morning Report, and Evening Report buttons.
- Broker cards now include a broker-specific Daily Report button.
- Generated reports are shown immediately inside the app and saved as Markdown to the configured output directory.
- Added `TRADING_REPORTS` SQLite storage for generated reports.
- Generated report Markdown files now live under the backend output folder's `reports/` directory.
- Added browser report pages at `/reports/{report_id}`.
- Updated the mobile app to open the report browser URL automatically and show an `Open Report` button.
- Expanded report detail for daily, morning, evening, weekly, and monthly windows:
  - report window start/end,
  - start and end balances,
  - period performance summary,
  - every closed trade with opened/closed times, entry, exit, quantity, and P&L,
  - broker trade/order rows,
  - explanation of why money was won or lost,
  - lessons learned,
  - Founder-approved recommendations.
- Added Weekly Report and Monthly Report buttons to the mobile Reports section.
- Added broker-fill FIFO reconstruction to reports so buy/sell fills can be paired into realised P&L even when `PERFORMANCE_ATTRIBUTION` has no closed row.
- Reports now list open/unmatched fills separately so fills like an unmatched `SELL ROG` are visible and explained as not enough evidence to compute closed-trade P&L inside the report window.
- Updated broker trade-history recording to preserve Alpaca `transaction_time` for future fill rows.
- Added a regression test proving a negative P&L day and losing closed trade are explained in the generated report.
- Verification completed:
  - Python compile check passed.
  - Python unit test suite passed: 70/70.
  - `git diff --check` passed.
  - `npx expo-doctor` passed: 17/17 checks.
## 2026-07-17 World-Class Trading Intelligence Transformation

- Added `src/ai_trader/trading_intelligence.py` as the new evidence layer before recommendation persistence.
- Added SQLite schema for:
  - `STRATEGY_REGISTRY`
  - `MARKET_REGIME_SNAPSHOTS`
  - `TRADE_SIGNALS`
  - `TRADING_COMMITTEE_REVIEWS`
  - `PROBABILITY_ESTIMATES`
  - `TRADE_LIFECYCLE`
  - `CONFIDENCE_CALIBRATION`
  - `STRATEGY_LAB_RUNS`
- Seeded formal deterministic strategy definitions for:
  - conservative AI-assisted equity setup,
  - crypto trend-following 2R,
  - paper validation 2R.
- Updated stock and crypto proposal generation so recommendations are only persisted after Trading Intelligence creates:
  - strategy,
  - regime,
  - signal evidence,
  - trade setup,
  - portfolio fit,
  - trading committee review,
  - probability estimate,
  - strongest argument for,
  - strongest argument against.
- Updated the audit payload to store the full intelligence packet with each recommendation.
- Updated the Investment Orchestrator to append lifecycle stages after approved, submitted, and rejected outcomes.
- Updated `/recommendations` to expose strategy, market regime, committee, probability, signals, lifecycle, and bull/bear arguments.
- Updated the mobile Recommendations screen to show the new evidence without changing execution authority.
- Added regression tests in `tests/test_trading_intelligence.py`.
- Documentation added:
  - `architecture/WORLD_CLASS_TRADING_INTELLIGENCE_ARCHITECTURE.md`
  - `architecture/WORLD_CLASS_TRADING_INTELLIGENCE_IMPLEMENTATION_REPORT.md`
  - `architecture/WORLD_CLASS_TRADING_INTELLIGENCE_DATABASE_CHANGES.md`
  - `architecture/WORLD_CLASS_TRADING_INTELLIGENCE_TESTING_REPORT.md`
  - `architecture/WORLD_CLASS_TRADING_INTELLIGENCE_FOUNDER_BRIEFING.md`
  - `architecture/WORLD_CLASS_TRADING_INTELLIGENCE_KNOWN_LIMITATIONS.md`
  - `architecture/WORLD_CLASS_TRADING_INTELLIGENCE_ROADMAP.md`
- Verification:
  - Focused Trading Intelligence tests passed: 4/4.
  - Full Python unit test suite passed: 90/90.
  - `npx tsc --noEmit` is not available because the Expo mobile app does not include TypeScript; no dependency changes were made.

## 2026-07-17 World-Class Trading Intelligence Phase 2

- Extended `src/ai_trader/trading_intelligence.py` from evidence recording into evidence discovery.
- Added deterministic market-intelligence metrics from available candles:
  - trend score,
  - momentum score,
  - moving-average position,
  - volatility,
  - ATR percentage,
  - relative strength proxy,
  - volume trend,
  - price structure,
  - breakout/breakdown state,
  - mean-reversion state,
  - support,
  - resistance,
  - contradictory evidence.
- Updated regime inference to use market-intelligence metrics and store contradictory evidence.
- Updated signal scoring so signals are independently calculated rather than copied from proposal confidence.
- Expanded strategy registry with:
  - Trend Following,
  - Momentum,
  - Pullback,
  - Breakout,
  - Mean Reversion,
  - Range Trading,
  - Volatility Expansion,
  - Swing Continuation,
  - Crypto Infrastructure Trend,
  - Institutional Accumulation,
  - Quality Growth,
  - Value Pullback.
- Expanded Trading Committee into deterministic independent reviewers with member votes, questions, disagreements, and outcomes.
- Enhanced probability estimation with strategy history, regime history, signal history, small-sample penalty, volatility penalty, calibration evidence, and confidence intervals.
- Added `HISTORICAL_CANDLES`, `STRATEGY_BACKTEST_RESULTS`, and `PERFORMANCE_INTELLIGENCE` tables.
- Added `record_historical_candle`, `run_strategy_backtest`, `calculate_calibration_metrics`, and `calculate_performance_metrics`.
- Extended `TRADE_LIFECYCLE` with fees, slippage, R-multiple, MAE, MFE, and holding-time fields using additive SQLite migration.
- Fixed `/recommendations` intelligence merging so normalized committee/probability rows do not hide richer strategy, regime, and market-intelligence payloads.
- Fixed a SQLite lock path in calibration refresh by calculating metrics outside the write transaction.
- Added Phase 2 documentation:
  - `architecture/WORLD_CLASS_TRADING_INTELLIGENCE_PHASE_2.md`.
- Verification:
  - `py_compile` passed for Trading Intelligence and API modules.
  - Focused Trading Intelligence tests passed: 10/10.
  - Full Python unit test suite passed: 96/96.

## 2026-07-17 Institutional Intelligence & Founder Experience Phase 3

- Added long-term architectural principle:
  - Does it help AI Trader make a better investment decision?
  - Does it help the Founder make a better decision?
  - Does it help AI Trader learn to make better decisions in the future?
- Updated strategy selection to score multiple candidate strategies against available evidence instead of relying on a fixed default.
- Strategy records now include selection reason, candidate scores, rejected strategies, production-readiness status, and validation status.
- Added Strategy Lab walk-forward validation with train/test windows, out-of-sample results, cost/slippage assumptions, benchmark comparison, and bias-control notes.
- Added richer portfolio intelligence fields for exposure, prospective exposure, largest position, proposed risk contribution, diversification, capital efficiency, liquidity-data availability, and risk-budget notes.
- Added a `founder_experience` payload to `/status` for executive dashboard, portfolio command, market intelligence centre, and learning lab screens.
- Reframed the mobile app into five Founder screens:
  - Dashboard
  - Recommendations
  - Portfolio
  - Market
  - Learning
- Added dark executive shell with white decision cards and plain-English status pills.
- Moved trade-history and broker-panel workflows under Portfolio.
- Moved strategy rankings, institutional tests, signal rankings, lessons, and Ask AI Trader under Learning.
- Added documentation:
  - `architecture/INSTITUTIONAL_INTELLIGENCE_PHASE_3.md`
  - `architecture/FOUNDER_EXPERIENCE_PHASE_3_MOCKUPS.md`
  - `governance/FOUNDER_BRIEFING_PHASE_3.md`
- Verification:
  - `py_compile` passed for Trading Intelligence and API modules.
  - Focused Trading Intelligence tests passed: 13/13.

## 2026-07-17 World-Class Trader Transformation Phase 4-8

- Reviewed existing architecture and governance before implementation.
- Created `architecture/WORLD_CLASS_TRADER_PHASE_4_8_IMPLEMENTATION_PLAN.md`.
- Added `src/ai_trader/operational_truth.py` for canonical lifecycle, reconciliation, execution costs, true R, MAE, and MFE.
- Added `src/ai_trader/market_intelligence_platform.py` for provider-neutral market observations, data quality, multi-timeframe conclusions, and Regime 2.0 evidence.
- Added `src/ai_trader/portfolio_intelligence.py` for metadata, exposure, concentration, correlation, and proposed-trade portfolio impact.
- Added `src/ai_trader/experience_engine.py` for immutable experience records, post-trade reviews, analogues, and governed learning proposals.
- Wired additive schema initialization into `LocalApiService`.
- Reconciled Alpaca/Kraken broker history into canonical lifecycle records during startup and broker-history writes.
- Added `/operational-truth` and `/world-class-evidence`.
- Added `world_class_evidence` to `/status` for Founder-facing truth, unknowns, operational health, portfolio intelligence, and learning boundaries.
- Tightened recommendation actionability: auto-trade eligibility now requires both strongest argument for and strongest argument against.
- Updated the mobile Dashboard, Portfolio, and Recommendation screens around progressive disclosure and explained unknowns.
- Added Phase 4-8 architecture, standards, testing, implementation, deployment-contract, and Founder briefing documents.
- Verification:
  - `py_compile` passed for new backend modules and API.
  - Focused World-Class Transformation tests passed: 6/6.

## 2026-07-17 Always-On Operations, Shadow Trading, and Alpaca Recovery

- Reviewed the existing Render blueprint, API startup scheduler, CLI, and operational tables.
- Confirmed the previous topology had one Render web service and background daemon threads owned by the API process.
- Added `src/ai_trader/always_on.py` with durable schemas and helpers for:
  - scheduled job runs;
  - worker heartbeats;
  - research funnels;
  - shadow trades;
  - operations incidents;
  - operations health;
  - scheduler status;
  - Alpaca inactivity diagnosis.
- Added package entry point `src/ai_trader/__main__.py` so `python -m ai_trader ...` works.
- Extended the CLI with:
  - `run-worker`;
  - `run-job`;
  - named jobs for premarket, market open, midday, market close, overnight crypto, daily learning, daily report, broker poll, managed exits, and auto execution.
- Wired additive always-on schema initialization into `LocalApiService`.
- Added API endpoints:
  - `/operations-health`;
  - `/scheduler-status`;
  - `/job-runs`;
  - `/shadow-trades`;
  - `/shadow-performance`;
  - `/research-funnel`;
  - `/alpaca-inactivity-diagnosis`.
- Added `operations_health` to `/status`.
- Added Alpaca and Kraken research funnel recording.
- Added proposal-to-shadow-trade recording for Alpaca and Kraken proposals.
- Added process commands for explicit API, worker, and cron job topology. Left `render.yaml` on the current single web service until Supabase/Postgres is connected, because SQLite on a persistent disk is not a safe multi-process shared datastore.
- Updated the mobile Dashboard with a 24-Hour Operations card.
- Added focused tests in `tests/test_always_on_operations.py`.
- Added Always-On architecture and Founder briefing documents.
- Added a governed Supabase Postgres migration plan. SQLite remains the current implementation; Supabase Postgres is the recommended production target for API, worker, and cron shared state.
- Verification:
  - Focused Always-On tests passed: 9/9.
- Not yet proven:
  - live Render worker heartbeat after deploy;
  - scheduled cron job execution while app is closed;
  - hosted Alpaca fresh research path from live provider to order or persisted no-trade reason.

## 2026-07-18 Supabase/Postgres Always-On Evidence Backend

- Implemented the next controlled datastore step after the Always-On sprint.
- Added settings for:
  - `AI_TRADER_DATABASE_BACKEND`;
  - `DATABASE_URL`;
  - `SUPABASE_DATABASE_URL`.
- Added `Settings.uses_postgres` and exposed safe database backend diagnostics through `ai-trader config`.
- Added Postgres schema support in `src/ai_trader/always_on.py` for:
  - `SCHEDULED_JOB_RUNS`;
  - `WORKER_HEARTBEATS`;
  - `RESEARCH_FUNNELS`;
  - `SHADOW_TRADES`;
  - `OPERATIONS_INCIDENTS`.
- Added dual-backend persistence for Always-On job claims, job completion, worker heartbeats, research funnels, shadow trades, shadow outcomes, operations incidents, and list/read helpers.
- Added `database_backend` details to `/operations-health` so the Founder/CTO can see whether Always-On evidence is using SQLite or Supabase/Postgres.
- Added `psycopg[binary]` as the Postgres driver dependency.
- Updated `render.yaml` with `AI_TRADER_DATABASE_BACKEND` and `DATABASE_URL` placeholders while keeping worker/cron disabled until Postgres is proven active.
- Updated:
  - `architecture/SUPABASE_POSTGRES_MIGRATION_PLAN.md`;
  - `architecture/RENDER_SERVICE_TOPOLOGY.md`;
  - `architecture/DATABASE_REFERENCE.md`;
  - `README.md`;
  - `STATUS.md`.
- Boundary:
  - This does not migrate the full trading/audit database yet.
  - Broker runtime, recommendations, canonical lifecycle, trade audit, reports, and learning records remain on the existing SQLite-oriented modules until their schemas are ported deliberately.

## 2026-07-18 Autonomous Operations Completion and Render Activation

- Reviewed the Sprint 6 production-control layer, Always-On worker commands, Render topology, database architecture, and hosted activation gates.
- Updated `render.yaml` from a web-only production shape to an activation-ready topology:
  - `ai-trader-api`;
  - `ai-trader-worker`;
  - premarket, market-open, midday, and market-close equity cron jobs;
  - overnight crypto cron job;
  - daily learning cron job;
  - daily, weekly, and monthly report cron jobs.
- Added hosted startup validation in `Settings.production_startup_errors`:
  - hosted runtime now requires `AI_TRADER_DATABASE_BACKEND=postgres` plus `DATABASE_URL` or `SUPABASE_DATABASE_URL`;
  - the check also honors `AI_TRADER_PROCESS_ROLE=render`;
  - this prevents silent hosted SQLite fallback.
- Added `AI_TRADER_DISABLE_API_BACKGROUND_WORKERS`:
  - when true, the API does not start duplicate scheduler, broker poll, exit monitor, auto-executor, crypto refresh, or push-dispatch loops;
  - Render worker/cron services become the intended background owners.
- Extended `python -m ai_trader run-worker` so every worker cycle processes the Sprint 6 closed-loop learning outbox after broker polling, managed exits, and auto-execution evaluation.
- Added the learning outbox processor:
  - idempotent claim/retry handling;
  - abandoned claim recovery;
  - manual review for incomplete deterministic evidence;
  - immutable preservation of the original queued payload;
  - operational-event evidence for every processor cycle.
- Extended `python -m ai_trader run-job` to support daily, weekly, and monthly report jobs.
- Updated `.env.example` and `cloud.env.example` with the production database/process-role contract.
- Added architecture evidence documents:
  - `AUTONOMOUS_OPERATIONS_COMPLETION_REPORT.md`;
  - `POSTGRES_PRODUCTION_MIGRATION_REPORT.md`;
  - `RENDER_PRODUCTION_TOPOLOGY.md`;
  - `RENDER_DEPLOYMENT_EVIDENCE.md`;
  - `RENDER_ENVIRONMENT_MANIFEST.md`;
  - `AUTONOMOUS_RESEARCH_VERIFICATION.md`;
  - `BROKER_RECONCILIATION_COMPLETION.md`;
  - `LEARNING_PROCESSOR_VERIFICATION.md`;
  - `AUTOMATIC_REPORTING_VERIFICATION.md`;
  - `PHONE_CLOSED_VERIFICATION.md`;
  - `HOSTED_RESTART_AND_RECOVERY_TESTS.md`;
  - `OPEN_RELEASE_GATES.md`;
  - `FOUNDER_COMPLETION_BRIEFING.md`.
- Updated `README.md`, `STATUS.md`, `architecture/RENDER_SERVICE_TOPOLOGY.md`, and `architecture/DATABASE_REFERENCE.md`.
- Verification completed locally:
  - `python -m py_compile src\ai_trader\config.py src\ai_trader\api.py src\ai_trader\cli.py src\ai_trader\sprint6.py` passed.
  - `python -m unittest tests.test_always_on_operations tests.test_sprint6_institutional_spine` passed: 23/23.
- Hosted activation not completed from this environment:
  - Render deployment ID not available;
  - Supabase/Postgres live connection not verified;
  - phone-closed worker/cron proof remains an open release gate.

## 2026-07-19 Always-On Worker Activation Wording Correction

- Founder-provided hosted evidence confirmed:
  - `/operations-health` returned `overall=healthy` and `worker_health=healthy`;
  - `/scheduler-status` returned `status=active` with a background-worker heartbeat;
  - `/job-runs` returned durable background job records, including auto-execution cycles.
- Corrected backend status wording so resolved deployment proof is not still presented as an open blocker:
  - `phase5_status` now reports `operational_with_hardening_backlog` when Supabase/Postgres and worker supervision are healthy;
  - `sprint6_status` now reports that production control gates are active when Postgres is configured and no kill switch/open incident blocks operation.
- Updated the mobile Dashboard label from `Still To Migrate` to `Hardening Backlog` so remaining database-spine work is not confused with a current trading blocker.
- Boundary:
  - No guardrails, broker permissions, risk limits, or trading thresholds were weakened.
  - Remaining hardening backlog still matters for institutional maturity, but it no longer masks the proven always-on worker milestone.

## 2026-07-19 Autonomous Activity Screen

- Implemented a new Founder-facing `Activity` tab in the mobile app.
- Added a compact Dashboard `Autonomous Activity` card so the home screen now shows:
  - operating state;
  - last meaningful action;
  - research runs;
  - recommendations;
  - orders submitted;
  - latest blocker or no-trade explanation.
- Added `src/ai_trader/autonomous_activity.py` as a deterministic read model over persisted evidence:
  - scheduled job runs;
  - worker heartbeats;
  - research funnels;
  - operational events;
  - decision journal rows;
  - Portfolio Manager decisions;
  - broker trade history;
  - canonical reconciliation cases;
  - closed-loop learning runs;
  - generated reports;
  - incident lifecycle.
- Added authenticated API routes:
  - `/autonomous-activity`;
  - `/activity/status`;
  - `/activity/summary`;
  - `/activity/timeline`;
  - `/activity/why-no-trade`;
  - `/activity/brokers`;
  - `/activity/founder-attention`.
- Added the mandatory Why No Trade funnel. It separates:
  - research did not run;
  - no opportunity found;
  - opportunity found but rejected;
  - approved/candidate blocked;
  - approved but not submitted;
  - order submitted or trade completed.
- Added timeline filtering by category and importance/action-required mode.
- Added Founder attention items for stale worker heartbeat, durable database not proven, connected-broker issues, disabled Alpaca paper auto-trading, and unresolved incidents.
- Added tests in `tests/test_autonomous_activity.py`.
- Added documentation:
  - `architecture/AUTONOMOUS_ACTIVITY_ARCHITECTURE.md`;
  - `architecture/AUTONOMOUS_ACTIVITY_DATA_MAPPING.md`;
  - `architecture/AUTONOMOUS_ACTIVITY_API.md`;
  - `architecture/AUTONOMOUS_ACTIVITY_LIVE_VERIFICATION.md`;
  - `architecture/FOUNDER_ACTIVITY_SCREEN_GUIDE.md`.
- Verification:
  - `python -m py_compile src\ai_trader\autonomous_activity.py src\ai_trader\api.py` passed.
  - `python -m unittest tests.test_autonomous_activity` passed: 6/6.
- Boundary:
  - No mock events or synthetic activity rows were added.
  - No guardrails, broker permissions, auto-trading settings, or risk thresholds were changed.
  - The Activity screen is evidence visibility only; it does not approve or place trades.

## 2026-07-19 Mobile Refresh Performance Hardening

- Investigated the slow mobile startup/refresh spinner reported by the Founder.
- Root cause found in the mobile refresh path:
  - the app waited for eleven API calls to complete before clearing the global loading spinner;
  - optional/secondary endpoints such as intelligence, reports, notifications, performance attribution, and daily learning could keep the whole interface waiting;
  - Render free-tier cold starts can still add startup delay before the first hosted API response.
- Updated `mobile/App.js` so refresh now happens in two phases:
  - primary evidence first: status, portfolio, recommendations, and autonomous activity;
  - secondary evidence in the background: Founder brief, benchmark, themes, companies, notifications, performance attribution, and daily learning.
- Added request timeouts:
  - primary refresh calls use a 14 second timeout;
  - secondary calls use an 8 second timeout;
  - long POST commands use a 45 second timeout.
- Expected Founder impact:
  - the app should show the main operating picture sooner;
  - optional panels can continue filling in after the main screen is usable;
  - a single slow optional endpoint should no longer make the entire app look frozen.
- Boundary:
  - this does not change trading logic, governance, guardrails, broker permissions, or autonomous execution behaviour.
  - a paid/no-spin-down Render web service or external uptime monitor is still required to remove Render cold-start delays entirely.

### Installed-App Follow-Up

- Founder verification showed the previous 14 second `/status` timeout could still raise a blocking `Backend unavailable` modal during Render cold-start or slow hosted status responses.
- Adjusted refresh behaviour:
  - `/status` now uses a structured degraded-status fallback instead of failing the whole refresh;
  - primary refresh timeout increased from 14 seconds to 18 seconds;
  - Activity fallback messaging is centralized so timeout states remain plain-English and truth-labelled.
- Result:
  - a slow `/status` response should no longer interrupt the Founder with a modal;
  - the app should remain usable and explain that hosted status evidence is delayed or unavailable.

## 2026-07-19 Production Evidence Activation Sprint - Completed

- Implemented a shared Postgres production-evidence layer for research, recommendations, broker snapshots, trade evidence and learning evidence.
- Added authenticated `/founder-evidence` and `/founder/trades` APIs and connected all six Founder screens to the same compact read model.
- Added cached mobile startup so the last proven evidence renders before the hosted refresh completes.
- Activated worker-owned research scheduling while retaining one scheduler owner and preserving all execution gates.
- Hardened worker liveness with an independent durable heartbeat pulse during long broker operations.
- Changed the worker order so due research and managed exits are not starved by slow broker polling; broker polling uses durable ten-minute buckets.
- Corrected Kraken analysis so unavailable pairs create explicit no-trade evidence and do not abort the remaining approved symbols.
- Hosted verification on revision `573c36b346a896e83886348a83204feaa9b1fe05` proved:
  - heartbeat advancement from `23:02:23` to `23:03:40` UTC during autonomous work;
  - active scheduler, healthy worker and Postgres shared state;
  - four research runs, 36 assets analysed, 24 recommendations, two broker snapshots and 20 trade-history rows;
  - explicit no-trade conclusion when no opportunity passed every portfolio, strategy and risk gate.
- Published Android runtime `1.0.2` OTA updates:
  - `hosted-preview` group `daa2d530-92b9-4ea8-b358-50ae8ced9648`;
  - `preview` group `ca32b0ba-a219-4dbf-b418-138b32873749`.
- Verification:
  - full Python suite: 148 passed;
  - Expo Doctor: 17/17 passed;
  - Android export passed.
- Safety boundary:
  - no guardrail, strategy maturity gate, portfolio authority, broker permission or risk limit was weakened;
  - the sprint exposes real trades and P&L evidence but does not fabricate missing exit attribution or force an order.
## 2026-07-20 - Production Completion and Architectural Cutover Programme

### Governance review and forensic gate

- Reviewed the repository-derived database, execution, lifecycle, learning, worker, API, mobile and configuration paths before implementation.
- Created `architecture/PRODUCTION_COMPLETION_ARCHITECTURE_AUDIT.md`.
- Determined that the four requested cutovers were necessary but insufficient.
- Added two mandatory blockers to programme scope:
  - worker responsibility timeout isolation;
  - source-aware Founder evidence that cannot hide missing authority behind projections.

### Production database unification

- Added `src/ai_trader/database.py` as the mandatory runtime connection provider.
- Migrated production-capable domain repositories away from direct SQLite opens.
- Hosted runtime now fails closed unless Postgres is selected and configured.
- Retained SQLite only for local/test usage, migration input and local inspection.
- Replaced ambiguous `INSERT OR REPLACE` usage with explicit conflict-safe upserts.
- Added `src/ai_trader/database_migration.py` and CLI command `migrate-sqlite-to-postgres`.
- The migration fingerprints its source, preserves existing Postgres rows, records row/table evidence and fails on missing target schemas.

### One production execution pipeline

- Made `InvestmentOrchestrator` the owner of Strategy Maturity, Portfolio Manager, Risk Engine, deterministic guardrails and Production Risk Sentinel evaluation.
- Created the canonical execution intent before broker submission and linked the broker response afterward.
- Removed duplicate API-owned pre-execution checks.
- Disabled legacy `ExecutionEngine` broker submission in hosted runtime while preserving local tests and demos.

### Canonical reconciliation and learning

- Added `src/ai_trader/canonical_trades.py` with one logical trade aggregate, immutable event ledger and immutable fill ledger.
- Added deterministic partial/multiple-fill aggregation, weighted prices, remaining quantity, broker/exchange fees, gross P&L, net P&L and reconciliation confidence.
- A filled entry is now explicitly open, not terminal.
- Duplicate broker events and fills do not alter trade quantities or create additional logical trades.
- Canonical terminal reconciliation now queues closed-loop learning exactly once.
- Complete evidence runs the existing full learning pipeline; incomplete historical evidence completes as `completed_insufficient_evidence` without fabricated metrics.

### Worker resilience

- Added `AI_TRADER_WORKER_JOB_TIMEOUT_SECONDS` with a 180-second default.
- A timed-out worker responsibility records a `timed_out` job result and operational incident while preserving worker heartbeat evidence.

### Verification

- `python -m compileall -q src`: passed.
- `pytest -q tests/test_production_completion.py`: 5 passed.
- Focused production suite: 48 passed.
- `pytest -q tests`: 153 passed in 48.14 seconds.
- Unrestricted root discovery is not authoritative because `mobile/inspect-output` contains stale copied test/package artifacts.

### Honest release boundary

- Repository gate passed.
- Hosted production-completion gate remains open pending Render deployment, real Supabase schema/migration validation, a genuine Alpaca paper round trip, terminal-learning evidence and a sustained phone-closed soak.
- No governance threshold, strategy maturity, broker permission or risk limit was weakened.
- No synthetic trade, P&L, recommendation or learning evidence was created.

## 2026-07-20 - Founder Evidence Latency and Mobile Navigation Fix

- Confirmed from the installed-app screenshots that `/founder-evidence` timing out caused Dashboard, Activity, Portfolio, Market and Learning to fall back to unavailable states together.
- Removed repeated hosted schema initialization from the Founder evidence read path; schema migration remains owned by process startup, while isolated local SQLite databases retain idempotent bootstrapping.
- Replaced broad production evidence reads with a compact projection that excludes raw job, funnel, heartbeat, trade, learning and broker payload blobs not used by the Founder interface.
- Reduced recent job and funnel projection limits from 250 to 100 while preserving the selected-period operational totals and newest-first timeline.
- Changed the six primary mobile destinations to a stable three-column, two-row navigation grid.
- Set the Android runtime and Expo status bar to the application navy background with light system icons.
- Verification: 9 focused evidence/activity tests passed; the authoritative root suite passed with 153 tests; Python compileall passed; Expo Doctor passed all 17 checks.
- No trading rules, broker permissions, portfolio authority, risk controls or execution behavior changed.

### Hosted API cold-start correction

- Live verification showed the Render web service remaining on its infrastructure wake page while the paid autonomous worker continued operating normally.
- Found that the API process performed eleven schema initializers, seed writes, generated documents and startup reconciliation before binding its HTTP socket.
- Assigned hosted schema/bootstrap ownership to the production worker and made the hosted API a fast read/command process over the already-initialized shared Postgres database.
- Retained self-initializing behavior for local development, tests and combined-process deployments.
- Added regression coverage proving a worker-owned API service can start and read Founder evidence without invoking schema writes.
- Render free-tier infrastructure can still impose a provider cold-start delay; the application caches the last successful Founder evidence, and upgrading the API service is the operational route to eliminating provider sleep entirely.

### Deterministic Android release

- Bumped the mobile release to `1.0.3` / Android build `4` so the two-row navigation and native dark status bar are embedded in a fresh APK rather than depending on an existing installation accepting an OTA update.
- No trading, broker, governance, portfolio or risk behavior changed in this release.

## 2026-07-23 - Alpaca Portfolio and Rich Recommendation Recovery

- Traced the hosted Alpaca connection failure to duplicate broker-history
  observations aborting a shared Postgres transaction before the portfolio
  snapshot could be stored.
- Replaced exception-driven duplicate handling with database-level
  `ON CONFLICT DO NOTHING` idempotency for broker-history and managed-exit
  history writes.
- Added regression coverage proving a duplicate Alpaca broker event is ignored
  and does not create a second history row.
- Enriched production research handoff records with the existing structured
  recommendation dossier while preserving authoritative proposal execution
  fields.
- Added compatibility aliases for historical recommendation evidence without
  fabricating absent strategy, probability, committee or due-diligence facts.
- Added regression coverage for rich dossier persistence and authoritative
  execution-field precedence.
- Verification: Python compileall passed; focused suite passed 30 tests; full
  suite passed 164 tests.
- No risk limits, broker permissions, strategy gates, position sizing rules or
  autonomous trading controls were weakened.
## 2026-07-22 - Founder Evidence Snapshot Recovery

- Investigated installed-app evidence showing Dashboard, Activity, Portfolio, Market, and Learning all failing together on an 18-second `/founder-evidence` timeout.
- Confirmed the shared failure was backend request-time reconstruction, not missing mobile widgets or an inactive worker.
- Added `PRODUCTION_FOUNDER_EVIDENCE_SNAPSHOTS`, keyed by display period, as a durable derived read model in shared Postgres.
- Assigned projection ownership to the worker's existing five-minute evidence-snapshot responsibility.
- Changed hosted Founder reads to one snapshot lookup; the legacy live builder remains available only for local SQLite development and tests.
- Added explicit first-snapshot warm-up and stale-snapshot states without generating synthetic events, trades, P&L, research, or learning.
- Added bounded Postgres connection and statement timeouts and process-local idempotent schema initialization.
- Restricted pytest discovery to authoritative `tests/` so ignored mobile inspection exports cannot shadow the installed source package.
- Added regression tests for snapshot reads, stale evidence, worker projection refresh, and unavailable hosted snapshots.
- Verification: `python -m compileall -q src` passed; `pytest -q` passed 158 tests.
- Hosted proof remains pending deployment. Render free-tier API wake time remains a separate provider constraint.

## 2026-07-23 - Postgres Lifecycle and Founder Projection Recovery

- Identified the remaining Alpaca evidence failure as a canonical lifecycle
  duplicate insert handled by catching a uniqueness exception inside an active
  Postgres transaction. PostgreSQL then rejected the later portfolio snapshot
  write with `current transaction is aborted`.
- Replaced lifecycle exception handling with atomic
  `ON CONFLICT(idempotency_key) DO NOTHING` and deterministic duplicate lookup.
- Applied the same correction to immutable Experience Engine records so
  repeated terminal-learning inputs cannot poison a Postgres transaction.
- Changed multi-period Founder snapshot generation to load shared evidence
  rows once and filter the four display periods in memory.
- Added regression coverage for duplicate immutable experience records and
  one-load multi-period snapshot generation.

## 2026-07-23 - Bounded Incremental Broker Reconciliation

- Production evidence showed `broker-poll`, `evidence-snapshot` and
  `auto-execution` exceeding the worker's 180-second boundary despite healthy
  API and worker heartbeats.
- Root cause: broker activity was replayed without a hard bound, all historical
  rows were normalized on every cycle, missing event timestamps were replaced
  by the current time, and hosted hot paths repeatedly attempted idempotent
  schema initialization.
- Bounded Alpaca activity retrieval and broker-event selection to the 100 most
  relevant unique observations, preserving current orders before history.
- Changed canonical normalization to process only rows newly inserted into
  broker history.
- Assigned a deterministic timestamp marker to broker events that genuinely
  lack a broker timestamp, preserving idempotency across polling cycles.
- Removed duplicate legacy reconciliation from the broker-history insert path;
  the broker poll now owns the single canonical normalization pass.
- Removed repeated schema DDL from Postgres canonical-trade, Sprint 6 and
  production-evidence hot paths. Hosted startup migration remains authoritative.
- Added clean worker-process restart semantics after a timed-out production
  job, preventing unfinished daemon work from accumulating across cycles.
- Added focused regression tests for timestamp-less duplicate events, bounded
  event ordering and timeout-triggered process restart.
- Verification: focused suite passed 31 tests. Full-suite and hosted Render
  verification follow before the recovery is marked complete.
- No guardrail, strategy threshold, broker authority, risk limit or allocation
  rule changed.

## 2026-07-23 - Broker Evidence Write Ownership Recovery

- Hosted verification of the bounded reconciliation release proved that worker
  timeout evidence and clean Render restart behavior worked, but `broker-poll`
  still exceeded 180 seconds.
- Traced the remaining write amplification to production trade evidence being
  rewritten for every selected historical broker event on every poll.
- Changed broker polling to write production trade evidence only for rows that
  broker-history persistence classified as new or changed.
- Removed order and fill evidence writes from broker snapshot capture. Broker
  polling now owns order/trade evidence; snapshot capture owns balances,
  buying power and positions.
- Removed production-schema initialization calls from hosted evidence hot
  paths. Production startup remains the migration authority; isolated SQLite
  development and test databases still bootstrap themselves.
- Added regression coverage proving unchanged broker events are not rewritten
  and broker snapshots do not duplicate trade evidence.
- Focused verification passed 40 tests.
- No execution permission, portfolio rule, risk limit, strategy threshold or
  broker safety control changed.

## 2026-07-23 - Hosted Alpaca Verification and Intelligence Dossier Preservation

- Verified the deployed broker evidence recovery against the authenticated
  hosted operations and Founder evidence contracts.
- Confirmed a completed bounded broker poll and completed evidence snapshot in
  shared Postgres. The Founder projection now contains the current Alpaca
  account, portfolio value, cash, buying power and open-position count.
- Inspected the hosted recommendation contract and proved that the remaining
  sparse cards were not a mobile rendering fault. The persisted proposal
  contained price, stop, target, thesis and confidence, but omitted the
  structured Trading Intelligence packet.
- Traced the loss to both AI proposal paths: the intelligence packet was
  calculated and written to the local audit event, then omitted from the
  `TradeProposal` returned to production evidence.
- Added optional intelligence evidence to the normalized proposal model and
  attached it after guardrail validation for equities and crypto.
- Updated recommendation projection to retain the complete immutable packet
  and expose strategy, probability, expected return, confidence interval,
  committee result, strongest arguments, regime, signals and invalidation as
  stable Founder-facing aliases.
- Added an end-to-end regression test using the real nested packet shape,
  proving it survives recommendation storage and Founder projection.
- Historical thin recommendations are not backfilled with invented facts.
  Rich fields become available on recommendations generated after deployment.
- Verification: compilation passed; focused suite passed 46 tests; complete
  suite passed 171 tests.
- Safety boundary: this change transports and presents existing evidence only.
  It does not alter portfolio approval, Risk Engine approval, broker
  permissions, execution eligibility, sizing, stops, targets or guardrails.

## 2026-07-23 - Kraken Reconciliation and Closed-Loop Learning Recovery

- Activated a reconciliation hold for new Kraken entries. Existing managed
  exits continue to be monitored and may still submit their protective exit.
- Added an explicit Kraken order-ownership registry populated from durable
  order-intent and managed-exit identifiers and from new orchestrator
  submissions.
- Prohibited symbol-based ownership and entry/exit inference for Kraken.
  Unlinked evidence is classified as personal/unmanaged and excluded.
- Corrected Kraken API semantics so `ClosedOrders` records order state while
  only `TradesHistory` records create canonical fills.
- Prevented a closed order with executed-volume fields from being treated as a
  closed investment.
- Added a £100 AI-managed capital ledger separate from the Founder's existing
  Kraken assets.
- Added canonical result projection for entry, exit, quantities, fees,
  realised and unrealised P&L, holding time, planned/gross/net R, slippage,
  and reconciliation confidence.
- Added read-only persisted evidence replay. It has no broker client or
  submission path and explicitly reports zero broker orders submitted.
- Added idempotent learning recovery: a genuinely terminal logical trade queues
  one closed-loop learning workflow and repeated replay does not queue it
  again.
- Changed managed exits to `exit_submitted` after broker submission. They are
  marked closed only after a matching canonical exit fill proves terminal
  state.
- Added authenticated replay, status, verification, and Founder-controlled
  resume endpoints.
- Added a Kraken reconciliation and £100 ledger section to the mobile broker
  panel.
- Verification passed:
  - Python compilation for all changed modules;
  - 6 focused Kraken reconciliation tests;
  - 32 production-spine and institutional-control tests;
  - complete Python suite: 177 tests;
  - Expo Doctor: 17/17 checks.
- The entry hold remains active. Hosted Supabase replay, evidence review, and
  Founder approval are required before Kraken entries resume.
- No broker permission, risk limit, strategy gate, allocation limit, stop,
  target, or governance threshold was weakened.

## 2026-07-27 - Render Worker Timeout Isolation

- Reviewed the persisted 24-hour Render worker log rather than inferring
  health from source code.
- Confirmed the worker repeatedly exited when `auto-execution` or
  `overnight-crypto` exceeded the configured 180-second job boundary.
- Confirmed repeated container restarts caused Render to suspend the paid
  background worker after repeated crashes.
- Replaced supervisor termination with process-isolated job execution.
- The supervisor now claims each durable job, starts a child process for the
  bounded operation, terminates only that child on timeout, records
  `timed_out`, creates an operational incident and continues running.
- Added a read-only durable job lookup so the supervisor reports the child
  process's persisted result rather than inventing an outcome.
- Added regression coverage for timeout survival, child-process termination
  and persisted completion outcomes.
- Focused verification passed 24 tests; the complete Python suite passed 179
  tests.
- No trading threshold, broker permission, allocation, position limit,
  stop-loss, take-profit, portfolio gate or Risk Engine rule changed.
- Production remains paused until the new worker release is deployed and the
  suspended Render worker is manually resumed and verified.

## 2026-07-27 - Startup Reconciliation Isolation

- Queried the protected hosted scheduler and job endpoints using the locally
  configured command token without exposing it.
- Confirmed deployment `0f063e02` was alive and heartbeating, but had remained
  in `kraken-startup-reconciliation` and had created no new scheduled job rows.
- Confirmed the visible job history ended on 26 July and therefore did not
  prove that the timeout-isolation release had entered its normal worker loop.
- Converted Kraken startup reconciliation into a durable, process-isolated,
  time-bounded worker job.
- A stalled reconciliation can no longer indefinitely prevent managed exits,
  broker polling, research, evidence snapshots, execution evaluation, or
  learning from running.
- Kraken entries remain paused when startup reconciliation does not complete;
  no broker permission or trading guardrail was weakened.
