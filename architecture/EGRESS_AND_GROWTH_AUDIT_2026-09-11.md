# Supabase egress and growth audit — 11 September 2026

Read-only observation: 17:51 UTC. No exports of trade payloads, deletion, vacuum,
statistics reset or retention changes. Existing paused backup work remains untouched.

## Measured database growth

Database size is **1,267,076,243 bytes (1.267 GB / 1,208.4 MiB)**, up
61,292,544 bytes (58.5 MiB, 5.1%) since 10 September 09:19 UTC. That interval
is about 32.5 hours, not one day; its average is approximately 45 MB/day and
must not be extrapolated as a stable forecast. Physical relation allocation is
not a direct measure of network transfer or exact logical payload volume.

Largest relations, including table/TOAST/index allocation:

| Relation | MiB | Interpretation |
| --- | ---: | --- |
| decision_journal | 216.0 | Persisted decision evidence |
| execution_decisions | 161.9 | Execution decision records |
| trade_audit | 99.4 | Trade audit records |
| trade_lifecycle | 71.9 | Lifecycle history |
| production_broker_snapshots | 69.2 | Repeated broker snapshots |
| scheduled_job_runs | 66.9 | Operational job history |
| operational_events | 60.2 | Operational event detail |
| trade_signals | 48.8 | Signal history |
| portfolio_manager_decisions | 44.6 | Portfolio decision evidence |

The first three occupy approximately 477 MiB, about 39.5% of the database.
Their estimated dead tuples are only 19, 6 and 0. This does not support a claim
that ordinary vacuum would recover most of that space. All records in these
three tables are younger than 90 days: shortening nothing and merely running
the existing 90-day cutoff would remove none of them now.

The four experiment/learning relations total **442,368 bytes (0.42 MiB)**:
rule_experiments 90,112; experiment_opportunities 106,496; experiment_events
81,920; learning_findings 163,840. They are not currently a material storage
driver. Small storage does not prove small egress if repeatedly downloaded.

## Egress evidence and limitations

The standard SUPABASE_ACCESS_TOKEN is not configured in the inspected environment.
Existing SQL audit access works and pg_stat_statements is available. Authoritative
current billed egress, service breakdown, allowance and billing-period totals
have **not** been obtained. A Supabase Usage screenshot/export or suitably scoped
management access is needed to reconcile them. No exact GB/day or dollar saving
is claimed from query counts.

Statistics reset: **18 July 2026 11:17:52 UTC**. The following counts are cumulative
since that reset, not today's traffic:

| Read pattern | Calls | Returned rows |
| --- | ---: | ---: |
| information_schema column discovery | 654,603 | 10,199,224 |
| Serial sequence discovery | 5,850,090 | 5,850,090 |
| Recent market-observation history | 27,048 | 3,198,943 |
| Broker history updated_at normalization scan | 6,178 | 2,966,762 |
| Broker history opened_at normalization scan | 6,178 | 2,966,762 |
| currval lookup | 2,791,625 | 2,791,625 |

A follow-up sample minutes later showed four more column-discovery calls
(66 rows), while the other listed counters were unchanged. Thus metadata reads
remain observable, but it would be incorrect to present the multi-million
historical sequence or normalization counts as the current daily cause. The
short window is not representative enough to estimate a steady-state rate.

Likely contributors to investigate, not proven billed-byte attribution:

- Repeated schema/initialization reads, especially after restarts: high historical
  frequency, ongoing column discovery observed.
- Broad history and market-data reads: high cumulative returned-row counts;
  current frequency and response size require a comparable longer window.
- Operational snapshot/report polling: inspect projected fields and cache reuse;
  large stored snapshots alone do not prove they are all repeatedly transmitted.

Fourteen retained background-worker starts are recorded for September 11 so far,
versus ten on September 10. These are not necessarily all deployments, and
neither restart count nor the app refresh count establishes exact network bytes.
Mobile OTA assets come from Expo, not these database tables.

## Recommendations, in priority order

1. **Measure current traffic before attributing the bill.** Obtain daily Supabase
   egress split by pooler/PostgREST/Storage/etc. Take bounded query-counter deltas
   during comparable steady-state periods with reset timestamps, and correlate
   with releases and job schedules. Expected benefit: reliable targeting, not
   an immediate saving. Keep diagnostic traffic small.
2. **Reduce repeated reads where current deltas confirm them.** Reuse process-level
   schema metadata, project only required columns, retain reporting caches and
   batch shared experiment inputs. Verify compatibility and cache invalidation;
   do not break identity return/linking to save catalog reads. Savings unknown
   until rates and payload sizes are measured.
3. **Stop avoidable storage growth at the writer.** Investigate repeated full
   decision/audit/snapshot payloads and use compact references or change-only
   snapshots where all consumers can retain exact decision provenance. Preserve
   fills, fees, approvals, reference versions and learning evidence.
4. **Evaluate research cadence separately from protection.** Skip redundant AI
   assessments when information is unchanged; reuse existing market data. This
   can reduce model expense and associated reads, but reduced calls alone do not
   guarantee lower Supabase egress. Do not slow protective exits or reconciliation.
5. **Plan archival only after evidence dependencies are mapped.** A verified
   archive plus explicit approved retention scope may help older bulky diagnostics.
   Deletion may not immediately reduce allocated disk and is not authorized here.

No optimization savings or current billed-egress total are claimed. This report
provides measured storage and historical query evidence, plus the remaining
measurements needed to identify today's dominant network contributors.

Provider definitions: https://supabase.com/docs/guides/platform/manage-your-usage/egress
and https://supabase.com/docs/guides/platform/database-size .
