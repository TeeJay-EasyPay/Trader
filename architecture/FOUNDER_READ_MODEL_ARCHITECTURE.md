# Founder Read Model Architecture

## Purpose

`GET /founder-evidence` is the bounded production read model for the six Founder screens. It joins shared operational evidence without making live broker calls during mobile startup.

Parameters:

- `period`: `1h`, `24h`, `7d` or `30d`.
- `trade_limit`: bounded server-side trade evidence count.

The payload contains:

- overall autonomous state and reason;
- current worker and database health;
- latest broker snapshot per connected broker;
- research evidence and totals;
- recommendation evidence;
- real broker/order/fill evidence;
- learning evidence;
- recent durable job runs;
- activity timeline and no-trade explanation;
- generated-at timestamp.

`GET /founder/trades` provides a bounded broker-filterable trade view for future focused pagination.

## Screen mapping

- Dashboard: operating state, latest action, broker values, activity and no-trade conclusion.
- Activity: period totals, timeline, worker health and operational reasons.
- Recommendations: saved recommendation evidence including both the strongest case for and against.
- Portfolio: latest broker snapshots, positions and trade/P&L evidence.
- Market: current research cycles, scope, freshness and results.
- Learning: completed learning cycles and evidence-backed metrics.

## Mobile loading contract

The mobile app reads the last successful Founder payload from AsyncStorage first. It then requests one fresh `/founder-evidence` response and atomically replaces the screen models. Secondary narrative endpoints load afterward and cannot block the primary experience.

The legacy `/status` endpoint remains available for compatibility and diagnostics but is not the startup dependency. This avoids serial broker calls and large local SQLite aggregates on every app open.

## Performance controls

Queries are time-bounded and row-limited. The projection stores safe serialized source payloads so screens do not fan out to broker APIs. Indexes cover broker/time, recommendation time, trade broker/time and learning time. No unbounded operational log is returned.
