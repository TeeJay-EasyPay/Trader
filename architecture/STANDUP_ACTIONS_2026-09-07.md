# Standup actions — 7 September 2026

The first real three-way standup. Written up by Claude Code rather than by the standup itself:
the $5 of Anthropic credit ran out partway through, so the automatic write-up returned the
credit error instead of a summary. The conversation up to that point still produced a finding,
and it is recorded here the way the handoff would have recorded it.

## What the standup concluded

Claude was asked whether the falling candle coverage was real. It said yes, and named a cause
neither the trader nor Claude Code had found: a cap in the scoring universe, filled
alphabetically, that silently stops at 80 of 170 coins.

## Action 1 — raise or reshape MAX_SCORING_SYMBOLS

**What.** `src/ai_trader/scoring_universe.py:53` sets `MAX_SCORING_SYMBOLS = 80`.
`build_scoring_universe` adds the tradeable pairs first, then walks the classified coins in
`sorted()` order and breaks at the cap. The Founder's classified list has grown to 170 active
symbols, so 90 of them are never reached, never scored, and therefore never get candles.

**Why.** Verified against production before writing this down, because the same day's earlier
lesson was that a plausible cause is not a confirmed one:

- 170 classified symbols; 116 have ever had a Kraken daily bar.
- Of those 116, the ones still updating form a **contiguous alphabetical prefix of 78**.
- The boundary falls at **NPC**. Everything from NPC onward is stale.
- The only five fresh symbols past the boundary are **SAND, SOL, SUI, XLM, XRP** — exactly the
  tradeable pairs the code exempts from the cap.

That last line is the reason to trust it. A cap plus a documented exemption predicts precisely
that shape, and the shape is what the data has.

**A correction worth keeping.** My own first check said this hypothesis was *wrong* — it found
33 stale symbols sorting before the last fresh one and called that a falsification. The test was
contaminated: it used XRP as the boundary, and XRP is one of the five exemptions the code
comment explicitly warns about ("the currently-traded pairs come first and are never dropped by
the cap"). A control built without reading the comment above the code it was testing.

This also retires an earlier wrong answer of mine. On 6 September I attributed the candle
decline to the research job budget, fixed the budget, and the decline continued. That hypothesis
is now dead; this one explains the shape the data actually has.

**Confidence.** High on the mechanism. **Not yet established:** whether 80 is still the right
number. The comment calls it "a ceiling on API calls per cycle, not a view about how many coins
are interesting," and says the classified universe was "comfortably inside this" — true when
written, no longer true. Raising it costs one OHLC fetch plus one order-book read per symbol per
cycle, against a `crypto-candle-refresh` job that spent most of August timing out. So the number
should be chosen against the measured job duration, not raised on principle.

**Verify.** After the change, the count of symbols with a bar dated that day should rise above
83 and keep climbing toward the listed universe of 116, and the alphabetical prefix pattern
should disappear — stale symbols should no longer be predictable from their first letter. If
`crypto-candle-refresh` starts timing out again, the cap was raised too far and the ceiling is
doing its job.

## Discussed, not settled

- **DOGE** is the one stale symbol inside the fresh prefix (last bar 29 August). It sorts early
  enough to be well inside the cap, so the cap does not explain it. Unexplained; not an action
  until someone looks.
- **Whether wider coverage produces more trades at all.** The reason the universe was widened
  was to answer exactly that, and it is still unanswered. More candles is not more trades.

## Not an action

The standup's own write-up endpoint could not run: no Anthropic credit. Nothing is wrong with
the code — the failure surfaced as the plain message the Founder needs to see, which is what it
is meant to do.
