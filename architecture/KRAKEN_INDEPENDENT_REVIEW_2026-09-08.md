# Independent Kraken trading review — 8 September 2026

> **Follow-up implementation:** After the review, the Founder authorised implementing the fixes and updating the implementation log. The working tree now contains a separate AI sizing contract, premature-expiry fix and corrected fee explanation. These are local changes, not a production deployment. The original findings below describe the production version inspected during the review; implementation details follow at the end.

**Opinion:** Kraken's current inactivity is explained by the research and AI-review gates, rather than a demonstrated exchange outage. There is a confirmed mismatch between the reviewer's instructions and the software's treatment of its answer. However, the evidence does **not** establish that the blocked candidates would have been profitable. The earlier conclusion that historical simulations prove today's refusals correct is also unsupported.

Reviewed the current checkout, relevant implementation history and handover, live Supabase records through an enforced read-only connection, the authenticated Render-hosted API and persisted worker evidence, and the installed app running in the Pixel 9 emulator. The worker reported deployment commit `59dbf586dd6df873255c198a2d010a7bf410419c`, matching the checkout.

The Render dashboard itself required sign-in; its private console logs and environment-variable dashboard were not inspected. Render findings below come from the deployed API and persisted job records, not from assuming the blueprint describes live settings. The exact model used for these individual reviews was not independently established.

## 1. What is stopping trading now

Database snapshot during the review, approximately 19:29 BST; events dated from 8 September 00:00 UTC (01:00 BST):

| Recorded refusal | Events |
|---|---:|
| Research score below minimum or non-positive qualifying trend | 327 |
| Reviewer says proceed, but lowered confidence fails the minimum | 79 |
| Reviewer explicitly declines | 74 |
| Unfavourable liquidity structure | 19 |
| Fee hurdle not cleared | 14 |
| **Total** | **513** |

These are repeated evaluations, not 513 independent investment opportunities. All 153 candidates reaching the reviewer in this snapshot were stopped: 74 by an explicit decline and 79 by the subsequent confidence check.

The live policy minimum was **0.70**. The 79 proceed-but-rejected reviews scored **0.50–0.60**, averaging **0.550**. Current examples include ADA at 0.54, XLM at 0.53, and SUI at 0.53. Their stored assessments support a cautious or smaller entry while acknowledging risks; their structured `proceed` field is true.

Kraken's snapshot showed connected, auto-trading enabled, no broker block reason, and GBP 500 buying power. There were **61 completed Kraken broker polls** and **81 auto-execution runs completed without action** that day. Research was completing. The old all-polls-time-out incident is therefore not the present explanation. This does not constitute a new order-placement test: no order was submitted for this review.

## 2. Confirmed design mismatch: smaller entry becomes no entry

