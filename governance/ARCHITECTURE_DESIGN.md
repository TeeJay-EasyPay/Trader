# AI Trading Assistant V1 Architecture Design

Date: 2026-07-02
Status: Approved baseline for Version 1 implementation
Scope: Personal paper trading only

## Purpose

Version 1 is a deliberately small, traceable paper trading system. It separates AI analysis from deterministic execution so that every trade idea is independently validated before any broker call is made.

This project is not a commercial trading platform and must not trade live capital.

## System Components

The system has only two runtime components.

### 1. AI Trading Agent

Responsibilities:

- Read market data, news, sentiment, and existing positions.
- Analyse a small configured symbol universe.
- Apply the shared guardrails before proposing any trade.
- Produce structured trade proposals.
- Produce the Daily Founder Trading Brief.
- Analyse completed trades and suggest improvements for founder approval.

Restrictions:

- The agent never places orders.
- The agent never bypasses guardrails.
- The agent never changes guardrails, strategy, or execution logic automatically.

### 2. Execution Engine

Responsibilities:

- Load trade proposals.
- Independently validate each proposal against the same shared guardrails.
- Reject invalid proposals.
- Place approved orders through the Alpaca Paper Trading API.
- Retrieve positions, order status, and trade history.
- Record every validation and execution event in the audit database.
- Monitor open positions and support stop-loss updates where appropriate.

Restrictions:

- The engine is deterministic software, not an AI.
- The engine must never place an order until validation passes.
- The engine must only use Alpaca paper trading endpoints.

## Data Flow

1. Configuration is loaded from environment variables and optional CLI arguments.
2. The agent fetches market context for configured symbols.
3. The agent builds a structured trade proposal or records a no-trade decision.
4. The shared guardrail validator checks the proposal in agent mode.
5. Proposals are written to JSON and audit rows are appended.
6. The execution engine reads proposals.
7. The same shared guardrail validator checks the proposal in execution mode using fresh account and position context.
8. Approved trades are submitted to Alpaca paper trading.
9. Execution results are appended to the SQLite audit database.
10. The founder briefing summarizes the day.

## Trade Proposal Contract

Every proposal contains:

- Symbol
- Side: buy or sell
- Entry price
- Stop loss
- Take profit
- Position size
- Risk percentage
- Confidence score
- News summary
- Market sentiment summary
- Technical summary
- Plain English reasoning
- AI guardrail result
- Creation timestamp

## Guardrails

The same guardrail function is used by both components. Required Version 1 guardrails:

- Paper trading only.
- Maximum account risk per trade.
- Maximum daily loss.
- Maximum open positions.
- Position size must be positive.
- Stop loss is mandatory.
- Take profit is mandatory.
- Stop loss direction must match side.
- Take profit direction must match side.
- No duplicate open positions.
- Trading hours validation.
- Confidence score must meet the configured minimum.

Any failed guardrail rejects the proposal.

## Audit Database

The audit database is SQLite for Version 1. It is append-only by convention: new events create new rows or immutable event records; historical records are not overwritten.

A human-readable append-only trading log is also maintained at `governance/TRADING_LOG.md`. The SQLite database remains the structured audit source, while the trading log gives the founder a plain Markdown ledger of proposal, validation, rejection, and execution events.

Primary tables:

- `trade_audit`: one durable row per proposal/execution lifecycle.
- `execution_events`: append-only execution and validation events.
- `daily_briefings`: generated daily summaries.
- `governance/TRADING_LOG.md`: append-only human-readable trading ledger.

The database stores reasoning, summaries, guardrail results, execution results, P&L fields, lessons learned, and recommendations.

## Broker Integration

Broker: Alpaca Paper Trading API.

Required environment variables:

- `ALPACA_API_KEY`
- `ALPACA_SECRET_KEY`
- `ALPACA_PAPER_BASE_URL`

Default paper URL:

- `https://paper-api.alpaca.markets`

