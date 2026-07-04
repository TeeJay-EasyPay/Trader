# AI Trading Assistant V1

Personal AI-assisted paper trading system for Alpaca.

## Developer Setup

The project is configured for local Windows development in VS Code.

1. Clone the repository.
2. Open the folder in VS Code.
3. Run one command:

```powershell
.\start_project.ps1
```

This creates or uses `.venv`, activates it, sets local environment variables, initializes SQLite tables, starts the Local API, and opens the Developer Dashboard.

VS Code is configured by `.vscode/settings.json` to use:

```text
.venv\Scripts\python.exe
```

The previous `python` issue was caused by the Windows Store app execution alias at `C:\Users\t_jeh\AppData\Local\Microsoft\WindowsApps\python.exe`. The project now avoids that global shim by using the local virtual environment.

Run tests:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

## CLI

```powershell
.\.venv\Scripts\python.exe -m ai_trader.cli config
.\.venv\Scripts\python.exe -m ai_trader.cli propose --symbols AAPL,MSFT --demo
.\.venv\Scripts\python.exe -m ai_trader.cli execute --proposals data/proposals.json --demo
.\.venv\Scripts\python.exe -m ai_trader.cli briefing
.\.venv\Scripts\python.exe -m ai_trader.cli run-once --symbols AAPL --demo
.\.venv\Scripts\python.exe -m ai_trader.cli intelligence-init --report
.\.venv\Scripts\python.exe -m ai_trader.cli intelligence-refresh --report
.\.venv\Scripts\python.exe -m ai_trader.cli intelligence-report
.\.venv\Scripts\python.exe -m ai_trader.cli benchmark-init --report
```

`--demo` uses local deterministic market context and a mock broker path for safe end-to-end demonstration. Real order placement requires Alpaca paper credentials and the paper base URL.

Trade lifecycle events are written to SQLite and appended to `governance/TRADING_LOG.md` by default.

## Investment Intelligence Engine

Sprint 2 adds a local SQLite knowledge base for long-term investment research. It keeps Version 1.0 trading frozen and does not redesign the AI Trading Agent, Execution Engine, guardrails, or Trading Journal.

The intelligence tables live in the same SQLite master database:

- `COMPANY_MASTER`
- `COMPANY_FINANCIALS`
- `COMPANY_DAILY_UPDATES`
- `INVESTMENT_WATCHLIST`
- `MARKET_THEMES`

Initialize the curated watchlist and market themes:

```powershell
$env:PYTHONPATH='src'
python -m ai_trader.cli intelligence-init --report
```

Run the daily append-only refresh:

```powershell
$env:PYTHONPATH='src'
python -m ai_trader.cli intelligence-refresh --report
```

The scheduled helper script is `scripts/run_daily_intelligence_refresh.ps1`. To register it as a local Windows Task Scheduler job, run `scripts/register_daily_intelligence_refresh.ps1`. It is local-only and writes to SQLite; it does not use Supabase or cloud storage.

## Sprint 3: Local API and Mobile App

Sprint 3 adds benchmark trader intelligence, a small local HTTP API, and a simple Expo mobile app. The trading engine, execution engine, guardrails, and SQLite storage remain unchanged.

Initialize benchmark intelligence:

```powershell
$env:PYTHONPATH='src'
python -m ai_trader.cli benchmark-init --report
```

Start the local API:

```powershell
scripts/start_local_api.ps1
```

Developer Dashboard:

```powershell
.\start_project.ps1
```

Then open `http://127.0.0.1:8765/developer-dashboard`.

API endpoints:

- `GET /status`
- `GET /portfolio`
- `GET /founder-brief`
- `GET /recommendations`
- `GET /intelligence/companies`
- `GET /intelligence/themes`
- `GET /benchmark-traders`
- `GET /benchmark-daily-brief`
- `POST /run-analysis`
- `POST /start-trading`
- `POST /pause-trading`
- `POST /resume-trading`
- `POST /stop-trading`
- `POST /auto-execute-recommendations`
- `POST /approve-and-execute`

Browse SQLite without SQL:

```powershell
scripts/browse_database.ps1
```

This opens a read-only local browser viewer at `http://127.0.0.1:8770`. It lists all tables, supports search, sorting, and record viewing, and exposes no edit controls.

Run the mobile app:

```powershell
scripts/start_mobile_app.ps1
```

For a physical phone, replace `127.0.0.1` with the laptop LAN IP address in `EXPO_PUBLIC_AI_TRADER_API_URL`.

