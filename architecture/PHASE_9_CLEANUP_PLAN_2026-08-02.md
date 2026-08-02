# Proposed Phase 9 — Cleanup (plan only, not executed)

**Status: proposal, not started.** Written per the Phase 8 directive's instruction to produce a
"short proposed Phase 9 cleanup plan" after Phase 8 passes, without removing any wrapper or
consolidating any helper in the same commit. Nothing in this document has been done yet.

## Current state (as of the end of Phase 8)

| File | Lines |
|---|---|
| `src/ai_trader/api/__init__.py` | 2,332 |
| `src/ai_trader/api/http_server.py` | 143 |
| `src/ai_trader/application/broker_service.py` | 990 |
| `src/ai_trader/application/research_service.py` | 933 |
| `src/ai_trader/application/reporting_service.py` | 903 |
| `src/ai_trader/application/execution_service.py` | 711 |
| `src/ai_trader/application/founder_experience_service.py` | 649 |
| `src/ai_trader/application/operations_service.py` | 389 |
| `src/ai_trader/application/administration_service.py` | 212 |
| `src/ai_trader/persistence/schema_once.py` | 76 |
| `src/ai_trader/persistence/query_executor.py` | 55 |

`api/__init__.py` started this effort at 6,152 lines (as `api.py`, before Stage 0). It now
contains: `LocalApiService.__init__` and construction of all 7 application services, the
GET/POST route dispatch table, ~50 thin compatibility delegate methods, and the presentation
code not yet assigned to any service (`recommendations()`, `portfolio()`, `founder_brief()`,
`_account_context_for_broker`, the Kraken wallet-pricing subsystem, `_control_state`,
`_proposal_broker`, and others).

## 1. Compatibility delegate wrappers

Approximately 50 methods in `api/__init__.py` are one-line delegates to an extracted service
(`return self._X_service.method(...)`), left in place across every phase per "delegation before
deletion." They fall into three categories - a full audit categorizing every one of the ~50 is
the first concrete task of Phase 9 itself (not done here), but the pattern is:

- **Still genuinely needed** (cannot be removed without also changing another file): delegates
  called from the GET/POST route dispatch table (`self.approve_and_execute(body)` etc. - dozens
  of these), from `run_server()`'s scheduled `IntervalWorker`/`ResearchScheduler` wiring
  (`poll_broker_activity`, `monitor_managed_exits`, `refresh_crypto_universe`, etc.), from
  `cli.py` (`auto_execute_recommendations_alpaca`/`_kraken`, `refresh_strategy_lab`), or from
  tests that call `service.method_name(...)` directly (the majority of the ~50).
- **Candidates for removal**: any delegate whose only callers turn out to be *other delegates in
  this same file* rather than an external route/worker/test - none were found to fit this
  description during Phase 8's own audit of the 10 methods it touched, but the other ~40 have
  not been individually re-checked since their originating phase.
- **Already correctly removed, not delegated**: methods with a single containing caller that
  also moved (e.g. `_proposal_with_manual_amount`, `_manual_approval_auto_config`,
  `_auto_config_for_broker` in Phase 8; similar single-caller removals happened in Phases 3-7).

**Phase 9 action**: grep every one of the ~50 delegate names across `api/__init__.py`'s own route
dispatch table, `run_server()`, `cli.py`, and `tests/*.py` (the same check every phase has
already done for its own newly-moved methods) to produce a definitive keep/remove list, then
remove only the ones with zero external callers. Removing a delegate that still has an external
caller would break that caller, so this must be re-verified per-delegate, not assumed from this
summary.

## 2. Duplicated presentation helpers

Small pure formatting/config helpers are currently duplicated verbatim across sibling
`application/*.py` files rather than imported cross-service, per the convention established in
Phase 3 (avoids a circular import at module load time). Known duplicates as of Phase 8:

| Helper | Duplicated in |
|---|---|
| `_broker_label` | `reporting_service.py`, `founder_experience_service.py`, `broker_service.py` |
| `_money_text` | `reporting_service.py`, `founder_experience_service.py` |
| `_estimated_in_positions` | `reporting_service.py`, `broker_service.py` |
| `_broker_trade_payload` | `reporting_service.py`, `broker_service.py` |
| `_broker_trade_symbol` | `reporting_service.py`, `broker_service.py` |
| `_int_or_default` | `research_service.py`, `operations_service.py`, `execution_service.py` |
| `_csv_env` | `research_service.py`, `broker_service.py` |

**Phase 9 action**: if consolidated, these would move into one new shared module (e.g.
`application/_shared_presentation_helpers.py` or `persistence`-adjacent `formatting.py`) that
every `application/*.py` file imports from - a genuine dependency each service is allowed to
share, unlike importing from a peer service directly. This is import-safe (no service currently
imports from another service, so introducing one shared leaf module doesn't create a cycle) but
is pure code-hygiene with no behavior change, and was explicitly out of scope for Phase 8 per the
Founder/ChatGPT review decision ("do not introduce a shared helper module merely for tidiness in
this phase").

## 3. Dead code found

- **`autonomous_activity`** (`application/operations_service.py`, moved as-is in Phase 6b): zero
  callers anywhere in the codebase (route dispatch, tests, or elsewhere). The `/autonomous-activity`
  route actually calls `production_activity` instead. Not fixed or removed during extraction, per
  "do not mix feature fixes into the extraction." Phase 9 could remove it outright once confirmed
  still uncalled, or leave it - it is inert either way, not a safety concern.
- No other dead code was found during Phase 8's own extraction. A dedicated dead-code sweep
  across the other 6 already-extracted services has not been performed and would need its own
  pass if wanted.

## 4. Final module-size and dependency check

- `api/__init__.py` is now 2,332 lines, down from the original 6,152-line `api.py` (-62%).
- Dependency direction has held throughout: `api/*` depends on `application/*`, `application/*`
  depends on domain modules and `persistence/*`, no `application/*` file imports another
  `application/*` file (verified by the duplicated-helper pattern above being necessary at all -
  if a lateral import existed, duplication wouldn't have been needed).
- No circular imports exist anywhere in the new structure (confirmed at every phase by successful
  `python -c "from ai_trader.api import LocalApiService"` at minimum, and by the full test suite
  importing every module transitively).
- Safety-critical single-implementation invariants held throughout: Kraken capital-sleeve
  isolation (`_account_context_for_broker`/`_kraken_trading_allocation_gbp`), order-intent
  locking (`multi_broker.py`), the kill switch (`sprint6.py`), and the reconciliation hold
  (`kraken_reconciliation.py`) each still have exactly one implementation, injected into every
  service that needs them rather than duplicated.

## Explicitly not part of Phase 9

Per the Phase 8 directive: no visual redesign, no database cleanup, no task-queue migration, no
new trading functionality. Phase 9, if authorized, is restricted to items 1-4 above only.
