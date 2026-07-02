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
- `POST /pause-trading`
- `POST /resume-trading`
- `POST /stop-trading`
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

## Troubleshooting

- If plain `python` fails in a fresh terminal, activate the venv first: `. .\.venv\Scripts\Activate.ps1`.
- If VS Code does not select the venv, run `Python: Select Interpreter` and choose `.venv\Scripts\python.exe`.
- If PowerShell blocks activation, run: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.
- If the mobile app cannot reach the API from a physical phone, use the laptop LAN IP in `EXPO_PUBLIC_AI_TRADER_API_URL`.
- If Expo dependencies are missing, run `npm install` from `mobile/`.
