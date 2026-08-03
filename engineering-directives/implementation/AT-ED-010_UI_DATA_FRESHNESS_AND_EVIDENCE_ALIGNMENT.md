# AT-ED-010 — UI Data Freshness and Evidence Alignment

## Project

AI Trader

## Directive Title

UI Data Freshness and Evidence Alignment

## Objective

Close the gap between genuinely fresh, correctly-produced backend evidence and what the Founder
actually sees in the mobile app, by (1) making cache/staleness state visible instead of silent,
and (2) fixing two confirmed pre-existing backend performance problems that were found — but
deliberately not fixed — during the 2026-08-02/03 Phase 9 read-only investigation.

## Current State

As of 2026-08-03, Stage 0 through Phase 9 of the backend modularisation
(`architecture/AI_TRADER_MODULARISATION_ARCHITECTURE_2026-08-02.md`) are complete, committed,
and deployed to production (commit `8879aca9`, both Render services confirmed running it).

A read-only production investigation (see `governance/IMPLEMENTATION_LOG.md`, Phase 9 items 5-9
entry, and the investigation this directive is drawn from) found that **the backend evidence
data itself is genuinely fresh and correctly produced right now** — confirmed directly against
the hosted API: the Founder-evidence timeline contains 100 real, recent activity items (job
completions from the last few minutes at the time of checking), the Kraken reconciliation hold
is correctly `false`, the Kraken capital ledger correctly shows the full allocation available
with zero open positions, and scheduled jobs are actively running. This means the Founder's
long-standing reports of "Not available," zeroed activity cards, and stale broker info are **not
explained by backend data production failing** — the investigation traced the actual mechanism
instead.

## Governing Documents

- Constitution: `architecture/AI_TRADER_FOUNDING_PRINCIPLES_ARCHITECTURE_CONSTITUTION_v1.0.md`
- `architecture/AI_TRADER_MODULARISATION_ARCHITECTURE_2026-08-02.md`
- `architecture/MODULARISATION_COMPLETE_FINAL_REVIEW_2026-08-02.md`
- `architecture/PHASE_9_FOUNDER_BRIEFING_2026-08-03.md`
- `governance/IMPLEMENTATION_LOG.md` (Phase 9, items 5-9 and 1-4 entries specifically)

## Scope

