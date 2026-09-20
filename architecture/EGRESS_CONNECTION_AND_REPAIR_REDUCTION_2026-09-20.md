# Egress root-cause release — 20 September 2026

## Why the earlier reductions did not move the provider graph enough

A clean production interval from 19 September 11:02:54 UTC to 23:56:55 UTC
(12.9 hours, with no worker restart) recorded about 35.8 MB of consumed SQL row
values, equivalent to roughly 67 MB/day. Supabase continued to report roughly
350 MB/day of Shared Pooler egress. The application counters also recorded 29,843
SQL calls and 2,938 `pgbouncer.get_auth` calls in that interval, equivalent to
about 5,470 new database sessions per day.

The difference between measured result values and provider-billed transfer cannot
be assigned exactly without provider-side per-query byte accounting. It is strong
evidence, however, that session/protocol overhead and unmeasured framing are a
material part of the bill. The previous releases successfully removed large row
payloads, but every `connect()` still created a new physical session and two repair
paths continued scanning completed history.

## Changes in this release

- All normal and raw PostgreSQL helpers now share a bounded, process-local psycopg
  pool. A checkout preserves the existing transaction semantics and returns a clean
  connection to the pool on close. Short-lived worker subprocesses do not share
  state with one another, but sequential database operations within each job no
  longer require a new Supabase session each time.
- Managed-exit reason repair now selects only rows whose entry/exit reason remains
  blank or legacy. When no incomplete rows exist it stops immediately, instead of
  rescanning all closed managed exits and all broker performance records on every
  managed-exit cycle.
- Generic trade-reason repair now limits its base read to incomplete or genuinely
  legacy rows. Completed normalized history is not transferred again.
- Strategy-performance attribution results receive a five-minute hosted-process
  cache. The research cycle previously repeated the same full attribution read for
  individual candidates; identical requests now share one result.
- The experiment worker now loads up to ten active experiment records in one query,
  replacing the ID query plus one full-record query per experiment.

No trade cadence, strategy threshold, broker polling interval, protection check,
order authority or evidence-retention rule was reduced.

## Measured targets and expected effect

| Target in the clean interval | Observed before release | Change |
|---|---:|---|
| New database authentication/session calls | 2,938 in 12.9 h (~5,470/day) | Sequential operations in each process reuse a bounded set of sessions |
| Full strategy attribution reads | 171 calls, 23,689 rows, 3.86 MB (~7.2 MB/day) | At most one identical hosted-process read per five minutes |
| Trade-reason repair families | About 3.55 MB in 12.9 h (~6.6 MB/day), excluding linked lookups | Clean cycles return after a narrow incomplete-row check |
| Active experiment loading | ID list plus up to ten record reads per tick | One bounded batch read per tick |

A live read-only pool check reused one physical PostgreSQL backend for eight
sequential application checkouts. That verifies the mechanism, not the final billed
saving. The authoritative result is the first complete 24-hour deployment-free
Supabase usage day; the dashboard refreshes hourly and includes protocol traffic the
application cannot count.

## Verification

- Focused egress, database, experiment, production-completion and trade-reason tests
  pass, including an explicit clean second repair cycle and pooled-connection cleanup.
- The complete backend suite was also exercised. The egress regression discovered
  during that run was updated to assert the new one-query experiment load; the other
  failures reproduce unrelated current test/environment expectations (crypto fee
  fixtures, Standup copy and absent mobile `node_modules`).
- Live checks were read-only. They placed no orders and changed no production data.

## Deployment verification

Release `291ced6f` was deployed on both Render services. The API reported the full revision,
and a direct read-only heartbeat query showed the replacement worker on the same revision,
running normally with no last error. The first hosted API report on the new build recorded
214 SQL calls but only two physical connections, confirming that session reuse is active in
production. Provider billing still needs a complete deployment-free day before a before/after
claim is made.
