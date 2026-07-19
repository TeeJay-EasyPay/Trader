# Founder Activity Screen Guide

Date: 2026-07-19

## Loading Behaviour

The mobile app should show the main operating picture before every optional panel has finished loading.

Refresh is intentionally split into two phases:

- primary evidence: operations health, activity summary, why-no-trade evidence, portfolio, and recommendations;
- secondary evidence: full status, full autonomous activity timeline, Founder brief, benchmark brief, intelligence themes, company intelligence, notifications, performance attribution, and daily learning.

The global spinner should represent the primary evidence load only. Secondary cards may update shortly afterwards in the background. This prevents a slow optional endpoint from making the full app appear frozen.

If the Render web service is on a plan that spins down when idle, the first request after inactivity can still be delayed while Render wakes the API. That is infrastructure latency, not evidence that the worker or trading engine is stopped.

If the hosted `/status` or `/autonomous-activity` endpoint is slow, the app should show a lightweight operations view instead of blocking the whole screen. That lightweight view is built from `/operations-health`, `/activity/summary`, and `/activity/why-no-trade`. Activity evidence is persisted separately and may still prove that AI Trader is alive even while the large dashboard status payload or full activity timeline is delayed.

The full Activity timeline is allowed to hydrate after the Dashboard is usable. Until it arrives, the Activity screen may say that the complete timeline is still hydrating, but worker health, database backend, job evidence, and no-trade summaries should still be visible when those lightweight endpoints respond.

## What The Screen Shows

The Activity screen shows what AI Trader actually recorded while you were not watching.

It answers:

- Is AI Trader alive?
- Did research run?
- Did it find opportunities?
- Why did it not trade?
- Did it submit orders?
- Did brokers respond?
- Did learning or reporting happen?
- Does anything need your attention?

## How To Read The Top Card

The first card is the operating state.

- `OPERATING NORMALLY` means worker heartbeat and recent persisted activity are visible.
- `OPERATING WITH WARNINGS` means AI Trader is working, but something needs attention.
- `PARTIALLY OPERATING` means some subsystems are current and others are stale or missing.
- `BLOCKED` means a known blocker is preventing autonomous operation.
- `NOT OPERATING` means the worker or key autonomous evidence is not proven.
- `STATUS UNKNOWN` means the selected time period has no enough evidence to prove activity.

## Last 24 Hours

This card groups activity into:

- Research;
- Decisions;
- Execution;
- Operations.

Zeros are not shown as success. If zero orders were submitted, the Why No Trade section explains why.

## Timeline

The timeline shows newest activity first.

You can filter by:

- All;
- Research;
- Decisions;
- Risk;
- Execution;
- Brokers;
- Reconciliation;
- Learning;
- Reports;
- Incidents;
- System.

You can also switch between all events, important events, and Founder-action-required events.

## Why No Trade

This is the key section when nothing has traded.

It separates:

1. No opportunity found.
2. Opportunity found but rejected.
3. Opportunity approved or candidate blocked.
4. Approved but not submitted.
5. Order submitted or trade completed.

This prevents a quiet day from being mistaken for a broken system.

## Broker Activity

Alpaca and Kraken are shown separately.

Each broker shows:

- connection;
- account mode;
- last poll;
- polling freshness;
- autonomous execution state;
- orders and fills;
- open positions;
- reconciliation status;
- current blocker.

## Founder Attention

This section only shows items needing action.

Examples:

- worker heartbeat stale;
- durable database not proven;
- broker disconnected;
- open incident;
- Alpaca paper auto-trading disabled.

If no action is required, it says so plainly.
