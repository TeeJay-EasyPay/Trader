# Design Report

Date: 2026-07-02
Version: 1

## Design Summary

The system is implemented as a small Python command-line application with two runtime components:

- `AITradingAgent`: gathers market context, optionally calls an AI analyzer, creates structured proposals, and records the agent decision.
- `ExecutionEngine`: reloads proposals, obtains fresh account context, independently validates guardrails, places Alpaca paper bracket orders, and records execution results.

Both components depend on the same shared guardrail validator. This is the main safety mechanism in Version 1.

## Safety Model

- Broker calls are isolated in the Alpaca paper client.
- Non-paper Alpaca trading URLs are rejected at client construction.
- Credentials are read from environment variables only.
- The agent cannot execute orders because it receives only a market-data/broker-context interface and has no order placement call in its workflow.
- The execution engine treats proposals as untrusted input and validates them again.

## Traceability Model

- Proposal decisions are recorded in `trade_audit`.
- Execution approvals and rejections are recorded in both `trade_audit` and `execution_events`.
- Daily reports are stored in `daily_briefings` and written to Markdown.
- Historical rows are appended; the implementation does not update or delete audit rows.

## AI Model

If `OPENAI_API_KEY` is present, the agent can request a JSON trade proposal from the OpenAI Responses API. The returned JSON is parsed into the same `TradeProposal` contract and must pass guardrails.

If no AI key is present, the system does not invent trades in normal mode. It records no-trade events. The `--demo` mode creates deterministic mock proposals for local testing only.

## Execution Model

Valid proposals are submitted as Alpaca paper bracket orders:

- Market entry.
- Stop-loss child order.
- Take-profit child order.
- Day time-in-force.

Rejected proposals are never submitted to Alpaca.

## Known V1 Limitations

- US equity trading hours use regular-session validation and do not model exchange holidays yet.
- P&L learning is present in the briefing structure but requires future fill/close reconciliation to compute completed-trade lessons automatically.
- Real Alpaca paper smoke testing requires local credentials and a callable Python runtime.
- Market analysis is intentionally simple in Version 1; the focus is on traceable proposal and execution flow.

