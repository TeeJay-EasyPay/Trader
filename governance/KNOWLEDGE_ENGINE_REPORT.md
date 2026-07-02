# Knowledge Engine Report

Date: 2026-07-02

Status: Sprint 2 initial build complete

## Scope

The Investment Intelligence Engine is now a local SQLite-backed knowledge base for long-term investment research. It is separate from the Version 1.0 trading pipeline, which remains frozen.

## Delivered

- Created `COMPANY_MASTER`.
- Created `COMPANY_FINANCIALS`.
- Created `COMPANY_DAILY_UPDATES`.
- Created `INVESTMENT_WATCHLIST`.
- Created `MARKET_THEMES`.
- Added a curated initial watchlist of 31 companies.
- Added 10 market themes.
- Added append-only daily refresh logic.
- Added CLI commands for initialization, refresh, and report generation.
- Added a Windows PowerShell helper for scheduled daily refreshes.
- Generated machine-facing report: `data/INVESTMENT_INTELLIGENCE_ENGINE_REPORT.md`.

## Watchlist Shape

The initial list is weighted toward the requested sectors:

- Precious metals, gold, silver, copper, and mining
- Infrastructure and construction
- Utilities and clean energy
- Healthcare
- Airlines
- Sports

The list prioritises the United Kingdom, Europe, Asia, and Africa. North American companies were intentionally avoided in the initial seed.

## Daily Update Process

The daily refresh process reviews all active watchlist companies and all market themes. It appends company review rows into `COMPANY_DAILY_UPDATES` and updates the current company/theme profile timestamps.

Historical company update rows are not overwritten.

## Evidence

Initial database counts:

- `COMPANY_MASTER`: 31
- `COMPANY_FINANCIALS`: 31
- `COMPANY_DAILY_UPDATES`: 31
- `INVESTMENT_WATCHLIST`: 31
- `MARKET_THEMES`: 10

Validation:

- Unit tests: 6 passed.
- New intelligence tests verify watchlist/theme seeding and append-only daily refresh rows.

## Notes

Financial metrics were intentionally left as `NULL` placeholders where not verified during this sprint. This follows the instruction to avoid fabricating data.

The next sprint can build the mobile Founder Dashboard and Recommendation screens directly against the SQLite tables created here.
