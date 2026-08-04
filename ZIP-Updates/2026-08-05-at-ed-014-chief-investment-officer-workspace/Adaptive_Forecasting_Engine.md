# Adaptive Forecasting & Strategic Intelligence Engine — Design Note

## The Four Layers

`mobile/lib/forecasting.js` defines `FORECAST_LAYER = { FACT, INTERPRETATION, SCENARIO,
FORECAST }` and every value this engine produces is tagged with exactly one of them:

- **Fact** (`portfolioForecast().facts`) — current portfolio value, cash, deployed capital, open
  position count. Pass-through, unmodified, from the same `portfolio` object every other screen
  already reads.
- **Interpretation** (`deriveConviction()`) — a conviction level (High/Medium/Low) derived from
  whether real signals (market-health tone, average current-recommendation confidence, and
  learning win rate) agree with each other. Requires at least two real signals before naming a
  level at all — with fewer, it returns `'Not Established'` rather than guessing.
- **Scenario** (`autoTradeScenario()`) — the one scenario this evidence genuinely supports: how
  many currently-active recommendations already clear the real 85% auto-trade confidence
  threshold (`AUTO_TRADE_CONFIDENCE_THRESHOLD`, the same value `lib/recommendations.js` already
  gates auto-execution eligibility on), and what that implies if it holds.
- **Forecast** (`portfolioForecast().valueProjection` / `.expectedDrawdown` /
  `.expectedVolatility`) — every field that would require a time-series or volatility model this
  backend does not have. Always `available: false` with a specific reason.

## Why the 7/30/90-Day Figures Are Still Not Fabricated

Section 6 says: "Build the architecture now. Implement every capability that the current evidence
honestly supports. If additional backend capability is required for future intelligence, scaffold
the architecture rather than fabricating results." This is taken literally: the architecture
(`FORECAST_LAYER`, `portfolioForecast()`'s full shape including `valueProjection`,
`expectedDrawdown`, `expectedVolatility`) is built and in place. But this backend still has no
portfolio-value time-series model, no volatility model, and no economic-calendar feed — confirmed
by the same review of `production_evidence.py` and every `application/*.py` service that
AT-ED-013's `portfolioProjection()` was built on. So those three specific fields are always
scaffolded as unavailable, with the reason named, and `portfolioForecast()` reuses AT-ED-013's
exact `portfolioProjection()` for the value-projection reason (injected via the `valueProjection`
parameter) rather than defining a second, potentially-divergent "no model exists" statement.

## What Changed vs. What's Scaffolded

| Capability | Status |
|---|---|
| Current portfolio facts | Implemented (Fact) |
| Auto-trade-eligibility scenario | Implemented (Scenario) |
| Conviction from multi-signal agreement | Implemented (Interpretation) |
| 7/30/90-day portfolio value | Scaffolded — no time-series model exists |
| Expected drawdown | Scaffolded — no volatility model exists |
| Expected volatility | Scaffolded — no volatility model exists |
| Economic-calendar/macro-aware scenarios | Not attempted — no macro feed exists in this backend at all; not referenced anywhere in the UI, to avoid implying it exists |

## Tests

10 new tests in `lib/forecasting.test.js`, covering: honest "Not Established" conviction with
insufficient signals, correct High/Medium/Low derivation from real signal combinations
(including a caught bug — `'unfavourable'.includes('favourable')` was silently miscounting a
negative signal as positive; fixed by tracking each signal's polarity as a boolean instead of
substring-matching its text), the auto-trade scenario's real threshold-count behaviour, and the
portfolio forecast's fact pass-through plus its three always-honest forecast fields.
