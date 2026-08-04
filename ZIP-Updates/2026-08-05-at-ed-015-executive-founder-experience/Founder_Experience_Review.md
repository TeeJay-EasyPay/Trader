# Founder Experience Review — AT-ED-015

Same format as prior passes: for each screen, what single executive question does it now answer,
and what changed this pass. See `Executive_Communication_Review.md` for the "before" critique this
redesign responds to.

## Executive Briefing (renamed from CIO) — "What do I need to know, in the next sixty seconds?"

The primary landing screen, and now a distinct full-width button above the tab row rather than one
equal-weight tab (Section 11). Reads top to bottom as one flowing briefing, in Section 2's exact
order: greeting and overall position, current market environment, what happened overnight, current
and alternative thesis (with conviction now attached directly to the thesis it supports, not a
floating card), the Expected Outlook journey (Yesterday through Year End, Section 3, backed by the
new Forecast Intelligence Engine), Principal Risks and Principal Opportunities as individual
structured cards, Founder Actions Required (each answering what/why/benefit/risk/deadline/what-
happens-if-nothing), and a closing recommendation. No sentence appears twice - the Market Outlook
and Principal Risks duplication AT-ED-014 had is gone; each fact has exactly one card that owns it.
Trading Organisation, Investment Committee, and Investment Rhythm remain available below the main
briefing as supporting detail, not interleaved with the narrative - Trading Organisation now reads
in plain business language (Research/Learning/Execution/Risk/Infrastructure/Governance, each
"Healthy" or "Attention Needed" - no "Worker Health" or "Database Durability" labels), and
Investment Rhythm is now a single checklist with a ✓/▶/○ mark per stage instead of six separate
metric-heavy cards.

## Operations — "Is the underlying infrastructure healthy?" (unchanged)

Not touched this pass. Still the engineering-facing detail screen for worker health, research job
timestamps, and broker connections - exactly where that detail belongs, now that Trading
Organisation on the Executive Briefing gives the plain-language summary and links here for anyone
who wants the raw detail.

## Activity, Recommendations, Portfolio, Market, Learning — unchanged

Not touched this pass. All five were reviewed and confirmed sound in AT-ED-012/013/014; this
directive was explicitly scoped to executive communication and forecasting, not a full re-review
of every screen.

## What Changed Structurally

- **Confidence and Conviction are no longer standalone cards** (Section 8). Conviction now sits
  directly beside the thesis it supports; confidence sits directly beside each forecast horizon
  that earned it.
- **Executive Messages dropped the unread-notification count** (Section 9). It now only ever shows
  items that materially affect an investment decision (real evidence gaps from
  `world_class_evidence.unavailable`) - if there are none, the card does not render at all, rather
  than showing an empty "Executive Messages" shell.
- **Founder Actions became genuinely actionable** (Section 10). Each outstanding recommendation is
  its own card answering what, why, expected benefit, risk, deadline (the recommendation's real
  expiry time), and what happens if the Founder does nothing. With nothing outstanding, the
  screen still says, verbatim, "No Founder action is required today."
