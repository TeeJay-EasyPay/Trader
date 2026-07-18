# Learning Processor Verification

Date: 2026-07-18

## Implemented

The background worker now calls `process_learning_outbox` every cycle.

The processor:

- claims pending or retryable closed-loop learning workflows;
- recovers abandoned claimed rows after timeout;
- requires deterministic terminal-trade evidence;
- moves incomplete evidence to manual review;
- runs closed-loop learning only when required context exists;
- records operational evidence for each processor cycle;
- preserves the original queued payload.

## Evidence Requirements

A learning workflow is considered complete only when:

- the workflow row is marked `completed`;
- `CLOSED_LOOP_LEARNING_RUNS` has exactly one row for the logical trade;
- original evidence payload is unchanged;
- an operational event records the learning processor result.

## Test Evidence

Focused tests prove:

- incomplete payloads move to `manual_review`;
- deterministic payloads complete once;
- repeat processor cycles do not duplicate closed-loop learning records.

## Boundary

Learning proposals remain governed recommendations only. They do not change production strategy settings or guardrails.