In scope: `mobile/App.js` (client-side staleness visibility and timeout/retry behaviour),
`src/ai_trader/production_spine.py` (`supervise_workers`'s job-history query performance),
`src/ai_trader/application/broker_service.py` (`broker_panels()`'s live-pricing call path).

Explicitly out of scope: any change to trading logic, risk/governance/kill-switch/reconciliation
controls, Kraken capital-isolation logic, order-intent locking, or any other authoritative
safety mechanism. No visual redesign. No new features beyond what is listed below. No database
schema changes beyond adding an index if genuinely required for finding 2 (see below) — no table
drops, renames, or data migrations.

## Required Review

Before modifying any code, review:

- [ ] Constitution
- [ ] `architecture/AI_TRADER_MODULARISATION_ARCHITECTURE_2026-08-02.md` (the app's current
      module structure — this directive assumes the post-Phase-9 layout)
- [ ] `governance/IMPLEMENTATION_LOG.md`, the Phase 9 entries specifically
- [ ] Current Git status and current branch
- [ ] `mobile/App.js`'s `refresh()` function (around line 614) and `request()` function
      (around line 560) in full, before changing either

## Findings This Directive Is Based On

**Finding 1 (confirmed, high confidence) — silent stale-cache fallback with no staleness
indicator.** `mobile/App.js`'s `refresh()` fetches `/founder-evidence` with an 18-second client
timeout (`PRIMARY_REFRESH_TIMEOUT_MS`). On any failure — timeout, network error, non-200
response — the app silently falls back to `loadCachedFounderEvidence()` (local `AsyncStorage`)
and renders that cached data with **no indication anywhere in the UI that the displayed data is
not live**. On app launch, cached data is shown immediately, before the live fetch even starts.
This means any transient network hiccup or slow response is indistinguishable, from the
Founder's point of view, from "the backend has stopped producing data" — which is exactly what
has been reported for weeks, even on days when the backend (independently verified) was
completely healthy.

**Finding 2 (confirmed, pre-existing, not caused by any part of this modularisation effort) —
three endpoints hang for ~60 seconds.** `/status`, `/phase5-status`, and `/brokers` consistently
time out in production (confirmed via direct hosted testing, both immediately after the Phase 9
deploy and on retry). Root cause: `production_spine.supervise_workers` (called by both
`/status` and `/phase5-status`) queries `SCHEDULED_JOB_RUNS`-family history against
approximately 12,000 accumulated rows, plausibly a missing-index/table-scan problem at this data
volume. `/brokers` calls `broker_panels()`, which likely blocks on a live external Kraken/Alpaca
pricing round trip. Confirmed via source-diff review that neither code path was touched by any
of the 12 commits in the Stage 0 - Phase 9 effort — this predates that work. The mobile app does
**not** call any of these three endpoints directly today (confirmed by cross-referencing every
`mobile/App.js` fetch call against the backend route table), so this is not the direct cause of
the reported symptoms, but it is a real, user-facing-adjacent performance bug worth fixing on
its own merits, and a future feature that does call one of these three would inherit the same
failure.

**Finding 3 (design confirmation, working as intended, not a bug) — the Founder-evidence
snapshot is deliberately not computed live.** `production_evidence.founder_evidence_payload`
reads a worker-persisted snapshot (refreshed roughly every 5-10 minutes by the `evidence-snapshot`
job, self-flagged stale past 15 minutes via a `snapshot.stale`/`status.state = "OPERATING WITH
WARNINGS"` mechanism the backend already computes). This is intentional, documented
("Hosted mobile reads should never reconstruct the complete Founder view on demand") and
correctly working — the live snapshot checked during this investigation was 8.6 minutes old
against a 5-minute expected cadence, not flagged stale. However, the mobile app does not
currently surface the `snapshot.age_seconds`/`generated_at` fields it already receives in the
payload anywhere in the UI — see Requirement 3 below.

## Implementation Requirements

1. **Add a visible staleness/cache indicator to the mobile app.** When `refresh()` falls back to
   cached data (the `catch` block in `refresh()`, and the initial-load cached-data path), the UI
   must show the Founder that displayed data is cached, and how old it is (e.g. a banner or
   inline label: "Showing cached data from [time] - last live refresh failed: [reason]"). This
   must be visually distinct from a genuinely fresh, live-refreshed screen. Do not silently
   merge cached and live states as the current code does.
2. **Reconsider the 18-second primary timeout.** Confirm (via the hosted API, at a range of
   times of day, including if possible around when the evidence-snapshot job is mid-run) what a
   realistic p95/p99 response time for `/founder-evidence` actually is, and set
   `PRIMARY_REFRESH_TIMEOUT_MS` accordingly with margin - or add one bounded retry with backoff
   before falling back to cache, whichever better fits the measured latency distribution. Do not
   pick a number without measuring first.
3. **Surface the existing `snapshot.age_seconds`/`snapshot.generated_at`/`snapshot.stale` fields
   the backend already returns.** The backend already computes and returns this; the mobile app
   currently ignores it. Show it plainly on at least the Dashboard/Command screen (e.g. "Evidence
   as of [time], Xm ago").
4. **Fix `production_spine.supervise_workers`'s job-history query performance** (Finding 2, the
   `/status`/`/phase5-status` hang). Profile `list_job_runs`/whatever query is actually slow at
   current production data volume; add an index if that's the root cause, or bound/paginate the
   query if it's an unbounded scan issue. Preserve the function's existing return contract
   exactly - this is a performance fix, not a redesign, per Phase 3-9's established "delegation
   before deletion" / "do not move and redesign simultaneously" discipline.
5. **Fix or bound `broker_panels()`'s live-pricing call path** (Finding 2, the `/brokers` hang).
   Add an explicit timeout around the external Kraken/Alpaca pricing call so a slow upstream API
   degrades to a clear "price unavailable" response within a few seconds, not a 60-second hang.
   Do not change what `broker_panels()` returns on the success path.

## Safety Boundaries

Preserve:

- Constitution and governance;
- auditability;
- production safety;
- every existing safety mechanism (kill switch, order-intent locking, strategy entitlement,
  portfolio/risk rejection, Kraken capital-sleeve isolation, the Kraken reconciliation hold,
  buy-only/allowed-pair/order-size enforcement);
- evidence lineage;
- deterministic behaviour;
- the `founder_evidence_payload` snapshot-serving design itself (Finding 3 is not a bug to fix,
  it's a working mechanism to make more visible).

Never:

- change what any endpoint's success-path response contains, beyond Requirement 3's additive
  staleness fields;
- weaken or bypass the reconciliation hold, kill switch, or any lock/entitlement/risk check to
  make an endpoint respond faster;
- introduce a new caching layer beyond what already exists (`AsyncStorage` client-side,
  `PRODUCTION_FOUNDER_EVIDENCE_SNAPSHOTS` server-side) without Founder/ChatGPT review;
- fabricate a "no error occurred" state when a real error occurred - Requirement 1 is about
  making failure visible, not hiding it more effectively.

## Testing Requirements

- [ ] Unit/characterization tests proving the cache-staleness UI state renders correctly given a
      simulated fetch failure with cached data present, and a simulated fetch failure with no
      cached data present (already partially covered by `unavailableActivity`/`unavailableStatus`
      - extend, don't replace).
- [ ] A regression test proving `supervise_workers`'s fixed query still returns the same shape of
      result it does today, just faster - measure and record the before/after query time against
      a seeded large dataset if practical.
- [ ] A test proving `broker_panels()` degrades gracefully (clear "unavailable" response, not a
      hang) when the injected Kraken/Alpaca pricing call is made to simulate a slow response.
- [ ] Full existing test suite must still pass, run clean twice independently, matching every
      prior phase's discipline in this effort.
- [ ] Document passed / failed / skipped / blocked results in the implementation log entry for
      this directive.

## Completion Criteria

- The Founder can, from the app itself, distinguish "this is live data" from "this is cached
  data from earlier, live refresh failed" without needing to ask Claude to check the backend
  directly.
- `/status`, `/phase5-status`, and `/brokers` respond in a bounded, reasonable time (single-digit
  seconds) in production, confirmed by direct hosted testing, not just local tests.
- No trading, risk, or governance behaviour changed.
- All safety and characterization tests pass.

## Required Deliverables

- Updated implementation log entry
- Updated architecture documentation, only if the as-built structure changes materially
- Testing summary
- Completed work summary
- Remaining blockers (external dependencies, Founder decisions, production approvals only)
- Git branch, commits, and files modified
- A short before/after comparison of `/status`/`/phase5-status`/`/brokers` hosted response times

## Final Instruction

This directive should only be started once explicitly authorized by the Founder (and, per this
project's established process, reviewed by ChatGPT alongside the Founder before implementation
begins) - it is a proposal produced by a read-only investigation, not a standing authorization to
implement. Do not combine this work with any other phase or unrelated fix. Stop and report back
after Requirements 1-3 (the mobile-visible staleness work) if time/session constraints require
splitting this directive - Requirements 4-5 (the two backend hangs) are independently valuable
and can be done as a separate follow-up without blocking the first three.
