# AT-ED-010 Implementation Summary

**Directive**: `engineering-directives/implementation/AT-ED-010_UI_DATA_FRESHNESS_AND_EVIDENCE_ALIGNMENT.md`,
per ChatGPT's follow-up "restore truthful LIVE operation" mission statement (2026-08-03).

## Scope executed

**Mobile (requirements 1-3)**: rewrote `mobile/App.js`'s `refresh()` into an explicit state
machine — attempt live fetch, one bounded retry on failure, then branch to apply-live or
apply-cached, with every path recording whether the result was live or a failure. New
`mobile/lib/refreshState.js` derives one of six distinct UI states (Live / Refreshing / Cached /
Backend Snapshot Stale / Refresh Failed / No Data Available) and centralizes their labels/tones
and the cache-staleness banner content. New 2-minute background auto-refresh gives a
Cached/Failed state a path back to Live without manual intervention. `AsyncStorage` cache
envelope changed to `{data, fetchedAt}` (backward-compatible with the pre-existing format) so the
app can report its own cache age distinctly from the backend's evidence-snapshot age.

**Backend performance (requirements 4-5)**: added an index supporting `list_job_runs`' existing
`ORDER BY COALESCE(...)` clause (measured ~100x locally); made `broker_panels()` fetch each
broker's portfolio concurrently on Postgres (mirroring an already-proven pattern from
`capture_production_broker_snapshots`), with graceful per-broker degradation on failure, plus
removed a redundant live Kraken pricing call and batched two per-row pricing loops.

**Two additional bugs found and fixed during production verification, not part of the original
directive scope but required to actually achieve it**: a semicolon inside a SQL comment that
broke `initialize_always_on_schema` on every call (introduced by this same round of work, caught
same-day); and the real root cause of `/status`/`/phase5-status` hanging — `supervise_workers`
treating every historical (dead, past-deploy) worker heartbeat row as currently stale and
writing an incident for each one, fixed by routing through the already-existing
`classify_worker_presence` helper. See `governance/IMPLEMENTATION_LOG.md` for the full,
detailed account of both, including how each was found.

## What was explicitly not done

No trading, risk, governance, execution, kill-switch, Kraken-limit, or capital-allocation logic
was touched anywhere in this work. No database tables were dropped, renamed, or migrated — only
one additive index was created. No new infrastructure or task queue was introduced. `/brokers`'s
remaining slowness (improved but not fully resolved) was investigated but not conclusively
root-caused within this session's scope, and is documented as a known follow-up rather than
forced to a premature fix.

## Commits

```
96e4cfd7 Add AT-ED-010: UI data freshness investigation findings and remediation proposal
2b50a9cb AT-ED-010 (4-5): fix job-history query and broker_panels performance
23c0733c AT-ED-010 (1-3): truthful live/cached state machine for the mobile app
2027c4b5 Hotfix: remove semicolons from SQL comments breaking Postgres schema init
4a1c7ca0 Fix the real cause of /status and /phase5-status hanging: unbounded incident writes
eef7994a Remove temporary diagnostic timing from phase5_status
01b2a2fc Document the two production bugs found and fixed during AT-ED-010 verification
```

All pushed to `origin/master` and deployed. Mobile APK built via EAS (`hosted-preview` profile)
and available at https://expo.dev/artifacts/eas/zIbnM0cNh-w0IN9Yy7NKK3Z8F1ME2qnUEq4WCOFtDE4.apk.
