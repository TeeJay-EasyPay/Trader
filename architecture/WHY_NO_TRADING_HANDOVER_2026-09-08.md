# Why is trading not happening? — brief for an independent review

**Written 2026-09-08 for a fresh reviewer with no history here.** Everything below is measured
from the production database on that date, not inferred from the code. Where something is an
opinion it says so.

The purpose of this document is to stop the review spending its first hours re-deriving what is
already known, and to say plainly which explanations have already been eliminated.

---

## The question, stated precisely

It is two different questions, and conflating them has already wasted time.

| | Alpaca (paper, US shares) | Kraken (real money, crypto) |
|---|---|---|
| Is it trading? | **Yes** | **No, since 5 September** |
| Positions held now | 9 | 13 |
| Account | $101,836 (flat: −$45 in a month) | £4,713.68, £502.03 cash |
| Finished round trips | 49 since 2 July | 27 since August |

**Alpaca is trading and has been all along.** What was broken there was *recording*: finished
trades never produced a profit figure, so nothing downstream could learn from them. Fixed on
2026-09-08; two months of history recovered. That was never the reason trades weren't happening.

**Kraken is the one that has stopped.** It holds 13 positions and has neither opened nor closed
anything since 2026-09-05 23:38. That is the thing to explain.

---

## What Kraken actually does all day

Research runs about 46 times a day over 10–19 coins. On 2026-09-08 it refused **509** candidates:

| Refused because | Count | Where |
|---|---|---|
| Due-diligence score below threshold, or trend negative | 325 | `agent.py`, first gate |
| AI reviewer cut confidence below the 0.70 bar | 78 | `agent.py` → `ai.py` `CryptoTradeReviewer` |
| AI reviewer declined outright | 73 | same |
| Order book too thin | 19 | `liquidity_map.py` |
| Profit would not cover fees | 14 | `technical_discretion.clears_fee_hurdle` |

Every refusal carries a stored reason in `EXECUTION_EVENTS` (`event_type='agent_no_trade'`).
1,051 over 7–8 September, all with reasons, against 1,025 coins examined — nothing is falling
out silently. As of 2026-09-08 13:25 each refusal that had a tradeable shape is also written to
`SHADOW_TRADES` so it can later be settled against real prices.

---

## Explanations already eliminated — please do not re-open these

**1. "It's the fees."** Partly, and it is now bounded. Kraken charges this account 0.40% patient
/ 0.80% market per side, confirmed by the Founder against his own account. It is the entry fee
tier and only falls with volume this account will never trade. The 27 closed Kraken trades made
**+£0.17 before fees and −£5.41 after**. So fees explain the *realised loss*; they do not explain
why no new trade is being opened.

**2. "The stop is too tight."** It was — 1.5% against a 1.60% round trip. Changed 2026-09-08 to
one full ordinary day's movement (1.0 × ATR, ceiling 8%). Confirmed live: ALGO at a 5.27% stop
and 10.54% target. Fee drag falls from ~1.06R to ~0.30R. This did not restart trading.

**3. "The 0.70 confidence bar is too high."** Not established, and deliberately untouched.

**4. "The per-coin track-record penalty is a doom loop."** Real mechanism (`symbol_track_record.py`,
up to −0.25 confidence), but it only applies to coins with 3+ recent closed trades. The candidates
being refused today are mostly coins with no record at all, so it is not the binding constraint.

**5. "Nothing is being recorded."** Was true of shadow trades and of Alpaca outcomes. Both fixed
2026-09-08.

---

## The finding that we think matters most, and would most like challenged

Across **1,494 settled shadow trades** (candidates the system simulated but mostly refused):

- 1,117 hit the stop, 238 hit the target, 139 expired
- **Gross expectancy −0.39R, before a single penny of fees**
- The geometry (2% stop, 4.2% target) needs roughly a **33%** hit rate to break even. It is
  getting **16%**.

If that is right, then the refusals have been *correct*, the caution is protecting the account,
and the binding constraint is **the quality of the ideas**, not any threshold, fee or stop.

**The honest limit on that claim**, raised by the trading AI and not yet answered: this measures
the pile the system *rejected*. It does not establish that the candidates it *accepts* are
equally poor. Recording accepted and refused candidates under identical simulation assumptions,
then testing whether higher scores actually predict better net outcomes, is the missing work.

---

## Open leads worth a reviewer's time

1. **Does the due-diligence score predict anything?** It is the first gate and refuses 64% of
   everything. A previous 385-trade replay found that *raising* the confidence bar made results
   worse (0.60 → −0.46R, 0.80 → −0.63R), which suggests the score may be anti-predictive over
   that window. That result was never acted on. See `governance/IMPLEMENTATION_LOG.md`,
   2026-09-05.

2. **The patient (maker) order path almost never fires.** Of Kraken fills ever recorded, exactly
   **three** got the 0.40% maker rate; 51 buys and 31 sells paid 0.80%. Entries rest for ~7
   minutes then fall back to market. `broker_adapters.py`, `KRAKEN_LIMIT_ENTRY_TIMEOUT_SECONDS`.

3. **`TRADE_EXCURSIONS` is an empty shell** — every high- and low-water mark reads 0.0. Without
   price paths, no stop-versus-target question can be settled by replay, only by waiting.

4. **Crypto price history is daily only.** Adequate for shadow settlement (only 9 of 1,117
   stop-outs were ambiguous, worth 0.02R — tested, so hourly candles are NOT needed), but it
   cannot answer intraday questions.

5. **Alpaca has no simulator at all.** 655 shadow rows marked unsettleable, nothing since
   28 August, because no share price history is stored to settle against.

---

## Where to look

| Concern | File |
|---|---|
| Crypto candidate pipeline, every gate, every refusal | `src/ai_trader/agent.py` (`propose_crypto_trades`) |
| The AI reviewer and its prompt | `src/ai_trader/ai.py` (`CryptoTradeReviewer`) |
| What the reviewer is told about past performance | `src/ai_trader/strategy_scoreboard.py` |
| Stop and target placement | `src/ai_trader/volatility_stops.py`, `technical_discretion.py` |
| Fee hurdle and measured fee rate | `src/ai_trader/trade_scorecard.py` |
| Per-coin penalty | `src/ai_trader/symbol_track_record.py` |
| Order placement, maker/taker | `src/ai_trader/broker_adapters.py` |
| Refusal recording | `src/ai_trader/crypto_shadow.py` |
| Shadow settlement | `src/ai_trader/shadow_outcomes.py` |
| Alpaca outcome reconstruction | `src/ai_trader/alpaca_reconciliation.py` |

Full history, dated and specific: `governance/IMPLEMENTATION_LOG.md`.

---

## What would be most useful back

Not a list of possible improvements. One answer to one question: **is the system refusing trades
it should be taking, or is it correctly refusing bad ideas?** Both are consistent with what is
above, they lead in opposite directions, and nothing here settles it.

Evidence is available to check any claim: the production database holds every refusal with its
reason, every simulated outcome, every fill and every account snapshot at 12-minute intervals.
Please check rather than infer — two of the three participants in the 2026-09-08 standup reached
confident conclusions from table shapes that turned out to be wrong, and both had to correct
themselves on the record.
