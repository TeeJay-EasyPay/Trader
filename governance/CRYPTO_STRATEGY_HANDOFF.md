# Handoff: is the crypto strategy actually broken?

Written 2026-09-04 by the outgoing session, for a fresh session with no shared context.

**Your job is to attack the conclusion below, not to build on it.** It was produced by
one session in one afternoon, and that session made several confident errors in the same
week (listed at the bottom). If the finding survives you, the Founder can act on it. If
it does not, that is a more valuable result than agreeing.

---

## 0. START HERE - added after the rest of this brief was written

**No new Kraken position has been opened since 25 August. Ten days, zero entries.**

The outgoing session got this wrong twice in one day and the correction matters. It saw
26 trades with September close dates and read that as trading resuming. Those trades were
all OPENED between 11 and 20 August and closed within a ten-minute window during a worker
restart on 4 September. That is reconciliation clearing a backlog, not the system
entering positions. Exits work. Entries do not.

So answer this before anything else:

> **What stops a Kraken entry today?** Take one candidate through the whole path and find
> where it dies. The last known gate was `ai_review_declined`, the LLM reviewer choosing
> not to trade - but that was observed, not confirmed as the current cause, and this
> system has a documented history of layered blockers where fixing one reveals another.

This reorders the brief. The backtest finding below is a theory about a strategy that is
not currently running, so it is worth less than knowing why it is not running. Verify the
blocker first, the backtest second.

Note also: 8 `logical_trades` rows still store a raw epoch (e.g. `1787150542.70311`)
rather than an ISO date, despite a backfill on 19 August. Small, but raw epochs break
date filters silently and this codebase has been bitten by exactly that before.

## 1. The claim you are testing

A replay of the live crypto entry rules over stored daily candles returned:

| Measure | Value |
|---|---|
| Replayed trades | 385, across 19 Kraken pairs |
| Window | 20 Jul - 4 Sep 2026 (47 days) |
| Win rate | 44% |
| Expectancy | **-0.65R after fees** |
| Buy-and-hold, same window | **+20.2%** average (BTC +23.8%, ETH +30.8%, SOL +32.6%) |

Two secondary claims:

- **The confidence score is anti-predictive.** At reward:risk 3.0, expectancy falls as
  the bar rises: 0.60 -> -0.46R, 0.70 -> -0.56R, 0.75 -> -0.61R, 0.80 -> -0.63R.
- **No reward:risk setting reaches break-even.** Sweeping 1.0 -> 5.0 improves expectancy
  from -0.70R to -0.31R but never crosses zero.

If true, the strategy destroys value versus doing nothing, and the Founder should not put
real money on Alpaca or add an exchange until it is fixed.

## 2. Reproduce it before you trust it

The engine is `src/ai_trader/backtest.py` (16 tests in `tests/test_backtest.py`).

```
# tests (note: pytest's default temp dir is permission-blocked on this laptop)
.venv/Scripts/python.exe -m pytest tests/test_backtest.py -q -p no:cacheprovider --basetemp=<writable dir>
```

To replay against production you need `DATABASE_URL` from the Render worker
(`srv-d9e0v1urnols73dbve6g`). The outgoing session pulled candles and research scores for
the 19 Kraken pairs into a local SQLite file and ran `backtest_symbol` against it. Keep
the pull narrow: Supabase egress has been blown twice and blocks the Founder's other app.

## 3. Where this is most likely to be wrong

Attack these first. They are ranked by how much damage they would do if wrong.

1. **The entry rule may not match the live one.** `_entry_days()` reproduces what it
   believes `propose_crypto_trades` does: `overall_due_diligence_score >= min_confidence`,
   skip negative `technical_trend_score`, one entry per symbol per day. Read
   `agent.py:437` onward and check. If the replay enters on days the live system would
   not, every number above is meaningless.
2. **47 days is one regime.** It happens to be a strong bull market, which is arguably
   the *worst* case for a tight-stop long-only system: you get shaken out of trends that
   then continue. A losing result here may not generalise. There are two years of candles
   but only 47 days of research scores, which is what caps the window.
3. **The stop-first assumption.** When one daily bar spans both stop and target, the
   engine records a stop. That is deliberate and it understates results. Quantify by how
   much - if most trades resolve on ambiguous bars, the true number is materially better.
4. **Exits are modelled as fixed stop/target.** Production uses native Kraken trailing
   stops. A trailing stop and a fixed target behave very differently in a trending
   market, and this is probably the single largest modelling gap.
