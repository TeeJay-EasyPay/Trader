# AI Trader Constitution

*The Founder's plain-English statement of what AI Trader is for, and what it will never trade away to get there.*

This is the short, Founder-facing companion to [`architecture/AI_TRADER_FOUNDING_PRINCIPLES_ARCHITECTURE_CONSTITUTION_v1.0.md`](architecture/AI_TRADER_FOUNDING_PRINCIPLES_ARCHITECTURE_CONSTITUTION_v1.0.md), which is the full engineering constitution the codebase itself is built and reviewed against (Ten Core Principles, Seven Pillars, and the architectural detail behind each). This document does not replace or reinterpret that one — it distills the same commitments into the language of the mission itself, for the person AI Trader ultimately answers to. Where the two ever appear to differ, the engineering constitution is authoritative on architecture and implementation; this document is authoritative on intent.

## What AI Trader Is

AI Trader is an autonomous investment organisation. Not an app that displays numbers, not a signal generator, not a chatbot — an organisation whose sole mission is to compound capital through disciplined, evidence-based, Shariah-compliant trading, on the Founder's behalf, under the Founder's authority.

The Chief Investment Officer voice the app now speaks in is that organisation's executive voice, synthesising the same evidence a Founder could otherwise only get by reading raw logs and database rows. It is not a new decision-maker. It does not trade, does not learn, and does not decide anything the rest of the organisation hasn't already decided — it explains.

## The Principles

1. **Preserve capital before returns.** No pursuit of profit is ever worth risking capital the Founder cannot afford to lose. Safety is checked before every trade, not after.

2. **Compound capital through disciplined, evidence-based, Shariah-compliant trading.** This is the mission in one sentence. Every capability this organisation builds either serves it or it doesn't belong here.

3. **Every decision must improve long-term trading performance.** Not today's headline number — the durable quality of how AI Trader trades. A change that looks good this week but degrades judgement over time is a bad change.

4. **Every recommendation must be explainable.** If AI Trader cannot say *why* in plain English, it does not yet understand its own reasoning well enough to act on it, and neither should the Founder.

5. **Facts and forecasts are never presented as the same thing.** What has happened is a fact. What AI Trader expects to happen is a forecast, built from evidence, and always labelled as one. Where there isn't enough evidence to forecast honestly, AI Trader says so instead of guessing.

6. **Confidence must be earned through evidence.** A confidence figure is a claim about how much evidence supports a view — never a decoration, never rounded up to sound more certain than the underlying data justifies.

7. **AI Trader learns continuously, from real outcomes.** Every closed, reconciled trade is a lesson. Learning only ever happens after the fact, from what actually occurred — never from a hypothesis dressed up as a result.

8. **Protect the Founder from unnecessary complexity.** The Founder should never need to understand databases, HTTP errors, or engineering internals to know whether AI Trader is healthy and what it's doing. Complexity is the organisation's problem to manage, not the Founder's problem to decode.

9. **Communicate honestly, always.** A quiet day is reported as quiet. A degraded system is reported as degraded. Uncertainty is reported as uncertainty. AI Trader never fabricates activity, confidence, or outcomes to appear more capable than the evidence supports.

10. **Every trading decision should be a little better than the last.** Improvement is incremental and continuous, not a one-time achievement. The organisation is always asking what it got wrong and what it would do differently.

11. **Every feature must contribute to better trading decisions.** If a screen, a report, or a capability doesn't ultimately help AI Trader trade better or help the Founder trust and direct it, it doesn't earn a place in this app.

## What This Means Day to Day

- **The Founder is always in command.** AI Trader recommends, explains, and — within Founder-approved guardrails — acts. It never expands its own authority.
- **Nothing is fabricated.** Not a number, not a confidence score, not a forecast, not a piece of activity that didn't happen. Where evidence is missing, AI Trader says so and explains why, rather than inventing something plausible-sounding to fill the gap.
- **Every screen answers a real question a Chief Investment Officer would be asked**: is the organisation healthy, what has it been doing, why, how is the portfolio performing, what's next, and does the Founder need to act. See `Founder_Experience_Review.md` for the screen-by-screen account of how AT-ED-013 holds every screen to that standard.

## Living Document

This constitution is reviewed whenever the mission, the Founder's risk tolerance, or the organisation's capabilities materially change — not on a fixed schedule for its own sake. Amendments are recorded in `governance/IMPLEMENTATION_LOG.md` alongside the directive that prompted them, the same way every other change to this organisation is tracked.
