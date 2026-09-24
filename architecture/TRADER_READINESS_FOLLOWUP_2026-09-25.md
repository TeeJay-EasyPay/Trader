# Readiness follow-up — 25 September 2026 (UK)

User authorised completing the broader reconciliation and verification work.
Preserve live capital/risk settings, experiment budgets and evidence. Voice UI
remains separate. Work uses the existing release checkout, not the dirty root.

## Findings and implementation

- **Kraken precision:** the pooler reports `extra_float_digits=0`. REAL output
  19.9322 is actually stored as 19.932243347168 when widened to DOUBLE PRECISION.
  Startup options were ignored; SET LOCAL returned more digits. Therefore the
  earlier inference of a corrupt/truncated stored quantity was premature. Widen
  numeric SELECT expressions in canonical fill aggregation, with no global session
  changes, schema migration, extra round trip or relaxed remainder tolerance.
  Retained original fill quantities still pass the existing consistency guard.
  Repair uses actual exit timestamps, not today's repair date.
- **Alpaca closure selection:** daily canonical repair repeatedly examines older
  groups without explicit exit ownership and already-reviewed groups. Filter those
  using one bounded metadata read BEFORE spending the ten-group daily allowance.
  Keep explicit ownership and complete cumulative quantity checks. No research or
  trading budget increase. Targeted preview/repair reads at most twenty linked
  orders and two hundred fill projections, refusing truncated inputs.
- **MDT:** one direct paper-broker GET verified the original bracket entry's 27
  shares and filled stop child on September 22. Five retained activity increments
  (27 entry; 12+11+3+1 exit) support the same closed trade, gross loss USD50.11.
  Fees remain unknown. A separate idempotent one-trade recovery checkpoint avoids
  resetting the ordinary daily reconciliation cursor or allowance.
- **Costs:** a direct bounded FEE read returned September 11 as latest; no order
  IDs in its schema. FILL activity is current through September 24 but contains no
  broker/exchange fee fields. Thus stale stored FEE dates reflect the available
  feed, not proof of broken polling or zero fees. No arbitrary account-fee
  allocation or fabricated verified net results is appropriate.
- **Capital:** internal evidence includes four orphan exit-only ownership records
  and four older completed records whose ledger cash flows differ from canonical
  net by more than one penny. BCH's entry and exit use different logical IDs;
  matching by symbol alone is not sufficient. No merging or capital increase.
  Add a founder-only authenticated diagnostic for up to ten explicitly owned
  Kraken order IDs, using only QueryOrders and Balance. No broker writes or automatic
  polling; it exposes GBP cash but excludes unrelated personal holdings.

## Verification boundaries

Seven new experiment versions have advanced cursors (Alpaca 43080, Kraken 43075
at 23:27 UTC September 24). Alpaca now records market-hours, duplicate-position
and stop/cost exclusions separately. This confirms intake progress, not completed
informative outcomes. No restarting or artificial settling for this check.

Worker telemetry published 23:00 UTC reports 3,324,205 consumed value bytes in its
partial host-local day. Top family: experiment_control 795,223 bytes. This is NOT
provider-billed egress, excludes other hosts/protocol traffic, and the day contains
deployments. There is not yet a complete day after the 22:38 UTC release. Provider
usage credentials are not present locally; do not invent a day total or savings.

Deployment, bounded repair results and remaining required evidence follow below.

## Applied and verified (23:40–23:47 UTC September 24)

- API and worker both verified at `9e4345d9a9b8fe3a24c85e2d5225247470f3ce85`.
  Intermediate release was 17f34dc8. The final adjustment scopes the precision
  projection to Kraken; Alpaca's numeric reader remains unchanged.
- Fresh Kraken QueryOrders confirmed the four exits closed and fully executed.
  GBP Balance was 401.1774. No broker orders or cancellations occurred.
- Repaired XRP, SOL, LTC and ADA exact closures and closed their stale local
  controls. Original fills retained, previous scalar/control fields audited.
  Actual closure dates: September 9 (XRP/LTC), September 10 (ADA), September 20
  (SOL), not the repair date. All four normal learning workflows completed.
- MDT targeted repair completed. Its canonical closure date is September 22;
  ordinary learning workflow completed with no error and no invented net fees.
- Coverage verified: Kraken 91 canonical terminal / 91 linked reviews / 91 known
  net results; Alpaca 26 terminal / 26 linked reviews / zero verified trade nets.
  Counts describe coverage, not improvement. They must not be pooled as one currency.
- Further reconciliation found four *already-repaired learning* records whose
  canonical synthetic exit records still had side=sell. The unchanged ledger and
  retained owned buy/sell fills proved the mismatch. `repair_legacy_direction.py`
  previews four fixed IDs, requires existing repair provenance, cross-checks the
  corrected arithmetic with ledger cash flows, preserves old values, and updates
  only canonical/result/linked attribution fields. No learning is repeated.
  Applied all four; corrected nets approximately -0.0676488, +0.0799101,
  +0.054855 and +0.12207 GBP. Every completed owned Kraken canonical result now
  agrees with its ledger cash flows within GBP0.01 (zero mismatches).
  Aggregate completed net is -GBP19.8958867. These are historical corrections,
  not new profits made today. Live capital and risk policy are unchanged.
- One currently open managed control remains (ETH), entry value GBP20.11472.
  This does not resolve the separate orphan/legacy ownership records.
- Full suite: 2,042 passed, 21 subtests passed, one skipped, eight known pre-existing
  failures (six crypto fee-hurdle fixtures; two old Standup section-copy assertions).
  Focused release checks: 112 passed, additional scope checks 32 passed, legacy
  repair tests 3 passed including idempotency and preserving learning count.
- The three bounded repairs consumed approximately 0.722 MB of returned row values
  in local telemetry, not provider-billed bytes. This included original decision
  context necessary for learning; no export of the full trade history was made.

## What cannot yet be signed off

1. **Whole cash/ownership bridge:** internal completed-trade P&L is reconciled, but
   ledger cash GBP445.715 and physical cash GBP401.1774 differ by about GBP44.54.
   An earmarked internal allocation is not itself an account deposit and these
   balances need not be identical. To account for the difference, the historical
   GBP account movements and opening funding basis must distinguish owned trade
   flows from deposits, withdrawals and non-Trader activity. Do not plug the gap.
   BCH has an explicitly identifiable split entry/exit across legacy logical IDs;
   SUI's control only says the balance was zero at a September 9 check, which is
   not proof of the missing exit price or profit. Four orphan exit-only records
   still require identity reconciliation. No identities were merged by symbol.
2. **Alpaca actual per-trade fees:** the available broker feed does not attach FEE
   activities to order IDs. Keep estimates labelled, and account fees separate;
   verified trade-net coverage cannot be manufactured from default zero fees.
3. **Prospective results:** cursors advance and exclusions are recorded, but the
   seven new versions have zero admitted pairs at the sampled check. Existing
   daily quotas were intentionally preserved and Alpaca is outside market hours.
   Need genuinely new eligible opportunities and completed bars, not a forced
   research run, reset quota or fabricated settlement.
4. **Egress:** a complete provider day after deployment is still unavailable.
   Local consumed-value telemetry cannot replace the provider's AI-Trader-only
   daily chart. No measured saving is claimed.

These remaining evidence gaps are not marked complete merely because code shipped.
