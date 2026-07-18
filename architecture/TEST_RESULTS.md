# Test Results

## 2026-07-18 Sprint 6 Institutional Production Control

Commands run:

```text
python -m compileall src
python -m unittest tests.test_sprint6_institutional_spine
python -m unittest discover -s tests
npx expo-doctor
```

Results:

- Compile: passed.
- Focused Sprint 6 tests: passed, 9/9.
- Full Python suite: passed, 133/133.
- Expo Doctor: passed, 17/17.

Covered:

- Strategy entitlement allows paper and blocks unpromoted micro-live.
- Kill switch blocks before broker submission.
- Decision journal persistence.
- Broker event normalization idempotency.
- Learning outbox idempotency.
- Incident lifecycle deduplication.
- Founder operational report persistence.
- Sprint 6 API status endpoint.
- SQLite limitation is reported in status.

Not covered by local tests:

- Render hosted worker soak.
- Supabase/Postgres end-to-end runtime sharing.
- Real Alpaca paper fill reconciliation.
- Real Kraken terminal-trade learning.
- Installed mobile app validation after OTA.

Date: 2026-07-18

## Commands Run

```text
python -m compileall src
python -m unittest tests.test_phase5_production_spine
python -m unittest tests.test_always_on_operations
python -m unittest discover -s tests
npx expo-doctor
```

## Results

- Python compile: passed.
- Phase 5 focused tests: 9 passed.
- Always-On operations tests: 10 passed.
- Full Python test suite: 124 passed.
- Expo Doctor: 17/17 checks passed.

## Phase 5 Coverage

Tests cover:

- partial production database spine reporting;
- stale worker incident generation;
- idempotent canonical reconciliation;
- closed-loop learning idempotency;
- governed learning proposal boundary;
- portfolio manager concentration authority;
- market-data quality blocking;
- strategy promotion and demotion gates;
- API exposure of `/phase5-status`.

## Not Yet Proven

The following require live deployment validation:

- Render worker heartbeat while the phone is closed;
- scheduled cron execution in Render;
- Supabase/Postgres as the shared datastore for every runtime family;
- live Alpaca paper reconciliation after a fresh order;
- live Kraken reconciliation after broker polling;
- Expo OTA installation verification.
