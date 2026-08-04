# Chief Investment Officer Workspace — Design Note

## Section 1: The CIO Is Its Own Screen

The directive is explicit: "The CIO is NOT a card. The CIO is NOT embedded within Dashboard. The
CIO is NOT an expandable section." This pass gives the CIO its own navigation item and its own
screen (`mobile/screens/CIO.js`), and the app now launches directly into it — `App.js`'s
`SCREENS` array is `['CIO', 'Operations', 'Activity', 'Recommendations', 'Portfolio', 'Market',
'Learning']`, and the initial `screen` state is `'CIO'`.

The former Dashboard is renamed **Operations** (`mobile/screens/Operations.js`,
`OperationsCentre`), and now covers operational health only: 24-hour operations, connection
readiness, broker panels, and the raw founder brief report. The executive/investment-leadership
content that used to open Dashboard (AT-ED-013's `CIOBriefingCard`) moved to the CIO screen and
was substantially expanded per Section 2/3 of this directive.

## Section 2: Modular Components, Not a Monolith

`CIO.js` exports 17 named components, exactly matching the directive's list, each doing one job
and each independently reusable:

`CIOHeader`, `MorningBriefCard`, `InvestmentSummaryCard`, `InvestmentThesisCard`,
`AlternativeThesisCard`, `PortfolioOutlookCard`, `ForecastCard`, `ConvictionCard`,
`ConfidenceCard`, `MarketOutlookCard`, `InvestmentCommitteeCard`, `DailyRhythmCard`,
`FounderActionsCard`, `ExecutiveMessagesCard`, `PrincipalRisksCard`,
`PrincipalOpportunitiesCard`, `TradingOrganisationCard`.

`CIOWorkspace` assembles them in one place. This follows the same convention every other screen in
this codebase already uses (Portfolio.js, Activity.js, etc. each define several small functions
in one file) rather than inventing a new component-directory structure — modularity here means
"one function, one job, one evidence source," not "one file per component."

## Section 3: The Morning Brief's Ten Questions

`MorningBriefCard` answers the directive's ten questions in order, each backed by a specific real
field:

1–2 (what happened / why) → `cioExecutiveSummary()` (`executive.headline`/`what_to_do`/
`what_to_worry_about` — unchanged from AT-ED-013).
3–4 (actions taken / why) → `cioOvernightActivity()` (`activity.summary.research`/`.execution`).
5 (what we believe) → the Investment Thesis card, immediately below.
6 (risks) → `cioPrincipalRisks()` — real upcoming-risk evidence plus a real count of positions
currently at a loss.
7 (opportunities) → `cioPrincipalOpportunities()` — a real fresh-recommendation count plus the
highest-confidence tracked theme.
8 (what's next) → `MarketOutlookCard`/`ForecastCard`, immediately below.
9 (what the Founder should know) → the full brief itself.
10 (does the Founder need to act) → `cioFounderActionRequired()` — literally binary: only says
"No Founder action is required today" when both outstanding-recommendation and unresolved-
incident counts are truthfully zero.

## No New AI System

Every card composes existing evidence through the same kind of pure, dependency-free `lib/*.js`
functions AT-ED-013 established for `lib/cio.js`. Three new modules were added for this pass —
`lib/investmentThesis.js`, `lib/forecasting.js`, `lib/investmentRhythm.js`,
`lib/investmentCommittee.js`, `lib/forecastAccountability.js` — each following the identical
convention: no React import, no network call, fully covered by plain-Node tests. See
`Adaptive_Forecasting_Engine.md`, `Investment_Rhythm.md`, `Investment_Committee_Model.md`, and
`Forecast_Accountability.md` for each module's own design account.

## Section 11/12: Visual Language and Future-Readiness

The CIO screen reuses the existing `StatusPill`/`Metric`/`TextBlock`/`Section`/
`CollapsibleSection` primitives and the 🟢🔵🟡🔴 tone system AT-ED-013 already introduced — no new
visual language was invented. `InvestmentCommitteeCard` renders `buildInvestmentCommittee()`'s
output as a plain array map, not a fixed set of named JSX slots, so a future specialist committee
(Global Macro, ETF, etc. — Section 12) is one more array entry, not a CIO-screen redesign.
