# Test Report — AT-ED-016

## Automated Test Suite

All 30 mobile test files pass, 361 total tests across the suite (up from 303 before this pass —
58 new tests, zero removed, zero modified in a way that changes what they assert).

| File | Result | New tests this pass |
|---|---|---|
| `lib/cio.test.js` | pass — 30/30 | +5 |
| `lib/forecastEngine.test.js` | pass — 17/17 | +6 |
| `lib/forecastFactors.test.js` (new) | pass — 19/19 | +19 |
| `lib/forecastHistory.test.js` (new) | pass — 14/14 | +14 |
| `lib/investmentThesis.test.js` | pass — 10/10 | +2 |
| `lib/investmentCommittee.test.js` | pass — 7/7 | +0 (rewritten for the 9-department structure, same count) |
| `lib/principalRisks.test.js` | pass — 8/8 | +2 |
| `lib/principalOpportunities.test.js` | pass — 12/12 | +2 |
| `lib/portfolioPosition.test.js` (new) | pass — 6/6 | +6 |
| All other files (21) | pass, unchanged | — |

## New Tests This Pass, By Module

**`lib/forecastFactors.js` (19, new file)** — all eight implemented multi-factor evaluators
(historical performance, unrealised P&L, portfolio concentration, market regime, learning
confidence, research conviction, opportunity capture, risk readiness), each tested for both its
honest-unavailable state and its real-evidence-driven direction; `evaluateFactors()`/
`summarizeFactors()` integration tests confirming exactly eight factors are considered and counts
are real, never fabricated.

**`lib/forecastHistory.js` (14, new file)** — record construction only from `available: true`
horizons (never an unavailable one); due/not-due/already-resolved logic; directional grading
(`judgeDirection`) including the "no meaningful direction" null case; a full integration test
confirming a resolved record flows directly into AT-ED-014's `forecastAccountability()` and
produces a real accuracy figure; dedup logic (`shouldRecordNewForecast`/
`buildNewRecordsForHorizons`) confirming a fresh forecast is recorded once per horizon per
~day, not on every refresh.

**`lib/forecastEngine.js` (+6)** — Bull Case uses the real average of only winning trades, Bear
Case only losing trades; a losing-trade-free sample honestly falls the bear case back to the base
case rather than fabricating a loss; `probability` is the real historical win rate; expected
volatility/drawdown are always honestly unavailable (no model exists); every available forecast's
`explanation` names the real sample size and win rate; `tradeStatistics()` exposes the new real
`winCount`/`lossCount`/`avgWinPnl`/`avgLossPnl` fields.

**`lib/portfolioPosition.js` (6, new file)** — real week-to-date/month-to-date P&L summed from
per-broker fields (and a caught bug: `Number(null) === 0` was silently counting a broker with no
real evidence as a real zero - fixed by filtering `null`/`undefined` explicitly before
conversion); largest winning/losing position selection, with an honest `null` when nothing
qualifies.

**`lib/investmentThesis.js` (+2)** — `evidenceStrength()`'s Strong/Moderate/Weak tiers from a
real factor-availability ratio, with the real counts named in the returned text.

**`lib/investmentCommittee.js` (rewritten, 7 tests, same count)** — re-verifies the new
nine-department order and evidence-honesty guarantee; new tests for the three added departments
(Forecast Engine, using the real `tradeStatistics()` shape; Broker Monitoring, counting real
connected brokers out of the total; Portfolio Intelligence, using the real `plain_english` field).

**`lib/principalRisks.js` (+2)** — the new Monitoring Owner and Estimated Portfolio Effect
fields: a real, quantified effect for the position-loss card, an honest "not quantified" for
market-sourced risks with no severity model.

**`lib/principalOpportunities.js` (+2)** — the new Catalyst field: a real, distinct
`strongest_argument_for` value for recommendation cards (confirmed distinct from the "Why"
field), and the first real key driver for theme cards, with an honest fallback when none exist.

**`lib/cio.js` (+5)** — `cioNoActionReason()`'s honest, evidence-explaining "why no action" text
(3 tests) and `cioExecutiveBriefingSummary()`'s fragment-joining behaviour, including its honest
empty-evidence fallback (2 tests).

## A Second Real Bug Caught By a New Test (not live reproduction this time)

`lib/portfolioPosition.js`'s `weekToDatePnl`/`monthToDatePnl` initially filtered values using only
`Number.isFinite()` after conversion - but `Number(null)` evaluates to `0`, which is finite, so a
broker with no real `week_pnl`/`month_pnl` evidence at all was being silently counted as a real
£0 contribution rather than excluded. The "no brokers with real evidence returns null" test caught
this immediately. Fixed by filtering out `null`/`undefined` explicitly before the `Number()`
conversion.

## Field-Safety Verification (the AT-ED-015.1 lesson, applied proactively this time)

Every new raw-evidence field this pass reads for the first time was verified via `grep` against
an already-proven-safe call site elsewhere in this codebase before being used, rather than
assumed:

| New field read | Verified safe via existing call site |
|---|---|
| `status.brokers[].week_pnl` / `.month_pnl` | `lib/founderEvidenceMapping.js`'s own mapping (`row.week_pnl`/`row.month_pnl`) |
| `portfolio_command.portfolio_allocation.deployed_pct` | `lib/founderEvidenceMapping.js`'s own computation |
| `world_class_evidence.portfolio_intelligence.plain_english` | `screens/Portfolio.js`'s existing `TextBlock` render |
| `recommendations[].strongest_argument_for` | `screens/Recommendations.js`'s existing `TextBlock` render |
| `connection_readiness.note` | Already read in the pre-AT-ED-016 `InvestmentCommitteeCard`/`OperationsCentre` |

## Live Device Verification

An Android emulator (Pixel 9 AVD) was booted and Expo/Metro was run against the exact current
codebase and the real production API, matching the method that successfully reproduced the
AT-ED-015.1 incident live. This pass, Expo Go's own navigation did not reliably land inside the
running project across repeated automated (non-human-tap) launches - the same tooling limitation
disclosed in AT-ED-015.1's `Test_Report.md`. No error was observed in Metro's bundle log or in
`adb logcat` during the sessions that did run, but this is not the same as a confirmed clean
on-screen render, and is reported honestly as inconclusive rather than as a pass. Verification for
this pass therefore rests on: the full automated test suite (361 tests), the babel/expo-doctor/
expo-export toolchain, and the field-safety grep audit above - not a second live confirmation.
On-device confirmation by the Founder is, as always, the final acceptance step.

## Static/Toolchain Verification

- **Babel parse**: clean on all 85 files checked (81 tracked `.js` files under `mobile/` at time
  of this pass, plus the 4 new untracked files checked individually before staging).
- **`npx expo-doctor`**: 17/17 checks passed.
- **`npx expo export --platform android`**: clean, 591 modules bundled, zero errors.

## Regression Check

No trading logic, execution logic, governance, broker-integration, or AI decision-making code was
touched (nothing under `src/` changed). Every existing test file continues to pass with its
original assertions intact, except `lib/investmentCommittee.test.js`, which was intentionally
rewritten to match the directive's required nine-department structure (documented as a deliberate
evolution in the design review, not an accidental regression) and `lib/principalOpportunities.test.js`/
`lib/principalRisks.test.js`, which gained additive fields alongside their original ones.