The app has three screens only: Trading Command Centre, AI Recommendations, and Market Intelligence. Missing values are shown as `Not available`. Execution still goes through the existing Execution Engine guardrails.

Recommendation freshness:

- Each recommendation shows when it was generated, when it expires, and whether it is Fresh, Stale, or Expired.
- High-confidence trade ideas expire after 4 hours, medium-confidence ideas after 12 hours, and lower-confidence ideas after 24 hours.
- Expired recommendations are blocked from manual execution until analysis is run again.
- Saved recommendations remain visible in the Recommendations screen for historical reference after app restart.
- Recommendation cards are ordered from highest confidence to lowest confidence.

Auto execution:

- `POST /auto-execute-recommendations` submits only Paper Trading recommendations at or above 85% confidence.
- Auto execution still uses the existing Execution Engine and guardrails.
- Auto execution skips expired recommendations, already executed recommendations, and recommendations that did not pass guardrails.
- Recommendation cards show both passed guardrails and failed guardrails so high confidence is not confused with trade approval.

Mobile controls:

- Trading controls are simplified to Start Trading and Stop Trading.
- The Recommendations screen has Refresh, Run New Analysis, and Auto Execute 85%+ controls.
- Market Intelligence shows theme definitions, drivers, and risks so related themes are easier to understand.
- Market Intelligence also shows monitored companies so sectors/themes can be connected back to the recommendation cards.

## Hosted Backend

The phone app can run without the laptop when the backend runs on an always-on host.

Architecture:

```text
Honor Magic V3 app -> Hosted AI Trader API -> SQLite + Trading Engine + Alpaca/OpenAI
```

The hosted API uses the existing Python trading engine, execution engine, guardrails, knowledge engine, and SQLite schema. It does not move broker keys or execution logic into the phone.

Cloud deployment files:

- `Dockerfile`
- `render.yaml`
- `cloud.env.example`

Recommended first host: Render with a persistent disk mounted at `/data`.

Render setup:

1. Push this repository to GitHub.
2. In Render, create a new Blueprint from `render.yaml`.
3. Add secret environment variables:
   - `AI_TRADER_API_TOKEN`
   - `ALPACA_API_KEY`
   - `ALPACA_SECRET_KEY`
   - `OPENAI_API_KEY`
4. Keep `PAPER_TRADING_ONLY=true` until the hosted app has been tested.
5. Deploy.

The backend exposes:

```text
GET /healthz
GET /status
GET /portfolio
GET /founder-brief
GET /recommendations
GET /intelligence/companies
GET /intelligence/themes
GET /benchmark-traders
GET /benchmark-daily-brief
POST /run-analysis
POST /start-trading
POST /pause-trading
POST /resume-trading
POST /stop-trading
POST /auto-execute-recommendations
POST /approve-and-execute
```

## Sprint 4: Investment Orchestrator

Sprint 4 adds an Investment Orchestrator between AI recommendations and broker execution. The AI researches and recommends; the orchestrator decides whether a recommendation is executable.

Core additions:

- Broker adapter interface with `AlpacaBrokerAdapter`.
- Placeholder `InteractiveBrokersAdapter`, `SaxoAdapter`, and `KrakenAdapter` that return not configured until credentials exist.
- `ORCHESTRATOR_DECISIONS`, `AUTO_TRADE_EVENTS`, and `DAILY_BRIEFS` SQLite tables.
- `AUTO_PAPER_TRADING=false` by default.
- Auto paper trading requires confidence >= 85%, philosophy fit >= 85%, paper mode, stop loss, take profit, no short selling, market open, asset availability, and all guardrails.
- Morning and evening brief generators write Markdown and append `DAILY_BRIEFS`.
- `research-once` runs one safe 24/7 research cycle for local or hosted schedulers.
- Render web service starts a safe hourly background research scheduler when `RESEARCH_SCHEDULER_ENABLED=true`.

Render can schedule safe research by invoking the existing `POST /run-analysis` endpoint or by running:

```powershell
.\.venv\Scripts\python.exe -m ai_trader.cli research-once --limit 30
```

Required Sprint 4 environment variables are shown in `.env.example` and `cloud.env.example`.

## Sprint 5: Operational Clarity and Crypto Preparation

Sprint 5 keeps the app to the existing three screens and keeps live stock trading disabled.

