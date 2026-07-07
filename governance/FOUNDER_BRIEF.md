# Founder Brief - Multi-Broker Autonomous Platform

Date: 2026-07-04

## Executive Summary

AI Trader has moved from a single-broker paper trading prototype toward a governed multi-broker autonomous investment platform.

The Investment Orchestrator is now the central execution authority. Brokers operate independently under the same Founder-approved Investment Policy Statement and risk controls.

## What Changed

- Broker-specific auto-trading controls were added for Alpaca, Kraken, Coinbase, Binance, and Interactive Brokers.
- Enabling Kraken auto trading no longer affects Alpaca, and enabling Alpaca no longer affects Kraken.
- The Command Centre now displays broker panels for each broker from backend runtime state.
- Recommendation history is persisted in SQLite recommendation sets.
- Recommendations are grouped by broker, collapsed by default, sorted by confidence, and filterable.
- Kraken now validates credentials and reads balances, holdings, open orders, closed orders, trade history, and prices.
- Continuous research state is tracked per broker, including current asset, current stage, queue, freshness, reviewed assets, and last recommendation.
- Notification events are queued in SQLite for future push delivery.

## Current Safety Position

- Kraken live order submission is implemented but remains behind explicit Founder approval switches.
- `KRAKEN_LIVE_TRADING_APPROVED=false` and `KRAKEN_SUBMIT_REAL_ORDERS=false` keep Kraken from placing real orders until changed in Render.
- Broker-specific auto-trading defaults to false.
- Existing positions remain managed when auto trading is disabled; new autonomous entries stop.
- Kraken micro-trading has mechanical protections: duplicate lock, max order size, min order size, max open trades, allowed pair list, balance check, mandatory stop/take-profit, broker confirmation, and managed exit tracking.

## Founder Decision Points

- Approve or reject live/sandbox Kraken execution implementation.
- Confirm broker-specific policy thresholds for each broker.
- Confirm whether push notification delivery should use Expo notifications, email, or both.
- Review several days of 24/7 research and paper decisions before expanding broker permissions.

## 2026-07-07 Release Manager Update

Codex completed an independent release review of the Autonomous Trading Readiness Sprint.

Release position: approved for controlled Kraken micro-live validation, not unattended scale-up.

New review artefacts:

- `governance/ENGINEERING_REVIEW_REPORT.md`
- `governance/ARCHITECTURE_ASSESSMENT.md`
- `governance/SAFETY_ASSESSMENT.md`
- `governance/REMAINING_RISKS.md`
- `governance/FOUNDER_RELEASE_BRIEF.md`

Verified locally:

- Python compile check passed.
- Python unit test suite passed: 66/66.
- Expo project health check passed: 17/17.
