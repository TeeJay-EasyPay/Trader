# Executive Communication Review — AT-ED-015

Every card on the Executive Briefing (née CIO) screen, reviewed against: "Would a real Chief
Investment Officer communicate this way?" Written before any AT-ED-015 code changes, per Section
1's instruction.

## Verdict: No. The screen is a well-organised data dump, not a briefing.

AT-ED-014 gave the CIO real evidence and real honesty discipline, but it stacked seventeen
same-weight cards in roughly the order they were built, not the order a CIO would actually talk.
A real CIO does not open a meeting by handing over seventeen index cards. They tell you where
things stand, in a conversation, in under a minute, and let you ask for more.

## Specific findings

**1. The screen repeats itself.** `MorningBriefCard` includes a "Market Outlook" line and a
"Principal Risks" line — and then `MarketOutlookCard` and `PrincipalRisksCard`, lower on the same
screen, say the *same thing again*, word for word (both call `cioMarketOutlook()`/
`cioPrincipalRisks()` with the same inputs). A real CIO does not repeat themselves twice in one
briefing. **Verdict: redesign — one owner per fact, not two cards computing the same sentence.**

**2. Confidence and Conviction are floating, standalone cards.** `ConvictionCard` and
`ConfidenceCard` sit alone with no attached claim — a conviction level with nothing to be
convicted *about* directly above it, a confidence percentage with no forecast or thesis directly
beside it. Section 8 is explicit: these numbers only mean something next to the claim they
qualify. **Verdict: redesign — remove both as standalone cards; attach confidence to the forecast
that earned it, and conviction to the thesis it supports.**

**3. Trading Organisation leaks engineering language.** `TradingOrganisationCard` — the one card
explicitly meant to answer "is my organisation healthy?" in one look — shows `Metric label="Worker
Health"` and `Metric label="Database Durability"`. A Founder does not know what a "worker" is and
should not have to. **Verdict: redesign — plain business framing only (Research/Learning/
Execution/Risk/Infrastructure/Governance, each as a one-word health read).**

**4. Executive Messages is a notification feed wearing a suit.** It surfaces a raw "Unread
Notifications" count alongside evidence-gap explanations. A CIO doesn't forward you your unread
inbox count — they tell you the two or three things that actually change what you should think or
do. **Verdict: redesign — drop the notification count entirely; keep only items that materially
affect an investment decision.**

**5. Investment Rhythm is six rows of metrics, not a rhythm you can see at a glance.** Each stage
is its own boxed row with a label, a pill, and a caption — technically accurate, visually a wall.
**Verdict: redesign — a single checklist/timeline (✓ / current / upcoming), current stage visually
distinguished, not six separate cards' worth of vertical space.**

**6. Principal Risks and Principal Opportunities are single paragraphs, not individual items.**
One sentence lists two or three risks joined with semicolons; one sentence lists a fresh-
recommendation count and a theme name. Section 6/7 want each risk and each opportunity to stand
on its own with its own structured fields (impact, likelihood, mitigation / why, evidence,
expected benefit, confidence, horizon). **Verdict: redesign — one card per risk, one card per
opportunity, each with real fields, not a joined sentence.**

**7. Founder Actions doesn't actually tell you what to do.** It repeats the same one-line
"X recommendations awaiting your review" sentence already said in the Morning Brief, plus two
buttons. It never answers what the directive asks: what do I need to do, why, what's the benefit,
what's the risk, is there a deadline, what happens if I do nothing. **Verdict: redesign — each
outstanding action becomes its own structured item; the honest "No Founder action is required
today" state is kept exactly as-is when nothing is outstanding.**

**8. There is no journey.** Nothing on the screen tells the Founder where AI Trader believes
things are headed — yesterday, today, tomorrow, in a week, a month, a quarter, by year end.
Portfolio Outlook and Forecast show current facts and an honest "no model exists yet" placeholder,
but never attempt a real, evidence-based trajectory. **Verdict: build new — a Forecast
Intelligence Engine using real historical closed-trade evidence (see
`Forecasting_Engine_Architecture.md`), and a Story/Journey card that walks through each horizon
honestly, including the horizons evidence still can't support.**

**9. The screen's actual reading order doesn't match how a CIO would speak.** Facts about the
current portfolio appear before the thesis that explains them; the organisation's health appears
last, after risks and opportunities that depend on knowing whether the organisation is even
functioning normally. **Verdict: redesign — reorder to Section 2's structure: position, market
environment, what happened and why, thesis and alternative, expected outlook (the journey), risks,
opportunities, actions, closing recommendation — with Trading Organisation and Investment
Committee/Rhythm available as supporting detail below the fold, not interleaved with the
narrative.**

**10. "CIO" as a navigation label reads like a job title, not an experience.** Section 11 is
right that the Founder should feel they're opening a briefing, not clicking into an org chart
entry. **Verdict: rename the screen and its navigation entry to Executive Briefing, and give it
the visual weight of the primary entry point, not one equal-sized tab among seven.**

## What does NOT need redesigning

The underlying evidence discipline from AT-ED-013/014 is sound and is kept as-is: every honest
"not enough evidence" fallback, the four-layer Fact/Interpretation/Scenario/Forecast labelling,
the never-fabricate-completion rhythm logic, and the department-pipeline synthesis in Investment
Committee. This pass changes *how* that evidence is organised and spoken, not what it's allowed to
claim.
