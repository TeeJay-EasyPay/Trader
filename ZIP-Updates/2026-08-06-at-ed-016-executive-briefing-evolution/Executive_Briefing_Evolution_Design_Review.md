# Executive Briefing Evolution & Forecasting Engine Phase 2 — Design Review (AT-ED-016)

Produced before any code changes, per the directive's explicit instruction. Covers the required
review and the design decisions this pass makes as a result.

## What Was Reviewed

- **Governance/architecture**: `architecture/AI_TRADER_FOUNDING_PRINCIPLES_ARCHITECTURE_CONSTITUTION_v1.0.md`,
  `AI_TRADER_CONSTITUTION.md`, `architecture/ARCHITECTURE_DELTA.md` (full history), `governance/IMPLEMENTATION_LOG.md`.
- **Every prior AT-ED-01x report this session produced**: AT-ED-011 through AT-ED-015.1, in full
  (this session authored all of them and retains complete working knowledge of each - the current
  Executive Briefing, forecast engine, and every helper module were all built in this same
  continuous session).
- **Current CIO/forecast implementation**: `mobile/screens/ExecutiveBriefing.js`,
  `mobile/lib/cio.js`, `mobile/lib/forecasting.js` (AT-ED-014), `mobile/lib/forecastEngine.js`
  (AT-ED-015), `mobile/lib/investmentThesis.js`, `mobile/lib/investmentCommittee.js`,
  `mobile/lib/investmentRhythm.js`, `mobile/lib/principalRisks.js`,
  `mobile/lib/principalOpportunities.js`, `mobile/lib/founderActions.js`,
  `mobile/lib/forecastAccountability.js` (AT-ED-014, scaffold only, no persistence).
- **The AT-ED-015.1 incident**: the white-screen root cause (a raw backend field assumed
  array-shaped when it was sometimes a string) directly informs this pass's evidence-typing
  discipline - every new factor/field this pass reads from raw evidence is defensively typed
  before any array/string method is called on it.

## What This Pass Evolves vs. Retains

