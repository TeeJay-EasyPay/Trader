# Learning and Founder reflection — action plan

**Date:** 17 September 2026  
**Status:** Implemented, deployed and production-verified.  
**Safety boundary:** Research, simulation and reporting only. Nothing in this plan
authorises live strategy activation, higher risk, new orders or weaker safeguards.

## What today's review established

1. Completed, linked trades already feed the daily hypothesis-proposal batch. The
   batch may use up to 30 recent outcomes per eligible broker to propose bounded
   rule experiments.
2. The overnight historical screen is separate. It tries to replay a proposed rule
   against stored opportunities and completed daily price bars. The 17 September
   run found 25 Alpaca signals across nine dates but no matching replay bars, and
   four Kraken signals across three dates with only three bars. All historical
   trials therefore reported `data_required` rather than inventing results.
3. Seven fresh forward shadow experiments are running: four Alpaca and three
   Kraken. They were restarted after the deployed baseline changed.
4. The eight earlier records were not ended merely because three days elapsed.
   Their recorded reason is `Baseline deployment changed; freeze a new comparison.`
   They should be presented as superseded/restarted, not as ordinary failed or
   inconclusive hypotheses.
5. Three days is the review cadence, not the experiment lifetime. A frozen version
   can receive up to 12 checkpoints (36 days), subject to progress, evidence,
   drawdown and final-stop rules.
6. The app exposes detailed experiment machinery but does not yet give the Founder
   a short, trustworthy answer to: “What did Trader learn, is it more capable, and
   is it actually trading better?”
7. The 17 September scheduled review could verify production evidence, but Trader's
   direct answer returned an internal error, the stored self-assessment timed out,
   and the latest Strategy Lab refresh exceeded its execution boundary.

## Agreed workstreams

### 1. Controlled historical market-data cache

- Perform one bounded initial backfill, followed by incremental completed-bar
  updates and occasional gap/corporate-action repair.
- Use Alpaca as the primary equity source and verify the account's IEX/SIP
  entitlement before choosing coverage.
- Use Kraken GBP market data as the primary crypto source; introduce a secondary
  provider only for a demonstrated depth or coverage gap, with provenance retained.
- Keep the reusable dataset in a persistent Render research cache. Do not repeatedly
  move the full history or simulated-trade ledger through Supabase.
- Persist only compact screening results, experiment summaries and provenance in
  Supabase. This keeps expected Supabase egress close to the current level.
- Reuse the frozen forward simulator for chronological, after-cost screening. A
  historical pass remains development evidence and never replaces fresh forward
  validation.

### 2. Evidence-adaptive experiments

- Retain three-day checkpoints for visibility.
- Continue a frozen experiment while it is making useful progress, up to the
  existing 36-day maximum; do not manufacture a verdict at a checkpoint.
- Revisit the “two quiet checkpoints” stop so infrequent but valid hypotheses are
  not retired solely because the market produced few qualifying opportunities.
- Preserve the existing recommendation gates: usable paired opportunities,
  independent days/symbol-days, after-cost advantage, concentration, drawdown,
  execution validation and human approval.
- Display a baseline-change termination as **Superseded and restarted**, with a
  link between versions. Do not describe it as evidence against the hypothesis.

### 3. Founder learning scorecard

Add a concise, first-level scorecard above the technical evidence. It must separate:

- **More capable:** new verified information, tooling or operational controls.
- **Learned something:** a hypothesis was supported, rejected or remained unknown.
- **Trading better:** an adopted frozen change improved after-cost outcomes versus
  the unchanged strategy and an appropriate broker-specific market benchmark.

The scorecard should show, without combining GBP and USD:

- ideas examined, historically rejected and admitted to forward testing;
- running, completed, superseded and recommended experiments;
- simulated opportunities, resolved pairs, independent days and uncertainty;
- approved/adopted rule versions and their subsequent paper/live evidence;
- baseline-versus-candidate after-cost change and drawdown;
- Alpaca and Kraken benchmark comparisons appropriate to each account; and
- a plain headline such as `Learning activity only`, `Candidate improvement
  detected`, `Improvement verified`, or `No improvement / regression`.

