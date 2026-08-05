# Forecast Engine Enhancements — AT-ED-017 Part 2

## Scope

`lib/forecastEngine.js` already produced a real, evidence-based Base/Bull/Bear projection of
expected portfolio value per horizon (Tomorrow / 7 Days / 30 Days / Quarter / Year End), built by
extrapolating the historical pace and average result of closed trades. This directive asked for
the same engine to also communicate expected realised profit, expected unrealised profit, expected
portfolio value, expected realised cash, expected exit timing, expected number of exits, expected
number of new entries, confidence, and best/base/worst case — where evidence supports it, honestly
disclosed where it doesn't.

This was an extension of the existing engine, not a replacement. No formula that already existed
was changed; every new field is derived from the same `tradeStatistics()` sample the engine already
computes.

## What Was Added

### `caseValue()` — `expectedRealisedProfit`

`expectedChange` (the projected change in portfolio value for a given case) has, since this engine
was first written, only ever been computed by extrapolating trades that **closed** — see
`normalizeClosedTradesFromAttribution()`'s `TERMINAL_STATUSES` filter. A closed trade's P&L is, by
definition, realised. `expectedChange` therefore always meant "expected realised profit" — it was
simply never given that name. It now is, as an additive field (`expectedRealisedProfit`) alongside
the existing `expectedChange`, so callers can use the clearer name without any consumer of the old
field needing to change.

### `projectHorizon()` — exit/entry pace and timing

Three new fields, computed once per horizon from the same `stats.tradesPerDay` the engine already
derives:

- **`expectedExitCount`** — `tradesPerDay * horizon.days`, rounded to one decimal. The same pace
  that drives the P&L projection also implies how many positions are expected to close in that
  window; this was always latent in the sample and never surfaced.
- **`expectedNewEntryCount`** — the same value as `expectedExitCount`, under an explicitly disclosed
  assumption (see below). This backend has no separate model for how often *new* positions open —
  every closed trade in the sample had exactly one entry, so the closed-trade pace is the only
  real, dated basis available for an entry estimate too.
- **`nextExpectedExitInDays`** — `1 / tradesPerDay`, rounded to one decimal. Answers "when do we
  expect the next exit?" directly, rather than leaving the Founder to derive it from a pace figure.

A new line was added to the horizon's `assumptions` array disclosing the entries-reuse-exits-pace
assumption explicitly, so it is never silently implied.

### What Was Deliberately Not Added

- **Expected unrealised profit** as a *forecast* — this backend has no model for how currently open
  positions will move (that would require a price/volatility model, which
  `NO_VOLATILITY_MODEL_REASON` already, correctly, says doesn't exist). What *is* real is the
  **current** unrealised P&L on open positions right now — that's not a forecast, it's a fact, and
  it now lives in `lib/portfolioPosition.js` (see below), not the Forecast Engine.
- **Expected realised cash** as a distinct figure from realised profit — this backend tracks
  per-trade net P&L (`profit_loss`), not gross trade proceeds/notional. Reporting a separate "cash"
  figure would require data this backend doesn't have. `expectedRealisedProfit` is presented as the
  realised-cash-impact estimate, honestly scoped to what it actually is: net profit, not gross
  proceeds.

## Realised/Unrealised Facts (lib/portfolioPosition.js)

The Founder's other ask — "how much has Alpaca made, how much has Kraken made, is it realised or
unrealised" — is a **current-state fact question**, not a forecast, so it was added alongside the
existing `weekToDatePnl`/`monthToDatePnl`/`largestPosition` helpers rather than in the Forecast
Engine:

- `unrealizedPnlByBroker(openPositions)` / `totalUnrealizedPnl(openPositions)` — sums
  `open_positions[].unrealized_pl`, grouped by the real `broker` field
  `production_evidence.py`'s `_portfolio_payload()` already tags each position with.
- `realizedPnlToday(trades)` / `realizedPnlByBrokerToday(trades)` / `exitsTodayCount(trades)` —
  sums closed-trade `profit_loss` for trades that closed **today** (UTC calendar day), reusing
  `forecastEngine.js`'s own `TERMINAL_STATUSES` so "closed" never means something different in two
  places on the same screen.

All five functions follow the same null-safety convention already established in this file
(`sumBrokerField`'s `Number(null) === 0` guard) — a broker or trade with a genuinely missing value
is excluded, never silently counted as a real zero.

## Test Coverage

- `lib/forecastEngine.test.js` — 4 new tests covering `expectedRealisedProfit`,
  `expectedExitCount`/`expectedNewEntryCount`, `nextExpectedExitInDays`, and the disclosed
  entries-assumption. 21 tests total (up from 17).
- `lib/portfolioPosition.test.js` — 9 new tests covering broker grouping, null-safety, and the
  today-boundary filter. 15 tests total (up from 6).

## Known Limitation

The live account's closed-trade history is currently below `MIN_SAMPLE_SIZE` (5), so every live
verification this session exercised the honest "not enough evidence" path, not the enriched
available-forecast path with real numbers. The available-forecast path is covered by unit tests
with synthetic data but has not yet been observed live with real data.
