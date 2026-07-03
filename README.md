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

Auto execution:

- `POST /auto-execute-recommendations` submits only Paper Trading recommendations at or above 85% confidence.
- Auto execution still uses the existing Execution Engine and guardrails.
- Auto execution skips expired recommendations, already executed recommendations, and recommendations that did not pass guardrails.

Mobile controls:

- Trading controls are simplified to Start Trading and Stop Trading.
- The Recommendations screen has Refresh, Run New Analysis, and Auto Execute 85%+ controls.
- Market Intelligence shows theme definitions, drivers, and risks so related themes are easier to understand.

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

When `AI_TRADER_API_TOKEN` is set, the mobile app must send:

```text
Authorization: Bearer <token>
```

Test a hosted API:

```powershell
scripts/test_hosted_api.ps1 -BaseUrl https://ai-trader-api.onrender.com -ApiToken YOUR_TOKEN
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
