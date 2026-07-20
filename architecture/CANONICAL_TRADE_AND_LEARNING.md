# Canonical Trade and Learning Contract

## Identity contract

The logical trade ID is created from the proposal ID before any broker request. It does not change when a broker returns an order, trade or fill ID. Broker identifiers are evidence linked to the logical trade, not replacements for it.

## State and evidence

`LOGICAL_TRADES` stores current aggregate state. `LOGICAL_TRADE_EVENTS` stores immutable transitions with an idempotency key. `LOGICAL_TRADE_FILLS` stores immutable fills unique by broker and fill ID.

The aggregate stores intended entry, original stop, intended target and intended quantity alongside actual entry/exit averages, matched quantity, remaining quantity, costs and P&L. This preserves the original decision even when stops or exits later change.

## Reconciliation algorithm

1. Resolve the logical ID from proposal evidence, linked broker order, managed-exit record or stable external broker identity.
2. insert the raw canonical event using a deterministic idempotency key.
3. classify a fill as entry or exit from explicit broker mapping, managed-exit order linkage or the first linked order.
4. insert the fill once.
5. recompute weighted entry and exit prices from all immutable fills.
6. compute gross P&L on matched quantity.
7. subtract confirmed broker and exchange fees for net P&L.
8. mark terminal only when positive entry quantity is fully matched by exit quantity.
9. assign reconciliation confidence from evidence completeness.

Filled entry orders are open positions, not completed trades. Cancelled and rejected orders are not profitable or losing trades. Duplicate polling cannot increase quantities or costs.

## Learning trigger

Canonical reconciliation, not the API route, owns the terminal signal. Broker normalization queues one workflow using:

```text
closed-loop-learning:<broker>:<logical_trade_id>
```

The unique key makes repeated terminal broker events harmless. Claimed workflows are recoverable after lease expiry.

## Complete evidence path

When original decision context and terminal attribution are present, closed-loop learning calculates or records:

- confirmed execution costs and slippage;
- gross and net R using original monetary risk;
- MAE and MFE with observation granularity;
- expected versus actual result;
- decision and outcome quality;
- immutable Experience Engine record;
- post-trade review;
- strategy and regime statistics;
- analogues;
- a versioned learning proposal;
- `learning_completed` lifecycle evidence.

No learning proposal changes live settings automatically.

## Insufficient historical evidence

Imported or old broker records may lack proposal context, original stop, or matched fills. These workflows finish exactly once as `completed_insufficient_evidence`. They retain the missing-field list and raw broker payload. This prevents endless queues without pretending the missing P&L or lesson is known.

## Known boundaries

- MAE/MFE remain dependent on persisted observations; missing candles cannot be reconstructed honestly.
- Fee values are dependable only when returned by the broker or explicitly labelled estimated by an existing calculation.
- External pre-AI-Trader holdings may reconcile as broker activity without becoming AI-managed trades.
- A broker correction after learning completion requires a governed correction workflow; the present code does not silently rewrite immutable experience.
