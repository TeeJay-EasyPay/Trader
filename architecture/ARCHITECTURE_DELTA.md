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
