# AI Trader Modularisation — Stage 0 through Phase 7 Checkpoint

**Date:** 2026-08-02
**Prepared for:** ChatGPT review, per the Founder/Claude agreement that phases 3–7 would run
back-to-back and pause for a joint review before Phase 8 (execution service — the highest-risk
phase, sequenced last for that reason)
**Plan being implemented:** `architecture/AI_TRADER_MODULARISATION_ARCHITECTURE_2026-08-02.md`
**Full detail:** `governance/IMPLEMENTATION_LOG.md`, lines 1–666 (8 entries, one per stage/phase)
**Commits:** `d732ba35` through `8f586093` (10 commits, local only, nothing pushed/deployed)

This document is a condensed, purpose-built summary of that work for review — not a
replacement for the implementation log, which has the full reasoning behind every decision
below and is the authoritative record.

---

## 1. What changed, in one paragraph

`src/ai_trader/api.py` — a single 6,152-line module mixing HTTP transport, ~150 service
methods, and ~70 helper functions — is now `api/__init__.py` (2,828 lines of what's left) plus
six new focused modules: `api/http_server.py` (pure HTTP transport), `persistence/query_executor.py`
and `persistence/schema_once.py` (shared data-access/schema helpers), and five
`application/*_service.py` files (reporting, founder presentation, research, broker,
operations, administration). Every extraction preserved response contracts exactly — no
endpoint's behavior changed — verified by a full stable test suite run clean **twice
independently** after every single phase, not just once.

## 2. Stage/phase-by-phase summary

**Stage 0 (safety/characterization, mandatory before any extraction):**
- Proved by code trace + new test that `KILL_SWITCH_STATE` is genuinely consulted before a live
  order reaches a broker (previously an open question from the discovery pack).
- Proved order-intent locks are atomic under Postgres, not just SQLite.
- Fixed the schema-reinit-per-call bug (full `CREATE TABLE` sequence re-run on every call
  instead of once per process) in the 3 remaining modules with real hot-loop exposure, via a
  new shared `persistence/schema_once.py` helper.
- Added 21 API characterization tests covering all 17 mobile-consumed endpoints, plus a real
  mobile-source cross-check (found mobile also calls an 18th endpoint, `/benchmark-daily-brief`,
  not in the plan's named list).
- Added 7 missing safety tests (Kraken allowed-pair, capital-sleeve isolation, Alpaca
  paper-only, ambiguous-outcome lock retention, reconciliation no-fabrication) and root-caused
  + fixed a flaky test (a genuine wall-clock timing race in a worker-heartbeat check).

**Phase 1 — HTTP transport.** `ApiHandler` (auth, IP lockout, CORS, body parsing, error
envelopes, response serialization, logging) moved to `api/http_server.py`, zero dependency on
anything else in the app. Pure code-location move; every import and mock-patch target that
referenced `ai_trader.api.ApiHandler`/`LocalApiService` kept working unchanged.

**Phase 2 — Query execution.** `_connect`/`_row`/`_rows`/`_scalar`/`_count` extracted into a
`QueryExecutor` class, injected via composition (not inheritance, per the plan). The 73 existing
call sites across the file were left untouched — `LocalApiService`'s own methods became
one-line delegates ("delegation before deletion").

**Phase 3 — Reporting service.** The report pipeline (`trading_report`, `report_page`,
`generate_report`, etc.) moved to `application/reporting_service.py`. Found and correctly
*preserved* (not fixed) a real schema-reinit-per-call bug in `record_trading_report` — flagged
as a candidate for a later fix, out of scope for a pure extraction. Established the pattern
used in every later phase: cross-dependencies on not-yet-extracted `LocalApiService` state get
injected as narrow `Callable`s, never a reference to the whole service object.

**Phase 4 — Founder presentation service.** Read-only founder-facing aggregation
(`founder_experience_payload`, `world_class_evidence`, `executive_summary`,
`connection_readiness`, etc.) moved to `application/founder_experience_service.py`. Confirmed
genuinely read-only (grepped for any mutation call — zero). One extraction pass briefly deleted
three unrelated interspersed methods via an overly broad line-range edit; caught before any
test ran, fixed by reverting and redoing method-by-method.

**Phase 5 — Research service.** `run_analysis`/`run_crypto_analysis` (kept as two separate
entry points, per the plan) and the research recording/enrichment pipeline moved to
`application/research_service.py`. The Kraken AI capital-sleeve isolation logic
(`_account_context_for_broker`) was injected, not duplicated, so that safety-critical logic
keeps exactly one implementation anywhere in the codebase. Two design bugs (stale bound-method
captures instead of live-reading lambdas; two "private" methods removed instead of delegated
because AST analysis doesn't see test-file-only callers) were caught by running the suite and
fixed.

**Phase 6a — Broker service.** 23 broker-presentation methods moved to
`application/broker_service.py`. Four methods were deliberately *not* moved after inspection —
one (`_adapters`) because moving it would deadlock construction order, and three because they
mutate trading-state authorization rather than presenting it (see the correction in Phase 7
below — this reasoning was later found to be inconsistently applied to the phase's own
instructions).

**Phase 6b — Operations service.** 13 methods (`status`, `notifications`, `operations_health`,
`phase5_status`, `sprint6_status`, etc.) moved to `application/operations_service.py`.
`reconcile_on_startup` was correctly excluded (it writes lifecycle events and notifications — a
genuine mutation, not presentation). `autonomous_activity` was found to be pre-existing dead
code (the `/autonomous-activity` route actually calls `production_activity` instead) — moved
as-is, not fixed. Zero fix-cycle: every test passed first try.

**Phase 7 — Administration service, plus a correction to Phase 6a.** See §3 below — this is the
one item in this checkpoint that most needs review.

## 3. The one thing that went wrong, and how it was caught and fixed

While scoping Phase 7, a review against the plan's own Phase 7 list ("broker auto-trading
settings," "guarded lock release") found that Phase 6a's fork instructions had been written
from only Phase 6's one-sentence plan description, without cross-checking Phase 7's explicit
list. As a result, four genuinely *mutating* methods had been placed in
`application/broker_service.py`, which the plan's Section 5 dependency rule 4 requires to stay
presentation-only ("may read operational state but must not mutate trading state"):
`set_broker_auto_trading`, `_render_api_json`, `_sync_broker_auto_trading_to_render`, and
`release_order_intent_lock_for` (the last is explicitly a "guarded" action per its own
docstring, and per this exact plan section's wording).

This was corrected as part of Phase 7: all four moved a second time into the new
`application/administration_service.py`, where the plan's own list already said they belonged.
No functional bug ever existed — behavior was identical either way, tests passed throughout —
this was purely an architectural-boundary violation (a mutation sitting in what's meant to be a
read-only service), caught by re-reading the plan before starting the next phase rather than by
a test failure.

Separately, the fork that started Phase 7 was terminated mid-task by a session usage limit
after completing both code moves but *before* wiring the new service into
`LocalApiService.__init__`'s constructor/imports/delegates — leaving the working tree in a
genuinely broken intermediate state (delegates pointing at methods that no longer existed).
This was completed and fully re-verified before committing; see the Phase 7 log entry for the
full account.

## 4. As-built module map

```
src/ai_trader/
  api/
    __init__.py                    2,828 lines  (LocalApiService + remaining routing/helpers)
    http_server.py                   143 lines  (ApiHandler — pure HTTP transport)
  application/
    reporting_service.py             903 lines  (Phase 3)
    research_service.py              933 lines  (Phase 5)
    broker_service.py                990 lines  (Phase 6a)
    founder_experience_service.py    649 lines  (Phase 4)
    operations_service.py            389 lines  (Phase 6b)
    administration_service.py        212 lines  (Phase 7)
  persistence/
    query_executor.py                 55 lines  (Phase 2)
    schema_once.py                    76 lines  (Stage 0)
  [existing domain modules unchanged: orchestrator.py, multi_broker.py,
   trading_intelligence.py, production_spine.py, operational_truth.py,
   portfolio_intelligence.py, kraken_reconciliation.py, production_evidence.py,
   always_on.py, foundation.py, sprint6.py]
```

`api/__init__.py`'s remaining 2,828 lines are entirely Phase 8 scope (execution: `approve_and_execute`,
autonomous recommendation execution, managed-exit monitoring, forced managed exits) plus
whatever thin delegate wrappers point at the six extracted services.

## 5. Verification methodology used throughout

Every phase followed the same discipline, refined slightly after each phase's review:
1. AST call-graph analysis (not grep-proximity) to determine what's genuinely exclusive to a
   given cluster before moving it — this caught false positives in Phases 3 and 4.
2. Cross-check `tests/*.py` for direct external callers of "private" methods before removing
   rather than delegating them — a gap found in Phase 5 (AST analysis alone doesn't see
   test-file callers) and applied to every phase since.
3. Method-by-method edits (exact `def`-to-next-`def` boundaries), never a blind wide-range
   replace — after Phase 4's fork briefly deleted unrelated interspersed methods this way.
4. Delegation before deletion: every extracted method's `LocalApiService` counterpart became a
   one-line delegate, not a deletion, so the GET/POST route dispatch table never needed to
   change across any of the 7 phases.
5. Narrow `Callable` injection for any dependency on not-yet-extracted state — never a
   reference to the whole `LocalApiService` object — wired as call-time lambdas (not captured
   bound methods) after Phase 4/5 found tests monkeypatch instance attributes post-construction.
6. Full stable suite run clean **twice independently** after every phase (once by whichever
   agent did the extraction, once again independently by the coordinating session before
   committing) — 286/286 passing at every checkpoint from Phase 3 onward (245 at Stage 0, growing
   as new tests were added).
7. Every phase's commit was reviewed line-by-line by the coordinating session before being
   made — including one case where a fork committed without waiting for review (flagged,
   verified after the fact, content was correct) and prompts for every subsequent phase were
   strengthened accordingly.

## 6. Test coverage added this effort

- `tests/test_schema_once.py` (5 tests, new)
- `tests/test_api_contract_characterization.py` (21 tests, new — all 17 named mobile endpoints
  plus the discovered 18th)
- `tests/test_query_executor.py` (9 tests, new)
- 7 new safety tests added to existing files (`test_guardrails.py`, `test_multi_broker_platform.py`,
  `test_orchestrator.py`, `test_world_class_transformation.py`)
- `test_phase5_production_spine.py` — flaky test root-caused and fixed
- Various test files updated to track moved call sites (patch targets, monkeypatch targets) —
  all confirmed to be mechanical consequences of the code moves, not behavior changes

Suite size: 245 tests at the start of Stage 0 → 286 tests now.

## 7. Specifically what would be useful to hear back on

1. **Does the Phase 6a correction (§3) fully resolve the dependency-rule-4 concern**, or is
   there anything else in `broker_service.py`/`operations_service.py` worth a second look before
   Phase 8 builds on top of them?
2. **Is the "delegation before deletion" residue acceptable to carry into Phase 8**, or should a
   cleanup pass (removing the now-73+ thin wrapper methods and pointing internal callers at the
   services directly) happen first? The plan's own Section 11 treats this as intentional
   ("old body removed in a later commit"), but Phase 8 is the last one, so if cleanup is wanted
   at all, this is close to the last natural point to do it before or alongside Phase 8 rather
   than after.
3. **The duplicated small helper functions** (`_broker_label`, `_money_text`, `_human_time`,
   `_broker_trade_payload`, etc. — each duplicated 2-3 times verbatim across sibling
   `application/*` files to avoid circular imports) — acceptable as a permanent pattern, or
   worth a `application/_shared_presentation_helpers.py`-style consolidation at some point?
4. **Anything specific you want gated or double-checked before Phase 8 begins**, given it's the
   phase that touches `approve_and_execute`, autonomous execution, and managed-exit monitoring —
   the actual order-placement path.

## 8. Reference

- Architecture plan: `architecture/AI_TRADER_MODULARISATION_ARCHITECTURE_2026-08-02.md`
- Discovery pack (pre-work): `architecture/AI_TRADER_MODULARISATION_DISCOVERY_PACK_2026-08-02.md`
- Full implementation log: `governance/IMPLEMENTATION_LOG.md` (lines 1–666 are this effort;
  everything below is earlier, unrelated work)
- Commits: `git log d732ba35^..8f586093 --oneline` (10 commits, all local, not pushed/deployed)
