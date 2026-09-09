# Kraken cycle corrections and Supabase egress follow-up

> Release update: these corrections were committed and pushed as `564b0377`, with
> the API and worker verified live and Android OTA published to both existing
> channels. The earlier local-only status below records the pre-release snapshot.
> See `PORTFOLIO_TRENDS_2026-09-09.md` for the outstanding emulator visual check.

## Confirmed live result

The authorised manual Kraken cycle `752a88794dbd` ran from 21:01:43 to
21:31:46 UTC on 8 September. Kraken accepted and filled the XLM entry
`OX4QO3-IFJ3U-ZAETN7` (about GBP12.50). A native stop was recorded separately.
The app's conclusion saying no trades were placed was wrong.

On 9 September, a read-only, database-side aggregate of that exact window
returned **one submitted Kraken order**. A second aggregate returned one approved
and five rejected latest-per-proposal broker decisions; the rejection reason was
`max_stop_loss_pct_exceeded`. These two diagnostic queries returned only three rows
in total, not proposal payloads or a trade-history dump.

This establishes a software/reporting gap, not whether refused trades would have
made money. The earlier commission/reviewer change is distinct from these defects.

## Changes implemented locally

- Count actual approved execution decisions with a nonempty order ID, joined to
  the proposal's broker. Deduplicate order IDs. Do not rely on nonexistent audit
  event names. Say **submitted**, not **filled**; say **unverified** if the read fails.
- Isolate Kraken/Alpaca summaries. Aggregate the latest broker decision per proposal
  in SQL and calculate the genuinely most common rejection reason. Scope crypto
  pre-proposal refusal reads to crypto event IDs too.
- Summaries describe orders recorded **during the run**, not exclusive causal
  attribution: independently scheduled workers may also execute in that window.
- Generate crypto proposals using the stricter of the saved policy stop ceiling
  and the crypto configuration ceiling. Live policy remains 5%; it is not raised
  to the configuration's 8%. Protect boundary stops from floating-point/eight-decimal
  rounding rejection. A volatility floor exceeding policy is still subject to refusal.
- Manual universe refresh no longer runs hidden research before the explicit
  research stage. Scheduled/standalone callers retain the existing default.
- Replace the misleading 2–4 minute promise with realistic duration guidance and
  elapsed time calculated from existing progress data. Poll every 10 seconds,
  previously every 3 seconds; server trading cadence is unchanged.
- Crash messaging warns that orders might already exist rather than declaring
  nothing traded and encouraging an unsafe retry.

## Egress protection in these changes

There are no new recurring jobs, tables, bulk exports or payload-history reads.
The stop-policy change reuses the policy read already needed for the confidence
bar. Actual-order reporting replaces an existing count with another single-scalar
query; broker decision reporting returns aggregate groups rather than individual
decision rows. Elapsed time requires no requests. Removing one research pass per
manual cycle eliminates its repeated market/history/reviewer-context work.

At a fixed 30-minute run, periodic progress reads fall from approximately 600 to
180 (70% fewer, excluding initial/manual reads). This is a reduction for this
endpoint, **not** a claim of 70% less total Supabase egress.

No source-code review can guarantee the account's total billed egress will never
increase: traffic, more legitimate trades, restarts and other consumers matter.
These changes do not introduce additional database-read paths, and the affected
scheduled polling/read workload is reduced. Production byte savings still need a
comparable post-deployment measurement window.

## Next reductions, in priority order

The existing local September 7 snapshots cover about 2.7 hours. The repository's
row-width estimator attributes approximately 53 MB/day to production evidence,
30 MB/day to strategy performance, 26 MB/day to metadata lookups and 21 MB/day to
learning readiness. These are historical, extrapolated **estimates**, not today's
Supabase bill; aggregate expressions and JSON widths can distort that estimator.

1. **Return only the latest broker snapshot per broker from SQL.**
   `production_evidence._load_founder_evidence_rows` reads 20 rows with position/payload
   JSON, then retains one per broker. Select the newest per broker in SQL with a
   deterministic tie-break. With two brokers, this would return two rows instead
   of 20 for this query (about 90% fewer rows when the current limit is full).
   Preserve every displayed field; test missing brokers and identical timestamps.
2. **Reuse outcome data within a single learning/strategy calculation.**
   `strategy_performance` calls `assess_learning_readiness`, which reads the whole
   outcome table, then reads that table again. Share a narrow, request-scoped
   outcome set or push readiness aggregates into SQL. Preserve malformed-date,
   stale-outcome and minimum-sample safeguards. Do not cache live risk decisions.
3. **Fetch only the strategy context needed from proposal JSON.**
   The strategy calculation needs strategy ID and stop-loss, yet its already
   filtered audit query still returns full proposal dossiers. Extract those fields
   in SQL (with compatible SQLite/Postgres handling), or persist a compact context
   when the proposal is created. Test malformed/missing JSON and result parity;
   avoid a bulk production backfill just to save a read.
4. **Reduce schema introspection and avoid repeated cold starts.**
   The compatibility layer remains a material historical estimated source, but
   already has per-database/table caches. Measure remaining misses and restarts
   before adding another cache. Preserve migration invalidation and database
   isolation. The old snapshot alone does not prove today's caches are ineffective.

Validate each change independently with narrow result parity tests and query/row
counts. For production comparison, use equal steady-state windows, record restarts
and workload, collect only relevant query-stat counters, and compare the Supabase
egress dashboard. Do not repeatedly export all query texts or reset shared counters.

## Verification and release status

New regression tests cover real execution counting without the old event names,
duplicate rows, validation without an order, rejected attempts, cross-broker
isolation, unavailable storage, actual modal reasons, Postgres mapping rows,
strict stop-policy plumbing with one policy read, boundary prices, one manual
research pass, and compatibility of standalone refresh. Mobile tests cover elapsed
time and the slower polling interval.

These follow-up changes are local at the time this document was written. They have
not been committed or deployed, and no additional live cycle has been triggered.

Validation completed: full backend suite **1,794 passed, 21 subtests passed**
(261 seconds); final targeted cycle/reporting/lean-read suite **38 passed**;
Node mobile suite **66 passed**; changed mobile files compiled with the Expo Babel
preset; `git diff --check` passed. Production aggregates were checked read-only as
described above. This follow-up did not include a new emulator/live-cycle run.
