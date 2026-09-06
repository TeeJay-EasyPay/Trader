# Plan from the trading AI's own assessment — 2026-09-06

Founder-directed: the AI was asked whether it has what it needs, what is wrong, and what the
gaps to world class are. It answered well. This is the plan built from that answer.

**Read this section first.** Every claim below was checked against production before any work
was planned around it, and three of its four "what is actually wrong" items turned out to be
artefacts of the census I built, not defects in the system. The AI hedged them correctly
("I cannot tell whether those inputs are absent from the system or simply absent from the
census"), and I would have wasted days building things that already exist.

---

## Part 0 — What the assessment got right, and what my census made it believe

| Its finding | Verdict | Evidence |
|---|---|---|
| Crypto price feed ~6 days stale | **Real, already fixed today, unverified** | `crypto-universe-refresh` timed out 237 times, last completed 2026-08-31 17:24 |
| ...and decisions may consume stale prices | **FALSE ALARM** | Nothing anywhere SELECTs from `CRYPTO_MARKET_DATA`. Entries call `adapter.current_prices([pair])` — a live Kraken Ticker read at decision time (agent.py:631) |
| No Alpaca quote/bar or execution feed | **Census gap** | `market_data_observations` 22,199 rows; `production_broker_snapshots` 5,878; `broker_trade_history` 784. My census listed none of them |
| Realised P&L lacks broker attribution | **Census gap** | `PERFORMANCE_ATTRIBUTION.broker` exists and is populated. The real split is kraken 27 trades / -GBP 5.41. My census summed across brokers and threw it away |
| ...lacks currency | **Real, small** | There is genuinely no currency column |
| Backtest results empty | **Real** | `strategy_backtest_results` = 0 rows |
| Research arriving, no recommendations | **Real, now explained** | Drop reasons surfaced 2026-09-06: due diligence 161, AI declined 49, AI lowered confidence 20, liquidity 17, fee hurdle 15 (3h sample) |

**The lesson, and it is the same one as the rest of this week:** a wrong census produces
confident, specific, wrong findings. This already happened once today in a harder-to-spot
way — a single bad column name cascaded and told the AI six feeds had vanished, and it
reported the learning loop as gone. Fixing what it can SEE is therefore the first job, not
an afterthought.

---

## Task 1 — Make the census honest (do this before anything else)

Cheapest task here and it gates the value of every future daily answer.

1. Add the feeds that exist and were never shown: `market_data_observations`,
   `broker_trade_history`, `production_broker_snapshots`, `logical_trades`,
   `execution_events` (the drop reasons), `research_funnels`.
2. Split the realised record **by broker**, since the column is already there. The AI
   explicitly refused to state a combined P&L, and it was right to.
3. State what actually prices a decision — a live Kraken Ticker call — so the AI stops
   reasoning about `CRYPTO_MARKET_DATA` as if it were the decision source.
4. Label each feed with whether a decision READS it. "Stale" matters enormously for an input
   a trade depends on and not at all for one nothing consumes.

**Done when:** tomorrow's answer contains no finding that is contradicted by a direct query.

## Task 2 — Freshness at the moment of decision (its ranked gap #1)

Its actual words: *"Record each input's age at every decision, with freshness limits
appropriate to the strategy."*

This is the one genuinely new capability it asked for, and it is worth building.

1. When a candidate is judged, record the AGE of each input that informed it — price, news,
   sentiment, regime, candles — into the existing proposal context.
2. Surface it in the drop reasons already recorded, so "rejected on stale evidence" becomes a
   visible category rather than an invisible one.
3. NO hardcoded freshness gate. The Founder's standing position, applied three times now:
   give the model the age and let it weigh it. A threshold cannot tell a quiet market from a
   broken feed.

**Done when:** a rejected candidate's record shows how old every input was.

## Task 3 — Close the loop it cannot currently see (its ranked gap #2)

Its words: *"Link decisions, orders, partial fills, fees, slippage and exits; retain rejected
and skipped candidates."*

Most of this exists and is not connected:
- decisions → `execution_events`, `research_funnels`
- orders/fills → `broker_trade_history`, `logical_trade_fills`
- fees → on the fills
- exits → now recorded with reasons (2026-09-06)
- rejected candidates → now recorded with reasons (2026-09-06)

So this is a **joining** job, not a building job. One view, per broker, from decision to net
result. That is also what would answer the Founder's fee question properly: whether losses
come from signals, sizing, or costs.

**Done when:** one query returns, per broker, every closed trade with its decision, its
reasons in and out, its fees, and its net result.

## Task 4 — The fee reality (Founder's own question, and its gap #3 in practice)

The XRP trade on 2026-09-05 called direction correctly and still lost 33p: +GBP 0.07 on price,
-GBP 0.40 in fees. Kraken costs roughly 1.6% round trip at GBP 25 stake.

`fee_hurdle_not_cleared` already fires (15 times in a 3h sample). What is missing is whether
that hurdle is the binding constraint across the whole universe, and what stake size would
change it. This is an ANALYSIS first, not a code change — and explicitly not a hardcoded
minimum trade size.

**Done when:** we can say what proportion of rejections are economic rather than judgemental,
and what account size makes the strategy viable at Kraken's fee schedule.

## Task 5 — Backtest evidence (its gap #3)

`strategy_backtest_results` is genuinely empty. But note what already exists: 1,184 settled
SHADOW trades in the 45-day window, giving `crypto_trend_following_2r` 1,164 samples at
-1.17R and a 20% win rate.

That is real out-of-sample evidence and it is not flattering. Before building a backtest
engine, the honest question is whether the strategy should be running at all — a question the
shadow record can already answer more cheaply.

**Done when:** a decision is taken on that strategy, on the evidence that exists.

## Deliberately NOT planned

- **Portfolio-risk evidence (its gap #4).** Real, and premature: exposure limits and drawdown
  controls matter at scale, and the account is GBP 500 with 27 closed trades.
- **More feeds (its gap #5).** It ranked this last itself and was right: *"More sentiment
  rows, broader dashboards and extra research volume are merely nice to have until then."*
- **A backtest engine.** See Task 5 — the shadow record may make it unnecessary.

## Order, and why

1 first because it is cheap and every later answer depends on it. Then 4, because it may show
the blocker is economic rather than technical and would reorder everything below it. Then 2
and 3, which are the AI's own top two and share plumbing. Then 5.

Egress constraint applies throughout: the account is restricted, measured 276 MB/day today
against roughly 170 MB/day allowed. Nothing here may add a per-view query.
