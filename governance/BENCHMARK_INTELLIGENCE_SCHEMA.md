# Benchmark Trader Intelligence Schema

Date: 2026-07-02

Storage: `data/audit.sqlite3`

Benchmark intelligence is local-only and uses public information only. It does not redesign the trading engine, execution engine, guardrails, or SQLite storage.

## BENCHMARK_TRADERS

- `trader_id` INTEGER PRIMARY KEY
- `trader_name` TEXT NOT NULL
- `platform` TEXT
- `region` TEXT
- `strategy_style` TEXT
- `markets_traded` TEXT
- `risk_rating` TEXT
- `performance_notes` TEXT
- `drawdown_notes` TEXT
- `consistency_score` REAL
- `why_monitored` TEXT
- `source_urls` TEXT
- `active` INTEGER NOT NULL DEFAULT 1
- `created_date` TEXT NOT NULL
- `last_updated` TEXT NOT NULL

Unique key: `trader_name, platform`

## BENCHMARK_DAILY_RESEARCH

Append-only benchmark research log.

- `id` INTEGER PRIMARY KEY
- `research_date` TEXT NOT NULL
- `trader_id` INTEGER NOT NULL
- `source` TEXT
- `observed_trade_or_portfolio_change` TEXT
- `ai_interpretation` TEXT
- `risk_lesson` TEXT
- `market_lesson` TEXT
- `related_company` TEXT
- `related_sector` TEXT
- `related_theme` TEXT
- `confidence` TEXT
- `impact_on_our_view` TEXT
- `created_date` TEXT NOT NULL

## Data Rules

- Use only publicly available information.
- Do not fabricate private trades, performance, drawdowns, or consistency scores.
- Leave unavailable information as `NULL` in SQLite.
- Use this screen for learning only; do not copy benchmark trades automatically.
