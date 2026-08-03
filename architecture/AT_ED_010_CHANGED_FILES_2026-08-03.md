# AT-ED-010 Changed Files

Cumulative diff across all 7 commits (`96e4cfd7^..01b2a2fc`): 11 files changed, 1,354 insertions,
66 deletions.

| File | Change |
|---|---|
| `engineering-directives/implementation/AT-ED-010_UI_DATA_FRESHNESS_AND_EVIDENCE_ALIGNMENT.md` | New — the directive itself, produced by the read-only investigation |
| `governance/IMPLEMENTATION_LOG.md` | +229 lines across 3 entries (investigation, mobile, backend+bugs) |
| `mobile/App.js` | Rewrote `refresh()` into the live/cached state machine; new header UI states |
| `mobile/lib/refreshState.js` | New — pure state-classification logic (128 lines) |
| `mobile/lib/refreshState.test.js` | New — 19 tests (191 lines) |
| `src/ai_trader/always_on.py` | Added `SCHEDULED_JOB_RUNS` index (both schema strings); fixed the semicolon-in-comment bug |
| `src/ai_trader/application/broker_service.py` | `broker_panels()` concurrent fetch + graceful degradation + pricing batching |
| `src/ai_trader/production_spine.py` | Fixed `supervise_workers` to use `classify_worker_presence`, eliminating the incident write-amplification loop |
| `tests/test_always_on_operations.py` | +3 tests proving the index/query-plan fix |
| `tests/test_multi_broker_platform.py` | +4 tests proving `broker_panels()` batching/degradation |
| `tests/test_phase5_production_spine.py` | +1 regression test proving historical worker rows never trigger incidents |

No file outside `mobile/`, `src/ai_trader/{always_on,application/broker_service,production_spine}.py`,
`tests/`, `governance/`, and `architecture/`/`engineering-directives/` documentation was touched.
No domain module governing trading, risk, or execution decisions
(`orchestrator.py`, `multi_broker.py`, `sprint6.py`, `guardrails.py`, `broker_adapters.py`,
`kraken_reconciliation.py`, `foundation.py`) appears anywhere in this diff.