Counts of research, experiments or lessons are activity metrics, not proof that
trading skill improved.

### 4. Trader's daily reflection

- Generate one short reflection from the same verified scorecard evidence, rather
  than hard-coding a celebratory sentence.
- Let Trader choose natural wording while requiring four truthful answers: what it
  examined, what it learnt, whether it became more capable, and whether improved
  trading performance is demonstrated.
- Store each daily reflection for a visible history and include its headline in the
  existing 09:00 London daily review.
- Provide a deterministic evidence-based fallback when the reasoning-model call is
  unavailable or times out. The card must never be empty and must never turn missing
  evidence into a claim of improvement.

### 5. Reliability needed for the reflection

- Diagnose the hosted `/ask-ai-trader` internal error.
- Diagnose the overnight self-assessment timeout and Strategy Lab execution timeout.
- Keep trading, broker polling, exits and safeguards independent of these reporting
  failures.
- Verify the repaired daily reflection against production evidence before presenting
  it as Trader's own assessment.

## Proposed implementation order

1. Correct experiment status semantics and add version/supersession presentation.
2. Repair the Trader/self-assessment and Strategy Lab timeout paths.
3. Add the bounded persistent historical importer/cache, starting with Alpaca.
4. Connect historical coverage to candidate admission and expose coverage plainly.
5. Build the Founder scorecard and evidence-based daily reflection with fallback.
6. Add Kraken historical depth once the equity path is measured and stable.
7. Observe Supabase egress and provider/API usage before expanding the universe or
   moving from daily to more granular bars.

## Completion evidence

This plan is complete only when production demonstrates all of the following:

- an initial historical backfill and a small incremental refresh with measured
  network/storage impact;
- at least one historical trial with real chronological coverage, or an explicit
  quantified reason that coverage remains inadequate;
- no material increase in recurring Supabase egress from replay work;
- a superseded experiment displayed distinctly from an evidence-based rejection;
- a visible Founder scorecard whose headline matches its underlying figures;
- a stored daily reflection with a verified fallback; and
- the daily review clearly distinguishing capability gains, lessons, and proven
  performance improvement.

## Implementation checkpoint — 17 September 2026

- A bounded provider-to-Render daily-bar cache now performs an initial five-year
  Alpaca backfill and the maximum Kraken OHLC history available from its endpoint,
  then refreshes only a seven-day overlap. It caps symbols, pages, bars per symbol
  and total disk usage. One failed symbol cannot fail the batch.
- Live read-only provider checks returned 1,253 completed MSFT daily bars from
  Alpaca and 720 completed XRPGBP daily bars from Kraken. These checks did not
  create orders or write market history to Supabase.
- Historical screening now merges source-qualified cached bars with existing
  recorded evidence and stores only compact result/provenance summaries in
  Supabase. It does not fabricate historical AI decisions: replay coverage remains
  limited to signals that the system actually recorded.
- Three-day reviews remain checkpoints and the existing evidence gates and 36-day
  maximum remain intact. Baseline-change records are now displayed as
  `Superseded and restarted`, rather than as evidence that a hypothesis failed.
- The Experiments screen now includes a Founder scorecard and plain reflection
  separating `More capable`, `Learned something`, and `Trading better`. A claim of
  verified improvement requires adopted forward evidence; activity alone cannot
  produce it.
- The scorecard is refreshed after learning measurement and historical screening,
  with a bounded history. If the reasoning-model self-assessment fails or times
  out, Trader records the deterministic evidence-based reflection instead of an
  error-only answer.
- Strategy Lab refresh now receives the research-job execution budget rather than
  the shorter default job timeout.
- Focused backend regression suite: 102 passed. Mobile experiment checks: 5 passed.
- Release `6a47b978` is live on the Render API and background worker. The first
  production scorecard returned `Learning activity only`: Trader is more capable,
  four forward experiments are being tracked, and better trading performance has
  not yet been proved.
- Android runtime 1.0.4 OTA was published from the clean release revision to
  `hosted-preview` (group `8182e63c-01a1-4e61-bfa4-9753341893a1`) and `preview`
  (group `e0f521a3-f21f-4c7c-b9df-3d1ba6e7a4ac`).
