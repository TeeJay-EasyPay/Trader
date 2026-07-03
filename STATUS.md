# AI Trading Assistant V1 Status

Date: 2026-07-02

Status: Version 1 validation sprint passed; Sprint 2 Investment Intelligence Engine initialized; Sprint 3 mobile/API foundation added; Sprint 3.1 developer experience configured; hosted backend path added; Sprint 3.2 app intelligence refinements added

## Working

- Python runtime installed and verified: Python 3.12.10.
- Required dependency installed: `tzdata`.
- Unit tests pass: 14/14.
- `.env` loading works.
- Alpaca Paper Trading connection works.
- Alpaca account retrieval works.
- Alpaca position retrieval works.
- OpenAI API key works with `OPENAI_MODEL=gpt-4.1-mini`.
- AI proposal generation works with configured guardrail constraints.
- Execution Engine validates proposals independently before submission.
- Alpaca Paper Trading bracket order submission works.
- SQLite audit logging works for the real proposal and execution lifecycle.
- Trading Journal append works for the real proposal and execution lifecycle.
- Founder Brief generation works.
- Investment Intelligence Engine schema works locally in SQLite.
- Initial curated investment watchlist seeded.
- Market themes seeded.
- Daily intelligence refresh appends company updates without overwriting historical rows.
- Knowledge Engine Report generated.
- Benchmark trader intelligence schema added.
- Benchmark trader seed research added using public-information-only rules.
- Local API added for mobile app reads and guarded commands.
- Expo mobile app added with three screens.
- Local `.venv` created and verified.
- VS Code interpreter pinned to `.venv\Scripts\python.exe`.
- One-command startup script added.
- Read-only browser-based SQLite viewer added.
- Developer Dashboard added.
- Hosted backend deployment path added.
- API token authorization added for hosted use.
- Mobile app can send a bearer token to hosted API.
- Docker and Render blueprint added.
- Recommendations now expose generated time, expiry time, and Fresh/Stale/Expired status.
- Expired recommendations are blocked before execution.
- Paper-only auto execution added for eligible recommendations at or above 85% confidence.
- Mobile recommendations screen now supports Refresh, Run New Analysis, and Auto Execute 85%+.
- Command Centre now shows richer recent transaction and recommendation summary data.
- Mobile controls simplified to Start Trading and Stop Trading.
- Market Intelligence now shows theme definitions, drivers, and risks.
- Expo OTA update published to the `preview` branch.

## Validation Result

The resumed Validation Sprint completed one end-to-end paper trade on 2026-07-02.

- Symbol: AAPL
- Proposal ID: `581de766-62ff-4d16-9e7e-6b27407c29b0`
- Alpaca parent order ID: `94de407a-8a6d-42ab-a991-de938ef27e6e`
- Quantity: 333 shares
- Alpaca confirmation: parent paper buy order filled; bracket exit orders present.
- Proposal file: `data/validation_proposals_2026-07-02.json`
- Founder Brief: `data/founder_briefing_2026-07-02.md`

## Notes

During the resumed run, the first AI proposal was correctly rejected because the prompt did not state the configured guardrail thresholds and decimal risk format. The fix was limited to passing guardrail constraints into the OpenAI proposal prompt. The next proposal passed guardrails and executed successfully in Alpaca Paper Trading.

## Sprint 2 Investment Intelligence Engine

Sprint 2 created a local SQLite-backed knowledge base for long-term investment research. Version 1.0 trading remains frozen and unchanged.

- Tables created: `COMPANY_MASTER`, `COMPANY_FINANCIALS`, `COMPANY_DAILY_UPDATES`, `INVESTMENT_WATCHLIST`, `MARKET_THEMES`.
- Initial watchlist: 31 companies.
- Market themes: 10.
- Database: `data/audit.sqlite3`.
- Schema document: `governance/INVESTMENT_INTELLIGENCE_SCHEMA.md`.
- Knowledge Engine Report: `governance/KNOWLEDGE_ENGINE_REPORT.md`.
- Generated data report: `data/INVESTMENT_INTELLIGENCE_ENGINE_REPORT.md`.
- Tests: 6/6 passing.

## Sprint 3 Mobile App + Benchmark Intelligence

Sprint 3 keeps Version 1.0 trading frozen and continues using local SQLite.

- New tables: `BENCHMARK_TRADERS`, `BENCHMARK_DAILY_RESEARCH`.
- Benchmark schema document: `governance/BENCHMARK_INTELLIGENCE_SCHEMA.md`.
- Benchmark brief output: `data/BENCHMARK_TRADER_INTELLIGENCE_BRIEF.md` when `benchmark-init --report` or `serve-api` runs.
- Local API module: `src/ai_trader/api.py`.
- CLI API command: `python -m ai_trader.cli serve-api --host 127.0.0.1 --port 8765`.
- Mobile app: `mobile/App.js`.
- Mobile screens: Trading Command Centre, AI Recommendations, Market Intelligence.
- Missing or unavailable data is surfaced as `Not available` rather than fabricated values.
- `approve-and-execute` reconstructs stored proposals and sends them through the existing Execution Engine guardrails.
- Current test suite: 14/14 passing inside `.venv`.

## Sprint 3.1 Developer Experience

Root cause of the VS Code `python` issue:

