# Architecture Delta

This is a living document, updated at the end of each modularisation phase. It gives a rapid
architectural overview without needing to read the full implementation log.

## App.js

3,890 lines
↓
**Phase 1**
2,421 lines
↓
**Phase 2**
240 lines

## Major responsibilities removed

- All founder-evidence data fetching, retry, and cache logic
- All AT-ED-010 refresh/freshness state derivation
- Every screen's rendering, presentation, and business logic
- Every reusable card/component's rendering logic
- All trade/recommendation/market/chat formatting and text-shaping logic
- The shared API client (auth headers, timeouts, error normalisation)

## New modules

- `mobile/api/client.js` — the one authoritative `apiRequest` fetch/timeout/auth-header function
- `mobile/lib/founderEvidenceMapping.js` — `/founder-evidence` payload → screen-shape mapping
- `mobile/lib/tradeHistory.js` — trade normalisation, formatting, history summarisation
- `mobile/lib/recommendations.js` — freshness/expiry, auto-trade eligibility, filtering/grouping
- `mobile/lib/market.js` — market/orchestrator-decision presentation text
- `mobile/lib/chat.js` — Ask AI Trader text normalisation and timeout racing
- `mobile/lib/json.js` — generic JSON parse/format
- `mobile/lib/money.js`, `datetime.js`, `lists.js`, `notAvailable.js` — formatting primitives
- `mobile/lib/founderPresentation.js` — cross-screen tone/status/broker presentation logic (extended)
- `mobile/hooks/useFounderEvidence.js` — the founder-evidence data/refresh/cache state machine

## New components

- `mobile/components/shared/` — `Section`, `CollapsibleSection`, `Metric`, `TextBlock`, `Button`, `StatusPill`, `Empty`
- `mobile/components/BrokerPanel.js` — per-broker evidence card (+ `TradingPermissions`), shared by Dashboard and Portfolio
- `mobile/components/ReportPanel.js` — report evidence card, shared by Dashboard and Portfolio

## New screens

- `mobile/screens/Dashboard.js` — `ExecutiveDashboard` (+ `ConnectionReadinessCard`, `AutonomousActivitySummaryCard`)
- `mobile/screens/Activity.js` — `AutonomousActivity`
- `mobile/screens/Portfolio.js` — `PortfolioCommandCentre` (+ `TradeHistoryRow`, `TradeDetail`)
- `mobile/screens/Recommendations.js` — `Recommendations` (+ `RecommendationCard`)
- `mobile/screens/Market.js` — `MarketIntelligence` (+ `MonitoredCompaniesLinks`, `LinkedCompanyTitle`)
- `mobile/screens/Learning.js` — `LearningStrategyLab` (+ `AskAiTrader`)

## New hooks

- `mobile/hooks/useFounderEvidence.js` — all founder-evidence state, the fetch/retry/cache
  state machine, `command`/`reportCommand`, both lifecycle effects, and the header
  freshness-derivation memos. The single hook the Phase 1 discovery report identified as the
  highest-value extraction target.

## New helpers

- `mobile/lib/json.js` (`parseMaybeJson`, `formatJsonText`)
- `mobile/lib/chat.js` (`withTimeout`, `normalizeChatText`, `chatMessageText`, `chatTurnsNewestFirst`)
- 30 additional pure functions distributed across `tradeHistory.js`, `recommendations.js`,
  `market.js`, and `founderPresentation.js` (grouped by domain, not by screen, wherever a
  function is used by more than one screen)

## Remaining responsibilities in App.js

- Application bootstrap (imports, `SCREENS` constant)
- Local navigation/UI state (`screen`, `amounts`, `selectedExchange`,
  `targetRecommendationId`, `askMessages`)
- One call to `useFounderEvidence()`
- `approve()` — a thin wrapper needing the locally-owned `amounts` state
- The screen-router `content` `useMemo` (composition only — no rendering logic)
- The header/tab-bar JSX shell

## Architecture improvements

- One authoritative API client; no duplicated fetch/timeout/auth-header logic anywhere
- One authoritative founder-evidence data/refresh/cache state machine, owned by a single hook
- Every screen is now an independently readable, independently testable file
- Pure presentation/business logic is now unit-tested in isolation from React/React Native
- Zero circular imports (verified by static require-graph analysis)
- Zero unused exports or dead imports across the new module set (verified by static scan)
- One dead function (`selectedBrokerKey`, never called) identified and not carried forward

## Benefits achieved

- App.js is now a genuine application shell: bootstrap, navigation, and composition only
- A future screen or card change touches one small file, not a 2,000+ line monolith
- 169 mobile unit tests (118 new since Phase 1 began) protect the extracted logic directly
- No behaviour change: verified via real Metro bundle export (`expo export`, 569 modules,
  zero errors), `expo-doctor` (17/17), and systematic diffing of every hand-assembled file
  against the original source before validation

## Technical debt remaining

- `withRecommendationFreshness`'s client-side confidence-tier fallback still duplicates a
  rule that also lives in the backend (`execution_service._recommendation_freshness`) —
  flagged in the Phase 1 discovery report, not resolved by either phase
- `App.js`'s `content` router uses a chain of `if` statements rather than a lookup table;
  left as-is since it is simple, readable, and not a duplication problem
- No formal navigation library — `screen` is a plain string compared against `SCREENS`;
  sufficient for six flat tabs, would need revisiting if navigation gains hierarchy

---

# AT-ED-011.5 (Mobile Refresh Reliability and Data-Truth Alignment)

Builds directly on Phase 2 above. Phase 2 extracted `useFounderEvidence.js` as one hook;
AT-ED-011.5 first split Market's and the Dashboard founder-brief's screen-exclusive data out of
it (`useMarketData.js`, `useFounderBrief.js` — accepted, see Founder_Briefing.md), then (this
pass) answered the Founder's remaining question directly: does each screen's pull-to-refresh
genuinely own its refresh, or does it just show a screen-local spinner over a network call that
is secretly shared/reloads unrelated data?

## Refresh ownership table

The Founder's eight named areas map onto this app's six navigable tabs as follows: **Command**
is this app's Dashboard tab (labelled "Command Centre" in `ExecutiveDashboard`); **Broker
Panels** is the `BrokerPanel` component embedded inside both Dashboard and Portfolio — it is not
an independently navigable screen and has no refresh of its own (it re-renders from whichever
of Dashboard's/Portfolio's own refreshes just completed, via `status.brokers`).

| Screen | Refresh function invoked | Hook owning the refresh | API endpoint(s) | Data sections updated | Fetches other screens' data? | Changes another screen's loading/error? | Own last-refresh timestamp? |
|---|---|---|---|---|---|---|---|
| Dashboard (Command) | `screenRefresh.Dashboard.refresh` (composes `refresh()` + `founderBrief.refresh()`) | `useFounderEvidence` + `useFounderBrief` | `GET /founder-evidence`, `GET /founder-brief` (+ fire-and-forget `GET /notifications` on success) | `status`, `portfolio`, `activity`, `recommendations`, `performanceAttribution`, `dailyLearning`, `brief` | No — never calls Market's three endpoints | No — isolated from `useMarketData` entirely | Yes — `composeScreenRefresh` exposes the later of the two source timestamps |
| Activity | `screenRefresh.Activity.refresh` (= shared `refresh()`) | `useFounderEvidence` | `GET /founder-evidence` | `activity`, `notifications` (rendered as of this pass) | No | No — Market/Dashboard-founder-brief unaffected | Yes — mirrors the shared source's timestamp (see "Genuinely shared" below) |
| Recommendations | `screenRefresh.Recommendations.refresh` (= shared `refresh()`) | `useFounderEvidence` | `GET /founder-evidence` | `recommendations`, `performanceAttribution`, `dailyLearning` | No | No | Yes — mirrors the shared source |
| Portfolio | `screenRefresh.Portfolio.refresh` (= shared `refresh()`, driven only by the top `RefreshControl` — no in-screen button) | `useFounderEvidence` | `GET /founder-evidence` | `status`, `portfolio`, `recommendations`, `performanceAttribution` | No | No | Yes — mirrors the shared source |
| Market | `screenRefresh.Market.refresh` (= `marketData.refresh()`) | `useMarketData` | `GET /benchmark-daily-brief`, `GET /intelligence/themes`, `GET /intelligence/companies` | `benchmark`, `themes`, `companies` | No — never touches `/founder-evidence` | No — was previously mixed into the shared header badge; now isolated (see below) | Yes — its own `lastRefreshedAt`, never borrowed |
| Learning | `screenRefresh.Learning.refresh` (= shared `refresh()`) | `useFounderEvidence` | `GET /founder-evidence` | `dailyLearning` (`status.founder_experience.learning_lab` is also shared-sourced) | No | No | Yes — mirrors the shared source |
| Broker Panels (embedded, not a screen) | None of its own | Whichever of Dashboard/Portfolio's own refresh last completed | (none — pure render of `status.brokers`) | n/a | n/a | n/a | n/a — re-renders from its host screen |

