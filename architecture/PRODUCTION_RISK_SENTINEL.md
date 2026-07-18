# Production Risk Sentinel

## Purpose

The Production Risk Sentinel is a final operational safety gate before the Investment Orchestrator.

## Current Checks

Sprint 6 checks:

- kill switch state
- account equity availability
- mandatory stop loss
- mandatory take profit
- proposal risk percentage
- market data quality label
- open critical incidents

## Decision Outcomes

- `approved`: the proposal may continue to the Investment Orchestrator.
- `blocked`: the proposal must not reach broker submission.

## Kill Switch

`KILL_SWITCH_STATE` stores whether the emergency stop is active. When active, the Risk Sentinel blocks pre-execution approval.

## Important Boundary

The Risk Sentinel does not replace the existing Risk Engine or guardrails. It runs before them to catch operational and governance risks earlier.

