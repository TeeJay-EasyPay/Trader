# Environment Variable Audit

Date: 2026-07-18

Scope: variables discovered from `config.py`, `render.yaml`, `.env.example`, `cloud.env.example`, `mobile/App.js`, and deployment documentation.

Secret values were not printed or copied into this document.

## High-Level Finding

Environment configuration is split across:

- local `.env`;
- `.env.example`;
- `cloud.env.example`;
- Render dashboard variables;
- `render.yaml`;
- Expo public variables compiled into the mobile app.

The most important production gap is not a single missing key. It is that Render is still configured in the blueprint for SQLite and a single web service, while the target autonomous topology requires shared Postgres plus worker and cron services.

## Core Backend Variables

| Variable | Purpose | Default | Required | Scope | If Missing |
|---|---|---:|---|---|---|
| `AI_TRADER_API_TOKEN` | Protects hosted API POST and protected GET endpoints. | None | Yes in hosted production | Render/API and Expo app must match | Hosted API becomes read-only or app receives unauthorized errors. |
| `AI_TRADER_API_HOST` | API bind host. | `127.0.0.1` | Optional local, required in Docker via Dockerfile | API | Hosted API may bind locally only if not set by Docker. |
| `PORT` | Render web service port. | `8765` fallback | Yes on Render | API | Render may not route correctly. |
| `AI_TRADER_DB_PATH` | SQLite file path. | `data/audit.sqlite3` | Required for SQLite production | API/worker/jobs | State may be written to ephemeral/local path. |
| `AI_TRADER_OUTPUT_DIR` | Reports and generated output path. | `data` | Required for persisted reports | API/jobs | Reports may not survive deploy/restart. |
| `AI_TRADER_TRADING_LOG_PATH` | Human-readable trading log path. | `governance/TRADING_LOG.md` | Required for hosted persistence | API/execution | Trading journal may be written into repo path instead of persistent disk. |
| `AI_TRADER_DATABASE_BACKEND` | Selects `sqlite` or `postgres`. | `postgres` if `DATABASE_URL` exists, else `sqlite` | Required for production autonomy | API/worker/jobs | Defaults may not match intended deployment. |
| `DATABASE_URL` | Postgres/Supabase connection string. | None | Required for shared production truth | API/worker/jobs | Always-On evidence remains SQLite. |
| `SUPABASE_DATABASE_URL` | Alternate Postgres URL name. | None | Optional alias | API/worker/jobs | Same as missing `DATABASE_URL` if no primary URL. |

Current repository evidence:

- `render.yaml` sets `AI_TRADER_DATABASE_BACKEND=sqlite`.
- `render.yaml` declares `DATABASE_URL` as a secret placeholder but does not set Postgres as active.
- Dockerfile correctly points SQLite output to `/data`.
- Local `.env` contains only a subset of production variables and does not include scheduler, broker-auto, Kraken or database backend variables in the inspected key list.

## Mobile Variables

| Variable | Purpose | Required | Scope | If Missing |
|---|---|---|---|---|
| `EXPO_PUBLIC_AI_TRADER_API_URL` | Hosted backend URL compiled into app/update. | Yes for hosted app | Expo/mobile | App may call wrong backend. |
| `EXPO_PUBLIC_AI_TRADER_API_TOKEN` | Public mobile command token. Must match `AI_TRADER_API_TOKEN`. | Yes for protected hosted endpoints | Expo/mobile | App shows unauthorized or missing token. |

Evidence from `mobile/App.js`:

- default API URL is `https://trader-no0f.onrender.com`;
- token is read from `EXPO_PUBLIC_AI_TRADER_API_TOKEN`;
- requests send `Authorization: Bearer <token>`;
- UI displays token readiness without exposing full token.

## Alpaca Variables

| Variable | Purpose | Default | Required | Service Dependency | If Missing |
|---|---|---:|---|---|---|
| `ALPACA_API_KEY` | Alpaca paper account auth. | None | Yes for Alpaca research/trading | API, worker, jobs | Equity market-data analysis is blocked. |
| `ALPACA_SECRET_KEY` | Alpaca paper account auth. | None | Yes | API, worker, jobs | Same as above. |
| `ALPACA_PAPER_BASE_URL` | Alpaca trading API URL. | `https://paper-api.alpaca.markets` | Yes | Alpaca adapter | Broker calls may target wrong endpoint. |
| `ALPACA_DATA_BASE_URL` | Alpaca market data URL. | `https://data.alpaca.markets` | Yes | Alpaca research | Market data unavailable. |
| `ALPACA_AUTO_TRADING` | Broker-specific auto trading switch. | legacy `AUTO_PAPER_TRADING` fallback | Required for auto entries | API/auto executor | No autonomous Alpaca entries. |

Current repository evidence:

- `render.yaml` declares Alpaca credentials as secret variables.
- `render.yaml` sets `ALPACA_AUTO_TRADING=false` by default.

## Kraken Variables

