# Forecasting Engine Architecture — AT-ED-015

## Two Forecasting Modules, Two Jobs

This pass adds `mobile/lib/forecastEngine.js` alongside AT-ED-014's `mobile/lib/forecasting.js`.
They do different jobs and both stay:

- **`lib/forecasting.js`** (AT-ED-014) — conviction derivation from multi-signal agreement, the
  auto-trade-threshold scenario, and the portfolio-facts/no-model-exists scaffold. Untouched this
  pass.
- **`lib/forecastEngine.js`** (new, this pass) — the Section 4 "Forecast Intelligence Engine":
  real, evidence-based portfolio-value projections for Tomorrow / 7 Days / 30 Days / Quarter /
  Year End, built from actual historical closed-trade data.

## The Interface Contract

Every screen that wants a forecast calls exactly one function:

```js
projectPortfolioHorizons({ closedTrades, currentPortfolioValue })
// -> [{ horizon, horizonKey, available, expectedValue, expectedChange, confidence,
//       confidenceReason, evidence, assumptions, principalRisks, alternativeScenario }, ...]
```

This is the directive's own requirement ("Design the architecture so improved forecasting models
can later replace the current implementation without changing the UI") implemented literally: the
UI (`screens/ExecutiveBriefing.js`'s `OutlookJourneyCard`) only ever reads this shape. A future,
more sophisticated model — one that incorporates market regime, macro events, or a real
volatility model — only needs to keep producing the same shape from `tradeStatistics()` and
`projectHorizon()`. Nothing in the screen needs to change.

## What Feeds It

`normalizeClosedTradesFromAttribution()` reads `performanceAttribution` (the same evidence
Learning's "Closed Trades"/"Win Rate" figures and Portfolio's trade history are already built
from) and filters to the same terminal-status list (`closed`, `target_exit`, `stop_exit`,
`manual_exit`) `founderLearningForMobile()` already uses for Learning's own closed-trade count -
so this engine's sample size can never silently disagree with what the Learning screen already
tells the Founder about the same underlying trades.

## The Model Itself: A Disclosed Linear Extrapolation

`tradeStatistics()` computes, from real dated trades: sample size, win rate, average realised P&L
per trade, and the observed pace (trades per day) over the dated span. `projectHorizon()` then
extrapolates: `expectedChange = tradesPerDay × horizonDays × averagePnl`. This is a simple model,
and every projection says so explicitly in its own `assumptions` field ("assumes the historical
pace of closed trades and their average realised result persist unchanged") and `principalRisks`
field (market conditions could invalidate the averages; short horizons are especially sensitive to
the next trade or two). See `Forecast_Model_Design.md` for the full design rationale.

## The Honesty Floor

`MIN_SAMPLE_SIZE = 5`. With fewer than five dated, realised trades, `tradeStatistics()` returns
`available: false` with the exact count and the threshold named, and every horizon in
`projectPortfolioHorizons()`'s output is `available: false` — never a partial or optimistically-
extrapolated figure from too little evidence. This mirrors AT-ED-013/014's `portfolioProjection()`
honesty pattern exactly, just with a real, working model behind the "available" branch now that
one exists.

## What Still Isn't Attempted

Macro events, economic-calendar data, and news are listed in the directive's signal list but no
feed for any of them exists anywhere in this backend's evidence. Rather than reference a
non-existent data source, this engine does not attempt to incorporate them - they are not
referenced anywhere in the forecast's evidence, assumptions, or risk fields, to avoid implying a
capability the app does not have. Market regime (a real, if qualitative, field -
`current_market_regime`) is surfaced separately, in the Current Market Environment section, rather
than folded into the numeric projection, since there is no way to weight a qualitative regime read
into a quantitative extrapolation without inventing a conversion.