**Genuinely shared, not a spinner illusion**: Activity, Recommendations, Portfolio, and Learning
all read fields of the *one* `/founder-evidence` response (confirmed against
`src/ai_trader/production_evidence.py`'s `_assemble_founder_evidence_payload` and every mapping
function in `founderEvidenceMapping.js`). The backend also exposes narrower slices
(`/activity/status`, `/activity/summary`, `/activity/timeline`, `/activity/why-no-trade`,
`/portfolio`, `/recommendations`, `/daily-learning-update`), but every one of them calls
`founder_evidence_payload(...)` internally and returns one field of it — switching these four
screens to their own narrower endpoint each would turn one shared, cheap, persisted-snapshot
read into four separate HTTP round trips against the same snapshot, which is strictly worse for
both mobile reliability (4 failure points instead of 1) and backend load. Per the directive's own
decision tree, the correct answer is rule 4: retain the one authoritative shared request/cache,
but expose screen-specific refresh state — which is what `mobile/lib/screenRefresh.js` now does
(see below), rather than leaving all four screens implicitly reading `useFounderEvidence`'s
fields directly with no per-screen composition at all.

**What was a spinner illusion, and is now fixed**: the app header's freshness badge, "Last
refreshed" line, backend-snapshot-age line, and cache/failure banners were previously *always*
derived from the shared `useFounderEvidence` hook, regardless of the active tab. Viewing Market
after a founder-evidence failure showed "Refresh Failed" over Market's own independently-healthy
data, and vice versa. `App.js` now computes a Market-specific `classifyDisplayState` (loading /
hasAttempted / succeeded from `useMarketData`'s own fields, `hasCachedData: false` and
`backendSnapshotStale: null` since Market has neither concept) and switches the entire header
block to it while `screen === 'Market'`; every other screen continues to show the shared state,
which is correct for them since they genuinely share the data it describes.

## New module: `mobile/lib/screenRefresh.js`

`SCREEN_DATA_SOURCES` is the single source of truth for which named source(s)
(`shared` / `market` / `founderBrief`) each screen depends on. `buildScreenRefreshRegistry`
composes each screen's `{ refresh, loading, lastRefreshedAt, lastRefreshError }` from only its
listed sources — `combineLoading` (OR), `latestTimestamp` (max), `combineErrors` (name every
failing source, never merge into one vague message, matching `combineOptionalResults`'
precedent in `refreshLifecycle.js`). Pure, dependency-free, unit-tested directly
(`screenRefresh.test.js`, 14 tests) the same way `refreshLifecycle.js` is. `App.js` builds one
`screenRefresh` registry via `useMemo` and reads `screenRefresh[screen]` for the shared
`RefreshControl`, replacing the previous three-way ternary.

## Mobile-side data-freshness fixes made in this pass

See `Data_Freshness_Findings.md` for the full investigation; the two confirmed, contained,
mobile-only fixes applied here:

- **`screens/Market.js`**: the "Alpaca Intelligence" and "Kraken Intelligence" sections
  both read the same generic `status.research_status` / `status.due_diligence_status` /
  `status.last_research_run`, so the two sections always showed identical text under different
  headings — never actually broker-differentiated. Now reads `status.brokers[].research_status`
  / `.due_diligence_status` per broker, and `status.operations_health.last_equity_research` /
  `.last_crypto_research` for each section's own "Last Update".
- **`screens/Market.js`**: "Companies Reviewed" read `status.last_research_run.companies_reviewed`,
  a field that does not exist anywhere in `PRODUCTION_RESEARCH_EVIDENCE` (confirmed against the
  query in `production_evidence.py`) — always silently rendered "Not available". Now reads the
  real field, `assets_analysed`, off the broker-specific research row.

## Notifications decision

`/notifications` was fetched on every successful founder-evidence refresh but rendered by no
screen. Confirmed against the backend (`NOTIFICATION_EVENTS`, `record_notification`,
`dispatch_pending_push_notifications`) that this is a real, separate Founder-facing channel:
high-priority event types already reach the phone as a native Expo push notification
independent of the app being open; this in-app fetch is the reviewable history, including
quieter event types that were never worth an interruptive push. Decision: **surface it**, in
`screens/Activity.js` (`NotificationsCard`, using the same `CollapsibleSection`/`Metric`
patterns as every other card on that screen — Activity is already this app's "what has AI
Trader done and does it need my attention" home). Unread is `delivery_status !== 'read'`
(`NOTIFICATION_EVENTS` has no separate read/acknowledged column); "Mark All Read" calls the
existing `POST /notifications/ack` through the existing `onCommand` path, no new command
plumbing.

---

# AT-ED-011.6 (Backend Data Availability Investigation and Correction)

Investigates the Founder's production report, following the AT-ED-011.5 OTA publish: top
banner "Refresh Failed", yellow banner "No Data Available", Command cards showing
"unavailable" across the board, Broker Panels empty.

## Root cause: infrastructure config drift, not a mobile or backend code bug

`render.yaml` (checked into this repo) declares `plan: starter` for the web service
(`ai-trader-api`), matching the always-on worker. The **live** Render service was found running
on the **free** plan — drifted from its own committed config. Free-tier Render web services
spin down to zero after ~15 minutes with no traffic and cold-start a fresh container on the
next request.

Ruled out with direct evidence, not assumption:
- **Not an auth/token bug**: the exact AT-ED-011.5 OTA bundle (update group `35bdf145`,
  built from commit `1e215de2`, confirmed via `eas update:view`) was downloaded and inspected —
  the full 64-character `AI_TRADER_API_TOKEN` is correctly inlined in it.
- **Not a backend logic/routing bug**: `/founder-evidence` returns `401` unauthenticated and
  `200` with genuine live data (real broker positions, current timestamps) authenticated, both
  confirmed by direct `curl` against production.
- **Not a mobile modularisation regression**: `mobile/api/client.js`'s auth header
  construction, base URL, and timeout handling were reviewed and are correct.
- **The three 500s found in Render's logs around the report window** are `BrokenPipeError`
  from a `127.0.0.1` (loopback) health-probe disconnecting before the server could write —
  internal noise, not something the mobile app or the Founder's request path ever saw.

**Confirmed with metrics, not just logs**: `cpu_usage`/`memory_usage` for the web service show
instance `srv-d93osvflk1mc739nga9g-wkl4k` reporting from 19:36 to 20:14 UTC (2026-08-03), then a
gap, then a **new** instance `srv-d93osvflk1mc739nga9g-pz8jc` starting fresh at 21:52 — a clean
container replacement with no new deploy in between, consistent with free-tier idle spin-down
and cold restart.

## Measured cold-start vs warm timing (2026-08-03, production)

| Request | DNS | TCP | TLS | TTFB | Total | 
|---|---|---|---|---|---|
| Cold (after ~21 min idle) | 0.043s | 0.072s | 0.128s | 16.753s | **17.132s** |
| Warm #1 (immediately after) | — | — | — | 2.881s | 3.255s |
| Warm #2 | — | — | — | 2.853s | 3.199s |
| Warm #3 | — | — | — | 3.101s | 3.819s |

Payload size was identical (4,269,846 bytes) across all four requests, so payload size is not
the variable — the ~13-14s difference is the container/interpreter/DB-pool cold start. The
previous `PRIMARY_REFRESH_TIMEOUT_MS` (18000ms) left only ~870ms (5%) of margin against this
single measured cold-start sample — thin enough that ordinary run-to-run variance (mobile
network latency, a slightly longer idle period) plausibly explains the intermittent nature of
the Founder's reports.

## Fix

**Primary correction (infrastructure, Founder-actioned)**: restore the web service to the
`starter` plan already declared in `render.yaml`, in the Render dashboard (not achievable via
the available Render MCP tools — service plan changes are a billing action). Not implemented by
this pass; assumed done by the Founder per their explicit direction.

**Mobile resilience (this pass, JS-only, no backend change)**:
- `mobile/lib/refreshState.js`: new pure `connectionMessage()` — distinguishes "Connecting to
  AI Trader..." (first attempt), "Waking backend service..." (on the bounded retry, before any
  data has ever loaded), "Refreshing..." / "Backend slow to respond - retrying..." (same,
  post-bootstrap).
