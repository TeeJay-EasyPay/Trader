# Forecast Accountability — Design Note

## The Honest Starting Point

Section 9 asks AI Trader to track every forecast against its actual outcome, and to explain why
forecasts succeeded or failed. This backend has no persisted forecast-history table — and
AT-ED-014 is the pass that introduces forecasting at all (`lib/forecasting.js`, this pass). There
is, quite literally, nothing yet to compare a forecast against a realized outcome.

Per the directive's own instruction ("scaffold the architecture rather than fabricating
results"), `mobile/lib/forecastAccountability.js` defines:

- `FORECAST_RECORD_SHAPE` — the field names a future forecast-history record should use
  (`forecast`, `expectedOutcome`, `actualOutcome`, `confidenceGiven`, `createdAt`, `resolvedAt`),
  so a future persistence layer has one authoritative shape to write to.
- `forecastAccountability(records)` — computes real statistics (accuracy, average confidence
  given) whenever a caller has real records to pass in, and otherwise returns the honest,
  literal truth: `available: false`, with the reason "AI Trader has not yet recorded a forecast
  to compare against an outcome."

With no persistence layer yet built (a backend change, out of scope for this presentation-only
pass), the CIO workspace does not currently call this module with real records — it exists as the
scaffolded architecture the directive asked for, ready for a future pass to wire up once forecasts
are actually being persisted and resolved.

## Why Accuracy Requires an Explicit Judgement, Not Just an Outcome

`forecastAccountability()` only counts a record toward accuracy once it has an explicit
`correct: true/false` field set by the caller — never inferred by this module comparing
`expectedOutcome` to `actualOutcome` itself. Whether a forecast "came true" is a domain judgement
(a portfolio projection that landed within a stated range might count as correct even if not
exact; a directional call might not) that this module deliberately does not make up a rule for.
An unresolved or unjudged record is excluded from the accuracy calculation entirely, not counted
as either a hit or a miss.

## Tests

5 tests in `lib/forecastAccountability.test.js`, including a "deliberate honesty check": no
records at all always returns `available: false` and `accuracy: null`, never a fabricated
percentage — the same pattern AT-ED-013's `portfolioProjection()` test established.