- `python` resolved to the Windows Store app execution alias at `C:\Users\t_jeh\AppData\Local\Microsoft\WindowsApps\python.exe`.
- That shim failed with: "A specified logon session does not exist. It may already have been terminated."
- The working interpreter is Python 3.12.10.
- The project now uses `.venv\Scripts\python.exe` through VS Code settings and project scripts.

Developer workflow:

- One-command startup: `.\start_project.ps1`.
- Local API helper: `scripts/start_local_api.ps1`.
- Mobile helper: `scripts/start_mobile_app.ps1`.
- Read-only database browser: `scripts/browse_database.ps1`.
- Developer Dashboard: `developer_dashboard.html` and `http://127.0.0.1:8765/developer-dashboard`.
- Tests: 14/14 passing inside `.venv`.

## Sprint 3.2 Mobile Trading Usability

Sprint 3.2 keeps the trading engine, execution engine, knowledge engine, mobile app structure, and SQLite storage intact.

- Recommendation freshness added:
  - Fresh/Stale/Expired status.
  - Generated and expiry timestamps.
  - Execution blocked for expired recommendations.
- Auto execution added for Paper Trading only:
  - Minimum confidence: 85%.
  - Existing Execution Engine guardrails still enforce execution.
  - Expired, duplicate, and guardrail-failed recommendations are skipped.
- API controls added:
  - `POST /start-trading`
  - `POST /auto-execute-recommendations`
- Mobile app updates:
  - Recommendations screen has Refresh, Run New Analysis, and Auto Execute 85%+.
  - Trading Command Centre shows recent transactions and recommendation counts.
  - Pause/Resume/Stop button cluster replaced by Start Trading and Stop Trading.
  - Market Intelligence shows theme definitions, key drivers, and key risks.
- Tests: 14/14 passing inside `.venv`.

## Sprint 3.2 OTA Update

An EAS Update was published for the mobile JavaScript changes.

- Branch: `preview`.
- Runtime version: `1.0.0`.
- Update group ID: `0727fd0a-4216-413c-affa-5c712cbc1155`.
- Android update ID: `019f2473-739d-78e5-849e-99092758dd78`.
- EAS dashboard: `https://expo.dev/accounts/nexuspay/projects/ai-trader-mobile/updates/0727fd0a-4216-413c-affa-5c712cbc1155`.

During the update, EAS installed and configured `expo-updates`:

- `expo-updates`: `~0.25.28`.
- `updates.url`: `https://u.expo.dev/58ca35af-2cf4-44a0-8da4-7f02563b635f`.
- `runtimeVersion.policy`: `appVersion`.

Important: the APK already installed before this configuration may not receive OTA updates. Builds created after this configuration are eligible for EAS Updates.

Fresh APK build after OTA channel configuration:

- Build ID: `d5ff21b3-6685-4940-a2d4-550cd0d9e984`.
- Preview channel: `preview`.
- APK: `https://expo.dev/artifacts/eas/c3aEW5gWWhVHVim0Mk2fwTGnRl7aCKosQkpYnC6n9VQ.apk`.
- Purpose: replace the earlier APK that did not have `expo-updates`/preview channel configured.

Follow-up OTA for mobile usability fixes:

- Update group ID: `c4e78a76-6233-48aa-a2ee-85ce3223007e`.
- Android update ID: `019f2657-bc70-7c6f-9e33-91ef6e217fc1`.
- EAS dashboard: `https://expo.dev/accounts/nexuspay/projects/ai-trader-mobile/updates/c4e78a76-6233-48aa-a2ee-85ce3223007e`.
- Added pull-to-refresh on all three app screens.
- Reformatted recommendation confidence from decimals to percentages.
- Reformatted timestamps into readable local date/time text.
- Added clearer auto-trade eligibility reason text.
- Added friendlier recent transaction wording.
- Restarted the local API after backend endpoint updates.

Hosted APK build:

- Build ID: `7e6b53a3-d492-4594-af36-4e56199878d4`.
- Channel: `hosted-preview`.
- APK: `https://expo.dev/artifacts/eas/s2G1DWe4aWyNiBCH7S1bJgXYmhoq8f8gSE3D6UQfe5U.apk`.
- Backend URL baked into build/update: `https://ai-trader-api.onrender.com`.
- Hosted OTA update group ID: `f9a4c794-8305-47d2-83a1-99fb5b777057`.
- Hosted Android update ID: `019f2669-3a99-765d-99f1-d747aff4f9db`.
- Hosted EAS dashboard: `https://expo.dev/accounts/nexuspay/projects/ai-trader-mobile/updates/f9a4c794-8305-47d2-83a1-99fb5b777057`.
- Current hosted backend check: `https://ai-trader-api.onrender.com/healthz` is not reachable yet, so hosted data will not load until the backend service is deployed.

## Hosted Backend Path

Option B has been scaffolded so the phone app can point to an always-on backend instead of the laptop.

- Dockerfile: `Dockerfile`.
- Render blueprint: `render.yaml`.
- Environment template: `cloud.env.example`.
- Hosted API test helper: `scripts/test_hosted_api.ps1`.
- Mobile EAS profile: `hosted-preview`.
- Health check: `GET /healthz`.
- Auth: optional `AI_TRADER_API_TOKEN` checked through `Authorization: Bearer <token>` or `X-API-Key`.

The next release build should use a real hosted API URL and API token in `mobile/eas.json`.

Local token-auth smoke test passed:

- `/healthz`: 200 without token.
- `/status`: 401 without token.
- `/status`: 200 with bearer token.