- Recommendations now parse qualitative values such as `Good`, `Medium`, `High`, `Low`, `Cautious`, and `Positive` without crashing.
- Portfolio dashboard refreshes append `PORTFOLIO_SNAPSHOTS`.
- Scheduled and manual analysis append `RESEARCH_RUNS`.
- `CRYPTO_ASSET_MASTER` is created for a future public-data crypto universe. The system does not insert dummy rankings when live public rankings are unavailable.
- Kraken and Coinbase adapters are prepared with safe not-configured/disabled states.
- Kraken required permissions: view balances, view open orders/trades, create/cancel orders. Do not grant withdrawal permission.
- Coinbase required permissions: view and trade. Do not grant transfer permission.
- Crypto auto-trade limits are separate from equity limits and default to smaller amounts.
- Command screen now includes an executive summary and exchange selector for All, Alpaca, Kraken, and Coinbase.

When `AI_TRADER_API_TOKEN` is set, the mobile app must send:

```text
Authorization: Bearer <token>
```

Test a hosted API:

```powershell
scripts/test_hosted_api.ps1 -BaseUrl https://trader-no0f.onrender.com -ApiToken YOUR_TOKEN
```

Build a phone APK that points to the hosted backend:

```powershell
cd mobile
npx eas build --platform android --profile hosted-preview
```

Before building, update `mobile/eas.json`:

```json
{
  "EXPO_PUBLIC_AI_TRADER_API_URL": "https://your-hosted-api.example.com",
  "EXPO_PUBLIC_AI_TRADER_API_TOKEN": "your-api-token"
}
```

Important: `EXPO_PUBLIC_*` values are embedded in the app bundle. For a personal app this is acceptable as a first hosted preview, but a stronger production release should add real user login and short-lived tokens.

Current hosted preview backend:

```text
https://trader-no0f.onrender.com
```

Mobile JavaScript changes are published with EAS Update to the `preview` and `hosted-preview` channels after verification. The installed hosted APK should pick up eligible OTA updates on restart.

## Foundation Sprint: Autonomous Investment Platform

The Foundation Sprint establishes Trader as a Founder-governed autonomous investment platform while keeping the existing three-screen app and paper/sandbox safety posture.

Governance documents:

- `governance/INVESTMENT_POLICY_STATEMENT.md`
- `governance/RISK_MANAGEMENT_POLICY.md`
- `governance/BROKER_EXECUTION_POLICY.md`
- `governance/AI_LEARNING_POLICY.md`
- `governance/INVESTMENT_UNIVERSE.md`

New SQLite policy and decision tables:

- `INVESTMENT_POLICIES`
- `RISK_POLICIES`
- `BROKER_POLICIES`
- `LEARNING_POLICIES`
- `CAPITAL_ALLOCATION_HISTORY`
- `DUE_DILIGENCE_ASSESSMENTS`
- `INVESTMENT_SCORES`
- `BROKER_DECISIONS`
- `EXECUTION_DECISIONS`

Crypto knowledge tables:

- `CRYPTO_MASTER`
- `CRYPTO_MARKET_DATA`
- `CRYPTO_DAILY_UPDATES`
- `CRYPTO_PROJECT_ANALYSIS`
- `CRYPTO_TOKENOMICS`
- `CRYPTO_ONCHAIN_METRICS`
- `CRYPTO_SENTIMENT`
- `CRYPTO_RISK`
- `CRYPTO_NEWS`
- `CRYPTO_BENCHMARK_ALIGNMENT`
- `CRYPTO_TRADING_HISTORY`

Execution rule:

```text
AI research -> due diligence -> investment score -> Investment Orchestrator -> broker adapter
```

The Investment Orchestrator is the only autonomous execution gate. It validates governance, due diligence, policy, risk, broker health, asset availability, market status, investment universe, and capital allocation before any paper order can be submitted.

Kraken credentials are read from Render environment variables only:

```text
KRAKEN_API_KEY
KRAKEN_PRIVATE_KEY
KRAKEN_TRADING_ENABLED=false
```

`KRAKEN_API_SECRET` is still accepted as a backward-compatible local alias, but `KRAKEN_PRIVATE_KEY` is the preferred Render name. Withdrawal permissions must never be granted.

## Multi-Broker Autonomous Platform

The Investment Orchestrator is now the central execution authority for all brokers. Each broker has independent auto-trading state stored in SQLite and controlled through the API/mobile app.

Broker-specific auto-trading flags:

