# Production Evidence Pipeline Audit

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

## Truth boundaries

- A trade is displayed only from persisted broker or canonical evidence.
- Realized P&L is displayed only when the broker or reconciled trade supplies it.
- An open position is not described as a completed profit or loss.
- Missing P&L remains unavailable with a reason; it is never inferred from account movement alone.
- A completed worker job proves that code ran, but does not prove that an order qualified.
- Auto-trading permission does not bypass strategy, portfolio, risk or broker gates.

## Residual limitations

Legacy domain tables remain SQLite-oriented. The production evidence tables are the shared Founder projection while deliberate schema-by-schema Postgres migration continues. Exact closed-trade attribution still depends on broker history quality and canonical reconciliation. Live hosted proof requires deployment of this commit and observation of at least one worker research cycle.
