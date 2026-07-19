# Autonomous Activity API

Date: 2026-07-19

All endpoints require the normal Founder API token, using either:

- `Authorization: Bearer <token>`
- `X-API-Key: <token>`

`/healthz` remains public. Activity endpoints are protected.

## Combined Payload

```text
GET /autonomous-activity?period=24h&limit=80
```

Query parameters:

- `period`: `1h`, `24h`, `7d`, or `30d`
- `category`: optional category filter
- `severity`: optional severity filter
- `important_only`: `true` or `false`
- `founder_action_required`: `true` or `false`
- `limit`: timeline item limit

Returns:

- `status`
- `summary`
- `timeline`
- `why_no_trade`
- `broker_activity`
- `founder_attention`
- `latest_completed_actions`
- `truthfulness`

## Current Autonomous Status

```text
GET /activity/status?period=24h
```

Returns:

- overall operating state;
- plain-English reason;
- last meaningful activity;
- worker status;
- scheduler status;
- database status;
- last successful research run;
- last broker poll;
- last report generated;
- unresolved incident count.

## Activity Summary

```text
GET /activity/summary?period=24h
```

Returns period totals grouped by:

- Research;
- Decisions;
- Execution;
- Operations.

## Activity Timeline

```text
GET /activity/timeline?period=24h&category=Research&limit=50
```

Supports:

- newest-first ordering;
- stable ordering by timestamp and activity ID;
- category filtering;
- severity filtering;
- important-only filtering;
- Founder-action-required filtering.

## Why No Trade

```text
GET /activity/why-no-trade?period=24h
```

Returns:

- no-trade state;
- plain-English conclusion;
- funnel counts;
- top rejection or block reasons.

The no-trade state distinguishes:

- `research_did_not_run`
- `no_opportunity_found`
- `opportunity_found_but_rejected`
- `approved_or_candidate_blocked`
- `approved_but_not_submitted`
- `order_submitted_or_trade_completed`

## Broker Activity

```text
GET /activity/brokers?period=24h
```

Returns safe Alpaca and Kraken operational status:

- connection;
- account mode;
- last poll;
- freshness;
- auto execution state;
- orders submitted;
- fills received;
- open positions;
- reconciliation status;
- latest error;
- current blocker.

## Founder Attention

```text
GET /activity/founder-attention?period=24h
```

Returns unresolved action items only.

If none exist:

```text
No Founder action is currently required.
```

