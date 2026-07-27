# Canonical Reconciliation Design

## Goal

Every broker event must reconcile into one logical trade without duplicate lifecycle corruption.

## Current Components

- `operational_truth.py` remains the canonical lifecycle event store.
- `production_spine.py` adds `reconcile_logical_trade`.
- `CANONICAL_RECONCILIATION_CASES` records reconciliation confidence and manual-review need.

## Event Grouping

Broker events are grouped by:

- `logical_trade_id`;
- `order_id`;
- `ordertxid`;
- `trade_id`;
- broker/symbol/side fallback when no broker ID exists, except for Kraken.

Kraken reconciliation never uses symbol matching to infer AI Trader ownership
or entry/exit role. A Kraken order ID must exist in
`KRAKEN_AI_ORDER_OWNERSHIP`, recovered from a durable order intent, managed
exit, or new Investment Orchestrator submission.

## Lifecycle Mapping

The reconciliation engine maps broker states into canonical lifecycle stages:

- submitted;
- broker_acknowledged;
- partially_filled;
- fully_filled;
- cancelled;
- exit states where supplied.

Each lifecycle write uses an idempotency key.

For Kraken, `ClosedOrders` and `TradesHistory` have different meanings:

- a closed-order record establishes order state but does not create a fill;
- a trade-history record is an executed fill and may change quantity, fees,
  capital, P&L, and lifecycle state.

A Kraken trade becomes terminal only after explicitly owned exit-fill quantity
covers entry-fill quantity. A closed order by itself can never close the
canonical investment.

## Confidence Scoring

Confidence decreases when:

- events require manual review;
- broker identifiers are missing;
- symbols are missing;
- event evidence is incomplete.

Manual review is required only when deterministic reconciliation is incomplete.

## Kraken Recovery Read Model

`KRAKEN_RECONCILED_RESULTS` projects the canonical trade into Founder-facing
entry, exit, fee, P&L, holding-time, slippage, and R fields.
`KRAKEN_RECONCILIATION_CASES` records owned, excluded, and ambiguous evidence.
`KRAKEN_AI_CAPITAL_LEDGER` is a separate £100 AI-managed cash ledger and never
includes the Founder's pre-existing Kraken holdings.

The replay path reads persisted evidence only and cannot submit a broker order.
Terminal learning is queued once through the existing Sprint 6 workflow
outbox.

## Limits

The deterministic Kraken fill and ownership path is implemented. Complex
broker corrections, replacement trees, and historical records with missing
order identifiers may still require manual review. Such records are not
guessed or silently attributed.
