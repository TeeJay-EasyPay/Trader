# Production Evidence Test Report

Date: 2026-07-19

## Automated results

| Check | Result |
|---|---|
| Focused production evidence and Always-On tests | 15 passed |
| Complete Python test suite | 147 passed |
| Python compilation | Passed |
| Expo Doctor | 17/17 passed |
| Android Expo export | Passed |

The suite covers shared evidence schema creation, research and recommendation persistence, broker snapshots, trade evidence, learning evidence, Founder payload reconstruction, API routing and duplicate trade-event idempotency. Existing tests continue to cover orchestration, guardrails, broker behavior, reports, mobile contract helpers and failure fallbacks.

The hosted Kraken research failure `EQuery:Unknown asset pair` produced an additional regression test proving that an unavailable pair is skipped rather than terminating the complete research cycle.

Expected exception logs in the complete suite are deliberate simulated timeout/failure tests. They did not fail the suite.

## Truthfulness assertions

- Duplicate broker evidence does not create duplicate projected trade rows.
- Empty source evidence remains empty/unavailable.
- Worker jobs and evidence can be reconstructed by an API process sharing the same database.
- No projection path submits a broker order.
- No P&L is synthesized when source evidence lacks it.

## Remaining live tests

Render worker cadence, Supabase latency, broker data completeness, installed-device startup time and Expo OTA behavior require hosted deployment. They are listed in `PRODUCTION_EVIDENCE_LIVE_VERIFICATION.md` and must not be claimed from local tests.
