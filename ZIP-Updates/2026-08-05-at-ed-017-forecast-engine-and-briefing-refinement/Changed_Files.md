# Changed Files — AT-ED-017

## `mobile/lib/portfolioPosition.js`
Added `unrealizedPnlByBroker`, `totalUnrealizedPnl`, `closedTradesToday`, `realizedPnlToday`,
`realizedPnlByBrokerToday`, `exitsTodayCount`. New import of `TERMINAL_STATUSES` from
`forecastEngine.js` (reused, not duplicated) and `dateMs`/`todayIso` from `datetime.js`.

## `mobile/lib/portfolioPosition.test.js`
9 new tests for the above, including the `Number(null) === 0` null-safety gotcha this file already
guards against elsewhere.

## `mobile/lib/forecastEngine.js`
`caseValue()` gained `expectedRealisedProfit` (alias of `expectedChange` under an explicit name).
`projectHorizon()` gained `expectedExitCount`, `expectedNewEntryCount`, `nextExpectedExitInDays`,
and a new disclosed assumption in the `assumptions` array. No existing field, formula, or branch
changed.

## `mobile/lib/forecastEngine.test.js`
4 new tests for the fields above.

## `mobile/lib/cio.js`
Added `cioTodaysMoneyBreakdown` (realised/unrealised narrative), `cioAutonomyStatement` (explicit
autonomy claim, with an `executionAnomaly` flag added mid-review to fix a real contradiction),
`cioActivityFunnel` (structured reviewed/approved/rejected/submitted counts). Reworded
`cioTodaysMoneyBreakdown` mid-review to stop implying realised + unrealised sum to today's P&L.

## `mobile/lib/cio.test.js`
14 new/changed tests for the above.

## `mobile/screens/ExecutiveBriefing.js`
- `CurrentPositionCard`: new `performanceAttribution` prop; realised/unrealised breakdown and
  per-broker (paper/live) today figures, merged into one `Text` block with real `\n\n` breaks.
- `ForecastHorizonCard`: "What I expect" now includes exit timing / expected realised profit,
  merged into one `Text` block.
- `OvernightNarrativeCard`: new `unresolvedIncidentCount` prop; funnel line and autonomy statement
  added, all four fragments merged into one `Text` block (fixing a pre-existing spacing bug found
  while already touching this card).
- `ExecutiveBriefing()` assembly: threads `performanceAttribution` into `CurrentPositionCard` and
  `unresolvedIncidentCount` into `OvernightNarrativeCard`.

## `mobile/lib/investmentThesis.js`
Not in this directive's stated scope, but fixed during the mandated visual review: added
`formatThemeConviction()` (handles string-label confidence, eliminating a live "NaN%" bug) and
`withPeriod()` (eliminates double-period typos). Fixed a subject-verb agreement error in the
strategy-lean sentence. `alternativeThesis()` now strips each risk's own trailing period before
joining.

## `mobile/lib/investmentThesis.test.js`
9 new tests for the above.

## No backend (Python) files changed
This entire pass is mobile-only presentation-layer work, consistent with the directive's "evolution
of existing UI/engine, no new architectural layers" framing. No API contract, database schema, or
governance/execution logic was touched.