In [ai.py](../src/ai_trader/ai.py#L191), the reviewer is told that reducing confidence is how it can recommend a smaller entry. But:

1. Liquidity and track-record markdowns can first bring the candidate to the 0.70 floor in [agent.py](../src/ai_trader/agent.py#L933). Of 119 recorded size-down events in this snapshot, 70 were exactly at that floor.
2. The reviewer may lower confidence but may not raise it. Its candidate input contains the current confidence, but does not explicitly identify the minimum as the boundary below which a proceed decision will be discarded.
3. [agent.py](../src/ai_trader/agent.py#L1157) rejects any reviewed score below 0.70, even with `proceed=true`.
4. The size scaler only becomes useful if the proposal survives that rejection. Its minimum size is already 50% of the approved ceiling at 0.70.

A candidate at 0.70 therefore has **no room for the promised confidence reduction while remaining eligible**. The code faithfully implements its threshold; the contract presented to the reviewer is misleading. This is a concrete explanation for 79 refusals, not proof that these 79 trades should have been bought.

The shared number also serves several different purposes: research ranking, markdowns, AI judgment, eligibility, and sizing. This review found no evidence establishing that the reviewer's 0.54 and the research score's 0.70 are calibrated measurements on the same scale. They should not be interpreted as validated probabilities of profit.

## 3. The historical simulation conclusion needs correcting

I reproduced the aggregate in the handover: **1,494 settled Kraken shadows**, gross mean **−0.3864R** and estimated net mean **−1.1799R**. That is adverse historical evidence and should not be dismissed.

But it does not validate today's reviewer refusals:

- **All 1,494 have a null rejection-reason field.** Joining their proposal identifiers to `trade_audit` finds **1,452 linked `agent_proposal` records with `ai_guardrails_passed=1`**. These passed the proposal/AI gate. Some might subsequently have been blocked by execution policy, but that is a different decision from today's reviewer vetoes.
- **1,490 were created in July or August**, generally with stops around 2%. Only four settled examples were created in September. Today's widened-stop strategy is materially different.
- The 1,494 rows cover only **130 distinct symbol-days**, with many overlapping repeated candidates. Treating every row as an independent trial exaggerates the effective sample size.
- The new explicitly rejected-candidate cohort contained **20 rows, all pending**: eight explicit AI declines, seven confidence rejections, four liquidity rejections and one fee rejection.

The statement in [the implementation log](../governance/IMPLEMENTATION_LOG.md#L4659) that these are overwhelmingly refused candidates and therefore prove the refusals correct is too strong. The old strategy's weak simulated results warrant caution, but cannot settle whether the present reviewer adds value.

## 4. Confirmed defect in the mechanism intended to answer that question

[shadow_outcomes.py](../src/ai_trader/shadow_outcomes.py#L183) marks a trade expired as soon as it has some subsequent candles and none hit the stop or target. It does not first require the seven-day horizon to have elapsed.

An offline reproduction with a 36-hour-old candidate, neither level touched, finalised it as expired. The database contains two XRP examples created late on 4 September and finalised on 6 September, several days before their seven-day horizon. Their reported holding times are 19 and 46 minutes because the daily candle's start timestamp is used for its closing-price outcome.

Additional limitations:

- The candle window excludes the entry day's bar. Any stop or target reached between an intraday entry and the next midnight is unobserved. The finding that few *included* bars touch both levels does not measure this omitted interval.
- The simulator uses a fixed seven-day horizon while the proposal recorder stores a four-hour `expires_at`; the resolver does not read that expiry. Order validity and holding horizon may legitimately differ, but the intended simulation contract must be explicit.
- Daily settlement models fixed stops and targets, not the entire live maker-order, fallback and trailing-exit lifecycle.
- New rejected rows use the generic strategy name `crypto_research_refused`, rather than retaining the actual assigned strategy. Their daily deduplication also means the first recorded setup represents potentially many changing intraday decisions.

These issues do not prove the negative historical average would become positive. They do mean that simply waiting a week for the existing simulator will not, by itself, provide a clean answer.

## 5. What the emulator showed

Launched the existing Pixel 9 emulator and installed AI Trader app, inspected Executive Briefing, Portfolio and Trade History, and selected Kraken specifically. After an Android System UI startup warning, the app opened and navigation worked.

- The broad briefing said operating normally and cited order activity across brokers.
- Kraken-filtered history showed **zero completed today**, **13 wallet positions**, and the most recent visible closed trade in early September. This is consistent with the database finding of current inactivity.
- The portfolio's AI-managed section displayed zero / not available. The 13 wallet positions are not proof of 13 open AI strategies; the documented distinction between personal holdings and AI-managed positions matters.
- The app displayed a **GBP 131.90 daily portfolio gain** while reporting zero completed Kraken trades. Portfolio appreciation is not evidence of new trading.
- The scorecard's explanation blamed small position sizes for percentage-fee losses, while its expectancy explanation correctly says fee/risk ratios do not improve by increasing size. The conflicting explanation is generated in [trade_scorecard.py](../src/ai_trader/trade_scorecard.py#L258) and was also returned by the live API.

The app is usable, but its overall health and performance wording does not reliably distinguish infrastructure health, trading inactivity, portfolio movements, and realised strategy results.

## Recommendation

First align the reviewer's decision contract with the execution policy. Make eligibility, qualitative judgment and size preference explicit, and preserve the original research score and reviewer assessment separately. The current contract promises a smaller trade where the code often delivers a veto. This should be resolved deliberately, without assuming an arbitrary lower confidence threshold produces better trades.

Next repair and validate shadow settlement, retain actual strategy and decision-stage provenance, and compare accepted candidates, explicit AI declines and proceed-but-below-threshold candidates using the same current execution assumptions. Evaluate net outcomes by distinct setup, with adequate follow-up and without treating overlapping evaluations as independent trades.

**My answer to the central question:** some refusals enforce plausible risk and quality rules, but the claim that all current refusals are sound is not established. There is a demonstrated decision-contract problem stopping otherwise eligible, reviewer-supported candidates. Whether taking those candidates would improve returns remains unproven; the existing historical analysis does not answer it. The priority is to make that decision and its measurement coherent, rather than chase trading volume.

## Verification and review artefacts

- 12 existing crypto-review tests passed.
- 32 existing refusal-recording/reviewer-context tests passed.
- Offline reproduction confirmed premature shadow expiry with an in-memory database stub.
- Supabase sessions explicitly enforced `default_transaction_read_only=on` and a statement timeout.
- No trading logic, deployed settings or production records were changed; no trading cycle or exchange order was triggered by this review.
- Added only this report and two review utilities: `tools/kraken_readonly_audit.py` and `tools/kraken_review_reproductions.py`. The existing untracked `.claude/` directory was preserved.

This was a targeted investigation of the Kraken refusal path and its supporting evidence, not certification of every module, table, or possible order-execution failure.

## Authorised follow-up: implemented locally

The Founder asked Codex to implement the recommendations after clarifying that the immediate issue is contradictory software behavior, separately from whether missed trades would have won.

### Decision and size now have distinct meanings

- New reviews carry `proceed`, diagnostic `confidence`, and an explicit `size_fraction` greater than zero and at most one.
- The research eligibility score stays in `confidence_score`; the same configured minimum still applies to research and downstream eligibility checks. The reviewer's confidence is retained separately as `reviewer_confidence`.
- `reviewer_size_fraction` survives proposal normalisation, JSON persistence and reconstruction. Capital allocation applies it **once**, after the existing risk, cash, position and research-conviction sizing rules.
- An explicit decline still stops entry. A new-contract proceed decision is not subsequently vetoed just because its separate qualitative confidence is below the research threshold. This is the deliberate behavioral change: some previously refused candidates can now reach execution checks.
- Invalid explicit sizing instructions are recorded as declines rather than becoming an unavailable-review fallback at full size. Legacy reviews without the new sizing field retain their original confidence-gate behavior.
- Kraken's minimum-order adjustment cannot increase a reviewed allocation. If the requested amount cannot meet the minimum, execution is refused with `reviewer_reduced_size_below_kraken_minimum` and the measured amounts.
- `ai_review_sizing_decision` records the decision, both scores, the sizing fraction and the review. Capital-allocation notes record the pre-review amount and applied fraction. No database migration is required.

For example: a research-qualified candidate at 0.70 can receive an AI assessment of 0.54 with `proceed=true, size_fraction=0.5`. Its research score remains 0.70; the final allocation is half what the unchanged sizing rules would otherwise allow. The fee gate remains in force before review. This does not assert a 54% probability of profit or change the configured confidence threshold.

### Supporting corrections

- A simulated candidate with neither level reached remains pending until its seven-day horizon has elapsed. Existing historical results are **not** rewritten automatically. Entry-day coverage, intraday path ambiguity, alternative expiry semantics and cohort provenance remain limitations described above.
- The scorecard now explains that captured **price moves**, not small position sizes themselves, failed to cover percentage fees. Its wording agrees with the fee/risk explanation.

### Validation and release boundary

169 focused tests passed, including research-to-review-to-JSON-to-allocation-to-order construction, explicit declines, failed research/fee gates, malformed sizing, Kraken minimum floors, strategy visibility and premature-expiry regression cases. The offline reproduction now verifies the expiry fix. The wider run had 1,770 passes, 21 subtest passes and eight failures: one source-inspection test was corrected and passes in the focused rerun; the remaining seven failures reproduce on unchanged HEAD (six limit-entry/fallback tests and one rejection rollup test). The full suite was not rerun after the test correction. Details are recorded in the implementation log.

Before release, have Claude independently review the diff and investigate the seven baseline failures, particularly the Kraken limit-order/fallback cases. Then obtain deployment approval and verify the new worker version and fresh review/allocation evidence. Do not force trades or relax fee/research gates simply to create activity. Broader shadow-model and cohort-provenance corrections remain separate follow-up work.

No production settings or historical database records have been changed, and no order or trading cycle has been triggered by this implementation. Deployment remains a separate step because it changes which newly reviewed candidates can reach real Kraken execution. After deployment, verify fresh sizing-decision events, matching capital-allocation records, and worker version before claiming the live behavior is fixed.

### Subsequent hardening and release authorisation

Claude independently reviewed the original changes and supported their correctness. The Founder
then authorised completing the safeguards, testing, committing and deploying. This supersedes
the preceding local-only release boundary; it does not authorise forcing trades or weakening gates.

The follow-up adds explicit contract-path logging, per-symbol isolation of review-application
exceptions (skip the candidate, not full-size fallback), environment-isolated limit-order tests,
and fixed-date monthly-rollup tests including a month-boundary regression. The 61 focused
hardening tests passed; all 19 limit-order tests also passed with deliberately conflicting parent
environment settings. Full-suite and release details are recorded in the latest implementation-log entry.
