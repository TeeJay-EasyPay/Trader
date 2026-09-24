# Broker learning and egress completion — 24 September 2026

## Scope and safety boundary

This release completes the nine Founder-approved learning/evidence actions. It changes
simulation, evidence projection, reporting and transfer efficiency only. It does not place
orders, loosen safeguards, change allocation, alter entry criteria or reduce managed-exit
monitoring.

## Implemented actions

1. **Broker adapters.** Legacy shadow settlement now uses an Alpaca adapter and a Kraken
   adapter. The shared arithmetic receives broker-normalised inputs; prices, symbols,
   currencies and costs remain broker-specific.
2. **Versioned schema.** Both adapters emit canonical settlement schema v2 with explicit
   broker, asset class, currency, market symbol and cost basis. Incompatible broker/asset
   combinations fail closed.
3. **Broker-separated evidence packets.** Trader receives compact Alpaca and Kraken packets
   showing the canonical decision-to-outcome learning coverage, after-cost results and
   limitations. GBP and USD are never pooled.
4. **Legacy evidence recovery.** Previously unsettleable shadows are examined once using the
   correct adapter. Recoverable rows re-enter settlement; irrecoverable rows remain labelled
   historical evidence and are never converted into invented outcomes.
5. **Kraken cost reconciliation.** The Kraken packet separately reports gross P&L, broker and
   exchange costs, net P&L, coverage and accounting mismatches. It does not infer missing
   costs from Alpaca or from a generic model.
6. **Calibration audit trail.** Material calibration changes now record the prior/new sample,
   win rate and calibration error by strategy and asset class.
7. **Evidence freshness.** Each broker packet records latest closure, latest completed
   learning handoff, evidence age and an explicit freshness status.
8. **Founder answer.** The permanent Learning card continues to answer “Is Trader getting
   better?” and now gives separate plain-English Alpaca and Kraken reasons beneath the shared
   headline.
9. **Measured egress reduction.** Active experiments no longer download their growing report
   books for cursor checkpoints; routine lifecycle views omit large payload JSON; experience
   analogue searches use broker/asset filters and a smaller bound; current broker-history
   panels omit payload JSON when normalised columns are present; legacy candle reads have a
   time bound. Telemetry now exposes daily and per-family row-value budgets and breaches.

## Evidence boundaries

- A completed linkage proves evidence arrived; it does not prove the strategy improved.
- Only the modern complete cohort supports improvement claims. Older incomplete trades remain
  in account history but do not dilute or invalidate the modern cohort.
- Provider-billed egress includes protocol and pooler overhead. Code-level reductions are
  deterministic; the Supabase graph must be compared after a complete deployment-free day.
- Safety-critical broker polling and managed exits retain their existing cadence.

## Verification

- 187 focused backend tests passed across broker settlement, self-assessment,
  experiments, learning, production evidence, multi-broker reporting, calibration and
  egress telemetry.
- All 6 mobile Learning-screen contract tests passed, and the Android Expo export
  completed successfully.
- The complete repository run reached 2,013 passes, 1 skip and the same 8 known baseline
  failures already documented on 15 September: six stale crypto fee-hurdle fixtures and
  two obsolete Standup markup assertions. No new full-suite failure family was introduced.
