# Production Evidence Pipeline Audit

## Worker priority correction

Hosted job evidence showed that a healthy worker could still leave the Founder
interface without broker truth: sequential crypto and equity research jobs
reached their three-minute limits before broker polling and evidence snapshot
publication. The production cycle now prioritises managed exits, broker
reconciliation, evidence publication and execution eligibility ahead of slow
research. Research remains autonomous and retains the same governance
requirements, but it can no longer prevent already-known Alpaca or Kraken state
from reaching the read model.

## Finding

The hosted API and the paid Render worker were alive, but they did not previously share enough Founder-facing evidence to prove what the worker had done. The worker scheduled broker polling, managed exits, auto-execution evaluation and learning. It did not own recurring market research. Most rich UI payloads were assembled from process-local SQLite, while worker heartbeats and jobs were stored in shared Supabase/Postgres. This caused a healthy worker to coexist with empty Market, Portfolio, Learning and Activity screens.

## Corrected evidence path

```text
Render worker
  -> scheduled research / broker poll / execution evaluation / learning
  -> broker and research services
  -> shared production evidence projection in Supabase/Postgres
  -> GET /founder-evidence
  -> cached mobile read model
  -> Dashboard, Activity, Recommendations, Portfolio, Market and Learning
```

The projection does not replace the Investment Orchestrator, Risk Engine, canonical lifecycle or broker adapters. It copies their observable outcomes into a bounded shared read model so the Founder can see the same truth from every process.

## Root causes corrected

1. The worker now owns recurring crypto research and market-aware equity research.
2. Broker snapshots, broker order/fill observations, recommendation evidence, research outcomes and learning outcomes are stored in shared Postgres.
3. The mobile application loads one bounded Founder payload instead of blocking startup on the legacy `/status` aggregate.
4. Cached evidence renders immediately while fresh evidence is requested.
5. Long implementation-phase diagnostic cards were removed from the primary Founder experience.
6. Live verification exposed Kraken `EQuery:Unknown asset pair`: research selected general active crypto records instead of only Founder-approved Kraken pairs. Autonomous Kraken research is now constrained to approved pairs, and an unavailable pair is recorded/skipped without aborting the remaining cycle.
7. Live Founder evidence exposed an Alpaca Postgres failure after repeated
   broker observations. Expected duplicates are now resolved by
   `ON CONFLICT DO NOTHING` inside the insert statement, preventing a duplicate
   from aborting the transaction that also records the current portfolio
   snapshot.
8. The worker's production research handoff now merges each base proposal with
   the existing rich recommendation dossier before refreshing Founder
   snapshots. Proposal identifiers, prices, position size and risk remain
   authoritative; strategy, probability, committee, signal, argument,
   invalidation and due-diligence evidence are added when genuinely available.
9. Canonical lifecycle duplicates previously raised a uniqueness exception
   inside an active Postgres transaction. A later portfolio snapshot write in
   that transaction then failed with `current transaction is aborted`.
   Lifecycle and immutable experience idempotency now use atomic conflict
   handling, so repeated polling is harmless.
10. Multi-period snapshot generation previously rebuilt the same evidence
    projection four times. The worker now loads one bounded maximum-period
    evidence set and derives each display period from that shared read.

## Truth boundaries

- A trade is displayed only from persisted broker or canonical evidence.
- Realized P&L is displayed only when the broker or reconciled trade supplies it.
- An open position is not described as a completed profit or loss.
- Missing P&L remains unavailable with a reason; it is never inferred from account movement alone.
- A completed worker job proves that code ran, but does not prove that an order qualified.
- Auto-trading permission does not bypass strategy, portfolio, risk or broker gates.

## Residual limitations

Legacy domain tables remain SQLite-oriented. The production evidence tables are the shared Founder projection while deliberate schema-by-schema Postgres migration continues. Exact closed-trade attribution still depends on broker history quality and canonical reconciliation. Historical recommendation records cannot gain evidence that was never stored; newly generated research records carry the rich dossier. Live hosted proof requires deployment of this commit and observation of at least one worker research cycle.

## Snapshot Performance Boundary

The snapshot worker performs one bounded evidence load for the longest
requested period. It then filters that immutable in-memory row set for the
one-hour, 24-hour, seven-day and 30-day snapshots. Broker capture still occurs
before projection refresh so the read model includes the latest available
account evidence, but SQL projection work is not repeated for every period.
