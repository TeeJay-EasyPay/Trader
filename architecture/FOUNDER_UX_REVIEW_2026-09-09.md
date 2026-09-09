# Founder screen review — 9 September 2026

Status: source-based review and recommendations, not an implemented redesign.
Scope: all four navigable screens (Executive Briefing, Portfolio, Standup,
Run a Cycle). Ask removal has been released and the Founder confirmed it is
no longer visible. Earlier emulator observations
support the briefing findings; no fresh all-screen visual acceptance is claimed.

## Main findings

1. ExecutiveSummaryCard and CurrentPositionCard repeat account movement;
   ExecutiveSummaryCard and WhatIDidCard both call cioOvernightActivity.
   Market commentary is also repeated in the greeting and View Ahead.
2. What I Did consumes aggregate research/execution counts without an exchange
   breakdown or a visible precise reporting window. Do not infer Kraken/Alpaca
   counts from asset names or split an aggregate speculatively.
3. Trades I Turned Down's mechanical rows are rejection-reason groups, NOT
   date groups. The default backend examines the latest 200 agent_no_trade
   events (8 × 25), not a defined day. Counts are events, not necessarily unique
   ideas/assets. Broker and time bounds are omitted. If judgement declines
   exist, the endpoint returns those instead of the mechanical summary, hiding
   another category. Read failure must also not look like no refusals.
4. Portfolio's top card groups by currency, not by exchange. Two USD exchanges
   would be merged. Other helpers explicitly allow only Alpaca/Kraken or map
   Kraken to GBP and everything else to USD. Scaling requires metadata-driven
   broker names/currencies, not simply another number in the same line.
5. Portfolio labels every negative open position as requiring attention. A
   temporary unrealised loss is not itself a software/support fault. Some
   position values use the default dollar formatter, risking a wrong currency
   label for Kraken. Fix meaning/currency before purely cosmetic changes.
6. Trade Scorecard and Trade History use different windows (rolling 24 hours
   versus calendar day since midnight). Similar totals can legitimately differ;
   make windows explicit or align definitions before presenting comparisons.

## Proposed information ownership

| Location | Main purpose | Recommended change |
| --- | --- | --- |
| Briefing greeting | What matters now? | At most two sentences: operational state and genuinely new exception. No repeated balances, activity totals or generic advice to review trades. |
| Where We Stand | Quick exchange performance | One compact, named row per active exchange: today's change, currency and account scope. Put full balance/cash/week/month detail in Portfolio. Keep the Portfolio tap-through. |
| What I Did | What happened in a stated period? | Per-exchange research checks, candidates, submitted orders and fills; distinguish those stages. Show date/window and time zone. Detailed cycle log stays in Run a Cycle. |
| Trade Scorecard | Results of completed trades | Short net-results summary by exchange and explicit window; charts/detail remain in Portfolio. Do not mix whole-account movement with AI trading profit. |
| View Ahead | Outlook rather than past activity | Preserve the liked per-asset forecasts. Make them directly accessible, not buried under repeated prose. Put a future macro summary here once, with freshness/source, not on every card. |
| Trades I Turned Down | Why no order? | Rename to Ideas Not Taken; show exchange, period and reason, distinguishing rule blocks from reviewer declines. Use unique candidate counts only with reliable IDs; otherwise label decision checks honestly. |
| What I Need From You | Actionable operational support | Keep the newly released operational-only approach. Show known fault, effect, and next support step. Avoid another broad health narrative. |
| Executive Messages | Exceptional missing evidence | Merge genuinely actionable problems into support; retain non-actionable missing forecast evidence next to that forecast. Do not silently remove important warnings. |
| Portfolio account overview | Where is the money? | Dynamic exchange cards: exchange, live/paper mode, currency, account value, cash and today's change. Label whole account versus AI allocation. No cross-currency sum without explicit dated FX. |
| Portfolio charts | Progress over time | Preserve charts and period selection. Reuse exchange identity/currency. No new independent polling. |
| AI-Managed Positions | What the AI holds and protects | Preserve. Keep asset, exchange, entry, current result and protection visible; move technical IDs/duplicate status/learning placeholders into detail. Use each position's currency. |
| Trade History | What actually executed? | Preserve filters and executed-trade history. Keep fill/fee/net distinctions and dates; remove redundant overview counts only if clearly available above. |
| Broker Diagnostics / Exposure detail | Troubleshooting | Remain collapsed. Show only known useful facts; group unavailable fields instead of many repeated not-available lines. |
| Ask | Retired from Briefing by Founder request | Removal released and Founder-confirmed. Standup is the conversation home. Preserve stored Ask history and backend code; no automatic history migration or action-routing transfer. Explicit cycle controls remain. |
| Standup | Group investigation | Keep shared conversation, named routing, bounded follow-ups and interruption. Do not duplicate portfolio dashboards here. |
| Run a Cycle | Run and inspect one cycle | Keep broker controls and step log. Put selected exchange, start date/time and final result upfront. Replace vague 'two rules' wording with actual checks; retain real-order warning and submission-versus-fill distinction. |

## Completed follow-up review: recommended final layout

The table above inventories current cards. It is not a recommendation to keep
all of them. Prefer five briefing sections with one responsibility each:

1. **Brief greeting/status** — one or two lines, last updated, and any real
   operational exception. Remove balance and research paragraphs here.
