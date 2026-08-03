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