- `mobile/hooks/useFounderEvidence.js`: new `isRetrying` signal set only while the bounded
  retry is in flight; the retry now uses `SECONDARY_REFRESH_TIMEOUT_MS` (8s) instead of a
  second full primary timeout — justified because by the time the retry runs, the cold start
  the primary timeout exists to absorb has already had that whole duration to finish booting in
  the background (measured warm response: 2.9-3.8s, well under 8s).
- `mobile/api/client.js`: `PRIMARY_REFRESH_TIMEOUT_MS` 18000ms → 25000ms — evidence-based
  headroom above the single worst measured cold-start sample (17.13s), not a blanket increase.
  `SECONDARY_REFRESH_TIMEOUT_MS` (8000ms) and `COMMAND_TIMEOUT_MS` (45000ms) left unchanged —
  no cold-start measurement was taken against the endpoints that use them.
- `mobile/App.js`: the exact banner combination from the Founder's report (StatusPill "Refresh
  Failed" directly above a banner reading "No Data Available") is confirmed to be this code
  working as designed, not a bug — both strings were independently, technically correct but
  gave no indication of why or that a retry was already happening. Failed-refresh banner
  renamed to "Backend temporarily unavailable", now shows "Last successful refresh: &lt;time&gt;"
  when one exists this session, and its retry button reflects "Waking backend service..." /
  "Retrying..." while a retry is actually in flight.
- Not changed: `useMarketData.js` and `useFounderBrief.js` still use `SECONDARY_REFRESH_TIMEOUT_MS`
  as a single attempt with no retry. No cold-start measurement was taken against
  `/benchmark-daily-brief`, `/intelligence/themes`, `/intelligence/companies`, or
  `/founder-brief` specifically, so no change is made here — flagged as an open follow-up only
  if the Founder reports these specifically failing after the Render plan restoration.

## Verification (this pass)

24 `refreshState.test.js` tests (5 new for `connectionMessage`), all 16 mobile test files pass
(no regressions), every touched file individually verified through the project's actual
`@babel/core` + `babel-preset-expo` toolchain, `expo-doctor` 17/17, `expo export --platform
android` Metro bundle succeeded (574 modules, zero errors). Production verification against the
restored Render plan and a published OTA update is pending Founder confirmation of the plan
change — see the AT-ED-011.6 Production Verification report once available.

---

# AT-ED-011.7 (Command Screen Data Failure and SQLite Error Root-Cause Investigation)

Investigates a second, separate report after the AT-ED-011.6 Render plan restoration: the
Command screen still showed widespread unavailable data, and the top banner exposed an error
message containing SQLite wording. Explicit instruction: do not assume SQLite was genuinely in
use, and do not assume the wording was harmless — prove the exact source.

## Database backend: proven Postgres, live

Direct evidence against the live Starter API: `/founder-evidence` and `/phase5-status` both
report `database_backend`/`status.database_status` as `"postgres"`; unauthenticated requests
correctly `401`; authenticated requests return genuine live broker data. `database.py`'s
`selected_backend()` fail-closed gate (raises if a hosted runtime would use SQLite) was not
observed to trigger. **Production is genuinely using Postgres, not SQLite.**

## Where "SQLite wording" could reach the Founder UI — two proven mechanisms

Neither was reproducing at the moment of investigation (all live requests tested clean), but
both are real, evidenced defects with a direct, traceable path to the Founder-facing UI:

**1. A raw backend-identifier field, unfiltered on the non-happy path.**
`production_evidence.py`'s `_assemble_founder_evidence_payload` sets
`status.database_status = "postgres" if uses_postgres() else "sqlite"` — a literal string,
computed by the *worker's* periodic snapshot write (every ~300s), not live per request.
`mobile/lib/founderEvidenceMapping.js` rendered this raw value directly into two Founder-facing
presentation fields: `operations_health.database_durability` and the "Connection and Trading
Readiness" card's Supabase Postgres check row (`connection_readiness.checks[].status`). Had
`database_status` ever briefly been anything other than `"postgres"` in a persisted snapshot
(e.g. in the seconds around a worker container restart, before `DATABASE_URL` is confirmed
available), the literal word "sqlite" would render directly on the Command screen with no
translation, exactly matching the report. `database_backend.active_backend` — a field
explicitly named and intended as the raw diagnostic value — is deliberately left showing the
literal identifier; only the two human-status presentation fields were unsafe.

**2. A systemic, codebase-wide exception-compatibility gap.** `database.py`'s
`PostgresConnection.execute()`/`executemany()` translates `psycopg.IntegrityError` to
`sqlite3.IntegrityError`, so pre-Postgres-migration code catching `sqlite3.IntegrityError`
keeps working. It did **not** translate `psycopg.errors.UndefinedTable`/`UndefinedColumn` —
the Postgres equivalents of SQLite's "no such table"/"no such column". Dozens of call sites
across the codebase (`application/founder_experience_service.py`, `trading_intelligence.py`,
`foundation.py`, `always_on.py`, `autonomous_activity.py`, and more) catch
`sqlite3.OperationalError` specifically to treat "this table/column doesn't exist yet" as
"no data available" rather than a hard failure — a pattern that only ever worked under a real
sqlite3 connection. Under Postgres, that `except sqlite3.OperationalError` was dead code: a
genuinely missing/not-yet-migrated table raised an **uncaught** `psycopg.errors.UndefinedTable`
instead of being gracefully absorbed, which is a direct, evidenced mechanism for "Command
screen sections show unavailable data" wherever they touch a table that isn't part of the
Postgres schema yet (`/phase5-status`'s own `database_spine.unmigrated_families` names several,
including `experience_learning` — the family `STRATEGY_LAB_RUNS`/`CONFIDENCE_CALIBRATION`/
`PERFORMANCE_INTELLIGENCE` almost certainly belong to).

**Separately found and fixed (same class of bug, not proven connected to this specific
report):** `api/__init__.py`'s `.portfolio()` caught a live-Alpaca-fetch failure with
`except Exception as exc:` and interpolated the raw exception directly into Founder-facing
fields (`f"Not available - {exc}"`) — exactly the "error-serialization leaking internal
implementation details" risk this investigation's own Section 5 named. `/portfolio` is not
currently called by mobile (confirmed: mobile only calls `/founder-evidence`, `/founder-brief`,
`/notifications`, `/trading-report`, and the POST command endpoints), so this could not be the
report's specific banner, but is a live, reachable HTTP route with the same defect class.

## Classification (per the investigation's own categories)

- Database backend: **PROVEN POSTGRES** — not the "GENUINE MISSING DATA" or backend-selection
  categories.
- SQLite wording reaching the UI: **UI PRESENTATION BUG** (raw `database_status` passthrough).
- Command screen incomplete data: **DATABASE QUERY FAILED**, specifically an
  **uncaught-exception class mismatch** (Postgres `UndefinedTable`/`UndefinedColumn` not
  translated to the `sqlite3.OperationalError` dozens of call sites already catch) — not a
  genuine SQLite connection, not an API routing bug, not a mobile modularisation regression.

