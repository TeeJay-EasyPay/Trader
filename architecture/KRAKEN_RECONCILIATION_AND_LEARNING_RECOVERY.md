# Kraken Reconciliation and Learning Recovery

## Purpose

This recovery closes a specific operational gap: Kraken broker history could
show completed orders without proving that an AI Trader investment had been
closed, attributed, or learned from. The recovery protects the Founder's
existing Kraken holdings while reconstructing only trades that can be linked
deterministically to AI Trader.

The recovery does not loosen strategy, portfolio, risk, allocation, stop-loss,
take-profit, or broker-permission controls.

## Safety State

New Kraken entries are paused by
`KRAKEN_RECONCILIATION_CONTROL.hold_new_entries`. The Investment Orchestrator
checks this hold before every Kraken entry. Existing managed exits remain
eligible for monitoring and protective execution.

The hold is created in the active state and remains active after a successful
verification. Resuming entries requires a separate authenticated Founder
command after the verification result has been reviewed.

## Ownership Boundary

The £100 Founder allocation is represented by
`KRAKEN_AI_CAPITAL_LEDGER`. The ledger includes only:

- the explicit Founder allocation;
- fills whose Kraken order IDs are registered in
  `KRAKEN_AI_ORDER_OWNERSHIP`;
- fees returned with those fills.

Existing personal Kraken holdings are not opening AI Trader positions, do not
consume AI-managed trade slots, and are not available to reconciliation by
symbol similarity. An unregistered order is classified as
`unmanaged_excluded`, even when its symbol matches an AI Trader symbol.

Ownership may be recovered only from durable identifiers already written by:

- `ORDER_INTENT_LOCKS.result_order_id`;
- `MANAGED_TRADE_EXITS.entry_order_id`;
- `MANAGED_TRADE_EXITS.exit_order_id`;
- new Investment Orchestrator submissions.

## Kraken Evidence Semantics

Kraken evidence is separated into two record types:

- `closed_order`: an order that is no longer open. It may have filled,
  partially filled, expired, or been cancelled. It is not a fill and is not
  proof that an investment position was sold.
- `trade_fill`: an executed exchange trade returned by Kraken trade history.
  Only this record type changes filled quantities, the capital ledger, or
  realised P&L.

The canonical lifecycle rejects fill attribution when the order role cannot be
resolved from explicit ownership. It does not guess entry or exit roles from
the symbol.

## Canonical Reconstruction

Each owned Kraken fill is routed through the broker-neutral canonical trade
reconciler. Multiple and repeated fills are idempotent. A logical trade becomes
terminal only when reconciled exit quantity covers reconciled entry quantity.

For each reconciled trade the recovery records, where supported by persisted
evidence:

- intended and actual entry;
- original stop and intended target;
- actual exit;
- entry and exit times;
- holding duration;
- filled quantity and remaining quantity;
- broker and exchange fees;
- gross and net P&L;
- initial monetary risk;
- planned, gross, and net R;
- entry and exit slippage;
- reconciliation confidence.

Unrealised P&L is calculated separately from realised P&L and only when a
current Kraken price exists for every AI-managed open position. Missing prices
remain explicitly unavailable.

## Replay Procedure

`replay_persisted_kraken_evidence` reads stored `BROKER_TRADE_HISTORY` rows.
It has no broker client and no order-submission path. Its result always reports
`broker_orders_submitted: 0`.

Replay is idempotent:

- canonical lifecycle events use stable idempotency keys;
- broker fills are unique;
- capital-ledger fills are unique;
- reconciliation cases are updated by stable raw-event hash;
- terminal learning uses the existing exactly-once workflow outbox.

The production worker performs a guarded replay at startup. A replay failure
does not terminate managed-exit monitoring. It records a degraded heartbeat
and an operations incident while leaving the entry hold active.

## Closed-Loop Learning Recovery

Only a genuine canonical terminal trade is queued for learning. The queue
payload contains the reconciled trade result and the historical decision
context retained by the canonical trade.

The existing Sprint 6 learning processor remains responsible for:

- performance attribution;
- immutable experience creation;
- post-trade review;
- learning conclusions and proposals;
- marking the workflow complete.

Retries do not create a second workflow or a second immutable experience.
Winning or losing personal holdings are never added to AI Trader learning.

## API and Founder Visibility

Authenticated endpoints:

- `GET /kraken-reconciliation`
- `GET /kraken-reconciliation/verify`
- `POST /kraken-reconciliation/replay`
- `POST /kraken-reconciliation/verify`
- `POST /kraken-reconciliation/resume`

The Kraken broker panel exposes:

- reconciliation pause and status;
- reason for the pause;
- £100 allocation;
- available AI-managed cash;
- deployed AI-managed capital;
- realised gross and net P&L;
- unrealised P&L or its unavailable reason;
- explicit confirmation that personal holdings are excluded;
- a replay command labelled `Reconcile Kraken Evidence`.

## Verification Gate

Verification requires:

- at least one explicit AI Trader Kraken order ownership record;
- no ambiguous owned evidence;
- personal holdings excluded;
- realised and unrealised P&L represented separately;
- one learning workflow per canonical terminal trade;
- one reconciled result per canonical terminal trade;
- a finite, internally consistent allocation ledger.

A successful verification does not automatically resume trading. Founder
review and the authenticated resume command are still required.

## Production Activation Procedure

1. Deploy the API and worker revision against shared Postgres.
2. Confirm the Kraken reconciliation schema initializes successfully.
3. Confirm new Kraken entries show as paused.
4. Run the persisted replay.
5. Review excluded personal orders and any ambiguous owned cases.
6. Compare the £100 ledger with Kraken order and trade evidence.
7. Confirm realised and unrealised P&L are separated.
8. Process the learning outbox and confirm terminal reviews are visible.
9. Run the verification endpoint.
10. Resume only after the Founder accepts the verified evidence.

## Honest Limitation

Historical Kraken rows that do not contain explicit AI Trader order IDs cannot
be attributed safely. They remain excluded or require manual evidence repair.
The system deliberately prefers an incomplete historical reconstruction over
inventing ownership, P&L, or learning.
