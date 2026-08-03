# AT-ED-010 Test Report

## Backend (Python)

Full suite run clean, twice independently, after every commit in this effort:

| Point in the work | Result |
|---|---|
| After backend perf fixes (`2b50a9cb`) | 309 passed, 0 failed |
| After mobile fixes (`23c0733c`, combined) | 309 passed, 0 failed |
| After schema-comment hotfix (`2027c4b5`) | 309 passed, 0 failed |
| After the real root-cause fix + new regression test (`4a1c7ca0`) | 310 passed, 0 failed |
| After diagnostic cleanup (`eef7994a`) | 310 passed, 0 failed |

New tests added this effort (8 total):
- `tests/test_always_on_operations.py`: 3 tests proving the `SCHEDULED_JOB_RUNS` index exists,
  the query plan uses it (not a full table sort), and `list_job_runs`' contract/ordering is
  unchanged at scale (3,000 seeded rows, asserts sub-0.5s).
- `tests/test_multi_broker_platform.py`: 4 tests proving `broker_panels()` reuses already-fetched
  Kraken prices instead of a redundant call, batches per-row pricing into one call, and degrades
  gracefully (not a hang) when pricing fails.
- `tests/test_phase5_production_spine.py`: 1 test seeding 50 historical worker rows plus one
  fresh row, proving the result is healthy with zero incidents created — the direct regression
  test for the real root-cause bug.

Safety-critical categories re-verified as part of this effort's full-suite runs (not re-listed
individually here — unchanged from the Phase 8/Phase 9 verification already on record in
`governance/IMPLEMENTATION_LOG.md`): Alpaca paper-only, Kraken isolated capital/pair/size/
buy-only/max-open-trades limits, reconciliation hold, kill switch, order-intent locking
(acquisition, duplicate prevention, definite-release, ambiguous-retention), managed exits, forced
exits, and all 20 API contract characterization tests.

## Mobile (JavaScript)

- `mobile/lib/refreshState.test.js`: **19/19 passed** (new).
- `mobile/lib/founderPresentation.test.js`: **24/24 passed** (pre-existing, unchanged — confirms
  no regression to existing presentation logic).
- `npx expo-doctor`: **17/17 checks passed** (this project's established mobile validation step).
- `App.js` compiled successfully through the project's actual `@babel/core` +
  `babel-preset-expo` build toolchain directly (not just `expo-doctor`) — zero syntax errors.

## What was not tested

No live device/emulator install-and-manual-test pass was performed as part of this verification
round; mobile correctness was established via unit tests of the extracted pure logic plus direct
code-path tracing of `App.js`'s render/state wiring, not an end-to-end UI test. The Founder
installing the built APK and confirming the new states render as described is the remaining
verification step, outside what an automated session can confirm.

No test in this entire effort submitted a real order to Kraken or Alpaca.
