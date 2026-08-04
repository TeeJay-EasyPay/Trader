# Changed Files — AT-ED-015.1

## The Fix

- `mobile/lib/principalOpportunities.js` — `themeOpportunityCard()` no longer assumes
  `theme.key_drivers` is an array; new `keyDriversText()` helper normalizes string-or-array input
  safely (the exact root cause of the white-screen incident).
- `mobile/lib/principalOpportunities.test.js` — 4 new tests, including the production-
  representative regression test that reproduces the exact live crash against the pre-fix source
  and confirms it is resolved by the fix.

## New: Error Boundary (defence-in-depth, Section 5)

- `mobile/components/ErrorBoundary.js` (new) — a screen-level React error boundary with a calm
  fallback (Retry, Open Operations, a safe diagnostic ID), logging the real error only via
  `console.error` for engineering diagnosis.
- `mobile/App.js` — the `screen === 'ExecutiveBriefing'` branch now wraps `<ExecutiveBriefing>` in
  `<ErrorBoundary>`.

## Housekeeping (found during validation, unrelated to the root cause)

- `.gitignore` (repo root) — added `mobile/.expo/`, a local Expo CLI state directory created
  while reproducing this incident on an emulator, which `expo-doctor` correctly flagged as
  machine-specific state that should never be committed.

## Explicitly Not Touched

No trading logic, execution logic, governance code, broker integration, or AI decision-making code
was touched. Nothing under `src/` changed. `lib/forecastEngine.js` and every other AT-ED-015
module were audited (see `Implementation_Summary.md`, Section 4) and found not to require any
change - no forecasting methodology was altered, per the directive's explicit instruction.
`screens/ExecutiveBriefing.js` itself is unchanged except for the one new `<ErrorBoundary>` wrapper
in `App.js` around its render call - the screen was not redesigned.
