# Founder screen review — 9 September 2026

Status: source-based review and recommendations, not an implemented redesign.
Scope: all four navigable screens (Executive Briefing, Portfolio, Standup,
Run a Cycle), including the embedded Ask card. Earlier emulator observations
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
| Ask | Retired from Briefing by Founder request | Removed locally; Standup is the conversation home. Preserve stored Ask history and backend code; no automatic history migration or action-routing transfer. Explicit cycle controls remain. |
| Standup | Group investigation | Keep shared conversation, named routing, bounded follow-ups and interruption. Do not duplicate portfolio dashboards here. |
| Run a Cycle | Run and inspect one cycle | Keep broker controls and step log. Put selected exchange, start date/time and final result upfront. Replace vague 'two rules' wording with actual checks; retain real-order warning and submission-versus-fill distinction. |

## Egress-safe implementation order

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
