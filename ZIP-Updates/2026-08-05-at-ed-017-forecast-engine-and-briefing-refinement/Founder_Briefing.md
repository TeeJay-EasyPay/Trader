# Founder Briefing — AT-ED-017

Tarik,

You asked for two things: make the Forecast Engine talk about returns, not just portfolio values,
and make the Executive Briefing actually answer whether we're making money, how much each broker
made, and whether it's realised or unrealised. I did both, and I want to walk you through what
changed and — more importantly — what I caught by actually looking at the app instead of trusting
the code.

## What Changed

**Current Position now splits today's money into what it actually is.** Before this pass, "Today"
was one blended number — a portfolio-value delta that mixed Alpaca and Kraken, realised and
unrealised, into a single figure. It now says, in plain sentences: how much is realised profit
(and from how many closed positions), how much is still unrealised and sitting in open positions,
and — separately — how much each broker made today, labelled paper trading (Alpaca) or live
trading (Kraken) so you always know which capital is actually at risk.

**The Forecast Engine now talks about the journey of the capital, not just an end number.** It
already had a real, evidence-based Base/Bull/Bear projection built from your closed-trade history.
What it never did was tell you when to expect the next exit, how many exits to expect in a given
window, or what that would realise in profit — even though that information was sitting right
there in the same sample. Each forecast horizon now says, for example: "I expect roughly 2
positions to close in this window, with the next exit likely in about 3 days. If that happens as
expected, I estimate realised profit of around £340." Same underlying math as before — nothing
about the projection itself changed — just a second thing it now tells you.

**AI Trader now states its own autonomy directly.** "What Happened Overnight" used to only ever
describe autonomy by omission — you'd have to infer it from the absence of a warning. It now says
plainly whether AI Trader operated fully autonomously today, or names exactly what still needs
your attention, using real structured counts (opportunities reviewed, approved, rejected,
submitted) rather than anything vague.

## What I Caught By Actually Looking

This is the part I want to be direct about, because it's the reason this pass took the shape it
did. I wrote all of the above, ran 384 passing tests, and was ready to call it done. Then I loaded
it on the emulator you'd left running, and found three real problems no test suite would have
caught:

1. **The new sentences were running together with no visual gap.** I'd built each new fact as its
   own text element, and React Native doesn't put a gap between separate elements unless the style
   says to — only a real line break *inside* one block of text does that. This is the exact same
   bug class I found and fixed once already this week in a different part of the screen. I clearly
   haven't fully internalised the lesson yet, and I'm flagging that honestly rather than pretending
   it was a one-off.
2. **The autonomy statement contradicted the sentence directly above it.** When AI Trader has an
   opportunity that cleared every gate but never got submitted, the funnel line already says "This
   requires attention." My new autonomy line, checking a different signal, said "operating fully
   autonomously — no Founder action required" right underneath it. Two true-in-isolation facts,
   flatly contradicting each other on the same card. I only saw this because I looked at the actual
   render.
3. **A pre-existing bug I wasn't looking for:** the Investment Thesis card was showing "My
   conviction in Airlines currently sits at NaN%." Real theme confidence data comes back as a
   string label ("Medium") in production, not always the numeric fraction the code assumed. I
   fixed it, along with two double-period typos and a subject-verb agreement error I found in the
   same card while I was there.

All three are fixed and confirmed live on the emulator, not just in code. I'm telling you about
them because "I found and fixed my own mistakes by actually looking" is more useful to you than a
report that pretends the first draft was clean.

## What I Could Not Fully Verify

The account's real closed-trade history is currently below the 5-trade minimum the Forecast Engine
requires before it will project anything. Every live check this session showed the Forecast
Centre's honest "not enough evidence" fallback text, which I did confirm renders correctly — but I
have not yet seen the new exit-timing/realised-profit sentences with real, non-empty numbers in
them. The logic is covered by unit tests with synthetic data, but that's not the same as seeing it
live. Once the account has more closed trades, that's worth a direct look.

I also noticed `portfolio.todays_pnl` is formatted with a `$` sign in every screenshot I took this
session, even though Kraken is a GBP-denominated live account — the underlying figure blends both
currencies and I did not touch that, since fixing it properly means deciding how a mixed-currency
total should even be labelled, which is your call, not mine to make silently.

— Claude
