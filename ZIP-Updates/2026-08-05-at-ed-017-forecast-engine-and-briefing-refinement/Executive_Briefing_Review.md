# Executive Briefing Review — AT-ED-017 Part 6/7

## Method

Every claim below is backed by a live screenshot captured from a real Android emulator (Pixel_9
AVD, Expo Go) connected to the hosted production backend, pulled via `adb screencap` — not source
review alone. Where a fix was made mid-review, it was redeployed via EAS Update and re-verified
live before being called done. This is the same verification standard established after the
AT-ED-015.1 white-screen incident, and it caught three real bugs this pass that source review and
384 passing unit tests did not.

## Card-by-Card Findings

### Current Position — improved, verified live

Now states, in order: a plain-English lead line, the realised/unrealised split with real
figures, each broker's own today figure labelled paper/live trading, then the existing compact
fact list. First render had the new sentences running together with no paragraph break (a React
Native sibling-`<Text>` spacing issue, same bug class as a prior pass); fixed and reverified live.
A second issue — the unrealised figure being framed as "the rest of" today's P&L, which isn't true
since the two figures measure different things (a delta vs. a snapshot) — was also caught and fixed
before considering this card done.

### What Happened Overnight — improved, verified live; one real contradiction caught and fixed

Now includes a real structured funnel (reviewed/approved/rejected/submitted, no raw internal
codes) and an explicit autonomy statement. First deploy had the autonomy statement flatly
contradicting the funnel conclusion directly above it when the funnel state was
"approved_but_not_submitted" (an opportunity cleared every gate but no order was submitted — a
state the backend's own logic labels "This requires attention."). Fixed and reverified live; the
two lines now agree.

### Forecast Centre — enriched, verified only on the honest-fallback path

"What I expect" now includes exit timing and expected realised profit alongside the existing
value range. The account's real closed-trade sample is currently below the 5-trade minimum, so
every live check saw the honest "not enough evidence" text, correctly rendered. The
enriched-with-real-numbers path is unit-tested but not yet seen live.

### Investment Thesis — pre-existing bugs found and fixed, verified live

Not part of this directive's stated scope, but found during the mandated visual pass: a literal
"NaN%" in the conviction sentence (theme confidence is a string label in production data, not
always the numeric fraction the code assumed), two double-period typos, and a subject-verb
agreement error ("1 ... recommendation lean"). All three fixed and confirmed live.

### Executive Summary, Market Assessment, Investment Organisation, Closing Remarks, Investment
Rhythm — unchanged this pass, previously verified in earlier sessions, spot-checked again this
session with no new issues observed.

### Principal Risks, Principal Opportunities, Founder Actions — unchanged this pass; not
re-verified visually this session (scrolling past this section on the emulator was attempted but
not completed before time was better spent on the sections directly touched by this directive).

## Honest Self-Assessment

**What works well now:** the Founder can genuinely answer "are we making money, is it realised or
unrealised, how much per broker" from Current Position alone, in under 30 seconds, without needing
to cross-reference another screen. The autonomy statement is no longer just an absence of a
warning — it's a direct claim, and it no longer contradicts itself. The Forecast Centre's
"why/what could change it" reasoning was already solid before this pass and remains so.

**What still feels weak:** the Forecast Centre's most valuable new content (exit timing, expected
realised profit) is gated behind a 5-trade minimum this account hasn't crossed yet, so right now a
Founder opening the app sees the honest fallback, not the enrichment — the value of this pass is
real but not yet visible in the live account. Also, `portfolio.todays_pnl` is still rendered with a
`$` symbol despite blending USD (Alpaca) and GBP (Kraken) capital — every screenshot this session
showed this, and it's a real, unresolved presentation gap I chose not to guess-fix, since the right
fix depends on a decision (blend and pick one symbol? show two totals?) that isn't mine to make
silently.

**What I'd improve next:** first, get the account past the 5-trade Forecast Centre threshold (or
find synthetic/staging evidence) so the new exit-timing content can actually be seen live rather
than only unit-tested. Second, resolve the currency-symbol question for blended P&L figures.
Third, this pass found bugs in a card (Investment Thesis) I wasn't specifically asked to touch —
worth a dedicated pass scrolling through every remaining card (Principal Risks/Opportunities,
Founder Actions) with the same live-screenshot discipline, since this session's experience is that
source review alone reliably misses real, visible defects.
