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

### 6. Demotion on live evidence - the missing half of the maturity ladder
Eleven crypto strategies were promoted to Micro Live on 2026-09-04 on Founder authorisation,
because the `Paper` stage they sat at was a bootstrap default rather than an earned position:
no strategy carried any `sample_size`, `expectancy`, `win_rate`, `profit_factor` or
`max_drawdown`, and `STRATEGY_PROMOTION_DECISIONS` and `STRATEGY_BACKTEST_RESULTS` were both
empty.

Promotion is now one-way. The ladder's real value is not blocking untested strategies -- it is
automatically pulling one that starts losing real money. Needs per-strategy live expectancy
measured from closed trades, and an automatic demotion when it deteriorates.
`production_spine.strategy_promotion_decision` already has the gate logic and a drawdown-based
demotion branch, but nothing computes the evidence to feed it and nothing applies its verdict
to the registry. This is the same question as item 5.

### 7. The tradable coin list is static, and lives in two places
`KRAKEN_ALLOWED_PAIRS`, a Render environment variable defaulting to `XBTGBP,ETHGBP,SOLGBP`, is
what actually gates which coins may be traded (`research_service.py:1316`,
`broker_service.py:770`). `broker_policies.allowed_pairs` in the database holds the same list
but is only used for display. Two homes for one value, and this one contradicts the standing
rule that trading variables live in the database and only infrastructure lives in Render.

Discovery, by contrast, IS dynamic: `crypto_asset_master` is refreshed from Kraken's live
`AssetPairs/Ticker` feed and ranked on real 24h turnover (154 coins classified on 4 Sep). So a
new Kraken GBP pair would be seen and measured but never traded until someone hand-edits an
environment variable.

Founder's framing: equities already work the right way -- a business-activity rule decides the
universe, so it grows and shrinks on its own. Crypto should be equivalent: any Kraken GBP pair
above a turnover floor, screened by rule rather than typed by hand. He rates this a nice-to-have,
and that is right -- 19 pairs is not the constraint when only 8 clear the score bar. The
env-versus-database duplication is worth fixing sooner than the dynamic universe itself.

### 8. Twelve of nineteen coins can never pass due diligence
Found 2026-09-05 immediately after the entitlement gate was cleared. LTC's rejection reason
changed from `strategy_entitlement_blocked` to `due_diligence_incomplete`, which is a different
gate doing its job on missing data.

`create_due_diligence_assessment` requires all six statuses to read "completed", and for crypto
the behavioural one needs a CRYPTO_SENTIMENT_SCORES row for that symbol from today. Measured
across the 19 Kraken pairs, only **7 carry a sentiment score from the last two days**: BTC, ETH,
LINK, SAND, SOL, XLM, XRP. The other twelve -- AAVE, ADA, ALGO, ATOM, BCH, DOT, FIL, GRT, KSM,
LTC, MINA, SUI -- cannot pass, however good the setup. LTC has never had one at all.

That is why XRP got a live order on 5 September and LTC did not: XRP happens to be one of the
seven. This does not block trading, it caps it at roughly a third of the universe. Either the
sentiment scoring needs to cover every allowed pair, or the behavioural dimension needs an
honest "insufficient_data" path that does not fail the whole assessment -- the same question as
whether a missing input should read as a negative finding.
