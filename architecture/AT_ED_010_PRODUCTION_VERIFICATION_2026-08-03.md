# AT-ED-010 Production Verification

Direct verification against the hosted API (`https://trader-no0f.onrender.com`), all GET
requests only — no mutating call was ever made during this verification.

## Core health

| Check | Result |
|---|---|
| API `/healthz` | 200, responsive |
| Worker heartbeat | Healthy, live, new `worker_id` confirming genuine restart across each deploy |
| Scheduled jobs | Actively running (`job_run_id` observed climbing between checks); `auto-execution-kraken`, `auto-execution-alpaca`, `evidence-snapshot`, `broker-poll-alpaca`, `broker-poll-kraken`, `managed-exits` all seen running/completed |
| Research | `last_research_run.status: completed`, fresh timestamp at time of check |
| Evidence snapshots | `evidence-snapshot` job recorded running |
| Import/circular-import failures | None — full local suite (310 tests) imports every touched module transitively, clean |

## Endpoint timing (before → after)

| Endpoint | Before | After | Status |
|---|---|---|---|
| `/founder-evidence` | 3.0-3.75s (10 samples) | Unchanged — never affected by any bug found | Confirmed fast throughout |
| `/operations-health` | Erroring (Postgres syntax error, Bug 1) | 200, ~5.8s | **Fixed** |
| `/sprint6-status` | Working, ~11.6s | 200, ~11.6s | Unaffected, confirmed still healthy |
| `/phase5-status` | Unbounded hang, killed at exactly ~60.0-60.15s (Render proxy timeout) | 200, ~12.1s (`supervise_workers` alone: 5.0s, measured directly) | **Fixed** |
| `/status` | Unbounded hang, ~60s | Still slow (shares `broker_panels()` with `/brokers`) | **Partially improved, not fully resolved** |
| `/brokers` | Unbounded hang, killed at ~60.0-60.15s | Completes, ~59.7s | **Marginally improved, not resolved** |

## Safety-critical state, unchanged throughout

- Kraken reconciliation hold: `hold_new_entries: false`, same 2026-08-01 founder-authorized
  reason string, unchanged before/during/after every fix in this session.
- Kraken capital ledger: `available_cash_gbp: 100.0`, `marked_open_positions: []` throughout —
  the full isolated allocation remains available and zero positions were ever opened during this
  entire investigation.
- No real Kraken order was submitted at any point, by any test, by any production check, or by
  any deploy in this work.
- Alpaca remains paper-only (unaffected by anything in this work; not touched).

## Mobile behavior

Verified via code trace and unit tests (`refreshState.test.js`, 19/19), not a live device install
during this verification round (the Founder installs and confirms separately via the APK link).
Confirmed by direct code reading: `refresh()`'s cache-fallback path and its one bounded retry are
wired exactly as specified; the header's `StatusPill`/banner render logic reads
`classifyDisplayState`'s output on every render, not a stale snapshot.

## Not observed

Multiple full worker cycles were not observed over an extended window (e.g. hours) within this
verification session, given the time already spent on deploy-timing investigation. Job-run
evidence across several distinct scheduled-job types (research, both auto-execution jobs,
broker polls, evidence-snapshot, managed-exits) was directly confirmed running and completing
during the verification window, which is treated as sufficient evidence of a healthy, non-crash-
looping worker rather than a single isolated success.
