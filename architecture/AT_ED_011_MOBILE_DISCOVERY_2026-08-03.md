# AT-ED-011 Mobile Discovery Report

**Read-only investigation. No code was moved, extracted, or modified in producing this report.**

Scope: `mobile/App.js` (3,890 lines — the entire mobile application) and the two existing
extracted modules, `mobile/lib/founderPresentation.js` (332 lines) and `mobile/lib/refreshState.js`
(128 lines, added in AT-ED-010). This report identifies what exists and where the natural
extraction seams are. It does not propose a target file/directory structure (that is Section 2's
separate step) and does not redesign anything.

## Correction to a starting assumption

The app has **6 top-level screens** (the `SCREENS` array, `App.js:54`): `Dashboard`, `Activity`,
`Recommendations`, `Portfolio`, `Market`, `Learning` — not 7. "Command Centre" and "Broker Panel"
are *components rendered within* the Dashboard/Portfolio screens, not separate top-level screens.

## The one modularisation pattern already established

`founderPresentation.js` and `refreshState.js` are both dependency-free (no React/React Native
imports), pure-function modules, tested via plain Node `assert` scripts (no test framework
installed), and `require()`'d into `App.js`. This is a real, working, already-proven pattern —
AT-ED-011's job is to extend it much further, not invent a new one.

## Largest single unit: the main `App()` component (lines 558-1024, ~466 lines)

This is the single highest-value extraction target in the file. It currently mixes, in one
function:
- **24 pieces of top-level state** (`useState` calls, lines 559-585): screen selection, loading,
  status, portfolio, brief, recommendations, benchmark, themes, companies, amounts,
  selectedExchange, lastRefreshedAt, hasAttempted, lastRefreshSucceeded, lastRefreshError,
  cachedAt, snapshotMeta, targetRecommendationId, notifications, performanceAttribution,
  dailyLearning, latestReport, activity, activityPeriod, askMessages.
- **Data fetching** (`request`, `fetchFounderEvidenceOnce`, lines 592-644).
- **Cache read/write and the AT-ED-010 live/cached state machine** (`applyLiveFounderEvidence`,
  `applyCachedFounderEvidence`, `refresh`, lines 646-742).
- **Two `useEffect`s**: initial mount load (744) and the AT-ED-010 2-minute auto-refresh interval
  (764).
- **A `useMemo`-based screen router** (`content`, line 836) that switches on `screen` and renders
  one of ~10 different screen components inline.
- **The outer JSX shell** itself: header, `StatusPill`, snapshot-age line, cache banner, tab bar.

This is exactly the kind of "mixed responsibilities" AT-ED-011 Section 1 asks to identify: data
fetching, cache/retry state machine, and top-level rendering/navigation are all one function. The
natural seams are already visible in the state groupings above — e.g. a `useFounderEvidence`
hook (state + `request`/`refresh`/cache functions) and a thin `App` shell that only handles
navigation and the header.

## Already-componentized screens and cards (good news: this is a move, not a rewrite)

19 named functions already exist as distinct, self-contained components — they are not one
undifferentiated JSX blob, just all declared in one file:

| Component | Line | Size |
|---|---|---|
| `CommandCentre` | 1415 | 190 lines |
| `MarketIntelligence` | 2075 | 133 lines |
| `AutonomousActivity` | 1284 | 131 lines |
| `PortfolioCommandCentre` | 1093 | 103 lines |
| `Recommendations` | 1903 | 97 lines |
| `AskAiTrader` | 2282 | 89 lines |
| `RecommendationCard` | 2000 | 75 lines |
| `LearningStrategyLab` | 2208 | 74 lines |
| `ExecutiveDashboard` | 1025 | 68 lines |
| `BrokerPanel` | 1196 | 65 lines |
| `TradingPermissions` | 1621 | 49 lines |
| `ReportPanel`, `TradeHistorySection`, `TradeHistoryRow`, `TradeHistoryScreen`, `TradeDetail`, `OperationsHealthCard`, `ConnectionReadinessCard`, `AutonomousActivitySummaryCard` | various | 15-45 lines each |

None of these individually exceeds the directive's 500-700 line soft target; `CommandCentre` at
190 lines is the largest. The extraction work here is mechanical relocation into
`components/`/`screens/` files plus updating imports, not a rewrite of any of these functions'
internals.

## Already-existing shared low-level components (exactly what Section 3 asks for, already built)

