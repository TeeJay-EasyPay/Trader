# Founder Release Brief - Autonomous Trading Readiness Sprint

Date: 2026-07-07

## Executive Summary

AI Trader is now ready for a controlled Kraken micro-live validation sprint, provided the Founder explicitly enables the live switches and watches the first trades.

The important shift is that Kraken trading is no longer just a broker adapter. The system can research crypto, create a recommendation, pass it through due diligence and risk, submit through the Investment Orchestrator, track exits, and record learning data.

## What You Should Expect In The App

- Recommendations should persist after reopening the app.
- Recommendations are grouped by broker and collapsed by default.
- Intelligence company links open the matching recommendation card.
- Kraken and Alpaca have independent Enable Auto Trading buttons.
- The global Emergency Stop All button stops new entries across all brokers.
- Existing managed exits continue even after Emergency Stop All.
- Notifications appear in the Command Centre notification section.

## First Live Kraken Test Position

Recommended first-run settings:

- `KRAKEN_AUTO_TRADING=true`
- `KRAKEN_LIVE_TRADING_APPROVED=true`
- `KRAKEN_SUBMIT_REAL_ORDERS=true` only when you are ready to observe a real order.
- `KRAKEN_MAX_ORDER_GBP=5` or less.
- `KRAKEN_MAX_OPEN_TRADES=1`
- `KRAKEN_ALLOWED_PAIRS=XBTGBP` or one selected pair only.

## Release Decision

Approved for controlled micro-live validation.

Not approved for unattended scale-up until live push delivery, hosted uptime, and several completed managed exits have been observed.

