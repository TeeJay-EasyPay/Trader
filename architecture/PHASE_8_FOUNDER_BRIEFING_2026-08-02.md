# Phase 8 Founder Briefing — Execution Service Extraction

**2026-08-02. Highest-risk phase of the modularisation effort. Not deployed.**

## What this phase did

This was the last of 8 phases reorganizing the app's single 6,152-line core file into smaller,
focused pieces. Phase 8 specifically moved the code that actually places and manages trades —
the part everyone agreed needed the most care, which is why it was done last and why a
pre-authorized directive from ChatGPT with detailed safety requirements was followed step by
step.

**Moved into a new file** (`application/execution_service.py`):
- Approving and executing a trade manually
- Autonomous (fully-automatic) trade execution for both Alpaca and Kraken
- Watching open Kraken positions and closing them when a stop-loss or take-profit is hit
- Manually forcing a position closed
- The small support checks these rely on (has this proposal already been executed, what's the
  auto-trade config for this broker)

**Did not move — this stays exactly where it was, and still makes every real decision:**
- The actual approve/reject logic (strategy rules, risk limits, portfolio limits, the kill
  switch) — all still lives in the original governance code, completely untouched
- Order-intent locking (the mechanism that stops the same order being submitted twice) — still
  the original code, untouched
- The Kraken reconciliation hold check — still the original code, untouched
- Kraken's buy-only / allowed-pair / order-size checks — still inside the Kraken adapter, untouched
- The £100 isolated Kraken capital calculation — deliberately kept as a single piece of code
  used by every part of the app that needs it, not copied

This phase only moved *where the code that calls into all of the above lives*, not what any of
it decides.

## Safety controls verified, not just assumed

Before moving anything, existing test coverage was checked against six safety categories
(paper-only Alpaca behaviour, Kraken capital/pair/size/lock limits, order-intent locking,
kill-switch/entitlement/risk rejection, managed-exit correctness, and API compatibility). Almost
all of it was already well covered by tests written in earlier sessions. One real gap was found
and filled: nothing proved that a Kraken trade actually gets blocked when the reconciliation
hold is active — only that the hold mechanism itself defaults to safe. A new test proves this
end to end, and as a side effect confirmed something reassuring: the hold defaults to **on**
(blocking) on a fresh setup, not off — it fails safe by default.

## Tests

- 1 new test added (the reconciliation-hold gap above)
- Full test suite: **287 passed, 0 failed**, run clean twice independently
- The two safety-critical test files (60 tests) and all 20 API-contract tests re-run individually
  for extra confidence — all unchanged
- No real Kraken order was placed by any test — all tests use fake/simulated broker connections

## Numbers

- `api/__init__.py`: 6,152 lines at the start of this whole effort → **2,332 lines** now
- New file `execution_service.py`: 711 lines

## What's left (not done in this phase, by design)

A cleanup plan has been written (not executed) covering: removing now-unused compatibility
wrappers, merging a handful of small duplicated helper functions, and one piece of dead code
found (an unused method, harmless, doesn't affect anything). None of this changes behaviour —
it's tidying, deliberately left for a separate, explicitly-authorized pass.

## Unresolved risk

None identified specific to this phase. The one pre-existing bug found in an earlier phase
(a report-generation function re-running its database setup on every call — a performance
inefficiency, not a safety issue) remains open and undisturbed, exactly as before.

## Status

Nothing has been pushed or deployed. All work is committed locally only, pending your and
ChatGPT's review of the complete modularised codebase, per the agreed process.
