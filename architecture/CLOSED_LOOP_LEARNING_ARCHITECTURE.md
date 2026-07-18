# Closed-Loop Learning Architecture

## Objective

When a logical trade reaches terminal state, AI Trader should learn from it without changing production parameters automatically.

## Current Implementation

`run_closed_loop_learning` performs the closed-loop sequence:

1. Calculate execution costs.
2. Calculate gross and net R.
3. Calculate MAE and MFE.
4. Store immutable experience.
5. Generate post-trade review.
6. Search historical analogues.
7. Create a governed learning proposal.
8. Mark lifecycle `learning_completed`.

## Idempotency

`CLOSED_LOOP_LEARNING_RUNS.logical_trade_id` is unique. A repeated run returns duplicate status and does not create another learning chain.

## Governance Boundary

Learning proposals are suggestions only.

They may recommend:

- threshold review;
- signal-weight review;
- strategy stability review;
- cost-assumption review.

They must not automatically change:

- broker permissions;
- live trading switches;
- risk limits;
- strategy production status;
- guardrails.

## Founder Meaning

AI Trader can now distinguish:

- a profitable result;
- a good decision;
- a bad decision with a lucky result;
- a good decision with an unlucky result;
- insufficient evidence.

