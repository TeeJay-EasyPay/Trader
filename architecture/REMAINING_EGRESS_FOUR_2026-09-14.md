# Four remaining egress paths — 14 September 2026

## Implemented

1. Kraken capital summaries support a totals/open-position-only path. Verification avoids historical result downloads; repricing reuses the result list already fetched in the request. Existing detailed responses retain their fields. Remaining detailed result reads transfer only new/changed rows.
2. Background briefing inputs reuse unchanged research, recommendation, broker-snapshot, trade, learning, job, funnel and worker rows. Each original SQL query and its exact window/limit still executes. The database returns the ordered list of row fingerprints and only changed row content; deleted rows disappear, duplicates and ordering are retained. No evidence fields or refresh cadence removed.
3. Schema discovery combines column and primary-key information in one query instead of two. Cross-process content reuse avoids sending unchanged column descriptions again after process-local caches clear. Existing positive caches and post-DDL invalidation remain intact; every cache-miss discovery validates current catalogue contents in SQL. No assumed schema TTL.
4. Alpaca historical fill reconciliation uses the same full SQL/ownership joins but transfers only changed fill rows. Old fill corrections, fees, ownership relinks and removals remain detectable. Full Python reconciliation still executes; this is not a timestamp-only incremental accounting algorithm and does not skip historical verification.

No changes to broker polling, protective exits, live approval, AI decisions, trading thresholds, retention or paused maintenance. Backend-only release; no new mobile rebuild.

## Correctness and storage

Content cache is local to the worker/API host, private directory (0700) and database file (0600) on Linux. No credentials stored. Maximum 48 entries, 2 MB serialized content each; SQL timeouts unchanged. Cache errors cause a fresh transfer, never stale-data fallback on database errors. Exact SQL result fingerprints are checked on every read, including rolling date parameters. Only selected known JSON-compatible projections use this helper, not arbitrary DB types. Initial/cold reads transfer complete results; frequently changing rows still transfer in full. The optimisation reduces network payloads, not necessarily SQL execution cost.

## Verification

- 41 Kraken/Alpaca reconciliation tests passed.
- 52 schema/database/production-evidence tests and two subtests passed.
- Four new projection-transfer tests passed: changed rows and rolling windows; corrections; deletions/duplicates/order; caller mutation; cache misses; unavailable database fails closed; connection identity and added columns.
- Read-only production comparison passed for eight briefing projections, 54 Kraken results, all 316 Alpaca fills, and schema descriptions for two tables. No broker/model calls, production writes, DDL or statistics reset during comparison.

Sample response serialization (JSON bytes, **not billed network bytes**):

| Read | Original result | Unchanged response |
| --- | ---: | ---: |
| 12 recommendations | 475,597 | 461 |
| Latest two broker snapshots | 131,407 | 101 |
| 100 research records | 66,763 | 3,629 |
| 100 trade records | 47,318 | 3,629 |
| 54 Kraken results | 80,929 | 1,973 |

Two conditional queries per sample took roughly 0.09–0.27 seconds including round trips in this check. This is not a load test or guarantee. The database still computes row encodings/hashes, so watch CPU as well as egress. Snapshot updates and new rows mean not every production response will be an unchanged response.

This finding corrects a limitation of ranking purely by returned-row counts or planner average widths: few wide recommendation/broker rows can matter more than thousands of narrow metadata rows. No claim is made that all of the earlier ~400 MB/day is now accounted for or eliminated. Compare complete post-release daily Supabase pooler totals and query deltas before claiming a daily saving.

Release verification: API and latest worker heartbeat both report runtime
`dc8317206cb7c828873f174ac5ba6e3d74b25458`, checked at approximately 01:14 UTC.
Additional API/capital-display/projection set: 31 tests and 19 subtests passed
(includes the four projection tests above; do not double-count).
Original main checkout fast-forwarded without changing the four paused local
maintenance files or their untracked supporting files. No mobile publication needed.
Normal post-release daily usage measurement remains outstanding; no savings
percentage for total billed egress is claimed.
