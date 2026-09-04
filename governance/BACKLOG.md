# Backlog — raised 2026-09-04, deferred until Kraken trading is confirmed working

Captured during the Option B design session. Nothing here blocks Option B; all of it
was found while proving what does.

## Deferred fixes

### 1. Position cap counts the raw wallet, not AI-managed positions
`guardrails.py:99` tests `len(account.open_positions)` against the cap, while the
`duplicate_open_position` check three lines below correctly narrows to `ai_managed_symbols`
(fixed 2026-08-25). The two disagree about what "a position" means.

Not firing today — 0 hits across 400 crypto proposals since 26 August, and the AI holds
nothing on Kraken. But the Founder's own pre-existing coins (14 in the wallet on 25 August,
11 of them his) would fill a 5-slot cap instantly if they ever reached this check, freezing
every entry permanently. **The Founder notes this class of bug has been hit before and was
believed fixed** — so the fix likely landed on the duplicate check only and missed this one.

### 2. USD pairs are unreachable — do not convert GBP yet
`_kraken_pair()` defaults to `quote_currency="GBP"` and `propose_crypto_trades` never passes
anything else, so the trading path is GBP-only. `broker_policies.allowed_pairs` still lists
the same 19 GBP pairs, and every production cycle evaluates exactly those 19. The widened
~40-coin universe exists in the research/asset tables but has not reached execution.

**Consequence: converting GBP to USD would leave the money idle.** Needs the pair mapping,
the allowed-pairs policy, and per-currency cash handling before it is worth doing.

### 3. Phantom / debris rows in `logical_trades`
20 rows sit in non-closed states (`open`, `execution_intent`, `broker_acknowledged`). Most
carry the symbol `UNKNOWN`; one is `ETHGBP` (the raw pair rather than the normalised symbol).
Harmless today because `_ai_managed_symbols` returns 0, but exactly the debris that later
surfaces as a phantom position. Needs a reconciliation sweep.

Related, same family: 26 of 66 `performance_attribution` rows store a raw epoch number
instead of an ISO date, and 8 `logical_trades` rows do the same. Any reader treating them as
text sorts them wrongly.

## Deferred questions — after trading is confirmed

### 4. How much is the AI actually doing?
Founder's framing: *"I don't want the app to just be arithmetic calculations and logic, it
needs to be proper intellectual trading."*

Today: Kraken gets **veto-only** review — the model may decline or lower confidence, and never
authors price, size, stop or target. Alpaca gets full model-authored proposals. Both run
`gpt-4.1-mini`, the budget tier, and the equity proposals it authors are rejected for an
unusable stop roughly two times in three. The Founder's own challenge stands: if the model can
only veto, a threshold could do the same job — so what is the model adding?

### 5. Is it actually learning?
No mechanism currently makes next month better than this one. The single outcome-driven loop
(the per-coin track record) created a doom loop that had to be reversed — and was separately
found on 2026-09-04 to have been crashing on Postgres for its whole life. `LEARNING_OUTBOX`,
`EXPERIENCE_LESSONS` and `STRATEGY_PROMOTION_DECISIONS` are written and read by nothing.
`STRATEGY_BACKTEST_RESULTS` is empty.

Open item the Founder raised: roughly **25,000 historical decisions** were once earmarked for
wiring in, but they are believed not to be genuine decisions. Provisional plan was to ignore
them, or take a subset — undecided. Needs a judgement on whether any of it is real signal
before any of it is fed to the model.

Also unresolved from the handoff: is the strategy actually losing money, and if so is it the
stops, the entry signal, or the fee structure? A backtest suggested **-0.65R expectancy against
+20.2% buy-and-hold** over 20 Jul - 4 Sep, but that finding is unverified and the entry rule it
replayed may not match the live one.
