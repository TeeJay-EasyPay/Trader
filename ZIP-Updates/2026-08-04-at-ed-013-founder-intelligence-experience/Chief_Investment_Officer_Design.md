# Chief Investment Officer — Design Note

## What the CIO Is

The directive is explicit and this design honours it literally: **"The CIO is NOT another chatbot. The CIO is NOT another AI model. The CIO is the executive voice of the autonomous investment organisation."**

The CIO is implemented as `mobile/lib/cio.js` — a pure, dependency-free presentation module. It calls no network endpoint, invokes no model, and stores no state. Every function takes fields the backend already computes (the same `status.founder_experience`, `status.world_class_evidence`, `activity.summary`, and `recommendations[]` fields the app already had access to and was already rendering as label/value grids) and composes them into plain-English, first-person prose.

Nothing the CIO says is new information. It is the same evidence, spoken instead of tabulated.

## Why a Separate Module

- **Testability.** Kept free of React/React Native imports, exactly like every other `lib/*.js` module in this project, so it runs under plain Node (`node lib/cio.test.js`) with no bundler or emulator.
- **Auditability.** Every function's only inputs are named fields; there is no hidden state, no fetch, no timer. Reading the function is reading the entire behaviour.
- **Reuse.** The same `cioMarketOutlook()` powers both the Dashboard's Market Outlook line and the Market screen's lead paragraph — one composer, one voice, everywhere.

## The Functions

| Function | Feeds | Used On |
|---|---|---|
| `cioGreeting()` | device clock | Dashboard |
| `cioExecutiveSummary()` | `executive.headline` / `what_to_do` / `what_to_worry_about` | Dashboard |
| `cioOvernightActivity()` | `activity.summary.research` / `.execution` | Dashboard, Activity |
| `cioMarketOutlook()` | `market_intelligence_centre.*` | Dashboard, Market |
| `cioAverageConfidence()` | `recommendations[]` | Dashboard |
| `portfolioProjection()` | (none — always honest) | Dashboard, Portfolio |
| `cioLearningNarrative()` | `dailyLearning.evidence_summary` | Learning |

## The Portfolio Projection Decision

Section 8 asks for 7/30/90-day portfolio value projections "only where evidence supports reasonable forecasting." This backend has no portfolio-value forecasting model anywhere — confirmed by reviewing `production_evidence.py` and every `application/*.py` service during this pass. It has per-trade R-multiple expectancy estimates on individual recommendations, which is not the same statistical object as a portfolio-value trajectory over time.

`portfolioProjection()` therefore always returns `{ available: false, reason: "..." }`, and every screen that surfaces it shows that honest reason rather than a number. This is the single clearest test of the directive's own "never fabricate" instruction against its own "show a 7/30/90-day projection" instruction — the two only reconcile by being honest about the gap. See `Founder_Briefing.md` for how this is explained to the Founder directly, and `lib/cio.test.js`'s "deliberate honesty check" test for how it's guarded against silent regression.

## Where the CIO Voice Now Appears

- **Dashboard** — the primary "morning briefing" landing screen (`CIOBriefingCard`): greeting, executive summary, overnight activity, market outlook, confidence, portfolio trajectory.
- **Activity** — the Trading Narrative card's opening paragraph.
- **Market** — the top summary card's lead paragraph, replacing a static question.
- **Learning** — the top summary card's lead paragraph, framed as a quarterly performance review.
- **Portfolio** — the honest Portfolio Projection line only (Portfolio's other content remains fact-first, deliberately, per Section 8's "do not alter calculations, improve clarity only").
