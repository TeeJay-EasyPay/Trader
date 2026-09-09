# Learning and egress audit — 9 September 2026

## Verdict and scope

Learning is **partly operational, not fully verified or complete**. Kraken has a
working terminal-trade workflow and outcome-based strategy feedback. Alpaca's
reconstructed outcomes are not yet connected to an equivalent closed-loop chain.
The application uses a pretrained AI plus retrieved evidence, deterministic
statistics, reviews and governed proposals; this audit found no model-weight
training pipeline. More tables or completed jobs are not proof of deeper learning.

Read-only production aggregates were collected on September 9. No live cycle,
broker order, production repair/backfill, commit, push or deployment was performed
in this audit. Changes below are **local and tested**, not live.

## Verified learning evidence

| Check | Production result |
| --- | --- |
| Kraken terminal trades | 27, each linked to an outbox workflow and learning run |
| Workflow statuses | 23 completed; 4 completed_insufficient_evidence; no pending/retry/failed rows |
| Completed-run artefacts | 23 reviews and 23 proposals exist, but only 22 linked experiences exist |
| Most recent completed learning run | September 6, 01:38 UTC; new open positions do not yet provide final outcomes |
| Recent learning processor | September 9, 09:12 UTC: zero queued workflows, zero failures |
| Outcome records | Kraken 27; Alpaca 50; all have P&L and exit price |
| Outcome identity duplicates | Zero duplicate (broker, symbol, closed_at) groups |
| Outcome-to-strategy linkage used by strategy_performance | Kraken 23/27; Alpaca 0/50 |
| Alpaca proposal linkage | 37/50 outcomes have no proposal ID; the remaining 13 lack the strategy link checked above |
| Alpaca canonical terminal trades / learning runs | Zero / zero |
| Daily learning job since September 2 | Six completed; latest September 8, 23:48 UTC |
| Self-assessment job | September 9 failure: NameError, undefined `report`, API line 1434 in deployed code |
| Probability-to-outcome join | 23 rows, 23 distinct outcomes; no join multiplication in this snapshot |

Code sources: `sprint6.process_learning_outbox`, `production_spine.run_closed_loop_learning`,
`alpaca_reconciliation`, `strategy_performance`, `trading_intelligence`,
`experience_engine`, `proposal_context`, and `LocalApiService.daily_learning_update`.

### Material outstanding gaps

1. **Alpaca learning identity:** reconstruction writes reporting outcomes but does
   not finish the canonical entry/exit lifecycle and enqueue the learning chain.
   Do not link old trades by symbol alone or manufacture stops/strategy IDs.
   Preserve fill/order identities, partial exits and fee uncertainty. Establish a
   reliable forward path first; any historical repair needs a bounded, idempotent
   plan and explicit evidence requirements.