This is an evolution, not a rewrite. Retained unchanged: the screen/nav structure (Executive
Briefing remains the primary, full-width entry; Operations/Activity/Recommendations/Portfolio/
Market/Learning untouched), the `ErrorBoundary` from AT-ED-015.1, the honesty discipline (facts
vs. interpretation vs. scenario vs. forecast, established AT-ED-013 through AT-ED-015), and every
existing pure `lib/*.js` module's public contract unless this document says otherwise. Evolved:
the Executive Briefing's card structure (Part 1's 11 named sections replace the current ad-hoc
ordering), the forecast engine (Part 2 - multi-factor, Bull/Base/Bear), and forecast accountability
(Part 3 - real persistence added on top of AT-ED-014's scaffold).

## Part 1: Section-by-Section Mapping (old → new)

| New section | Built from |
|---|---|
| 1. Executive Summary | Expanded `lib/cio.js` composer combining greeting + headline + position + market comment + comfort/action-needed, capped at 8-10 sentences |
| 2. Current Position | Existing `Overall Position` facts + new: WTD/MTD (summed from real `status.brokers[].week_pnl`/`.month_pnl`), current allocation (`portfolio_command.portfolio_allocation.deployed_pct`, already computed), largest winning/losing position (sorted `portfolio.open_positions` by `unrealized_pl`) |
| 3. What Happened Overnight | Existing `cioOvernightActivity()` extended with real committee/risk-review signals already in evidence (`why_no_trade` counts, `connection_readiness` checks) |
| 4. Market Assessment | Existing `Market Environment` card, reworded as CIO belief statements rather than a metrics list |
| 5. Investment Thesis | Existing `currentInvestmentThesis()` extended with structured Positive/Negative/Unknowns/Assumptions/Catalysts/Evidence-Strength/Alternative fields, all derived from the same theme/recommendation evidence already read |
| 6. Forecast Centre | `lib/forecastEngine.js` extended (Part 2) to add Bull/Base/Bear cases, probability, and a written per-horizon explanation |
| 7. Principal Risks | Existing `lib/principalRisks.js` cards + Monitoring Owner (mapped to the real department that evidence concerns) + Estimated Portfolio Effect (real £/% where computable, honestly "not quantified" otherwise) |
| 8. Principal Opportunities | Existing `lib/principalOpportunities.js` cards + Catalyst field (reused from theme/recommendation evidence already read) |
| 9. Founder Actions | Existing `lib/founderActions.js` + a new "why no action is required" composer for the empty-state case, built from the same real facts (risk readiness, zero outstanding recommendations, zero incidents) rather than the bare one-line fallback |
| 10. Investment Organisation | Existing `lib/investmentCommittee.js` extended from 7 to the 9 named departments (adds Forecast Engine, Broker Monitoring, Portfolio Intelligence; drops the standalone "Chief Investment Officer" entry, since this section is departments reporting to the CIO, not the CIO itself) |
| 11. Closing Recommendation | Existing `cioClosingRecommendation()` (one sentence) expanded to a short multi-sentence closing matching the directive's example structure |

## Part 2: Multi-Factor Forecast Engine — Evidence Availability Audit

The directive lists 18 candidate evidence streams. Each was checked against what this app's
mobile evidence surface actually contains before being implemented as a factor - per the
project's standing rule, a requested capability with no real evidence source is honestly left
unimplemented, not faked. Full detail in `Forecasting_Engine_Architecture.md`.

**Implemented as real factors (evidence exists):** historical realised performance (unchanged
from AT-ED-015), current unrealised P&L, open position exposure, portfolio concentration (largest
position by unrealised-P&L magnitude, the only per-position field this codebase reliably has -
see caveat below), market regime freshness (`market_health`, already an audited signal reused
from AT-ED-014's conviction derivation), learning engine confidence (win rate), research
conviction (average recommendation confidence), execution quality (orders submitted vs. rejected
in the period), risk readiness (`connection_readiness.trade_ready`).

**Important correction found during this review (a direct application of the AT-ED-015.1
lesson - never assume a field's shape or meaning without verifying it live):**
`market_intelligence_centre.volatility` and `.momentum` were initially assumed to be real
qualitative signals. Reading `founderEvidenceMapping.js`'s `statusFromFounderEvidence()` line by
line shows both are **unconditional hardcoded placeholder strings**
(`'See recommendation evidence where available'`) - never derived from real backend data, for
every response this client ever produces. Using either as a forecast factor would mean reading a
fixed sentence as if it were live analysis - exactly the class of mistake that caused the
AT-ED-015.1 incident, just on a string field this time instead of a `.join()` call. Both are
therefore explicitly excluded from the factor engine, not implemented as "always neutral" or any
other disguised form.

**Also not implemented - no real evidence source exists anywhere in this app's evidence surface,
and none was fabricated:** trend persistence (no time-series metric of any kind is retained
client-side), sector rotation (the field exists in the schema but is populated `[]` in every
observed production response - `founderEvidenceMapping.js:319`), committee confidence as a
distinct number (the Investment Committee section already reports department-level qualitative
conclusions, not a scored confidence this pass could reuse without inventing a scoring model),
macroeconomic events, economic calendar, broker liquidity (no liquidity metric exists, only
balances). This gap list is disclosed directly to the Founder in `Founder_Briefing.md`, not
hidden.

**Concentration caveat:** `portfolio.open_positions[]` items are only ever proven, in this
codebase, to reliably carry `symbol` and `unrealized_pl` (verified by grepping every existing
call site before adding a new one - no call site anywhere reads a position-level market value,
quantity, or price field). "Portfolio concentration" is therefore approximated by unrealised-P&L
magnitude, not true position size/market value, and is labelled as exactly that in the UI - a
real but limited signal, not the market-value-weighted concentration measure an institutional CIO
would ideally have.

## Part 3: Forecast Accountability — What "Store and Compare" Honestly Means Here

This is a mobile-only, presentation-layer pass - no backend/database change is in scope (matching
the constitution's boundary maintained since AT-ED-012). "Store every forecast" is implemented as
local `AsyncStorage` persistence (the same mechanism `lib/founderEvidenceCache.js` already uses),
not a backend table. "Compare forecast to actual outcome" is honestly bounded by what this device
can observe: a forecast's outcome is resolved against the portfolio value the app next observes
live on or after the forecast's target date - not a continuously-sampled time series, since none
is collected. This resolution granularity (bounded by how often the Founder opens the app) is
disclosed, not hidden. "Improve future models automatically" (true automated retraining) is out of
scope for this pass - the accountability *tracking* (store → resolve → report error) is real and
implemented; automatic model adjustment from that history is scaffolded architecture for a future
pass, exactly as AT-ED-014's `forecastAccountability.js` already scaffolded the shape for.

## Non-Negotiables Checklist

Modular architecture (new logic lives in new, single-purpose `lib/*.js` files, mirroring every
prior pass's convention) - no monolithic file. Every existing test suite is re-run and must
continue to pass unmodified except where a field this pass adds requires a new, additive test.
No mock data. No fabricated certainty - every new number is either a real evidence value, a
disclosed statistical derivation of real evidence (same discipline as AT-ED-015's linear
extrapolation), or an explicit "not available" state with a named reason.