2. **Today by exchange** — merge the useful parts of Where We Stand, What I Did
   and the daily scorecard into compact named exchange blocks. Each shows account
   movement (explicitly whole-account), asset checks, submitted/filled orders,
   and closed-trade net result if known. Put secondary counts behind expansion.
   Show the exact reporting window. Link to Portfolio for progress/detail.
3. **Outlook and per-asset forecasts** — preserve the liked forecasts, directly
   reachable. No research-completed activity masquerading as a market outlook.
   Macro context, if implemented later, appears once with date/source.
4. **Ideas not taken** — exchange and period first, then top reasons. Distinguish
   decision checks from unique ideas and model declines from rule blocks. Expand
   for examples, without promising complete totals from a limited sample.
5. **Support needed** — exceptions and concrete developer-help steps only. A
   short healthy state is enough; do not repeat general status prose.

Portfolio: named exchange overview cards, then existing charts, managed positions
and trade history. Retain collapsed diagnostics. Each overview card shows
exchange, live/paper mode, currency, account value, cash, and today's movement;
AI allocation is separately labelled where supported. This repeats a small
orientation figure intentionally, not a full briefing narrative. Cards are
generated from broker metadata and must support multiple brokers in one currency.

Standup: retain the conversation, routing, follow-up allowance, interruption and
cost controls. Shorten the introductory instructions; keep detailed help behind
an optional disclosure. No duplicated account-summary cards needed.

Run a Cycle: show scope, start time, current/final state and submitted-versus-filled
result first. Keep the detailed step log below. Preserve explicit execution
controls and warnings; this review does not authorise starting a live cycle.

### Additional verified issues and priority

**Correctness/meaning first:**

- founderHeadline counts distinct order IDs from evidence.trades, including
  protective orders when present. It is not a count of new filled investments.
  countDistinctOrders also keys on order ID without broker namespace; future
  integrations could reuse identifiers. Use broker + order ID and distinguish
  entries, exits, protection and fills in the relevant summary.
- The refusal endpoint silently switches between judgement declines and rule
  summaries. Show both categories when present, rather than treating one as
  evidence that the other did not occur. Preserve unknown/error states.
- Secondary forecast/scorecard/refusal fetches are independent of the main
  briefing refresh. Failure can leave earlier scorecard/refusal content visible
  without its own freshness label; a fresh page header is not proof every card
  is fresh. Preserve last-good data but show its timestamp/stale status.
- Currency assumptions also exist in PortfolioTrends' money formatter (GBP or
  dollar fallback). Preserve chart design while moving formatting to actual
  currency metadata; do not mislabel a future EUR exchange.
- Charts bucket by UTC day, while Trade History describes since midnight and
  scorecard uses rolling windows. Use explicit time-zone/window labels and test
  daylight-saving transitions. Do not silently change performance definitions.

**Simplification second:** remove duplicated greeting text, merge today cards,
remove permanently unavailable portfolio-projection clutter from the overview,
and hide technical identifiers/duplicate position-state rows in detail.
Keep meaningful warnings; do not label every temporary loss as a support issue.

**Egress checks alongside both:** the existing hook separately fetches forecasts,
scorecard and refusal reasons on a successful main refresh. Hiding or collapsing
cards does not stop those requests. Reuse/cache compact summaries with honest
freshness; no new per-card/per-broker query loops. Any regrouping backend change
must be measured, not advertised as automatically saving a percentage.

Review outcome: implement the meaning/currency/window corrections and compact
layout together in one scoped change, then test four brokers (two sharing a
currency), empty/stale data and multi-event orders. No UI redesign or macro
ingestion was implemented in this review. No new production data export was used.

## Egress-safe implementation order

Implementation follow-up: the exchange-first layout, sampling labels, explicit
currency formatting and secondary-card freshness changes are now implemented.
See the implementation log for verification/release status. Existing activity
arrays are grouped on the client instead of adding database aggregate queries.
Missing historical broker metadata remains explicitly unknown. Broader historical
backfill and macro ingestion remain out of scope. The Founder deferred local Expo
and authorised release without the planned emulator visual check.

1. First make client-only hierarchy, wording and metadata changes using existing
   responses. Fewer visible cards alone does NOT reduce database egress if the
   same queries still run. Do not add a request per exchange card.
2. For activity/refusal breakdowns, compute bounded per-broker/per-window counts
   server-side in the existing shared summary path. Return compact aggregates,
   not a bigger execution-event dump. Label incomplete sampling as incomplete.
3. Separate calendar-day and rolling-window totals; preserve unknown versus zero,
   live versus paper, account versus AI allocation, submitted versus filled.
4. Test at least four exchanges, including two sharing a currency; missing/stale
   evidence, repeated research checks, mixed rejection types and no activity.
5. Emulator check for scanability, scrolling, labels and accessibility. Keep
   graphs/managed positions/history; do not trigger a real cycle for layout QA.
6. Compare request counts/payload sizes and measured database bytes before/after;
   bundle any backend changes into one release. Macro ingestion is a separate
   proposal, not implemented by this review.

## Source pointers

- mobile/screens/ExecutiveBriefing.js: ExecutiveSummaryCard, CurrentPositionCard,
  WhatIDidCard, DeclineReasonsCard and TheViewAheadSection.
- mobile/screens/Portfolio.js: PortfolioCommandCentre and position rendering.
- mobile/lib/declineReasons.js; src/ai_trader/decline_reasons.py.
- mobile/lib/brokerStanding.js; mobile/lib/money.js.
- mobile/lib/founderEvidenceMapping.js; mobile/screens/Ask.js,
  mobile/screens/Standup.js and mobile/screens/RunCycle.js.