2. **Review quality and fee basis:** all 23 stored post-trade reviews lack the
   argument fields the fixed-rule classifier tests; all are therefore classified
   as poor decisions. Missing arguments are not proof of a poor decision. Three
   reviews have positive gross P&L but negative net R; the classifier's `gross > 0
   OR R > 0` can describe these as good outcomes. This is a real classification
   defect, not a profitability forecast. Still requires correction and dedicated
   regression tests; existing immutable experiences were not rewritten.
3. **Incomplete artefact:** one completed run has a null experience ID. Investigate
   the original insert/deduplication path before repairing that historic record.
4. **Analogues are not trained performance estimates:** 4,722 analogue records
   have null average R and win rate. The implementation explicitly leaves these
   metrics unset and retrieves matching cases. Retrieval is useful but not model
   training. Do not populate summary numbers from rejection simulations as though
   they were executed trades.
5. **Readiness quality:** readiness is currently global, not broker-specific;
   fresh Alpaca rows could mask a stale Kraken subset. Also, malformed-date rows
   can survive strategy window filtering via its cutoff fallback despite the
   readiness warning saying they are excluded. These behaviours were not changed
   by the read-reuse refactor and need separate safety tests.
6. **Self-assessment truthfulness:** its duplicate flag compares total rows to
   distinct proposal IDs, incorrectly treating missing IDs as duplicates. Its
   legacy combined P&L also adds currencies, although broker-specific figures are
   provided separately. Correct these before treating the assessment as an
   authoritative audit. Existing auto-demotion is called by daily learning;
   older general documentation saying learning never changes strategy status is
   incomplete. This audit did not alter demotion or risk rules.

## Local fixes and egress reductions

- Removed the stray standup callback reference that crashes scheduled self-assessment.
  Tests invoke the actual service method with mocked inventory/AI/storage, both
  without an AI key and with a successful answer. No extra schedule or AI call added.
- Historical-analogue prompt serialization now includes the actual stored
  `net_realized_pnl` and gross result, rather than reading only the legacy `pnl`
  field. All 22 linked real experiences have the actual keys and none has `pnl`.
  Net/gross labels, zero values, missing-net warnings and legacy records are tested.
  This uses data already downloaded; no additional query or backfill.
- Founder evidence now selects only the latest snapshot per broker in SQL,
  preserving wide display fields. Timestamp ties use snapshot ID. A quiet broker
  is no longer lost behind the other broker's latest 20 snapshots.
  Read-only SQL measured the two JSON columns: **841,554 bytes / 20 rows before,
  84,150 bytes / 2 rows after**, approximately 90% less for this query. Only two
  aggregate rows crossed the wire for this measurement. Not a 90% total-egress claim.
- Strategy calculation reuses its outcome rows for readiness: one history read
  instead of two. Evidence thresholds remain unchanged, without a cross-request
  risk cache. Ready calls previously fetched 5 + 8 fields per outcome, now 8.
  Caveat: blocked calls previously fetched only 5 fields, now 8 before declining;
  this is not a guarantee of savings under every workload.
- Corrected the diagnostic report's unsupported fixed "TWICE" billing wording.
  Row-width estimates are not a network bill and have no universal multiplier.

**150 targeted tests passed**, including learning, recovery, self-assessment,
production evidence, prompt context, institutional spine and crypto review tests.
The first run had two Windows pytest temporary-directory permission errors (90
tests passed); rerunning with a fresh unique temp directory resolved these without
weakening tests. `git diff --check` passed. No full-suite or live release claim.

## Egress breakdown found for Claude / Founder

The existing generator is `tools/egress_report.py`, with its supporting estimator
`tools/egress_window.py`. Saved local inputs:

- `data/egress_baseline_after_fixes.json`: September 7, 15:03:14 UTC.
- `data/egress_baseline_clean.json`: September 7, 17:47:52 UTC.

Recomputed offline, without another production export, these estimate **20.3 MB
of SQL row data over 2.74 hours**, or **178 MB/day if that rate persisted**:

| Component | Estimated MB/day | Share |
| --- | ---: | ---: |
| Founder/app evidence projections | 53.1 | 29.8% |
| Strategy performance | 30.1 | 16.9% |
| Schema / table-shape lookups | 25.7 | 14.5% |
| Learning readiness | 20.5 | 11.5% |
| Kraken reconciliation | 18.1 | 10.2% |
| Candle / market-data reads | 10.6 | 6.0% |
| Remaining components | about 20 | about 11% |

**Important correction:** despite its filename, that window contains **four
background-worker starts**. It is not a deployment-free steady-state baseline.
Retained worker records show **18 starts on September 7 and 9 on September 8**
(UTC day boundaries). Starts are not necessarily deployments: process recovery
and other restarts can contribute. These counts do not quantify restart bytes.

The older breakdown is referenced in `KRAKEN_CYCLE_AND_EGRESS_2026-09-09.md`.
The implementation log's August 6 egress section documents a different, earlier
4.79 MB Founder response problem and its remediation; don't treat it as today's
450 MB/day explanation. This document preserves the recovered September breakdown.

### Could tests and updates explain 450 MB/day?

- Current test-process environment selects SQLite with no database URL. The tests
  run here use local fixtures/mocks. Editing code and local tests do not themselves
  download production rows. There is no suite-wide conftest network isolation;
  an arbitrary run with production environment variables could still reach
  Postgres. We cannot retrospectively certify every Claude/test process.
- `Dockerfile` installs the package but does not run tests or download a database.
  **Deployed runtime starts** can read schema metadata, replay history and warm
  caches. Code updates can therefore raise egress indirectly. Existing replay
  skip/cache protections reduce, not eliminate, startup work.
- Manual live diagnostics, app use, SQL-editor queries, exports and live research
  checks can also return database data. Read-only does not mean free of egress.
- The first screenshot is **All projects**, with 22.35 GB used in the billing
  period, roughly 450 MB on each of September 7/8, and an organization restriction
  banner. The Founder then supplied project-filtered screenshots: **ai-trader**
  shows essentially the same daily bars; NexusPay shows no data in the period.
  This resolves the project-attribution concern: focus on AI Trader, not the
  other project. The images do not establish an exact 99% fraction or a service
  split. September 9 is partial. The 450 MB still cannot be reconciled exactly
  to the short SQL row-byte estimate.
- Supabase counts multiple services. Pooler traffic is labelled Shared Pooler
  Egress and is not double-counted as Database Egress. Its Cached Egress category
  is CDN traffic, not evidence that our Python/app caches are unused.
  Source: https://supabase.com/docs/guides/platform/manage-your-usage/egress

## Next steps / release gates

1. Project filtering is now verified by the Founder's screenshots. Obtain AI
   Trader's September 7/8 per-service tooltip breakdown to separate Database/Pooler
   traffic from Storage, Auth, Realtime and other services. Do not continue
   attributing the unexplained portion to the other project.
2. Use equal, preferably 24-hour, steady-state measurement windows; annotate
   restarts and research counts. Keep only relevant aggregate/query-ID counters,
   not repeated full query-text exports; never reset shared statistics. Existing
   cumulative stats cannot retrospectively split every day's bytes by cause.
3. Consolidate remaining strategy audit reads to compact strategy/stop fields,
   then share one request-scoped strategy dataset across per-coin/overall/calibration
   consumers. Preserve missing-evidence refusal and broker/fee distinctions.
4. Measure metadata cold-start traffic and bundle backend releases; skip Render
   restarts for documentation/mobile-only releases. Do not slow protective exits
   or broker reconciliation to reduce a display/read inefficiency.
5. Address the learning gaps above before calling the system fully learning.
   Restoring self-assessment restores its intended aggregate reads, so its net
   egress impact must be measured against the savings, not promised as zero.
6. The scoped fixes were released in `26092511` on September 9; the worker
   heartbeat confirmed that version at 10:03:59 UTC. See the implementation log
   for test and mobile verification details. No production backfill, automatic
   model training, new recurring measurement job, fee change, stop change or
   trading-permission change was introduced.
