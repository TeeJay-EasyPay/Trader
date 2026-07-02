# Investment Intelligence Engine Schema

Date: 2026-07-02

Storage: `data/audit.sqlite3`

The Investment Intelligence Engine uses the existing local SQLite master database. It does not modify the Version 1.0 trading pipeline, execution engine, AI trading agent, or Trading Journal.

## COMPANY_MASTER

Canonical company profile table.

- `id` INTEGER PRIMARY KEY
- `company_name` TEXT NOT NULL
- `ticker` TEXT NOT NULL
- `exchange` TEXT NOT NULL
- `country` TEXT
- `sector` TEXT
- `industry` TEXT
- `business_summary` TEXT
- `investment_thesis` TEXT
- `reasons_we_like_it` TEXT
- `reasons_for_caution` TEXT
- `potential_risks` TEXT
- `primary_products` TEXT
- `website` TEXT
- `latest_news_summary` TEXT
- `last_updated` TEXT NOT NULL
- `source_urls` TEXT
- `created_at` TEXT NOT NULL
- `updated_at` TEXT NOT NULL

Unique key: `ticker, exchange`

## COMPANY_FINANCIALS

Financial snapshot table. Sprint 2 creates placeholder rows and leaves unverified financial metrics as `NULL`.

- `id` INTEGER PRIMARY KEY
- `company_id` INTEGER NOT NULL
- `financial_snapshot_date` TEXT NOT NULL
- `currency` TEXT
- `revenue` REAL
- `revenue_period` TEXT
- `net_income` REAL
- `market_cap` REAL
- `dividend_yield` REAL
- `debt_to_equity` REAL
- `notes` TEXT
- `source_url` TEXT
- `created_at` TEXT NOT NULL

## COMPANY_DAILY_UPDATES

Append-only company update log. Daily refreshes insert rows here instead of overwriting history.

- `id` INTEGER PRIMARY KEY
- `company_id` INTEGER NOT NULL
- `update_date` TEXT NOT NULL
- `update_type` TEXT NOT NULL
- `summary` TEXT
- `material_change` INTEGER NOT NULL DEFAULT 0
- `source_url` TEXT
- `payload_json` TEXT NOT NULL
- `created_at` TEXT NOT NULL

## INVESTMENT_WATCHLIST

Active watchlist and philosophy-fit table.

- `id` INTEGER PRIMARY KEY
- `company_id` INTEGER NOT NULL
- `current_watchlist_priority` TEXT
- `current_investment_philosophy_fit` TEXT
- `active` INTEGER NOT NULL DEFAULT 1
- `added_at` TEXT NOT NULL
- `last_reviewed` TEXT NOT NULL
- `notes` TEXT

Unique key: `company_id`

## MARKET_THEMES

Market theme knowledge table.

- `id` INTEGER PRIMARY KEY
- `theme` TEXT NOT NULL UNIQUE
- `current_outlook` TEXT
- `confidence` TEXT
- `summary` TEXT
- `key_drivers` TEXT
- `key_risks` TEXT
- `last_updated` TEXT NOT NULL
- `source_urls` TEXT
- `created_at` TEXT NOT NULL
- `updated_at` TEXT NOT NULL

## Daily Refresh

Command:

```powershell
$env:PYTHONPATH='src'
python -m ai_trader.cli intelligence-refresh --date 2026-07-03 --report
```

Local scheduled runner:

- `scripts/run_daily_intelligence_refresh.ps1`
- `scripts/register_daily_intelligence_refresh.ps1`

Optional local update file:

```powershell
python -m ai_trader.cli intelligence-refresh --updates data/intelligence_updates.json --report
```

Expected JSON shape:

```json
{
  "companies": {
    "ANTO:LSE": {
      "summary": "Material copper project update reviewed.",
      "material_change": true,
      "source_url": "https://example.com/source"
    }
  },
  "themes": {
    "Copper": {
      "current_outlook": "Structurally positive",
      "confidence": "High",
      "summary": "Updated theme summary.",
      "key_drivers": "Updated drivers.",
      "key_risks": "Updated risks."
    }
  }
}
```
