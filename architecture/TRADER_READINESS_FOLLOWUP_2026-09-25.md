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