`Section` (2371), `CollapsibleSection` (2383), `Metric` (2400), `TextBlock` (2409), `Button`
(2458), `StatusPill` (2466, added in AT-ED-010), and `Empty` (2475, a single shared "Not
available" empty-state, reused **15+ times** across every screen) already exist as exactly the
kind of small, single-responsibility, reusable components the directive names (`StatusBadge`,
`SectionHeader`, `CollapsibleSection`, `EmptyState`). They just need to move into their own files
under `components/`. `LoadingState`, `ErrorState`, and `RetryButton` genuinely do **not** exist
yet as reusable components — see below.

## Duplicate formatting logic

**Money/currency** (6 related functions, `money`/`gbp`/`moneyOrText`/`gbpOrText`/`brokerMoney`/
`historyMoneyOrText`, lines 2479-2513): not truly duplicated logic (USD vs GBP is a real
distinction), but scattered rather than centralized — a clean, low-risk consolidation into one
`presentation/money.js`-style module.

**Date/timestamp**: genuinely centralized already. `formatDateTime`/`dateMs` (2846/2835) is the
one shared implementation; no other inline `.toLocaleDateString()`/`.toLocaleString()` date
formatting exists anywhere else in the file (confirmed by direct search). This is a negative
finding — nothing to fix here, just relocate the function.

**Guardrail-failure text — an exact duplicate.** `App.js`'s `formatGuardrails` (line 2932) is
**byte-for-byte identical logic** to `founderPresentation.js`'s already-exported
`formatGuardrailFailures` (that file, line 199) — same body, different name, living in two
files. This is the cleanest, lowest-risk, highest-confidence duplication finding in this report:
delete `App.js`'s copy, import the existing shared function instead.

**List formatting**: `formatList` (3004) and `formatListInline` (3017) — two similar but
distinct list-joining helpers (block vs inline rendering) - likely both genuinely needed, not a
duplicate, but worth co-locating in one formatting module regardless.

## Duplicate business logic (the more consequential finding)

**Recommendation freshness/expiry is computed independently in (at least) two places with the
same confidence-tier rule.** `App.js`'s `withRecommendationFreshness`/`clientAutoTradeReason`
(lines 2876-2930) recomputes freshness client-side *only when the backend hasn't already
provided `freshness_status`/`expires_at`* — using its own hardcoded confidence-tier lifetime
table (≥0.85 → 4h, ≥0.75 → 12h, else 24h). This exact same rule is the backend's own canonical
definition (`execution_service._recommendation_freshness`, confirmed present in
`src/ai_trader/application/execution_service.py` from this session's earlier backend work).
`founderPresentation.js`'s `recommendationLifecycle` correctly *reads* the backend's field
instead of recomputing it — the safer pattern already established in this codebase. `App.js`'s
fallback is a defensive measure for when the backend hasn't populated the field, but it means
the confidence-tier rule now lives in three places (Python backend, this JS fallback, and
implicitly trusted-not-duplicated in `founderPresentation.js`) that could silently drift out of
sync if the backend's thresholds ever change. Worth a deliberate decision during Section 2/3:
either extract this fallback into one shared client function (so there's exactly one JS copy) or
reconsider whether the client-side fallback is still needed at all now that the backend reliably
populates these fields.

**Broker "connected" check reimplemented.** `localConnectionReadiness` (1856) independently
re-derives `String(broker.connection_status || '').toLowerCase() === 'connected'` — the same
condition `founderPresentation.js`'s `brokerOverallReadiness` already encodes (for a related but
distinct purpose: connection-readiness-checklist building vs. overall-readiness-label). A small,
low-risk duplication, not a large one.

## Duplicate/parallel "data not yet available" API-shape builders

`unavailableStatus` (56), `unavailableActivity` (97), `statusFromOperations` (141), and
`activityFromEvidence` (208) each independently hand-construct a full, differently-shaped
"partial" or "unavailable" version of the real API response shape, for use while data is
hydrating or after a fetch failure. These four functions total roughly 210 lines and encode very
similar intent (a degraded-but-honest placeholder state) with different hardcoded English strings
and slightly different fabricated shapes each time. This is the file's largest concentration of
"duplicate API-shape mapping" and directly overlaps with the directive's requested `LoadingState`/
`ErrorState`/`EmptyState` component work — right now this is done via bespoke object literals
per data-domain rather than shared components with shared shapes.

## Loading / error / retry state: no reusable components exist yet

`ActivityIndicator` (React Native's spinner) is used directly exactly **once** (line 1012) — the
app does not have a widely-duplicated hand-rolled loading spinner pattern to consolidate, because
it barely uses one at all; `loading` mostly just disables buttons. "Retry now" (the AT-ED-010
cache-banner action) appears twice as near-identical `TouchableOpacity`/`Text` JSX (lines 978,
989) rather than one shared component. **`LoadingState`, `ErrorState`, and `RetryButton` as named
in the directive do not exist as components today** — these would be genuinely new components
built from the patterns above, not extractions of pre-existing duplicated code, unlike most of
the rest of this report.

## State management pattern

Confirmed: plain React hooks throughout (`useState`/`useEffect`/`useCallback`/`useMemo`), no
external state library (no Redux/Zustand/Context API usage found). All 24+ pieces of state live
in the single main `App()` component and are threaded down as props to every screen/card
component — there is no React Context or hook-based state sharing between siblings currently.

**On `refreshState.js`'s pattern**: `classifyDisplayState` is a pure function taking an explicit
state-shape object and returning a derived value, with zero hooks or side effects — genuinely
reusable as a template. It is currently narrow to the one live/cached data-freshness question it
was built for. The directive's proposed `useRefresh`/`useFounderEvidence` hooks would be a
natural place to keep using this exact pattern (pure classification function + a thin hook
wrapping the actual `useState`/`useEffect` plumbing around it), rather than writing new ad hoc
state logic for each additional shared hook.

## Summary: highest-value extraction opportunities, ranked

1. **The main `App()` component** (~466 lines, mixed data-fetching/cache/retry/navigation) — the
   single biggest win, and the one most directly named in the directive's own hook list
   (`useFounderEvidence`, `useRefresh`).
2. **The 19 already-named screen/card components** — pure relocation, very low risk, immediately
   reduces `App.js` from ~3,890 lines toward the directive's soft limit with no logic changes.
3. **The 7 already-named shared low-level components** (`Section`, `CollapsibleSection`,
   `Metric`, `TextBlock`, `Button`, `StatusPill`, `Empty`) — same: pure relocation.
4. **The exact-duplicate `formatGuardrails`/`formatGuardrailFailures`** — trivial, zero-risk,
   immediate fix.
5. **The four `unavailable*`/`statusFromOperations`/`activityFromEvidence` fallback-shape
   builders** — the best candidate for genuinely new `LoadingState`/`ErrorState` components,
   since this is where the directive's requested components don't exist yet and where the most
   duplicated intent (not code) currently lives.
6. **The client-side recommendation-freshness fallback logic** — lower urgency, but worth a
   deliberate decision (consolidate to one place, or remove now that the backend is reliable)
   rather than leaving three copies of the same business rule.
