# Experience Engine and Governed Learning

Date: 2026-07-17

## Objective

The Experience Engine stores not just trades, but what AI Trader knew at the time, what happened, and what it learned. Historical context is immutable and cannot be overwritten by future data.

## Tables

- `EXPERIENCE_RECORDS`: immutable decision, execution, and result context.
- `POST_TRADE_REVIEWS`: post-trade answer to what happened and whether the decision was good.
- `HISTORICAL_ANALOGUES`: "Have we seen this before?" results with sample warnings.
- `LEARNING_PROPOSALS`: versioned learning suggestions requiring approval.

## Outcome Classification

Outcomes are classified as:

- Good decision, good outcome
- Good decision, poor outcome
- Poor decision, good outcome
- Poor decision, poor outcome
- Insufficient evidence to judge

This prevents the system from treating every winner as good analysis or every loser as bad analysis.

## Governance

Learning proposals may suggest changes, but they cannot change production behaviour silently. Small samples remain research-only.
