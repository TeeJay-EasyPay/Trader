# Autonomous Learning Workflow

## Objective

Every terminal trade should move into learning without the Founder manually triggering a report.

## Sprint 6 Implementation

Terminal broker rows now enqueue `closed_loop_learning` workflows in `SPRINT6_WORKFLOW_OUTBOX`.

The outbox is idempotent by:

```text
closed-loop-learning:{broker}:{logical_trade_id}
```

Duplicate terminal rows do not queue duplicate learning work.

## Existing Learning Engine

Phase 5 already includes `run_closed_loop_learning`, which calculates:

- execution costs
- gross R
- net R
- MAE
- MFE
- experience record
- post-trade review
- historical analogues
- learning proposal

## Remaining Work

Sprint 6 queues learning. The next step is a worker-owned outbox processor that runs terminal workflows transactionally and marks completion or failure with retries.