## Fix (smallest safe correction, three files)

- `src/ai_trader/database.py`: `PostgresConnection.execute()`/`executemany()` now also
  translate `psycopg.errors.UndefinedTable`/`UndefinedColumn` to `sqlite3.OperationalError`,
  restoring every existing `except sqlite3.OperationalError` call site's intended behaviour
  under Postgres without touching any of them individually. Deliberately narrow: generic
  `psycopg.OperationalError` (connection failures, timeouts) is *not* translated — those are
  real, transient failures that must keep surfacing as errors, not be silently reinterpreted as
  "table doesn't exist, treat as empty".
- `src/ai_trader/api/__init__.py`: `.portfolio()`'s exception handler now logs the full
  exception server-side (`logger.exception`) and returns a safe, generic "Not available" reason
  instead of interpolating the raw exception into Founder-facing fields.
- `mobile/lib/founderEvidenceMapping.js`: new `databaseStatusLabel()` helper — the two
  Founder-facing presentation fields now show "Connected" / "Not Postgres - needs attention"
  instead of the raw backend identifier; `database_backend.active_backend` (the field whose
  explicit purpose is reporting the raw value) is untouched.

Not changed: the dozens of individual `except sqlite3.OperationalError` call sites themselves
(fixed for free by the `database.py` translation, per "delegation before deletion" — no
call-site-by-call-site rewrite needed); `ReportingService`/other `except Exception as exc`
sites not directly evidenced as reachable by this report.

## Tests

`tests/test_database.py`: 4 new tests on `PostgresConnection` (constructed via `__new__` with a
fake underlying connection, no real Postgres required) proving `UndefinedTable`/`UndefinedColumn`
translate to `sqlite3.OperationalError` with the real message preserved, `IntegrityError`
translation is unchanged, and unrelated `psycopg.OperationalError` is *not* translated.
`tests/test_developer_experience.py`: 1 new test proving `.portfolio()` never leaks a raw
exception's text into a Founder-facing field. `mobile/lib/founderEvidenceMapping.test.js`: 1 new
test proving a `database_status: 'sqlite'` input never renders the raw word to the Founder in
the two presentation fields, while the diagnostic `active_backend` field still carries it.

Full backend suite: 313 passed (two pre-existing, unrelated `test_cli_startup.py` errors are a
Windows temp-directory permission issue on this machine, reproducing identically before this
change — not a regression). All 16 mobile test files pass. Babel parse clean on every touched
file, `expo-doctor` 17/17, `expo export --platform android` clean (574 modules, zero errors).

---

# AT-ED-011.9 (Founder Evidence Cache Safety and Mobile Storage Remediation)

Fixes the AT-ED-011.8 root cause: `mobile/hooks/useFounderEvidence.js` writing the full
`/founder-evidence` response to AsyncStorage on every successful refresh, which threw a real
Android `SQLiteException: database or disk is full (code 13 SQLITE_FULL)` (AsyncStorage's
Android backing store is itself a small SQLite database with its own size ceiling — a known
upstream defect, `react-native-async-storage/async-storage#427`) — and, critically, the
cache-write failure was previously indistinguishable from a live-fetch failure, so a
successful, fully-live response got discarded and replaced with "Refresh Failed" fallback text.

## Measured payload composition (production, 2026-08-04)