5. **`reward_risk` was assumed, not read from policy.** Confirm the live value.
6. **Fees.** `ROUND_TRIP_FEE_PCT = 0.0154`, measured over 26 real round trips. Maker
   limit entries should be cheaper on the buy leg. If entries genuinely fill as maker,
   this over-charges every trade.

## 4. What is established, and how to re-check it cheaply

- **Trade outcomes are real but tiny.** 26 closed trades, all since the 31 Aug fee fix.
  Live expectancy -1.43R. The backtest being negative *and* the live record being
  negative is weak corroboration, not proof - both could share a common cause.
- **`STRATEGY_BACKTEST_RESULTS` is empty** and is the only genuinely unwired evidence
  source feeding the AI. Verified by `decision_inputs.py`, which prints at every boot.
- **The curated knowledge library is NOT missing** - seven files under `knowledge/`,
  read from disk. The outgoing session initially reported it missing. It was wrong.
- **The concentration rule is not blocking anything.** 11,433 rejections in July, 31 in
  August, none since. Already fixed twice in early August.
- **The last remaining crypto gate is `ai_review_declined`** - the LLM reviewer choosing
  not to trade. Note the uncomfortable implication: if the strategy really is -0.65R,
  the reviewer declining may be correct behaviour rather than a blocker.

## 5. Do not spend time on these - already fixed and logged

Four stacked blockers, the confidence bar's four separate homes, the track-record doom
loop, the double-counted position cap, the Postgres `LIKE` 500s, the excursion
measurement pointing at an empty table, the Supabase egress blowout, the OpenAI 429.
All in `governance/IMPLEMENTATION_LOG.md`, entries dated 29 Aug - 4 Sep.

## 6. Constraints that bite

- **Kraken is live money in GBP.** Alpaca is paper, USD. Never blend the two currencies.
- **Render has two services** (web `srv-d93osvflk1mc739nga9g`, worker
  `srv-d9e0v1urnols73dbve6g`) with independently drifting env vars. Know which one a
  reading came from. `render.yaml` is not live state - query the API.
- **A push restarts the worker into a ~15 minute startup.** Rapid pushes starve it
  entirely. Two commits are staged locally and deliberately unpushed (`3b2409f4`,
  `b14c1b35`).
- **Check Supabase egress after any change.** Standing Founder instruction.
- **The Founder is the owner, not an engineer.** Short answers, plain English, no jargon
  without a translation.

## 7. Do not load the backtest results into the database yet

`proposal_context` reads `STRATEGY_BACKTEST_RESULTS` into the AI reviewer's prompt.
Writing "-0.65R expectancy" there would make the reviewer veto everything, recreating
the doom loop that halted crypto for a week. Fix the strategy before handing the model
the verdict. This is a Founder decision, not an implementation detail.

## 8. Errors the outgoing session made this week - calibrate accordingly

- Claimed fee burden was a function of position size. Wrong; fees and risk both scale, so
  fee_R is identical at GBP 25 and GBP 500. The lever is stop distance.
- Recommended widening stops. The Founder pushed back and was right.
- Fixed the empty `observations` list by pointing at a table that was also empty.
- Reported the knowledge library as missing without checking the filesystem.
- Flagged the concentration rule as a live blocker without checking whether it still
  fired. It had been dead for a month.
- Said "running the check now" and then ended the turn without running it.

The pattern is asserting before verifying. Whatever else you do, verify first.

---

## The questions to answer, in this order

The Founder framed these himself, and the framing is correct - one functional, two
architectural:

1. **Functional, and first: why is no Kraken entry going through?** Ten days, zero new
   positions. See section 0. Everything else is downstream of this.
2. **Architectural: how is the AI actually being used?** Today: Kraken gets veto-only
   review (decline or lower confidence, never authors price, size, stop or target);
   Alpaca gets full model-authored proposals. Both run `gpt-4.1-mini`, the budget tier,
   and the equity proposals it authors are rejected for an unusable stop roughly two
   times in three. The Founder's own challenge is worth carrying: if the model can only
   veto, a threshold could do the same job - so what is the model actually adding?
3. **Architectural: is the app getting better?** No mechanism currently makes next month
   better than this one. One outcome-driven feedback loop exists (the per-coin track
   record) and it created a doom loop that had to be reversed. `LEARNING_OUTBOX`,
   `EXPERIENCE_LESSONS` and `STRATEGY_PROMOTION_DECISIONS` are written and read by
   nothing. There are 26 closed outcomes in total.

And underneath all three:

> **Is this strategy actually losing money, and if so, is it the stops, the entry signal,
> or the fee structure?**

The Founder intends to trade real money on Alpaca and then add one or two Asian
exchanges. Getting this right matters more than getting it fast.
