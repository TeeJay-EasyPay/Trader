# Trader readiness implementation

Approved on 24 September 2026 after the reconciliation investigation. Built on
deployed d57d700d / documentation 7f245ec4, not the dirty old root checkout.
Standup/voice UI and native/mobile runtime are unchanged; no OTA is required.

## Implemented

1. Kraken per-coin records: remove the PostgreSQL percent-in-comment query failure;
   aggregate by symbol in SQL, with alias normalization and original time/cohort
   boundaries. Restrict to Kraken crypto/GBP, preserve original caution thresholds,
   and distinguish unavailable history from no trades. The summary uses existing
   database-verified conditional transfer (no stale TTL). Chat reads it once, not
   once per symbol. Restoring the existing caution input can reduce entries.
2. Trader chat: replace its maintenance-capable daily-learning call with a small
   read-only daily projection. No calibration refresh, shadow settlement or strategy
   demotion from this path. Deliberate research requests and their action/budget
   controls remain intact, as do scheduled maintenance jobs.
3. Currency/cost truth: daily conversation reports are broker/currency/basis separated.
   The legacy maintenance report no longer adds mixed-currency monetary results.
   Existing Alpaca account-level FEE records are explicitly supplied to Trader,
   separate from estimated and individually verified costs; missing net results are
   not described as missing reviews. No fabricated zero-fee/net backfill.
4. Experiments: fetch independent bounded cursor groups; a stalled reference test
   no longer pins the other tests. New prospective admission specs count hard
   exclusions separately before paid reference assessment or comparison slots.
   Only baseline-eligible or explicitly supported intervention opportunities enter.
   Original risk exclusions, daily AI/observation/fan-out/storage bounds remain.
   Admission exclusions retain bounded reason counters and intake timestamps.
5. Capital evidence: show ring-fenced allocation, ledger cash, owned positions,
   managed-control value and current risk-basis definition without replacing them
   with whole-account equity. Existing limits/denominator are unchanged. Precision
   in Kraken canonical aggregation now uses the saved fill quantity when consistent
   with its float32 projection, not a broad dust tolerance.

## Bounded rollout/repair

- tools/readiness_rollout.py previews first, preserves existing observations/specs,
  and creates prospective admission versions with new cursors. It never resets the
  daily quota or places orders. Existing paid reference work is not pooled with the
  new selection cohort; no extra calls are bought to repeat it. Idempotent checkpoint.
- tools/repair_verified_kraken_closures.py checks at most eight owned candidates,
  verifies every fill's explicit ownership and exact decimal entry/exit balance,
  and only then refreshes aggregates, closes linked local exit-control records and
  queues existing idempotent learning work. It does not cancel or submit broker
  orders. Original fill evidence and prior aggregate/control scalars are retained.
  Preview found four exact balanced closures (XRP, SOL, LTC, ADA); genuine residual
  quantities and unowned/ambiguous evidence are not repaired.

## Verification

- Full suite: 2,035 passed, 21 subtests passed, one skipped, eight failures.
  The failures are the same six existing crypto fee-hurdle fixture expectations and
  two old Standup section-copy assertions already reproduced on the pre-release base.
- Targeted trading/canonical/research/action checks passed except one rollout test
  fixture initially failed to persist its simulated legacy spec. Corrected the fixture
  with an explicit SQL update (normal _save intentionally preserves immutable specs).
- Targeted final group: 64 passed, including closure repair idempotency, admission
  rollout preservation, independent cursor progression, hard-block admission,
  currency separation and read-only chat call-path checks.
- Live SELECT-only validation returned 15 Kraken symbol aggregates representing
  62 recent outcomes; broker-separated daily USD gross/GBP net figures; allocation
  GBP500; and 44 stored Alpaca account fee rows totalling -USD3.67. These are dated
  observations, not current profitability or complete historical cost coverage.
  This application-wrapper session used read statements but reported transaction
  read-only off (connection pool overrides URL options); do not describe it as a
  database-enforced read-only test.
- Validation consumed approximately 5.1 KB of value bytes; the four-candidate repair
  preview consumed about 14.2 KB. Neither number is billed provider egress. No raw
  account/trade history dump, provider-wide crawl, new research cycle or paid model
  call was needed for these checks. Useful unblocked experiments may add some work;
  preserve budgets and measure full-day provider totals rather than promising savings.

## Remaining boundaries

Ring-fencing exists, but a fully marked common capital contract is NOT established:
the ledger and actual broker cash still differ, and some owned nonterminal records
(including SUI/BCH) lack matching open managed-exit controls. Do not automatically
expand capital, reclassify personal holdings, place exits or install new protection
without authoritative order/position reconciliation. This release exposes that gap
and repairs only exact evidenced closures. A further risk-basis change requires a
clear agreed contract, not Trader's preference for a larger denominator.

Alpaca account fees exist, but the last stored activity is September 11 and last
observed row September 15. No newer row is not proof of zero costs; per-trade actual
fees/net results remain unknown where no authoritative allocation is available.
The existing polling path already captures FEE activities, so it is not duplicated.

Successful tests and Trader feedback do not prove profitable learning. Forward
comparisons must settle naturally; historical, paper and live evidence remain distinct.

Deployment and post-release results will be appended after verification.
