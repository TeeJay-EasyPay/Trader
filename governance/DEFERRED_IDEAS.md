# Deferred ideas

Ideas worth building that are **not** built. Written down here because an empty database table
does not preserve an idea — it only adds a name to guess between when someone is looking for
where a number lives.

Created 2026-09-02, when ten unused tables were removed. Two of them represented ideas worth
keeping; the other eight duplicated systems that already exist.

---

## 1. Exchange flow / on-chain metrics

**Status:** not built. Table removed 2026-09-02 — and deliberately not recreated, because the
schema it had was the wrong one (see below).

**Why it is worth building — the Founder's reasoning, 2026-09-02:**

> "On chain movements tend to be long term showing a certain trend, but they can also be
> indications of where the market may be going. So, for example, if more and more people are
> putting their coins onto an exchange, it could be they're about to sell. If more and more
> people are buying and pulling the coins off an exchange, those coin analytics tell us that
> they could be a rise in price coming because of scarcity. It's just another part of a
> broader puzzle."

This is the strongest case for on-chain data, and it corrected an assumption made when the
table was first proposed for deletion: that on-chain metrics are slow-moving fundamentals
mismatched to a multi-day holding period. **Exchange netflow is not that.** Coins moving *onto*
exchanges is supply arriving at the place selling happens; coins moving *off* is supply leaving
circulation. Both are leading rather than lagging, and both operate on a timescale that a
several-day position can actually use.

**Why the old table would not have worked.** `CRYPTO_ONCHAIN_METRICS` held
`active_addresses`, `transaction_count`, `network_fees_usd` — network *activity*, not flow.
None of those three columns can express the signal described above. Keeping the table would
have preserved the wrong shape and quietly made the good idea harder to build. The right shape
is roughly:

    symbol, observed_at,
    exchange_inflow, exchange_outflow, exchange_netflow,   -- the signal
    exchange_balance,                                      -- the level it moves
    active_addresses, transaction_count,                   -- context, secondary
    source, payload_json

**What it needs before it can be built:**

* **A data source.** No single free provider covers the traded universe. The 19 GBP pairs span
  several chains, and the ERC-20s among them (GRT, SAND, AAVE, LINK) need a different endpoint
  from the layer-1s (BTC, LTC, XLM, ADA, DOT, ATOM). Realistic options are Blockchair or
  Etherscan on free tiers with partial coverage, or a paid feed (Glassnode, Santiment,
  CryptoQuant) with full coverage. **This is the blocker, and it is a real integration, not a
  wiring fix.**
* **A decision about partial coverage.** A signal available for BTC and ETH but not GRT is
  still useful, but the app must not treat "no data" as "no pressure". Absence has to be
  explicit, the way `tradeable_now` is explicit in the scoring universe.

**Where it would plug in:** as an input to the crypto research score, alongside the technical
and liquidity components — one more part of the broader puzzle, in the Founder's words, not a
gate of its own.

---

## 2. Correlation warnings

**Status:** not built. Table `PORTFOLIO_CORRELATION_WARNINGS` removed 2026-09-02. Unlike the
on-chain one, its schema *was* correct — `symbols_json`, `correlation`, `sample_size`,
`warning`, `confidence` — so recreate it as-is when building rather than redesigning.

**Why it is worth building:** on 2026-09-02 Alpaca held **10 positions worth 23.9% of the
account**, sitting just under the 25% capital-allocation ceiling. That ceiling counts money,
not independence. If several of those ten move together, the account is not holding ten bets;
it is holding two or three, at triple the size the allocation rule believes it approved.

Nothing in the app can currently see that. Both existing controls — position count and capital
allocation — are blind to correlation.

**Why this one is cheap:** it needs **no external data**. `MARKET_DATA_OBSERVATIONS` already
holds 20,127 daily candles across 103 symbols, refreshed hourly. Correlation between held
positions is computable today from data the app already owns. Of everything on this page, this
has the best ratio of value to work.

**Shape it would take:** compute pairwise correlation across open positions on a rolling
window; warn when a cluster exceeds a threshold with a meaningful sample size; feed it into the
decision as a *sizing* input rather than a hard gate, so a correlated idea is taken smaller
rather than refused outright.

**Sample size matters.** The removed table had a `sample_size` column and a `confidence` field,
which was the right instinct: a correlation computed over five days is noise, and acting on it
would be worse than ignoring correlation altogether.

---

## Not kept, and why

Eight further tables were removed on 2026-09-02 with no idea worth preserving:

| Table | Reason |
|---|---|
| `CRYPTO_TRADING_HISTORY` | Crypto trades are already recorded in `BROKER_TRADE_HISTORY` (685 rows), `PRODUCTION_TRADE_EVIDENCE` (564), `LOGICAL_TRADES` (434) and `LOGICAL_TRADE_FILLS` (199) — all with fees, P&L and reconciliation this table lacked. A fifth home for the same fact is the exact problem the "one home per decision" work removed. |
| `CRYPTO_SENTIMENT` | `CRYPTO_SENTIMENT_SCORES` does this and holds 1,220 rows. The two names differ by one word, which is itself the argument for removing the empty one. |
| `CRYPTO_TOKENOMICS` | Supply and unlock schedules. Genuinely useful, but needs the same external feed as on-chain and has no reasoning recorded behind it. Fold into idea 1 if that is ever built. |
| `CRYPTO_DAILY_UPDATES` | Duplicated by the daily learning update and the executive briefing. |
| `CRYPTO_PROJECT_ANALYSIS` | Qualitative research with no source and no consumer. |
| `CRYPTO_RISK` | Superseded by the risk policies and the guardrail gates. |
| `CRYPTO_BENCHMARK_ALIGNMENT` | Benchmark trader research already lands in `BENCHMARK_DAILY_RESEARCH`. |
| `PORTFOLIO_STRESS_TESTS` | A real technique, but no reasoning was ever recorded for what would be stressed or how the answer would change a decision. Worth reopening as a fresh idea rather than resurrecting an empty shape. |