The implementation refuses non-paper base URLs unless explicitly running in the local mock test mode.

## AI Integration

Version 1 supports optional OpenAI API analysis through `OPENAI_API_KEY`. If the key is absent, the agent uses a conservative deterministic analysis mode that can produce no-trade decisions and test proposals from supplied market data. This keeps the system testable without external services.

The AI output is treated as untrusted input until the shared proposal parser and guardrails accept it.

## Operations

The CLI supports:

- Generate proposals.
- Execute proposals.
- Run a single end-to-end cycle.
- Generate a daily briefing.
- Inspect configuration.

## Non-Goals

- Live trading.
- Intraday high-frequency trading.
- Multi-broker support.
- Automatic strategy mutation.
- Portfolio optimization.
- Web dashboard.
- Commercial user management.

## Foundation Sprint Architecture Addendum

Date: 2026-07-04
Status: Founder-governed autonomous investment platform baseline

Trader now uses the following permanent execution chain:

```text
Research Engine
-> Knowledge Engines
-> Investment Intelligence Engine
-> Due Diligence Engine
-> Investment Orchestrator
-> Broker Adapter Layer
-> Alpaca / Kraken / Future Brokers
```

The Investment Orchestrator is the only autonomous component allowed to execute trades. AI components research, learn, score, and recommend, but they do not place orders.

New governance and policy layer:

- Constitutional governance documents live in `governance/`.
- Configurable SQLite policy tables define investment, risk, broker, learning, and capital allocation controls.
- Every autonomous trade records due diligence, investment score, broker decision, execution decision, and capital allocation history.

Due diligence has six required pillars:

- Fundamental Intelligence
- Technical Intelligence
- Market Intelligence
- Macro Intelligence
- Behavioural Intelligence
- Investment Policy Intelligence

Every recommendation now has a structured Investment Score:

- Fundamental Score
- Technical Score
- Market Score
- Macro Score
- Behavioural Score
- Investment Policy Score
- Risk Score
- Overall Confidence

## Autonomous Trading Readiness Sprint Addendum

Date: 2026-07-07
Status: Orchestrator-only execution guarantee now covers every execution path

"The Investment Orchestrator is the only autonomous component allowed to execute trades"
previously had one exception: the manual "approve and execute" API path constructed a
legacy `ExecutionEngine` directly, bypassing due diligence, investment scoring, capital
allocation, and the duplicate-order-intent lock. That exception is now closed -
`approve_and_execute` calls `InvestmentOrchestrator.evaluate_recommendation` exactly like
the autonomous path, with a human's approval substituting for the auto-trading toggle
rather than for the orchestrator's own checks. `ExecutionEngine` remains in the codebase
only for the offline CLI demo path (`ai_trader.cli execute`), which is not a live/networked
execution surface and does not touch the orchestrator's SQLite state.

Continuous monitoring is now a first-class part of the architecture rather than an
on-demand HTTP action: `run_server` starts background `IntervalWorker` loops (60-second
cadence) for managed-exit monitoring, broker order/fill polling, and crypto knowledge-base
refresh, alongside the existing hourly `ResearchScheduler`. All of these loops catch and
log any exception and continue on their next cycle rather than terminating the thread -
autonomous operation degrades to "skipped this cycle," never "silently stopped forever."

Known remaining architectural debt, out of scope for this sprint: `api.py` is a large
file mixing HTTP routing with business logic that in places duplicates decision logic the
orchestrator already owns (e.g. confidence/freshness pre-checks before calling the
orchestrator), and adding a new broker still requires touching several files (adapter,
orchestrator broker-name branches, `multi_broker.py`'s broker list, `foundation.py`'s
default broker policies, `api.py`'s adapter wiring). This is an Amber, not safety-blocking,
finding and is recommended as a dedicated follow-up rather than being mixed into a sprint
that also changed dozens of safety-critical behaviors.

Crypto knowledge schema is present, but crypto execution remains disabled unless the Founder changes policy and broker settings.
