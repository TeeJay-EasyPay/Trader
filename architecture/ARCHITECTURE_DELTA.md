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
