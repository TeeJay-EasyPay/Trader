# Forecast Model Design — AT-ED-015

## Why a Linear Extrapolation, and Not Something More Sophisticated

The directive lists many possible signals — historical trades, returns, positions, open risk,
volatility, capital deployment, research/learning trends, strategy performance, win rate, holding
periods, market regime, macro events, news, historical AI performance, broker history, portfolio
history. Of these, this backend's mobile evidence surface genuinely provides dated, per-trade
realised P&L (`performanceAttribution`) and nothing else with enough structure to build a
statistical model from. There is no volatility series, no macro feed, no news feed, and holding
period is only available per-trade, not aggregated into a distribution the mobile layer could
reason about without recomputing potentially-large history client-side.

Given that, the honest choice was between (a) a simple, fully-disclosed model built from the one
real dated dataset available, with every assumption and risk stated explicitly, or (b) continuing
to report every horizon as unavailable. AT-ED-015's directive explicitly asks for (a) - "implement
evidence-based forecasting... wherever possible" - so this pass builds it, but keeps every
projection honest about exactly how thin the model is.

## The Calculation

For each horizon (Tomorrow = 1 day, 7 Days, 30 Days, Quarter = 91 days, Year End = 365 days):

```
expectedTrades  = tradesPerDay × horizonDays
expectedChange  = expectedTrades × averagePnlPerTrade
expectedValue   = currentPortfolioValue + expectedChange
```

Where `tradesPerDay` and `averagePnlPerTrade` are both computed directly from the same dated,
closed-trade evidence Learning already reports a win rate and closed-trade count from.

## Confidence Is Sample-Size-Derived, Not a Model Score

`confidenceFromSampleSize()` returns Low (5–14 trades), Medium (15–29), or High (30+) - three
named tiers based purely on how much historical evidence backs the projection, not a probability
estimate from any statistical test. This is intentionally conservative: a bigger sample makes the
historical averages more likely to be representative, but does not by itself make the *future*
more predictable. The `confidenceReason` field always states the exact sample size and the number
of days it spans, so the Founder can judge the basis themselves rather than trusting a label.

## The Alternative Scenario

Every horizon's `alternativeScenario` is deliberately the simplest possible counter-case: "if no
further trades close in this period, the portfolio remains at its current value." This is not the
only plausible alternative, but it is the one alternative that requires no additional assumption
beyond the ones already disclosed - a genuinely conservative floor, not a cherry-picked bear case.

## Known Limitations (disclosed, not hidden)

- **No regime-awareness.** The model does not adjust for whether the market environment reads as
  favourable or unfavourable - a longer, calmer period and a shorter, volatile one contribute
  identically to `averagePnlPerTrade` if the historical window mixes both.
- **No time-decay or recency weighting.** A trade from the start of the historical window counts
  exactly as much as the most recent one. A future version could weight recent trades more
  heavily; this version deliberately keeps the calculation simple enough that every step is easy
  to verify by hand against the underlying evidence.
- **Longer horizons compound more assumption risk.** A Year End projection extrapolates the same
  daily pace 365 days forward from what might be a much shorter observed history - `projectHorizon()`
  states this explicitly in its `principalRisks` field for every horizon longer than 7 days.
- **Small samples are honestly excluded, not down-weighted.** Below `MIN_SAMPLE_SIZE = 5`, there
  is no partial projection at any confidence level - the evidence is judged too thin to extrapolate
  from at all, rather than shown with an artificially low confidence that might still mislead.

## Tests

11 tests in `lib/forecastEngine.test.js`, including: real terminal-status filtering that matches
Learning's own closed-trade definition; the honest under-`MIN_SAMPLE_SIZE` unavailable state; a
hand-verified real calculation (1 trade/day × 7 days × £10 average = a real £70 expected change,
asserted exactly); a missing portfolio value never producing a fabricated `expectedValue`; and
confirmation that all five directive-named horizons are returned, in order, honestly unavailable
together when evidence is insufficient (never partially guessed).
