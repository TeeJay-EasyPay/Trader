# Investment Committee Model — Design Note

## The Pipeline

Section 5 asks AI Trader to be represented as an investment organisation:

```
Research -> Learning -> Market Intelligence -> Strategy -> Risk -> Execution -> Chief Investment Officer
```

`mobile/lib/investmentCommittee.js`'s `buildInvestmentCommittee()` returns exactly these seven
departments, in this order, each with a `hasEvidence` boolean and a `conclusion` string. Every
conclusion is built from a field this app already reads elsewhere — no new per-department scoring
model was invented:

| Department | Evidence Source |
|---|---|
| Research | `operations_health.last_research_run` / `.last_equity_research` / `.last_crypto_research` |
| Learning | `dailyLearning.evidence_summary` (the same object Learning's own summary card already uses) |
| Market Intelligence | `market_intelligence_centre.market_health` |
| Strategy | `recommendation_summary.active` |
| Risk | `connection_readiness.trade_ready` / `.note` |
| Execution | `activity.summary.execution.orders_submitted` |
| Chief Investment Officer | `executive_dashboard.headline` |

A department with no evidence reports that honestly (`hasEvidence: false`, a named reason) rather
than inventing a conclusion — `InvestmentCommitteeCard` renders this as a "No Evidence Yet"
status pill, never a fabricated "Reporting" state.

## Future-Ready by Construction (Section 12)

`buildInvestmentCommittee()` returns a plain array, and `InvestmentCommitteeCard` renders it with
a single `.map()` — there is no fixed set of named JSX slots per department. A future specialist
committee (Global Macro, ETF, Commodities, etc.) is one more object appended to the array this
function returns; nothing about `CIO.js`'s structure needs to change to accommodate it.

## Tests

5 tests in `lib/investmentCommittee.test.js`: the seven departments in correct pipeline order; a
fully-honest all-empty-evidence case (every department reports `hasEvidence: false` with a
non-empty reason); Research reflecting real evidence when present; Risk correctly distinguishing
a ready vs. not-ready readiness state; the Chief Investment Officer department using the real
executive headline verbatim.
