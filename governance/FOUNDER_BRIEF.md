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

- Live trading remains unapproved.
- Kraken order submission remains disabled pending final Founder-approved execution implementation.
- Broker-specific auto-trading defaults to false.
- Existing positions remain managed when auto trading is disabled; new autonomous entries stop.

## Founder Decision Points

- Approve or reject live/sandbox Kraken execution implementation.
- Confirm broker-specific policy thresholds for each broker.
- Confirm whether push notification delivery should use Expo notifications, email, or both.
- Review several days of 24/7 research and paper decisions before expanding broker permissions.
