# Render State Comparison — AT-ED-015.1

Section 3 of the directive requires comparing the payload/state behind the successful first
render against the payload/state applied immediately before the white screen. This is derived
from two sources: the component architecture itself (which determines exactly which state update
can and cannot reach `PrincipalOpportunitiesSection`), and the live reproduction's own timeline.

## A. The Successful First Render

`App.js` constructs `useFounderEvidence()` and `useMarketData()` as two independent hooks, each
firing its own fetch on mount (this split was deliberate, from AT-ED-011.5 - see
`architecture/ARCHITECTURE_DELTA.md`'s ownership table). `ExecutiveBriefing` receives
`themes={marketData.themes}`, which starts as `[]` (the hook's initial state) and only becomes
populated once `/intelligence/themes` resolves - a separate network round-trip from the shared
`/founder-evidence` payload that `status`/`portfolio`/`recommendations` come from.

The first successful, visible render therefore uses:
- **Fresh live founder-evidence** (`status`, `portfolio`, `recommendations`, `activity`) - this is
  what makes the Executive Header, Overall Position, Market Environment (text-only fields from
  `status`), and Overnight Actions sections render correctly and match what the Founder described
  seeing ("the screen initially renders with live data").
- **`themes: []`** (not yet loaded) or a `themes` array whose current top-confidence entry does
  not yet have a string-shaped `key_drivers` field.

With `themes` in either of those states, `buildOpportunityCards()`'s `topTheme` lookup either
finds nothing (`themeOpportunityCard()` is never called) or finds a theme whose `key_drivers`
happens not to trigger the bug on that particular render - both paths render successfully.

## B. The Failing Render

Once `useMarketData()`'s `/intelligence/themes` fetch resolves (its own independent refresh cycle,
unrelated to the shared founder-evidence refresh the "Connecting to AI Trader..." /
"Refreshing" badge text is describing), `marketData.themes` updates to the real, live theme list.
`ExecutiveBriefing` re-renders with this new `themes` array. `buildOpportunityCards()` selects the
real highest-confidence theme, and if that theme's `key_drivers` field is a string (the real shape
returned by production `/intelligence/themes` evidence, per `Root_Cause_Analysis.md`),
`themeOpportunityCard()` throws synchronously during this render.

## What Changed Between A and B

| | A (successful) | B (failing) |
|---|---|---|
| `status`/`portfolio`/`recommendations` | live, fresh | live, fresh (unchanged) |
| `themes` | `[]` or a shape that doesn't trigger the bug | populated with the real top-confidence theme, `key_drivers` as a string |
| Trigger | — | `topTheme.key_drivers.slice(0, 3).join('; ')` throws `TypeError` |

The founder-evidence side of the state is not the cause - it is identical (live, correct) on both
renders. The only state that changes between the render the Founder saw succeed and the render
that blanked the screen is `marketData.themes` completing its independent fetch and supplying a
theme whose `key_drivers` field has the real, string shape this code did not defend against. This
is consistent with, and explains, the reported sequence: launch → live content visible (founder-
evidence already resolved) → "Refreshing"/"Connecting" (a coincidental, unrelated badge state
change, not causally connected to the crash) → blank (the moment the independent themes fetch
resolves and the render throws).

## Confirmed Directly, Not Just Inferred

In the live emulator reproduction (see `Root_Cause_Analysis.md`), the very first themes-populated
render was the one that crashed - the production API's real theme data already had a
string-shaped `key_drivers` on its top-confidence theme at the moment of testing, so no multi-
refresh cycle was needed to observe the failure; it reproduced on the first live data cycle. This
directly confirms the mechanism above rather than leaving it as an untested hypothesis.