| Variable | Purpose | Default | Required | If Missing |
|---|---|---:|---|---|
| `KRAKEN_API_KEY` | Kraken API key. | None | Yes for Kraken account/broker activity | Kraken connection unavailable. |
| `KRAKEN_PRIVATE_KEY` | Kraken API private key. | None | Yes | Kraken auth unavailable. |
| `KRAKEN_API_SECRET` | Alternate/compatibility secret variable. | None | Optional alias depending adapter path | Kraken auth may fail if expected secret name absent. |
| `KRAKEN_SANDBOX_MODE` | Sandbox/dry-run guard. | `true` in examples | Required safety flag | Real orders remain blocked if true. |
| `KRAKEN_AUTO_TRADING` | Broker auto-trading switch. | `KRAKEN_TRADING_ENABLED` fallback | Required for auto entries | Auto executor skips Kraken. |
| `KRAKEN_TRADING_ENABLED` | Broker trading permission. | `false` | Required for real orders | Real orders blocked. |
| `KRAKEN_LIVE_TRADING_APPROVED` | Founder/governance live approval. | `false` | Required for real orders | Real orders blocked. |
| `KRAKEN_SUBMIT_REAL_ORDERS` | Final mechanical real-order switch. | `false` | Required for real orders | Real orders blocked. |
| `KRAKEN_TRADING_ALLOCATION_GBP` | Ring-fenced capital allocation. | `100` | Required for live micro sizing | Position sizing may be blocked or too broad. |
| `KRAKEN_MAX_ORDER_GBP` | Maximum notional per order. | `5` | Required | Orders capped or blocked. |
| `KRAKEN_MIN_ORDER_GBP` | Minimum notional per order. | `1` | Required | Small orders may be rejected. |
| `KRAKEN_MAX_OPEN_TRADES` | AI-managed open trade limit. | `1` | Required | Capacity may block new entries. |
| `KRAKEN_ALLOWED_PAIRS` | Approved pairs. | `XBTGBP,ETHGBP,SOLGBP` | Required | Pairs outside list rejected. |

Current repository evidence:

- `render.yaml` declares Kraken credentials.
- `render.yaml` defaults all real-order switches to safe/disabled values.
- Strategy maturity defaults also block `micro_live` unless explicitly promoted.

## Trading And Guardrail Variables

| Variable | Purpose | Default | If Missing |
|---|---|---:|---|
| `AUTO_PAPER_TRADING` | Legacy global auto switch. | `false` | No global auto default. |
| `AUTO_TRADE_MIN_CONFIDENCE` | Auto execution confidence threshold. | `0.85` | Defaults to 85%. |
| `AUTO_TRADE_MIN_PHILOSOPHY_FIT` | Philosophy fit threshold. | `0.85` | Defaults to 85%. |
| `MAX_AUTO_TRADE_AMOUNT` | Stock max order notional. | `25` | Defaults to small paper trade size. |
| `DEFAULT_STOP_LOSS_PCT` | Stock default stop. | `0.03` | Defaults to 3%. |
| `MAX_STOP_LOSS_PCT` | Stock max stop distance. | `0.05` | Defaults to 5%. |
| `CRYPTO_MAX_AUTO_TRADE_AMOUNT` | Crypto max order notional. | `10` | Defaults to small crypto trade size. |
| `CRYPTO_DEFAULT_STOP_LOSS_PCT` | Crypto default stop. | `0.02` | Defaults to 2%. |
| `CRYPTO_MAX_STOP_LOSS_PCT` | Crypto max stop distance. | `0.05` | Defaults to 5%. |
| `PAPER_TRADING_ONLY` | Global paper/safety guardrail. | `true` | Defaults to paper-only. |
| `ALLOW_SHORT_SELLING` | Short-selling permission. | `false` | Shorting blocked. |
| `MIN_CONFIDENCE_SCORE` | Proposal guardrail threshold. | `0.65` in code, `0.85` in Render | Lower code default if not set. |
| `MAX_RISK_PER_TRADE_PCT` | Per-trade account risk cap. | `0.01` | Defaults to 1%. |
| `MAX_DAILY_LOSS_PCT` | Daily loss stop. | `0.03` | Defaults to 3%. |
| `MAX_OPEN_POSITIONS` | Open position cap. | `3` | Defaults to 3. |

## Scheduler Variables

| Variable | Purpose | Default | If Missing |
|---|---|---:|---|
| `RESEARCH_SCHEDULER_ENABLED` | Enables API in-process research scheduler. | `false` in code and examples, `true` in Render blueprint | Research scheduler does not auto-run in API process. |
| `RESEARCH_SCHEDULER_INTERVAL_MINUTES` | Research interval. | `60` | Hourly default. |
| `RESEARCH_SCHEDULER_LIMIT` | Number of equity symbols per run. | `30` | 30 symbol default. |
| `AUTO_EXECUTION_INTERVAL_SECONDS` | Auto executor interval. | `60` | 60 second default. |

Important distinction:

These variables affect API in-process threads. They do not create Render worker services or Render cron jobs.

## OpenAI Variables

| Variable | Purpose | Default | If Missing |
|---|---|---:|---|
| `OPENAI_API_KEY` | AI proposal analysis and Ask AI explanations. | None | App falls back to deterministic/local explanations or cannot generate AI-enhanced analysis. |
| `OPENAI_MODEL` | Model name. | `gpt-4.1-mini` | Default model is used. |

## Render Management Variables

| Variable | Purpose | Current Use |
|---|---|---|
| `RENDER_API_KEY` / `RENDER_API_TOKEN` | Render API automation. | Loaded in settings, but no evidence found that the app safely updates Render env at runtime. |
| `RENDER_SERVICE_ID` | Render service target. | Loaded in settings for future automation. |

## Environment Root Cause

The strongest environment/configuration root causes are:

1. `AI_TRADER_DATABASE_BACKEND=sqlite` in `render.yaml`.
2. Worker/cron services intentionally absent until Postgres is active.
3. Broker auto trading defaults are disabled in `render.yaml`.
4. Kraken live switches default to disabled in `render.yaml`.
5. Mobile app requires an Expo public token matching Render's API token.
6. Runtime Render values could not be fully verified from this environment.

