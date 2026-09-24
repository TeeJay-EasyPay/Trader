# Learning evidence and background transfer — 24 September 2026

## Scope

Two Founder-authorised items: useful, accurately reported experiments and lower
background database transfer. No live strategy activation, looser live limits,
broker orders, increased AI allowance, history deletion or protection slowdown.
Work starts from deployed fa7d4ece, not the older dirty master checkout. Existing
local maintenance/navigation edits are preserved and excluded from this release.

## Findings from read-only production checks

- Alpaca has 120 standalone settled simulations (77 stops, 43 targets), 53 pending,
  and 870 legacy unsettleable records. Standalone results already feed
  `shadow_strategy_records` / `shadow_symbol_records` and broker learning packets;
  they are not paired experiments and do not prove improvement.
- The active experiment mix at this check is four Alpaca / three Kraken. Earlier
  chat counts were snapshots, not permanent allocation facts.
- Alpaca's configured broker minimum stop distance is 1.5%. Example FCX entry
  72.31 / stop 71.90 is about 0.57%, legitimately below it. Later FSLR and VMC
  decisions had no rejection reasons: today's entire Alpaca stream was NOT blocked.
- Kraken's recorded decision context has equity 401.1774 GBP, existing managed
  exposure 80.93456 GBP, and proposed notional 40.22944 GBP. Together that is about
  30.20%, above the unchanged 25% capital cap. Its four open managed positions total
  80.9347 GBP; the four older exit_submitted rows are NOT included by the open-position
  reader. No duplicate open-position counting was found in this sampled calculation.
  This checks application accounting, not an independent fresh broker reconciliation.
- 20:13 UTC worker telemetry: 231,290 calls, 161.485 MB consumed values. Largest:
  experiments 45.113 MB, broker history 17.265 MB, experience 14.783 MB, news 9.879 MB,
  decision blobs 9.571 MB, audit 7.972 MB. API at 20:29 UTC: 6.566 MB. These are
  incomplete host-local counters, not the provider's 271 MB or a same-window balance.
- September 20–21 spikes were previously investigated: accelerated scheduler loops,
  repeated portfolio-history reads, and stale experiment-dependent telemetry.
  See EGRESS_CORRECTION records / September 20–21 release documentation. Those fixes
  are already in this base; this release does not count their savings a second time.

## Changes

1. Both-skipped pairs no longer count as useful completed comparisons or independent
   evidence. Reports show both-skipped, informative completed, differing decisions,
   capacity-rebased opportunities and recorded blocker counts. Existing observations
   remain intact. Trader's aggregate context distinguishes standalone outcomes from
   informative paired comparisons.
2. New experiment versions use separately budgeted virtual portfolios. ONLY an exact
   capital-allocation-only block can be replaced, identically for both arms. All other
   stop, cost, permission, data and unknown failures remain blocked. Each virtual arm
   retains frozen cash/risk/five-position limits and a 25% exposure ceiling with
   start-of-day reservations. Legacy specifications retain their former behaviour.
3. An idempotent transactional rollout preserves all old observations and starts
   eligible all-skipped Kraken tests as new prospective versions. No backdating or
   pooling of the old capacity-blocked sample. Other tests receive report corrections
   only; unrelated deployment changes still do not change the semantic fingerprint.
4. Proposal worker returns before reading research history once its daily model
   allowance is used. Reference assessments load only required experiment fields.
5. Experiment state, historical analogues, narrow broker history and news readers use
   existing lossless conditional-transfer machinery. Every query still runs against
   current database data; only unchanged bodies stay in the bounded host cache.
   Deletions, corrections and order remain authoritative. Full evidence is retained.
6. Worker invalid counts are per experiment, not the cumulative count from earlier
   experiments in the same tick.

## Verification and remaining boundaries

- Local paired entry/settlement tests cover both brokers, frozen virtual exposure,
  legacy behaviour, blocked safeguards, idempotent settlement and non-informative skips.
- Read-only production parity: experiment, experience, news and history queries returned
  identical direct/cold-cache/warm-cache records. Warm repeats transferred no changed
  row bodies. No assumption of a fixed TTL or omitted decision context.
- Actual egress saving is NOT yet measured. Compare a full post-release UTC day with
  the provider's AI-Trader-only chart, along with hourly value bytes, calls, connections,
  cache hit/miss bytes and deployment times. The provider/host accounting gap remains
  unattributed; do not label all of it protocol overhead or promise a percentage.
- Live new outcomes require future market bars. Passing local simulations and Trader's
  opinion are not evidence of trading profitability or a completed live comparison.

## Test results before deployment

- Complete suite: 2,029 passed, 21 subtests passed, one skipped, eight failures.
  All eight reproduce with the unchanged deployed base fa7d4ece: six crypto
  proposal fixture expectations fail the pre-existing fee hurdle, and two Standup
  tests expect obsolete section copy. None is introduced by this release.
- Focused release/experiment/learning suite: 74 passed. Additional egress, news,
  history and weekly-learning regression group: 83 passed.
- Five mobile timeline tests passed. Android Hermes export succeeded for runtime
  1.0.4. No connected physical device was available for visual acceptance testing.
- Direct PostgreSQL aggregate verification distinguishes Alpaca's 120 standalone
  settled outcomes from 30 active paired opportunities, all skipped by both arms
  in that retained sample. Kraken's retained active sample likewise has 30 skips.

## Deployment and Trader review

- Backend release d57d700dcf113b9a30d185fbc7a1cdf94d467e34 was pushed and verified
  on both the hosted API and worker. Worker verification at 20:55:32 UTC reported
  the release commit and no last error.
- Android OTA runtime 1.0.4 published to hosted-preview group
  f10c1dd1-0d43-47c9-bda6-ac1234349e7d and preview group
  0b58b833-fffc-49dd-be57-bd0c3c77d932. No new native build was required.
- Transactional shadow rollout applied at 2026-09-24T20:55:50.730478+00:00.
  Three legacy Kraken experiments were preserved and replaced prospectively by
  6f0bcf17-af2b-4135-ab3f-449708b93be8,
  59ec9829-dea5-436e-867f-c0799108f36b, and
  8fabdc70-0549-4301-8b5a-5fb30560c187. Alpaca reports were corrected without
  restarting their experiments. Hosted detail responses verified both behaviours.
- Trader was asked once through the normal authenticated /ask-ai-trader endpoint,
  in the Standup conversation, with a factual release summary and a read-only
  review request. The response was answered, read_only=true, and "partly satisfied".
  It supported the engineering changes but requested subsequent version-specific
  eligible entries, completed comparisons, blockers and after-cost differences,
  plus a full post-release provider egress measurement. Its learning packet
  predated the transition; it did not verify new forward outcomes.
- Trader also raised a valid accounting-basis question: the application labels
  a cash-capped approved trading allocation as account equity. Its sampled
  rejection arithmetic is consistent with that basis, but this does not establish
  that the denominator is the intended policy. Whole-account holdings and managed
  trading allocation must be reconciled before deciding whether code should change.
  No live capital cap or account settings were relaxed by this release.
- Other Trader-reported gaps (Alpaca actual-cost learning coverage, per-coin closure
  reporting and mixed-currency daily aggregates) are feedback for follow-up, not
  independently verified findings or fixes in this release. Its opinion is not
  evidence of improved profitability. No additional research cycle was requested.
