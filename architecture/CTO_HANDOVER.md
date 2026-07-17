# AI Trader CTO Handover

Date: 2026-07-17

This pack documents the current AI Trader implementation for a new CTO or Chief Architect. It describes the platform as it exists in this repository, not a target-state design.

## Handover Index

- [SYSTEM_OVERVIEW.md](SYSTEM_OVERVIEW.md) - project vision, maturity, status, and roadmap context.
- [ARCHITECTURE.md](ARCHITECTURE.md) - subsystem architecture and communication paths.
- [APPLICATION_FLOW.md](APPLICATION_FLOW.md) - end-to-end runtime flows.
- [MODULE_REFERENCE.md](MODULE_REFERENCE.md) - directory and module ownership.
- [DATABASE_REFERENCE.md](DATABASE_REFERENCE.md) - SQLite schema reference.
- [BROKER_ARCHITECTURE.md](BROKER_ARCHITECTURE.md) - orchestrator, broker adapters, Alpaca, Kraken, and future broker support.
- [KNOWLEDGE_ENGINE.md](KNOWLEDGE_ENGINE.md) - investment, crypto, benchmark, and learning systems.
- [UI_REFERENCE.md](UI_REFERENCE.md) - mobile app screens and workflows.
- [RISK_ENGINE.md](RISK_ENGINE.md) - guardrails, governance, capital allocation, and mechanical seatbelts.
- [GOVERNANCE_REFERENCE.md](GOVERNANCE_REFERENCE.md) - governance documents and control model.
- [IMPLEMENTATION_HISTORY.md](IMPLEMENTATION_HISTORY.md) - sprint-by-sprint architectural evolution.
- [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md) - current bugs, debt, and risks.
- [ROADMAP.md](ROADMAP.md) - future engineering roadmap.

## Current Platform Identity

AI Trader is a personal autonomous trading platform. It began as a simple Alpaca paper-trading assistant and has evolved into a multi-broker, continuously researching, governed execution system. The platform currently supports:

- Alpaca paper trading for equities.
- Kraken live micro-trading for approved GBP crypto pairs.
- Coinbase, Binance, Interactive Brokers, and Saxo placeholder broker surfaces.
- A Render-hosted Python API.
- A SQLite persistent audit and intelligence database.
- An Expo React Native mobile app.
- OpenAI-assisted proposal analysis and read-only Ask AI explanations when `OPENAI_API_KEY` is configured.

The system is intentionally founder-controlled. AI may produce recommendations and explanations, but it must not change governance, risk settings, or broker permissions automatically.

## Current Operating Model

The backend runs as a Python HTTP service through `src/ai_trader/api.py`. Render hosts it as a Docker web service using `render.yaml` and `Dockerfile`. Render persistent disk is mounted at `/data`, and the SQLite database path is normally configured through `AI_TRADER_DB_PATH`.

The mobile app is an Expo app in `mobile/App.js`. It calls the hosted API at `https://trader-no0f.onrender.com` or a local API depending on runtime configuration. Protected POST endpoints require `Authorization: Bearer <AI_TRADER_API_TOKEN>`.

The runtime has these control layers:

1. Environment variables configure credentials, limits, and broker permissions.
2. Governance documents define founder intent and constraints.
3. SQLite stores operational state, recommendations, decisions, orders, managed exits, reports, and learning data.
4. The Investment Orchestrator performs deterministic validation before any broker submission.
5. Broker adapters isolate broker-specific API behavior.

## CTO View Of The Architecture

The central architectural decision is separation between intelligence and execution.

- Intelligence produces research, scores, recommendations, and explanations.
- The orchestrator performs deterministic routing and validation.
- Broker adapters perform broker-specific API operations.
- Audit and reporting record what happened.

This separation should be protected. The AI should not directly place broker orders and should not bypass the risk engine.

## Immediate CTO Priorities

1. Improve trade attribution quality.
   Current broker histories can contain raw fills without full reconstructed round trips. Closed trade P&L is only reliable when `PERFORMANCE_ATTRIBUTION` rows are created or broker fills can be matched into an entry/exit pair.

2. Normalize broker trade history.
   Kraken and Alpaca return materially different payloads. A canonical `TradeLifecycle` model should be introduced so the UI does not depend on raw broker data shape.

3. Strengthen scheduler observability.
   The app shows research and due diligence status, but the scheduler should expose last successful run, last failed run, next run, current phase, and active worker heartbeat per worker.

4. Move runtime configuration management into an admin surface.
   The app can now request broker auto-trading changes and sync selected Render env vars if Render API credentials are configured. This should be expanded carefully into a governed configuration console with audit approval.

5. Add integration tests against mocked broker APIs.
   Existing tests cover platform behavior, but broker API edge cases, malformed payloads, idempotency, and reconnection behavior need stronger coverage.

## Architecture That Should Not Be Broken

- The AI must never submit directly to a broker.
- The orchestrator must remain the single execution authority.
- Every broker must maintain independent auto-trading state.
- Execution must require both broker permission and proposal validation.
- Historical audit data must remain append-only unless an explicit correction table is introduced.
- Existing positions must continue managed exits even when new entries are disabled.
- Kraken live trading must remain limited by explicit mechanical seatbelts.

## Main Runtime Commands

Local setup:

```powershell
.\start_project.ps1
```

Run tests:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

Start local API:

```powershell
scripts/start_local_api.ps1
```

Hosted health check:

```powershell
Invoke-WebRequest -UseBasicParsing https://trader-no0f.onrender.com/healthz
```

Build mobile app:

```powershell
cd mobile
npx eas build --platform android --profile preview
```

## Deployment Summary

Render deploys the Python API from Docker. Required production secrets include:

- `AI_TRADER_API_TOKEN`
- `ALPACA_API_KEY`
- `ALPACA_SECRET_KEY`
- `KRAKEN_API_KEY`
- `KRAKEN_PRIVATE_KEY` or equivalent Kraken secret variable expected by the adapter
- `OPENAI_API_KEY`

Optional Render control integration requires:

- `RENDER_API_KEY` or `RENDER_API_TOKEN`
- `RENDER_SERVICE_ID`

The mobile app must be built with `EXPO_PUBLIC_AI_TRADER_API_TOKEN` matching the hosted `AI_TRADER_API_TOKEN`. If the installed APK does not contain the token, protected hosted API calls return unauthorized.

## Handover Position

AI Trader is operational but not yet a clean institutional-grade trading platform. It is a working founder platform with strong architectural direction and growing operational surfaces. The next CTO should preserve the separation of research, recommendation, deterministic orchestration, and broker execution while improving data normalization, test depth, observability, and trade attribution.
