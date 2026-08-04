# Founder Briefing — AT-ED-016.1

Tarik,

You asked me to read the Executive Briefing the way a real CIO would present it to you, out loud,
and rewrite anything that didn't pass that test. I did that, and I found real problems.

## The Worst Thing I Found

Two lines on the Current Position card, when the data was missing, actually said this to you:
*"Not available - week-to-date P&L is unavailable because no broker has reported a week_pnl
figure yet."* That's a raw database field name — `week_pnl` — showing up in your briefing. No CIO
would ever say that to you, and you were right to want this stripped out. I fixed it, and while I
was at it I checked every other place in the screen that could leak something similar, and found
one more (the same issue with `month_pnl`). Both are gone now — when I don't have a number, I just
don't show that line, rather than explaining myself in field names.

## What Else Changed

The Forecast Centre used to show five separate stat rows per time horizon, including a sentence
that started with "AI Trader has no time-series or volatility model" — repeated five times. It's
now four short answers per horizon: what I expect, why, what could change it, and how confident I
am — using the exact same numbers as before, just said the way I'd actually say them to you.

Every risk used to have six labelled fields. Now it's four: the risk, why it matters, how likely
it is, and what I'm doing about it. Every opportunity went from six fields to four: why I like it,
the potential upside, what would trigger it, and my confidence. Founder Actions stopped being a
status form and became actual advice — "I recommend no intervention today, because..." instead of
a bare "no action required." And the nine-department organisation summary stopped reading like a
system log ("1 of 2 broker connection(s) currently confirmed connected") and now reads like nine
one-line updates from real departments.

The Executive Summary itself is now just what you'd expect from a CIO walking into your office —
a greeting, what happened, what I believe, and nothing else. No metrics, no percentages, no
labels.

## What I Deliberately Left Alone

Every number is exactly the same as before I touched anything. I did not touch a single
calculation, a single piece of committee logic, or anything that decides what AI Trader actually
does. This was entirely about the words wrapped around those numbers - I checked this specifically
by re-running every test that verifies the underlying logic (all 362 pass) and confirming none of
them needed to change for a reason other than "the wording changed," which is the whole point of
this pass.

## What I Could Not Verify

I tried to confirm this on an emulator again, the same way I caught the field-name bug last time.
The bundling process ran clean with no errors, but I couldn't get a full on-screen confirmation
this session — the same automation limitation as before. I'm telling you that plainly rather than
rounding it up. The real test of this pass is simple: does it read like a person now? Please open
it and tell me honestly.

— Claude