```text
ALPACA_AUTO_TRADING=false
KRAKEN_AUTO_TRADING=false
COINBASE_AUTO_TRADING=false
BINANCE_AUTO_TRADING=false
IBKR_AUTO_TRADING=false
```

`AUTO_PAPER_TRADING` remains only as a backward-compatible fallback. New broker controls should use the broker-specific settings or the mobile Command Centre buttons.

New API endpoint:

```text
POST /broker-auto-trading
```

Body:

```json
{
  "broker": "kraken",
  "enabled": true
}
```

Broker runtime and audit tables:

- `BROKER_AUTO_TRADING_SETTINGS`
- `BROKER_RUNTIME_STATE`
- `BROKER_TRADE_HISTORY`
- `NOTIFICATION_EVENTS`
- `RECOMMENDATION_SETS`
- `CRYPTO_RESEARCH_SCORES`

The Command Centre now renders broker panels from backend data. Enabling auto trading for Kraken does not enable Alpaca, Coinbase, Binance, or Interactive Brokers.

Recommendation history is persisted in SQLite through `RECOMMENDATION_SETS`, and the Recommendations screen continues to read saved recommendations from SQLite on open. Recommendation cards are grouped by broker, collapsed by default, sorted by confidence, and filterable by broker, confidence, asset type, and status.

Kraken read integration:

- Validates credentials when present.
- Fetches balances.
- Fetches holdings from balances.
- Fetches open orders.
- Fetches closed orders and trade history.
- Fetches ticker prices through the public API helper.
- Shows authentication failure reasons instead of pretending credentials are absent.

Kraken controlled live micro-trading:

- `KRAKEN_AUTO_TRADING=true` enables Kraken as a broker-specific autonomous entry candidate.
- `KRAKEN_LIVE_TRADING_APPROVED=true` is a separate Founder approval switch required before Kraken can submit real orders.
- `KRAKEN_SUBMIT_REAL_ORDERS=false` keeps Kraken AddOrder in validation mode; set it to `true` only when the Founder wants real spot orders.
- `KRAKEN_MAX_ORDER_GBP=5` caps one Kraken order.
- `KRAKEN_MIN_ORDER_GBP=1` prevents invalid tiny orders.
- `KRAKEN_MAX_OPEN_TRADES=1` limits simultaneous Kraken entries.
- `KRAKEN_ALLOWED_PAIRS=XBTGBP,ETHGBP,SOLGBP` restricts trading pairs.

Mechanical live-execution seatbelts:

- duplicate order intent lock before broker submission,
- maximum order amount check,
- minimum order amount check,
- allowed pair check,
- open Kraken order count check,
- GBP balance check for buys,
- stop loss and take profit mandatory,
- broker submission confirmation,
- managed exit record after entry,
- `POST /monitor-managed-exits` checks open managed exits and submits the protective exit when stop loss or take profit is hit,
- notification events are queued for trade accepted, stop loss, take profit, and exit submission.

Disabling Kraken auto trading stops new entries. Existing managed exits remain eligible for protective exit submission.

## Install On Honor Magic V3

Android preview build:

```text
https://expo.dev/artifacts/eas/1LZ_09cZkatp7D8bR09MlBl1KnR6ZcKQN7M-CU7nnQc.apk
```

Before opening the app on the phone:

1. Keep the laptop and Honor Magic V3 on the same WiFi network.
2. Start the local API on the laptop:

```powershell
scripts/start_local_api.ps1
```

3. Confirm the phone-facing API URL is reachable from the laptop:

```powershell
Invoke-WebRequest -UseBasicParsing http://192.168.0.142:8765/status
```

4. Open the APK link on the Honor Magic V3 and allow Android to install from the browser if prompted.
5. Open AI Trader.

This preview build embeds:

```text
EXPO_PUBLIC_AI_TRADER_API_URL=http://192.168.0.142:8765
```

If the laptop IP changes, update `mobile/eas.json`, rebuild with `npx eas build --platform android --profile preview`, and install the new APK.

## Troubleshooting

- If plain `python` fails in a fresh terminal, activate the venv first: `. .\.venv\Scripts\Activate.ps1`.
- If VS Code does not select the venv, run `Python: Select Interpreter` and choose `.venv\Scripts\python.exe`.
- If PowerShell blocks activation, run: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.
- If the mobile app cannot reach the API from a physical phone, use the laptop LAN IP in `EXPO_PUBLIC_AI_TRADER_API_URL`.
- If Expo dependencies are missing, run `npm install` from `mobile/`.
