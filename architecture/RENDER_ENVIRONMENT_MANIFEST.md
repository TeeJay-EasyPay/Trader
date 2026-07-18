# Render Environment Manifest

Date: 2026-07-18

Secrets are intentionally not documented here.

## Platform

| Variable | Required | Purpose |
|---|---:|---|
| `AI_TRADER_API_TOKEN` | Yes | Authenticates protected hosted API commands. |
| `AI_TRADER_PROCESS_ROLE` | Yes | Identifies hosted process role. Use `render` in Render. |
| `AI_TRADER_DISABLE_API_BACKGROUND_WORKERS` | Yes | Prevents duplicate API-owned loops when worker/cron own scheduling. |
| `AI_TRADER_REQUIRE_POSTGRES_IN_HOSTED` | Yes | Forces hosted fail-close if Postgres is not configured. |
| `AI_TRADER_DATABASE_BACKEND` | Yes | Must be `postgres` for production. |
| `DATABASE_URL` | Yes | Supabase/Postgres connection string. |
| `SUPABASE_DATABASE_URL` | Optional | Alternate Postgres connection string if `DATABASE_URL` is not used. |

## Alpaca

| Variable | Required | Purpose |
|---|---:|---|
| `ALPACA_API_KEY` | Yes | Alpaca API key. |
| `ALPACA_SECRET_KEY` | Yes | Alpaca API secret. |
| `ALPACA_PAPER_BASE_URL` | Yes | Alpaca paper trading endpoint. |
| `ALPACA_DATA_BASE_URL` | Yes | Alpaca market data endpoint. |
| `ALPACA_AUTO_TRADING` | Optional | Enables paper auto-trading only when all gates pass. |

## Kraken

| Variable | Required | Purpose |
|---|---:|---|
| `KRAKEN_API_KEY` | Required for Kraken | Kraken API key. |
| `KRAKEN_PRIVATE_KEY` | Required for Kraken | Kraken private key. |
| `KRAKEN_AUTO_TRADING` | Optional | Enables Kraken auto-trading permission gate. |
| `KRAKEN_TRADING_ENABLED` | Required for live Kraken | Broker trading permission gate. |
| `KRAKEN_LIVE_TRADING_APPROVED` | Required for live Kraken | Founder approval gate. |
| `KRAKEN_SUBMIT_REAL_ORDERS` | Required for live Kraken | Final real-order submission gate. |
| `KRAKEN_TRADING_ALLOCATION_GBP` | Required for live Kraken | Capital allocation seatbelt. |
| `KRAKEN_MAX_ORDER_GBP` | Required for live Kraken | Per-order cap. |
| `KRAKEN_MIN_ORDER_GBP` | Required for live Kraken | Minimum order value. |
| `KRAKEN_MAX_OPEN_TRADES` | Required for live Kraken | AI-managed open-trade cap. |
| `KRAKEN_ALLOWED_PAIRS` | Required for live Kraken | Allowed crypto pairs. |

## AI

| Variable | Required | Purpose |
|---|---:|---|
| `OPENAI_API_KEY` | Required for Founder AI/OpenAI proposal analysis | Read-only Ask AI and AI evidence explanations. |
| `OPENAI_MODEL` | Optional | Model name. Defaults to `gpt-4.1-mini`. |

## Scheduling

| Variable | Required | Purpose |
|---|---:|---|
| `RESEARCH_SCHEDULER_ENABLED` | Yes | Should be `false` in Render API when worker/cron owns scheduling. |
| `RESEARCH_SCHEDULER_INTERVAL_MINUTES` | Optional | Local scheduler cadence. |
| `RESEARCH_SCHEDULER_LIMIT` | Optional | Research asset limit. |
| `AUTO_EXECUTION_INTERVAL_SECONDS` | Optional | Worker auto-execution cadence. |

## Guardrails

| Variable | Required | Purpose |
|---|---:|---|
| `PAPER_TRADING_ONLY` | Yes | Global paper/live safety mode. |
| `MIN_CONFIDENCE_SCORE` | Yes | Minimum confidence threshold. |
| `MAX_RISK_PER_TRADE_PCT` | Yes | Per-trade account risk cap. |
| `MAX_DAILY_LOSS_PCT` | Yes | Daily loss guardrail. |
| `MAX_OPEN_POSITIONS` | Yes | Position-count guardrail. |

## Production Defaults

For Render production:

```text
AI_TRADER_DATABASE_BACKEND=postgres
AI_TRADER_PROCESS_ROLE=render
AI_TRADER_DISABLE_API_BACKGROUND_WORKERS=true
AI_TRADER_REQUIRE_POSTGRES_IN_HOSTED=true
RESEARCH_SCHEDULER_ENABLED=false
```
