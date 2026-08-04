# Founder Briefing — AT-ED-015.1

Tarik,

I'm sorry — that's a real production bug, and I found it, not guessed at it.

## What Broke

When your app loads the Executive Briefing, it fetches your founder evidence (portfolio, status,
recommendations) and, separately, market theme data. Once the theme data arrived, one specific
card — Principal Opportunities — tried to summarize a theme's key drivers, and it crashed. The
code assumed those key drivers always arrive as a list; on your live data, they sometimes arrive
as a single sentence instead. That mismatch threw an error, and because nothing was in place to
catch it, the crash took down the entire screen instead of just that one card — hence the white
screen, with no message at all.

## How I Know, Not Guessed

I didn't want to hand you a fix based on reading the code and hoping. So I actually ran the app —
booted an Android emulator on this machine, pointed it at your real production API, and watched it
crash live, with the exact error message and the exact component name in the logs:
`theme.key_drivers.slice(0, 3).join is not a function`, inside `PrincipalOpportunitiesSection`.
I also reverted to the exact broken code, wrote a test using the real shape of your data, watched
it fail with that same exact error, then confirmed the fix makes it pass. Two independent
confirmations, not one guess.

## The Fix

One function now handles both shapes — a list or a single sentence — the same way another part of
the app was already handling the exact same situation for a related field. Nothing about how your
forecasts, thesis, or any of the numbers on the screen work has changed.

## What I Added So This Can't Happen Again, Even If I Missed Something Else

I put a safety net around just the Executive Briefing screen. If any card on it ever fails again —
this bug or a different one — you'll see a calm message saying the briefing couldn't load, with a
button to retry and a button to jump to Operations, instead of a blank screen. Everything else in
the app stays fully working. This doesn't replace fixing bugs properly; it just means one bad card
can never again take down the whole app.

## What I Could Not Fully Verify

I got one clean live crash and one clean live confirmation of the underlying test, but I was not
able to get a second full on-screen confirmation of the fix working, purely because of a quirk in
how I was automating the emulator (not a real device, not a limitation of the fix itself). Please
treat this as fixed based on the evidence above, but the real confirmation is you — open the app,
let it sit for a few minutes, refresh it a few times, and switch screens and come back. If it holds
up, we're done. If anything looks off, tell me exactly what you see and I'll go again with the
same rigor.

— Claude
