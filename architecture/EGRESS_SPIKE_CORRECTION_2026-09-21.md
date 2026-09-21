# Egress spike correction — 21 September 2026

## Incident

Supabase Shared Pooler egress rose from roughly 330–390 MB/day to about 950 MB on
20 September, and the partial 21 September total showed the higher rate continuing.
The prior payload and connection reductions were active, but they also shortened the
shared worker cycle. Expensive jobs were scheduled by cycle completion rather than by a
separate cost-controlled wall-clock cadence, so faster execution caused more executions.

Production job history showed the following change from 19 to 20 September:

| Job family | 19 Sep | 20 Sep | Change |
|---|---:|---:|---:|
| Alpaca auto execution | 84 | 294 | +250% |
| Kraken auto execution | 84 | 293 | +249% |
| Managed exits | 85 | 293 | +245% |
| Push delivery | 85 | 292 | +244% |
| Each broker poll | 85 | 129 | +52% |

Nine Kraken auto-execution runs also reached the 600-second timeout between 18:50 and
22:18 UTC. The timing and approximately 3.5-times increase in the most expensive job
families explain why the billed egress rose even though individual requests had become
smaller.

## Corrections

1. Proposal evaluation now has an independent minimum 15-minute wall-clock interval.
   Managed-exit protection keeps its existing cadence; the fix does not weaken stop
   monitoring, broker polling, risk rules or trading thresholds. At the minimum interval,
   each broker can run at most 96 scheduled proposal evaluations per day rather than the
   approximately 294 observed on 20 September, a 67% request reduction.
2. Day and week P&L calculations now ask PostgreSQL for only the latest snapshot at or
   before the cutoff. They previously downloaded the broker's complete snapshot history
   and selected the row in Python.
3. Database-transfer telemetry is now published by the durable main worker. It no longer
   depends on the separate experiment thread, whose stale report hid the spike while it
   was occurring.

## Live read-only validation

All production `created_at` values involved in this calculation use ISO timestamps, so
the bounded PostgreSQL ordering is safe. The old and new calculations returned identical
timestamps and portfolio values for both the day and week cutoffs:

| Broker | Rows returned by each old query | Rows returned by each new query |
|---|---:|---:|
| Alpaca | 6,672 | 1 |
| Kraken | 6,854 | 1 |

One evidence snapshot performs four of these calculations. Its P&L-history transfer is
therefore reduced from approximately 27,052 rows to 4 rows, a reduction greater than
99.98%, without changing the calculated values. At the 135 evidence snapshots observed
per day, this removes roughly 3.65 million returned rows per day from this query family.

## Measurement boundary

The code-level request and row reductions are deterministic. Supabase's billed daily
egress includes protocol and pooler overhead and is reported after aggregation, so the
authoritative MB reduction must be measured over the first complete deployment-free day.
The restored hourly transfer report will make any remaining application query families
visible instead of relying only on the provider's aggregate bar.
