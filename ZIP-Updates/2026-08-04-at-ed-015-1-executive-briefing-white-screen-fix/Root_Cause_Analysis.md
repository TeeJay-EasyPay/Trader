# Root Cause Analysis — AT-ED-015.1

## One-Sentence Root Cause

`lib/principalOpportunities.js`'s `themeOpportunityCard()` called `theme.key_drivers.slice(0, 3).join('; ')` assuming `key_drivers` is always an array, but the live `/intelligence/themes` evidence returns it as a plain string — `String.prototype.join` does not exist, so this threw a `TypeError` during every render of `PrincipalOpportunitiesSection` once a theme with a string-shaped `key_drivers` field reached the screen, and with no error boundary in place, the uncaught render exception unmounted the entire React tree, producing the reported blank white screen.

## Exact Component and Data Value

- **Component:** `PrincipalOpportunitiesSection` (`mobile/screens/ExecutiveBriefing.js`), via `buildOpportunityCards()` → `themeOpportunityCard()` (`mobile/lib/principalOpportunities.js:29`, pre-fix).
- **Data value:** the highest-confidence entry in `themes` (sourced from `/intelligence/themes`, fetched independently by `hooks/useMarketData.js`) whose `key_drivers` field is a **string**, not an array. Corroborating evidence: `screens/Market.js:186` and `screens/Recommendations.js:91` both already render `key_drivers`/`key_risks` as a raw `TextBlock` value with no `.join()`, and `lib/investmentThesis.js:79` (AT-ED-014, untouched) already defensively normalizes the sibling field `theme.key_risks` with `Array.isArray(theme.key_risks) ? theme.key_risks : [theme.key_risks]` before calling `.slice().join()` on it — proof that this shape ambiguity was already known and handled everywhere else in the codebase except the one new AT-ED-015 call site that introduced it.
- **Exact error, captured live:** `TypeError: theme.key_drivers.slice(0, 3).join is not a function (it is undefined)`.
- **Exact stack trace, captured live via Android emulator + logcat:**
  ```
  ERROR  TypeError: theme.key_drivers.slice(0, 3).join is not a function (it is undefined)
  This error is located at:
      in PrincipalOpportunitiesSection (created by ExecutiveBriefing)
      in RCTView (created by View)
      in View (created by ExecutiveBriefing)
      in ExecutiveBriefing (created by App)
      in RCTView (created by View)
      in View (created by ScrollView)
      in RCTScrollView (created by ScrollView)
      in AndroidSwipeRefreshLayout (created by RefreshControl)
      in RefreshControl (created by App)
      in ScrollView (created by ScrollView)
      in ScrollView (created by App)
      in RCTView (created by View)
      in View (created by App)
      in App (created by withDevTools(App))
      ...
      in AppContainer
      in main(RootComponent), js engine: hermes
  ```

## How This Was Proven, Not Inferred

Section 1 of the directive required proof, not inference from the white screen alone. This was achieved in two independent, corroborating ways:

1. **Live device reproduction.** An Android emulator (Pixel 9 AVD) was booted, the exact current `master` codebase (commit `3c0ba21b`, pre-fix) was run via Expo/Metro against the real, live production API (`https://trader-no0f.onrender.com`, the same backend the Founder's device talks to), and `adb logcat` captured the crash above on first live render — the exact component, the exact error message, and the full component stack, with zero speculation.
2. **Source-level regression proof.** The exact pre-fix file (`git show HEAD:mobile/lib/principalOpportunities.js`) was temporarily restored and run against a new test (`buildOpportunityCards: a string-shaped key_drivers on the top theme never crashes`) using a production-representative payload shape (`key_drivers: 'Strong capex growth'`, a string). It failed with the byte-identical error message: `TypeError: theme.key_drivers.slice(...).join is not a function`. The fixed source was then restored and the same test passed. This proves the fix addresses the exact defect that produced the exact live crash, not a guessed-at symptom.

## Where in the Failure Timeline This Occurs

Per the directive's Section 1 checklist:

- **Not** during initial refresh in isolation — the very first render of the Executive Briefing (before `themes` has loaded) never reaches `PrincipalOpportunitiesSection` with a populated `topTheme`, so it renders safely.
- **After founder evidence is applied**, in combination with **market/theme data being applied** — `themes` is fetched independently by `hooks/useMarketData.js` (a separate endpoint, `/intelligence/themes`, on its own refresh cycle from the shared `/founder-evidence` payload - see AT-ED-011.5's screen-refresh-ownership design). The crash fires on whichever render is the first to have both a real `topTheme` (by confidence) selected AND that theme's `key_drivers` field shaped as a string.
- **Not** after forecast calculation, cache persistence, a timer/interval in the sense of a background job, or navigation - it is a synchronous render-phase exception, not an async one, and not specific to the new Forecast Intelligence Engine (`lib/forecastEngine.js`, audited separately and found safe - see Test_Report.md).
- **The React view blanks; the native app process does not crash.** The Hermes JS engine and the native Android process both remain alive (confirmed live: `adb logcat` continued reporting on the same process ID after the error, and the process was not killed) - this is React unmounting its component tree in response to an uncaught render exception with no boundary to catch it, not a native/process-level crash. This matches the incident report's "blank white screen, not a normal error message or fallback UI, not an app close/restart."

## Why the Existing Test Suite Did Not Catch This

`lib/principalOpportunities.test.js`'s only pre-existing test of `themeOpportunityCard()` used `key_drivers: ['a', 'b', 'c', 'd']` — an array. Every test of this function assumed the same array shape the code assumed, so the test suite and the implementation shared the same blind spot rather than the test suite ever exercising the real, string-shaped production data. This is the same class of gap AT-ED-015's own `Test_Report.md` should have caught, and is now closed with a production-representative regression test (see Test_Report.md, "New Tests This Pass").
