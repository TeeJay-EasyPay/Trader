# AI Trading Assistant V1 Implementation Plan

Date: 2026-07-02
Status: Active

## Principles

- Keep Version 1 small and operable from the command line.
- Use shared validation code so the AI agent and execution engine enforce the same guardrails.
- Store credentials only in environment variables.
- Prefer standard library components to reduce setup friction.
- Record every meaningful decision in SQLite.
- Never call live trading endpoints.

## Phases

### Phase 1: Governance Baseline

- Create architecture design document.
- Create implementation plan.
- Create decision register.
- Create implementation log.
- Create founder briefing template.

Exit criteria: governance documents exist before implementation code.

### Phase 2: Core Domain Model

- Define trade proposal schema.
- Define guardrail configuration.
- Define validation result model.
- Add JSON serialization helpers.

Exit criteria: proposals can be parsed, serialized, and validated in tests.

### Phase 3: Audit Database

- Create SQLite schema.
- Implement append-only audit writes.
- Implement daily briefing source queries.

Exit criteria: tests prove audit events are persisted without overwriting history.

### Phase 4: Alpaca Paper Integration

- Implement environment-based authentication.
- Retrieve account, positions, orders, and activities.
- Place bracket orders with stop loss and take profit.
- Reject non-paper endpoints.

Exit criteria: integration can be smoke-tested with paper credentials or a mock client.

### Phase 5: AI Trading Agent

- Load market context.
- Produce proposals using optional OpenAI analysis or deterministic fallback.
- Apply guardrails before persisting proposals.
- Write proposal JSON and audit records.

Exit criteria: agent produces structured proposal files and records no-trade/proposal decisions.

### Phase 6: Execution Engine

- Load proposals.
- Rebuild fresh account and position context.
- Re-run guardrails independently.
- Submit approved orders to Alpaca paper trading.
- Record validation and execution events.

Exit criteria: invalid proposals are rejected; valid mock proposals execute in tests.

### Phase 7: Daily Founder Briefing

- Summarize proposals, executions, rejections, P&L, guardrail breaches, observations, lessons, and recommendations.
- Persist briefing and write a Markdown report.

Exit criteria: briefing command produces a concise daily report.

### Phase 8: Verification

- Unit-test guardrails, audit, proposal parsing, and execution behavior.
- Run an end-to-end mock demonstration.
- Document any feature that requires real Alpaca paper credentials for live verification.

Exit criteria: test suite passes and the CLI can run without hard-coded credentials.