A representative `/founder-evidence` fetch: 4,555,434 bytes total. `recommendations` alone was
**4,324,201 bytes — 94.9% of the entire payload** — across 100 items (~43KB each), dominated by
per-item fields (`intelligence`, `committee`, `strategy`, `signals`, `probability`) that
`statusFromFounderEvidence` never reads beyond a handful of scalars. Every other section
combined was under 230KB. Two further redundancies were found: `portfolio.brokers` is a
verbatim duplicate of the top-level `brokers` array (63,551 of portfolio's 64,736 bytes) and is
never read; each broker's `payload_json`/`positions_json` are raw-JSON-string re-encodings of
the already-present `payload`/`positions` objects.

A **second** AsyncStorage key was also found contributing to the same failure mode:
`RECOMMENDATION_CACHE_KEY` wrote the entire untrimmed `recommendations` array (the same ~4.3MB)
to a separate key on every successful refresh, independent of the main founder-evidence cache.

## Fix

**New `mobile/lib/founderEvidenceCache.js`** (pure, tested): `buildFounderEvidenceCacheSnapshot()`
produces a versioned (`v: 2`), bounded projection — same top-level shape as `/founder-evidence`
(so `statusFromFounderEvidence()`/`activityFromFounderEvidence()`/`founderLearningForMobile()`
need zero changes to consume it), with every array capped (recommendations → 10 tiny stubs of
just `proposal_id`/`symbol`/`broker`/`suggested_broker`/`freshness_status`/`confidence`/
`created_at`; trades/jobs/timeline items/research/learning → 20/20/20/10/10) and the two
duplicate fields dropped entirely. A representative multi-megabyte test fixture (mirroring the
production measurement) shrinks from 4MB+ to comfortably under 500KB. `parseCachedFounderEvidenceEnvelope()`
validates the `v` field and treats any pre-AT-ED-011.9 or unrecognised-version cache as
incompatible — discarded (safe, simple "migration"), never guessed at or partially reused.

**`mobile/hooks/useFounderEvidence.js` restructured**: `applyLiveFounderEvidence()` now only
sets display state — it performs zero AsyncStorage writes, so it can no longer be the thing
that throws and gets reported as a failed refresh. Two new functions,
`persistFounderEvidenceCache()` and `persistRecommendationsCache()` (capped to 15 full-fidelity
items for the Recommendations screen's own offline view), run **after** success is already
determined, are **never awaited** by `refresh()` (fire-and-forget with their own
`.then/.catch/.finally` — no unhandled rejection, no blocking the loading spinner), are guarded
against overlapping writes to the same key via dedicated in-flight refs, and are safe post-unmount
(`isMountedRef` checked before every `setState` inside their callbacks). A cache-write failure
now sets a new `cacheWarning` state, never `lastRefreshError` — and `cacheWarning` is
deliberately not rendered anywhere, satisfying "no Founder-facing banner for a cache-only
failure" without inventing new UI.

**`founderEvidenceMapping.js`**: `unavailableStatus()`'s connection-readiness check hardcoded
`component: 'Render API', status: 'timeout'` regardless of the actual cause (auth failure,
malformed response, or a genuine timeout) — corrected to `component: 'Founder Evidence',
status: 'unavailable'`; `detail` already carries the real, specific reason.

## Tests

12 new tests in `founderEvidenceCache.test.js` (bounded-array maximums, heavy-field stripping,
duplicate-field dropping, the size-budget assertion against a representative large fixture,
envelope version compatibility/incompatibility including the exact AT-ED-011.8-shaped legacy
cache). `refreshLifecycle.test.js` gained a test proving the core AT-ED-011.9 contract
structurally: a cache-only failure has no code path back into `applyError`, so an otherwise
successful refresh can never be marked failed by one. `founderEvidenceMapping.test.js` gained a
wording-correction regression test. Hook-level integration behaviour (the actual React state
wiring) is not unit-tested — this project has no React Native test renderer configured, and
`useFounderEvidence.js` cannot be `require()`'d under plain Node (it pulls in `react-native` and
the AsyncStorage native module) — verified instead via code inspection (documented per-function
above) plus the full babel/expo-doctor/expo-export toolchain and on-device verification.

All 17 mobile test files pass (185 mobile tests total), babel parse clean on every touched file,
`expo-doctor` 17/17, `expo export --platform android` clean (575 modules, zero errors, +1 from
the new lib file). No backend file, and no trading/risk/governance/reconciliation/capital
logic anywhere, was touched.

## Separate, not fixed in this pass

Founder Brief generation is stale (~12 days as of this investigation) because the three cron
services `render.yaml` declares (`ai-trader-daily-learning`, `ai-trader-weekly-report`,
`ai-trader-monthly-report`) were found, via Render's own service listing, to not exist as
provisioned Render services at all — confirmed separately from this cache work, deliberately
not mixed into it. Tracked as a proposed follow-up (verify and restore scheduled Founder Brief
generation), not addressed here.

---

# AT-ED-012 (Founder Experience, Information Design & Executive UX)

A presentation-only pass across all six mobile screens: no backend, trading, governance, risk,
or database file touched (11 files changed, all under `mobile/`). Full per-screen findings in
`Founder_Experience_Review.md`; summarized here.

## What was reviewed

Every screen (`Dashboard`, `Activity`, `Recommendations`, `Portfolio`, `Market`, `Learning`),
the shared `BrokerPanel`/`ReportPanel` components, and every shared UI primitive
(`Section`/`CollapsibleSection`/`Metric`/`TextBlock`/`Button`/`StatusPill`/`Empty`), documented
against: purpose, audience, the question it should answer, information overload, duplicate
information, missing information, technical wording, and misplaced content.

**Findings:** Dashboard carried two independently-computed executive summaries back to back,
plus a full page of always-open infrastructure diagnostics before reaching Broker Panels.
`BrokerPanel` (shared by Dashboard and Portfolio) was the densest component in the app — roughly
30-45 fields per broker, always fully expanded, appearing twice. Market had zero progressive
disclosure at all (9 permanently-expanded sections) and duplicated both an internal metric
(Research Running/Research Freshness — same field, two labels) and an entire other screen's
purpose (a full copy of Learning's Trade Outcomes data). Activity and Learning were already
close to the target shape (a short summary card, then collapsed detail) and needed only wording
polish.

## Phase 4 — financial terminology audit

Traced every Kraken money field to its exact backend source
(`application/broker_service.py:_exchange_portfolio`). Confirmed the ambiguity the directive
named as an example is real: "Portfolio"/"Cash" describe the Founder's **whole personal Kraken
account** (`balance_summary.total_estimated_gbp`/`gbp_cash`); "Buying Power" is **not a live
figure at all** — it's the static, configured `KRAKEN_TRADING_ALLOCATION_GBP` ceiling
(`balance_summary.trading_allocation_gbp`), which never changes as capital is deployed. The
number that actually answers "what can the AI still spend" (`ai_capital_ledger.available_cash_gbp`)
already existed in the data model but was three taps deep inside a collapsed "Trading
Permissions & Seatbelts" section. No calculation was changed — only which existing, already-
computed values are shown prominently and how they're labelled.

## Changes made

1. **Dashboard**: merged "Command Summary" and "Executive Summary" into one `CommandSummaryCard`
   (status pill + 2-3 sentence plain-English summary + supporting metrics); "24-Hour Operations"
   and "Connection & Trading Readiness" demoted to collapsed sections.
2. **BrokerPanel**: leads with a new plain-English readiness sentence
   (`brokerReadinessSentence()`); Kraken's money fields relabelled to make the whole-account-vs-
   AI-sleeve distinction explicit, with the actual AI buying-power figure surfaced prominently
   instead of buried; all deep governance/ledger/raw-balance detail moved behind one "Full
   Broker Diagnostics" collapsible.
3. **Market**: converted to the Activity-screen's collapsible pattern for reference/browse
   content (Research Status, Benchmark Traders, Theme Definitions, Companies Monitored); removed
   the duplicate Research Running/Freshness metric; replaced the full Learning-screen duplicate
   with a one-line pointer plus two headline numbers.
4. **Recommendations**: static description replaced with a dynamic summary
   (`recommendationsSummaryText()`) naming how many opportunities are actually fresh right now.
5. **Portfolio**: static question replaced with an actual answer (`portfolioHeadline()`) built
   from the same position/P&L data already on screen.
6. **Activity/Learning**: wording polish only ("Founder Action Required" → "Needs Your
   Attention"; two Learning fallback strings de-jargoned).
7. **Visual consistency**: Dashboard and Market's top cards now use the same
   `summaryCard`/`summaryReason` treatment Activity/Portfolio/Learning already used, so every
   screen's "here's the story" card looks and reads the same way — no new styles introduced.

## New pure, tested functions

`founderPresentation.js`: `brokerReadinessSentence()`, `krakenWholeAccountNote()`,
`portfolioHeadline()`. `recommendations.js`: `recommendationsSummaryText()`. All four are
dependency-free and unit-tested (14 new tests total) exactly like every other function in these
files — no new data is invented by any of them; each composes plain-English sentences from
fields the backend already computes and the screens already had access to.

## Verification

All 17 mobile test files pass. Babel parse clean on every touched file. `expo-doctor` 17/17.
`expo export --platform android` clean (575 modules, zero errors — no new files this pass, so
the module count is unchanged from AT-ED-011.9). No rendered browser/device check was performed
— this project has no `react-native-web`/`react-dom` configured, and installing them to bootstrap
a one-off web preview was judged out of scope for a presentation-only pass; verification is via
code review, the full babel/expo-doctor/expo-export toolchain, and (pending) the Founder's own
on-device review.

# AT-ED-013 (Founder Intelligence Experience, Chief Investment Officer & Autonomous Investment Organisation)

A presentation-only pass introducing the "Chief Investment Officer" narrative voice across the
mobile app, making Dashboard the primary CIO morning briefing, and adding a Founder-facing
`AI_TRADER_CONSTITUTION.md`. No backend, trading, execution, governance, or broker-integration
file touched (11 files changed under `mobile/`, plus one new root-level document). Full
per-screen findings in `Founder_Experience_Review.md`; design rationale in
`Chief_Investment_Officer_Design.md`.

## New module: `mobile/lib/cio.js`

The CIO is explicitly not a new AI system, model, or chat — it is a pure, dependency-free
presentation module (matching every other `lib/*.js` convention) that composes plain-English,
first-person prose entirely out of evidence fields the app already had access to
(`status.founder_experience`, `status.world_class_evidence`, `activity.summary`,
`recommendations[]`). Seven exported functions: `cioGreeting`, `cioExecutiveSummary`,
`cioOvernightActivity`, `cioMarketOutlook`, `cioAverageConfidence`, `portfolioProjection`,
`cioLearningNarrative`. 16 new tests (`lib/cio.test.js`), including a "deliberate honesty check"
asserting `portfolioProjection()` never returns a fabricated number — this backend has no
portfolio-value forecasting model anywhere (confirmed by reviewing `production_evidence.py` and
every `application/*.py` service this pass), only per-trade R-multiple estimates, so the
directive's 7/30/90-day projection request is satisfied by an honest "not available yet" state
rather than an invented figure.

## Changes made

1. **Dashboard**: `CommandSummaryCard` replaced by `CIOBriefingCard` — the new primary "home"
   experience. Opens with a time-of-day CIO greeting, then executive summary, overnight
   activity, market outlook, portfolio health, brokers, Founder decisions required, current-
   recommendation confidence (a real average, not a forecast), and the honest portfolio-
   trajectory line.
2. **Activity**: new `TradingNarrativeCard` — a narrative paragraph (`cioOvernightActivity`)
   followed by a compact trade-by-trade table (entry, current price, target exit, P&L,
   confidence-if-linked), reusing `lib/tradeHistory.js`'s existing, already-tested
   `combinedTransactions`/`normalizeTradeRow` rather than recomputing anything.
3. **Market**: the summary card's static lead question replaced with a real `cioMarketOutlook()`
   narrative built from the same market-intelligence-centre fields already shown below it.
4. **Portfolio**: Facts explicitly labelled ("Portfolio Value (Fact)", etc.); a "Portfolio
   Projection (Forecast — 7/30/90 Day)" line added beneath them, always honest about the
   forecasting-model gap. No calculation changed, per the directive's explicit instruction.
5. **Learning**: summary narrative now uses `cioLearningNarrative()`, framed as a CIO quarterly
   performance review.
6. **Visual status language (Section 12)**: `lib/refreshState.js`'s `displayStateBadge()` now
   attaches a 🟢/🔵/🟡/🔴 emoji derived from each state's existing tone (good/neutral/warn/
   danger) — the six existing `DISPLAY_STATE` values keep their distinct, Founder-meaningful
   labels; the four-icon language layers on top rather than collapsing them.
7. **Technical-detail leak sweep (Section 12)**: two raw-error leaks found and fixed. Learning's
   "Ask AI Trader" no longer echoes a raw exception string on non-timeout failures. The app-
   header "Live refresh failed: …" banner and the cached-data banner's reason line no longer
   interpolate `api/client.js`'s raw HTTP-status/timeout/path error text (e.g. `"Request failed:
   500"`, `"/founder-evidence"`) — a new `friendlyRefreshFailureReason()` in `refreshState.js`
   reduces any such error to one of two honest, plain-English reasons (slow backend vs.
   unreachable backend).
8. **`AI_TRADER_CONSTITUTION.md`** (repo root, new): a ~800-word Founder-facing constitution
   covering the eleven principles named in the directive (preserve capital, compound capital
   through disciplined evidence-based Shariah-compliant trading, explainability, facts-vs-
   forecasts, earned confidence, continuous learning, protecting the Founder from complexity,
   honest communication, continuous improvement, feature-mission alignment). Explicitly
   cross-references rather than duplicates the existing engineering constitution
   (`architecture/AI_TRADER_FOUNDING_PRINCIPLES_ARCHITECTURE_CONSTITUTION_v1.0.md`).

## New pure, tested functions

`lib/cio.js`'s 7 functions (16 tests). `lib/refreshState.js`'s new `friendlyRefreshFailureReason()`
(3 new tests) plus 2 new tests on the existing `displayStateBadge()` covering the emoji mapping.
21 new tests total this pass, all dependency-free and following the same convention as every
other function in these files.

## Verification

All 18 mobile test files pass (225 tests total across the suite — AT-ED-012's count of "17 mobile
test files" did not include `api/client.test.js`; re-counted this pass with a full
`find . -name "*.test.js"` sweep, not a `lib/*.test.js` glob, after that omission was caught
mid-pass). Babel parse clean on every touched file. `expo-doctor` 17/17. `expo export --platform
android` clean (576 modules, zero errors — one net new file, `lib/cio.js`, plus its test file
which is not bundled). No rendered browser/device check was performed, for the same reason
recorded in AT-ED-012: this project has no `react-native-web`/`react-dom` configured;
verification is via code review, the full babel/expo-doctor/expo-export toolchain, and the
Founder's own on-device review after the OTA update lands.

# AT-ED-014 (Chief Investment Officer Workspace, Adaptive Forecasting & Strategic Intelligence)

Gives the CIO its own dedicated screen and navigation item (it was a card inside Dashboard as of
AT-ED-013; this pass makes it the app's primary, launch-into experience), renames the former
Dashboard to Operations (operational health only), and introduces the Adaptive Forecasting &
Strategic Intelligence Engine. No backend, trading, execution, governance, or broker-integration
file touched. Full account in `Chief_Investment_Officer_Workspace.md`,
`Adaptive_Forecasting_Engine.md`, `Investment_Rhythm.md`, and `Investment_Committee_Model.md`
(this pass's docs bundle); summarized here.

## Screen restructure

`mobile/screens/Dashboard.js` deleted; replaced by two files. `mobile/screens/CIO.js`
(`CIOWorkspace`, new) takes over the executive/investment-leadership content (including
AT-ED-013's `CIOBriefingCard`, now expanded) as its own screen. `mobile/screens/Operations.js`
(`OperationsCentre`, new) keeps everything else Dashboard had - 24-hour operations, connection
readiness, broker panels, founder brief. `App.js`'s `SCREENS` array is now `['CIO', 'Operations',
'Activity', 'Recommendations', 'Portfolio', 'Market', 'Learning']`; initial `screen` state is
`'CIO'`. `lib/screenRefresh.js`'s `SCREEN_DATA_SOURCES` key `Dashboard` renamed to `Operations`;
new `CIO` key added (same sources: `shared` + `founderBrief` - CIO synthesises the same evidence
Operations shows in detail, not a new backend source).

## Five new pure lib modules (35 new tests)

- `lib/investmentThesis.js` (8 tests) - current/alternative investment thesis derived from the
  real, already-fetched `themes` evidence (`/intelligence/themes`, the same data Market's Theme
  Definitions section renders) and the dominant strategy among active recommendations. No
  "investment thesis" object exists in this backend; this module derives one honestly rather
  than inventing a separately-tracked thesis.
- `lib/forecasting.js` (10 tests) - the Adaptive Forecasting Engine's four layers (`FORECAST_LAYER`:
  Fact/Interpretation/Scenario/Forecast). `deriveConviction()` requires at least two independently
  agreeing real signals before naming a High/Medium/Low level, else honestly "Not Established".
  `autoTradeScenario()` is built from the exact same 85% confidence threshold
  `lib/recommendations.js` already gates auto-execution on. `portfolioForecast()`'s value/
  drawdown/volatility projections are always `available: false` with a named reason - this
  backend has no time-series or volatility model - reusing AT-ED-013's `portfolioProjection()`
  for the value-projection reason specifically, so there is one "no forecasting model exists"
  statement in the codebase, not two that could drift apart. Caught and fixed a real bug during
  testing: `'unfavourable'.includes('favourable')` was silently double-counting a negative signal
  as positive; fixed by tracking each signal's polarity as an explicit boolean.
- `lib/investmentRhythm.js` (7 tests) - the six-stage published daily schedule (Research/Learning/
  Strategy Committee/Risk Committee/CIO Review/Founder Brief). Schedule position
  (`scheduledCurrent`/`scheduledNext`) is a pure function of the clock (UTC) against the published
  times - not an evidence claim. Per-stage completion is separate and always evidence-gated:
  Research and CIO-Review/Founder-Brief are `completed` only with a real timestamp; Learning,
  Strategy Committee, and Risk Committee are always `not_tracked`, since no separately-
  timestamped evidence exists for them in this backend (governance runs per-recommendation, not
  as a scheduled batch) - the literal implementation of "never fabricate completion".
- `lib/investmentCommittee.js` (5 tests) - the seven-department pipeline (Research -> Learning ->
  Market Intelligence -> Strategy -> Risk -> Execution -> CIO), each department's conclusion
  built from a real field this app already reads elsewhere. Returns a plain array (Section 12
  future-readiness: a future specialist committee is one more array entry, not a CIO-screen
  redesign).
- `lib/forecastAccountability.js` (5 tests) - forecast-vs-outcome tracking. This backend has no
  persisted forecast-history table yet (AT-ED-014 is the pass that introduces forecasting at
  all), so with no records this always honestly reports "no track record yet" rather than a
  fabricated accuracy figure - the scaffolded architecture Section 6 asked for, ready for a
  future pass to wire up once forecast persistence exists.

## `lib/cio.js` additions (6 new tests)

Three new composer functions supporting the Morning Brief's ten-question structure (Section 3):
`cioPrincipalRisks()`, `cioPrincipalOpportunities()`, `cioFounderActionRequired()` - the last one
deliberately binary, only ever saying "No Founder action is required today" when both its inputs
are truthfully zero.

## Verification

All 23 mobile test files pass (267 tests total - 42 new this pass: 8 in `investmentThesis.test.js`,
10 in `forecasting.test.js`, 7 in `investmentRhythm.test.js`, 5 in `investmentCommittee.test.js`,
5 in `forecastAccountability.test.js`, 6 in `cio.test.js`, and 1 net-new in `screenRefresh.test.js`
after the Dashboard->Operations/CIO rename; see `Test_Report.md` for the full per-file table).
Babel parse clean on all 57 tracked `.js` files under `mobile/` (a full sweep, not just touched
files, since this pass deleted a file and restructured navigation). `expo-doctor` 17/17.
`expo export --platform android` clean (581 modules). No rendered browser/device check performed,
for the same disclosed reason as every prior pass - no `react-native-web`/`react-dom` configured
in this project.

# AT-ED-015 (Executive Communication, Founder Experience & Forecast Intelligence)

Redesigns the CIO screen (renamed Executive Briefing, Section 11) from AT-ED-014's seventeen
same-weight, occasionally self-repeating cards into a single flowing briefing matching Section 2's
prescribed structure, and adds a real, evidence-based Forecast Intelligence Engine. No backend,
trading, execution, governance, or broker-integration file touched. Section 1's required
pre-code review is `Executive_Communication_Review.md`; full technical account in that file's
sibling docs, summarized here.

## Screen rename and restructure

`mobile/screens/CIO.js` deleted; replaced by `mobile/screens/ExecutiveBriefing.js`
(`ExecutiveBriefing`). `App.js`'s `SCREENS` key `CIO` renamed `ExecutiveBriefing`
(`lib/screenRefresh.js`'s `SCREEN_DATA_SOURCES` key renamed to match); a new `SCREEN_LABELS` map
renders the tab text as "Executive Briefing" rather than the one-word routing key. The Executive
Briefing button is now rendered as a distinct, full-width `styles.primaryTab` above the regular
tab row (two new styles: `primaryTab`/`primaryTabActive`, `primaryTabText`/`primaryTabTextActive`)
rather than one equal-weight tab among seven.

Removed as standalone cards, per Section 8: `ConvictionCard`, `ConfidenceCard` - conviction is now
rendered directly beside the current investment thesis it supports; confidence is now rendered
directly beside each forecast horizon that earned it. Removed the AT-ED-014 duplication where
`MorningBriefCard` and the standalone `MarketOutlookCard`/`PrincipalRisksCard` computed and
rendered the identical sentence twice on the same screen - each fact now has exactly one owning
card. `ExecutiveMessagesCard` no longer surfaces an unread-notification count (Section 9); it
renders `null` (nothing) when there are no material evidence gaps to report, rather than an empty
shell. `TradingOrganisationCard` no longer exposes "Worker Health"/"Database Durability" labels
(Section 12) - six departments (Research/Learning/Execution/Risk/Infrastructure/Governance) each
report Healthy/Attention Needed in plain business language. `InvestmentRhythmTimeline` (formerly
`DailyRhythmCard`) is now a single checklist (✓ complete / ▶ current / ○ upcoming) instead of six
metric-heavy cards (Section 13).

## New: `lib/forecastEngine.js` - the Forecast Intelligence Engine (11 tests)

Real, evidence-based portfolio-value projections for Tomorrow / 7 Days / 30 Days / Quarter / Year
End (Section 4), built from `performanceAttribution`'s dated, realised closed-trade evidence - the
same data Learning's "Closed Trades"/"Win Rate" figures are already built from, filtered to the
identical terminal-status list `founderLearningForMobile()` uses, so this engine's sample size can
never silently disagree with what Learning already tells the Founder. A disclosed linear
extrapolation (observed trades-per-day × horizon days × average realised P&L per trade); every
projection carries `confidence` (from real sample size, three named tiers), `evidence`,
`assumptions`, `principalRisks`, and an `alternativeScenario`. Below `MIN_SAMPLE_SIZE = 5` dated
trades, every horizon is honestly `available: false` with the exact count and threshold named -
never a partial or optimistic extrapolation from too little evidence. The interface
(`projectPortfolioHorizons()`'s fixed output shape) is deliberately the only thing the UI depends
on, so a future, more sophisticated model can replace the internals without a UI change - the
directive's own requirement, implemented literally. Full design rationale in
`Forecasting_Engine_Architecture.md` and `Forecast_Model_Design.md`.

## New: structured Principal Risks / Opportunities / Founder Actions (18 tests)

`lib/principalRisks.js` (6 tests) - individual risk cards (Impact/Likelihood/Potential Effect/
Mitigation) replacing AT-ED-014's single joined-sentence summary. Positions-at-a-loss get a real,
computed Impact tier from the actual percentage of portfolio value at risk (Low/Medium/High,
disclosed thresholds); market-sourced risks (upcoming_risks/theme key_risks) honestly report
"not currently scored" for Impact/Likelihood, since no severity/likelihood model exists for plain-
string risk evidence. `lib/principalOpportunities.js` (6 tests) - individual opportunity cards
(Why/Evidence/Expected Benefit/Confidence/Time Horizon) built from real recommendation fields
already rendered on the Recommendations screen (`reason_for_recommendation`, `expected_return_r`,
`confidence`, `expires_at`) plus the highest-confidence tracked theme. `lib/founderActions.js`
(6 tests) - each outstanding recommendation becomes a structured action (What/Why/Expected
Benefit/Risk/Deadline/What Happens If Nothing); with nothing outstanding, `buildFounderActions()`
returns `[]` and the screen shows the honest, literal "No Founder action is required today" line
via `lib/cio.js`'s existing `cioFounderActionRequired()`.

## `lib/cio.js` addition: `cioClosingRecommendation()` (3 tests)

The Executive Briefing's final line (Section 2), composed from conviction level, thesis
availability, and whether Founder action is outstanding - never a new claim, only a synthesis of
values already computed elsewhere on the same screen.

## Verification

All 27 mobile test files pass (299 tests total - 32 new this pass: 11 in `forecastEngine.test.js`,
6 each in `principalRisks.test.js`/`principalOpportunities.test.js`/`founderActions.test.js`, 3 new
in `cio.test.js`, 0 net-new in `screenRefresh.test.js` after the CIO->ExecutiveBriefing rename).
Babel parse clean on every new/touched file (a full-repo sweep was also run). `expo-doctor` 17/17.
`expo export --platform android` clean (585 modules). No rendered browser/device check performed,
for the same disclosed reason as every prior pass.

# AT-ED-015.1 (Executive Briefing White-Screen Production Regression)

A production incident found and fixed with a live, reproduced root cause - not inferred from the
white screen alone. Full account in `ZIP-Updates/2026-08-04-at-ed-015-1-executive-briefing-white-
screen-fix/Root_Cause_Analysis.md`; summarized here.

## Root cause

`lib/principalOpportunities.js`'s `themeOpportunityCard()` called
`theme.key_drivers.slice(0, 3).join('; ')` assuming `key_drivers` is always an array. Live
`/intelligence/themes` evidence returns it as a plain string on at least some themes -
`String.prototype.join` does not exist, so this threw a `TypeError` during
`PrincipalOpportunitiesSection`'s render whenever the highest-confidence tracked theme had a
string-shaped `key_drivers` field. With no error boundary anywhere in the app, the uncaught
render exception unmounted the entire React tree - the reported blank white screen. Notably,
`lib/investmentThesis.js`'s `alternativeThesis()` (AT-ED-014) already defended against the
identical shape ambiguity on the sibling field `theme.key_risks`
(`Array.isArray(theme.key_risks) ? theme.key_risks : [theme.key_risks]`) - this was a real,
proven-live gap in the one new AT-ED-015 call site that didn't replicate that existing pattern,
not a systemic issue across the codebase.

## Proof, not inference

Reproduced two independent ways: (1) an Android emulator (Pixel 9 AVD) ran the exact pre-fix
`master` commit against the real production API, and `adb logcat` captured the exact error and
full component stack trace live; (2) the exact pre-fix source was temporarily restored and run
against a new production-representative regression test, which failed with the byte-identical
error message, then passed once the fix was restored. Both are documented in full in
`Test_Report.md` and `Root_Cause_Analysis.md`.

## Fix

`themeOpportunityCard()` now normalizes `theme.key_drivers` via a new `keyDriversText()` helper
(`Array.isArray(raw) ? raw : [raw]`, the same pattern `investmentThesis.js` already used for
`key_risks`) instead of assuming array shape. No forecasting methodology changed; no content was
hardcoded or removed.

## Defence-in-depth

New `components/ErrorBoundary.js` - a screen-level React error boundary wrapping only
`<ExecutiveBriefing>` in `App.js`. On any future uncaught render exception in that subtree, the
app shell (header, tab bar) and every other screen remain fully usable; the Founder sees a calm
"The Executive Briefing could not be displayed." message with Retry and Open Operations buttons
and a safe diagnostic ID, never a stack trace or a blank screen. The real error is still logged via
`console.error` for engineering diagnosis.

## Verification

All 27 mobile test files pass (303 tests total - 4 new, all in `principalOpportunities.test.js`).
`lib/forecastEngine.js` was independently re-audited against this incident's own checklist (NaN/
Infinity, invalid dates, divide-by-zero, malformed records, unavailable-state schema stability)
and found not to be the source and not to require changes. Babel parse clean (78 files checked).
`expo-doctor` 17/17 (one transient local-state finding - an uncommitted `mobile/.expo/` directory
created during emulator testing - fixed via `.gitignore`, not a code defect). `expo export
--platform android` clean (586 modules). A second live post-fix UI confirmation was attempted on
the same emulator but not cleanly achieved (Expo Go's automated navigation via `adb`, without a
human tapping the screen, repeatedly returned to its own project picker) - the fix is proven via
the source-level regression test and live pre-fix reproduction described above; on-device
confirmation by the Founder remains the final acceptance step per the directive's Section 10.

# AT-ED-016 (Executive Briefing Evolution & Forecasting Engine Phase 2)

Evolves (not rewrites) the Executive Briefing into the directive's exact 11-section CIO-meeting
format, extends the Forecast Intelligence Engine into a multi-factor Bull/Base/Bear model, and
adds real, on-device forecast accountability persistence on top of AT-ED-014's scaffold. Required
pre-code design review is
`ZIP-Updates/2026-08-06-at-ed-016-executive-briefing-evolution/Executive_Briefing_Evolution_Design_Review.md`.
No backend, trading, execution, governance, or broker-integration file touched.

## Executive Briefing: 11-section restructure

`screens/ExecutiveBriefing.js` reorganised into: Executive Summary, Current Position (extended
with real week-to-date/month-to-date P&L, current allocation, largest winning/losing position -
`lib/portfolioPosition.js`, new), What Happened Overnight (extended with trades-considered/
rejected and risk-review evidence), Market Assessment, Investment Thesis (extended with real
Positive/Negative Factors, Unknowns, Assumptions, Expected Catalysts, Evidence Strength, and the
existing Alternative Thesis), Forecast Centre (rewritten - see below), Forecast Accountability
(new), Principal Risks (extended with Monitoring Owner and Estimated Portfolio Effect), Principal
Opportunities (extended with Catalyst), Founder Actions (extended - "no action required" is now
always explained, never bare), Investment Organisation (renamed from Investment Committee,
extended from 7 to the directive's 9 departments), Closing Recommendation (expanded to a full
multi-sentence close). Investment Rhythm and Executive Messages remain below-the-fold supporting
detail. The AT-ED-015 Trading Organisation card is retired - Investment Organisation now covers
"is my organisation healthy" with real per-department evidence, so the two cards would otherwise
duplicate each other.

## New: `lib/forecastFactors.js` - the multi-factor evidence layer (19 tests)

Eight independent, real evidence-based factors (historical performance, unrealised P&L, portfolio
concentration, market regime, learning confidence, research conviction, opportunity capture, risk
readiness), each returning `{ name, available, direction, note }` - never a synthesized score.
Two directive-requested signals (volatility, momentum) were found during the design review to be
**hardcoded placeholder strings** in `lib/founderEvidenceMapping.js`
(`'See recommendation evidence where available'`, unconditional, never derived from real backend
data) and are deliberately NOT implemented as factors - a direct, proactive application of the
AT-ED-015.1 incident's lesson (verify a field's real shape/meaning before reading it, don't
assume). Several other requested signals (trend persistence, sector rotation, macro events,
economic calendar, broker liquidity) also have no real evidence source anywhere in this app and
were left honestly unimplemented.

## Extended: `lib/forecastEngine.js` - Bull/Base/Bear cases (6 new tests, fully backward compatible)

`tradeStatistics()` now also computes real `avgWinPnl`/`avgLossPnl`/`winCount`/`lossCount`.
`projectHorizon()` adds `baseCase`/`bullCase`/`bearCase` (bull/bear built from the real average of
only winning/only losing trades in the same dated sample, falling back to the base case when the
sample has no trade of that kind - never a fabricated number), `probability` (the real historical
win rate, labelled as exactly that), `expectedReturnPct`, and a written `explanation` naming the
real sample size and win rate. `expectedVolatility`/`expectedDrawdown` remain always honestly
unavailable - no time-series or volatility model exists in this backend, confirmed again this
pass. All existing fields/tests are unchanged and still pass.

## New: `lib/forecastHistory.js` + `hooks/useForecastHistory.js` - real forecast accountability (14 tests)

Turns AT-ED-014's `lib/forecastAccountability.js` scaffold into a working system for the first
time. Only `available: true` horizons are ever stored as a promise; records use exactly
`FORECAST_RECORD_SHAPE`'s field names so they flow directly into the existing, unmodified
`forecastAccountability()` summary function. Persistence is local `AsyncStorage`
(`ai-trader:forecast-history:v1`), following `lib/founderEvidenceCache.js`'s established read/
parse-defensively/discard-on-incompatible pattern. A forecast is graded on **directional**
accuracy only (did it correctly call up/down/flat) against the real portfolio value this device
next observes on or after the target date - not a continuously-sampled time series, since none is
collected; this bound is disclosed, not hidden. New forecasts are recorded at most once per
horizon per ~20 hours (`shouldRecordNewForecast`) so an auto-refreshing screen never spams
duplicate promises. Automated model retraining from this history is explicitly out of scope for
this pass - the tracking is real; using it to improve the model is future, scaffolded work.

## Extended: Investment Organisation, Principal Risks, Principal Opportunities, Founder Actions

`lib/investmentCommittee.js` extended from 7 to 9 departments (adds Forecast Engine, Broker
Monitoring, Portfolio Intelligence; drops the standalone "Chief Investment Officer" entry - this
section is departments reporting to the CIO, not the CIO's own entry), each from a real evidence
field (Forecast Engine from `tradeStatistics()`'s own availability; Broker Monitoring counts real
connected brokers; Portfolio Intelligence from the same `world_class_evidence.portfolio_intelligence.plain_english`
Portfolio.js already renders). `lib/principalRisks.js` gained Monitoring Owner (a real department
mapping) and Estimated Portfolio Effect (a real quantified £ figure for the position-loss card, an
honest "not quantified" for market-sourced risks). `lib/principalOpportunities.js` gained Catalyst
(the real, distinct `strongest_argument_for` field for recommendations; the first real key driver
for themes). `lib/cio.js` gained `cioNoActionReason()` (the directive's "never simply say no
action required - explain why" requirement) and `cioExecutiveBriefingSummary()` (the Executive
Summary's fragment-joining composer); `cioClosingRecommendation()` was expanded with a monitoring-
commitment closing sentence.

## Real bug caught by a new test

`lib/portfolioPosition.js`'s week-to-date/month-to-date sum initially filtered only on
`Number.isFinite()` after conversion - but `Number(null)` is `0`, a finite number, so a broker
with no real evidence was being silently counted as a real £0. Caught by the "no brokers with real
evidence returns null" test; fixed by filtering `null`/`undefined` explicitly before conversion.

## Verification

All 30 mobile test files pass (361 tests total - 58 new this pass). Babel parse clean on all 85
files checked. `expo-doctor` 17/17. `expo export --platform android` clean (591 modules). A live
Android emulator session (the same method that reproduced AT-ED-015.1's incident) was run against
this pass's code and the real production API; no error was observed in the bundle log or logcat
during the sessions that ran, but Expo Go's own automated navigation did not reliably confirm a
clean on-screen render this time (the same tooling limitation disclosed in AT-ED-015.1), so this
is reported as inconclusive live verification, not a confirmed pass - the primary verification for
this pass is the automated test suite plus a proactive field-safety audit (every newly-read raw
evidence field was grep-verified against an already-proven-safe call site before use, applying the
AT-ED-015.1 lesson prospectively). On-device confirmation by the Founder remains the final
acceptance step.
