# System Overview

## Vision

AI Trader is a personal autonomous investment assistant. Its purpose is to research markets, produce trade recommendations, validate those recommendations against founder-approved rules, execute approved trades through broker adapters, monitor open positions, record every decision, and explain performance in plain English.

The platform is not designed as a commercial product. It is a founder-controlled trading workstation with increasing automation. The product goal is not maximum feature breadth; it is traceable autonomy with visible controls and audit history.

## Current Maturity

The platform is between prototype and early operational system.

Implemented:

- Hosted Python API on Render.
- Persistent SQLite state and audit database.
- Expo mobile app.
- Alpaca paper account integration.
- Kraken live micro-trading integration with explicit safety controls.
- OpenAI-assisted proposal analysis and read-only Ask AI explanations.
- Recommendations screen with saved recommendation history.
- Broker panels with independent broker state.
- Trade History screen.
- Reports and report browser endpoints.
- Runtime scheduler workers for research, broker polling, managed exits, auto execution, crypto refresh, and push dispatch.

Not fully mature:

- Broker trade attribution is incomplete for all cases.
- Raw broker fill data is still exposed in places where canonical trade lifecycle data should be shown.
- Supabase is not currently part of the AI Trader runtime.
- Coinbase, Binance, Interactive Brokers, and Saxo are placeholders or future adapters.
- Push notifications exist server-side but need full mobile notification registration and delivery hardening.
- Operational reporting is improving but still depends on quality of broker sync and attribution records.

## Architectural Philosophy

The architecture follows these principles:

1. Separate AI from execution.
   AI can analyze, propose, and explain. It cannot directly place broker orders.

2. Deterministic execution authority.
   The Investment Orchestrator is deterministic software. It independently validates all guardrails before broker submission.

3. Broker independence.
   Alpaca, Kraken, and future brokers have separate runtime state, auto-trading settings, permissions, balances, and histories.

4. Append-only audit first.
   Historical decisions and trade events are persisted. New records explain changes instead of overwriting history.

5. Governance controls behavior.
   Trading rules, risk tolerances, and learning boundaries are defined in governance documents and represented in policy/configuration tables.

6. Founder approval for capability expansion.
   The AI may recommend improvements, but strategy, guardrails, broker permissions, and execution logic are founder/engineer controlled.

## Current Implementation Status

Backend:

- Package: `src/ai_trader`.
- API entrypoint: `src/ai_trader/api.py`.
- CLI entrypoint: `src/ai_trader/cli.py`.
- Configuration: `src/ai_trader/config.py`.
- Deployment: `Dockerfile` and `render.yaml`.

Mobile:

- Expo React Native app: `mobile/App.js`.
- Current app version: `1.0.2`.
- Android package: `com.local.aitrader`.
- EAS project: `58ca35af-2cf4-44a0-8da4-7f02563b635f`.

Data:

- SQLite database default: `data/audit.sqlite3`.
- Hosted database path is normally configured through `AI_TRADER_DB_PATH`.
- Render persistent disk is mounted at `/data`.
- Trading journal path defaults to `governance/TRADING_LOG.md`.

Governance:

- Governance documents live in `governance/`.
- The current Investment Policy Statement is `governance/INVESTMENT_POLICY_STATEMENT.md`.
- Risk governance is supplemented by `governance/RISK_MANAGEMENT_POLICY.md` and `governance/BROKER_EXECUTION_POLICY.md`.

## Long-Term Roadmap

The intended evolution is:

1. Stabilize the current Alpaca/Kraken experience.
2. Normalize all broker history into canonical trade lifecycle records.
3. Improve performance attribution and reporting.
4. Add a governed configuration UI for broker limits and permissions.
5. Complete push notifications.
6. Add richer market data and paid data providers for sentiment, news, and on-chain crypto signals.
7. Add future brokers through the adapter interface.
8. Introduce a more formal strategy lab where AI can propose strategy changes for approval without modifying live strategy.
