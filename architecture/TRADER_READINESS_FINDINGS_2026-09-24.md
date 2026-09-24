# Trader readiness: investigation results for discussion

24 September 2026, approximately 21:53–22:00 UTC. Investigation only.
No source fixes, database writes, broker calls/orders, paid model calls, deployment,
experiment starts or settings changes were performed. This document is the only
new deliverable. Read-only PostgreSQL sessions used 5–10 second statement limits,
aggregate queries and bounded metadata. No full trade histories were exported.
Two health GETs checked the hosted API; these may update its ordinary local
telemetry. Diagnostic bytes were not separately instrumented or equated to billed
egress. A query failure was isolated to its read-only transaction before continuing.

API and current worker both reported d57d700d. Worker was idle, with no last error
at the sampled heartbeat. Local documentation commit is 7f245ec4; it does not
change executable code. These checks do not establish all jobs are healthy.

## Executive conclusion

The founder was right: capital ring-fencing and learning repairs already exist.
Do not rebuild them. However, working newer components coexist with older readers
and scheduler behaviour. Several of Trader's concerns are misleading descriptions
of existing evidence; two concrete defects and a read/action boundary need repair.
Trader saying it is satisfied is not an acceptance test for these changes.

## Findings and proposed action

### 1. Capital isolation exists; its consumers are not one reconciled basis

Confirmed existing configured allocation and ownership-filtered ledger; personal
holdings are explicitly excluded. Ledger entries total GBP500 allocation,
GBP1,665.06 exit credits and GBP1,719.34 entry debits: ledger cash GBP445.72.
Owned canonical realised net P&L is -GBP19.0403. The current ledger formula implies
deployed capital GBP35.2397 (500 - 19.0403 - 445.72).

Separately, the stored broker snapshot has GBP401.18 cash and GBP5,831.05 whole-
account value. Four open managed-exit controls total GBP80.9347 at entry prices;
seven nonterminal owned logical trades total GBP42.3657 at entry prices. These are
different populations and are not reconciled by this aggregate inspection. Four
exit_submitted controls (GBP8 total) are excluded from the open-control reader.

api._account_context_for_broker still uses min(configured allocation, broker GBP
cash) as equity, and open exit controls valued at entry as exposure. It does NOT
use kraken_capital_ledger_summary as that denominator. Existing protections against
whole-account loss figures being compared with isolated capital are present.

Classification: prior isolation implemented; remaining accounting integration /
reconciliation question, not proof that personal funds are being traded. Do not
switch the denominator to the ledger or whole-account value before reconciling
ownership, open/partial/exiting orders, reserved cash, fees and current marks.
Proposed action: a small linked order reconciliation, then agree the exact
ring-fenced equity versus spendable cash contract before changing any risk input.

### 2. Per-coin history: reproduced PostgreSQL defect, not absent records

PERFORMANCE_ATTRIBUTION contains 177 rows; 62 Kraken and 75 Alpaca rows have close
dates at/after August 31. Every sampled-table timestamp is ISO-like, so the earlier
epoch-filter defect does not explain today's symptom.

The exact symbol_track_record SQL, passed through the deployed SQL translator,
fails with ProgrammingError: incomplete placeholder '%'. Literal percent signs
remain in SQL comments. psycopg parses placeholders inside those comments too.
The function catches every exception and substitutes an empty history. Its caller
then reports "No closed ... trades". A count-only control query with the comments
removed returns 171 matching rows, without changing the predicates or database.
The symbol discovery query itself returns 38 distinct symbols in its window.

This reader is also called by agent.py during proposal assessment, not just chat.
The previously intended caution/penalty can therefore be silently absent. Restoring
it may legitimately reduce trading; that behavioural impact requires explicit tests.
Earlier commits intended to repair PostgreSQL history access did not eliminate this
remaining failure. This is not evidence that today's release created the defect.

Proposed action: fix the narrow SQL/comment problem; distinguish unavailable from
empty evidence; use one bounded broker/asset-scoped aggregate rather than repeated
per-symbol reads. Preserve symbol aliases and cohort/date rules, and review whether
cross-asset symbol collisions or mixed P&L bases can contaminate the existing reader.
Tests: real PostgreSQL parameter binding, unavailable vs zero, symbols, dates,
ownership/broker separation and the resulting proposal cautions.

### 3. Alpaca learning: earlier repairs worked; actual net evidence still missing

All 25 canonical terminal Alpaca trades have linked experiences and reviews, and
all 25 have gross P&L. None has net P&L. Fee columns are numerically zero on these
rows, but the inspected source fields broker_fee/exchange_fee are absent on all
884 retained Alpaca broker-history rows. Those zeros do not independently verify
actual account costs. September 11 release notes already documented this limitation.

There are 91 completed Alpaca learning runs overall, versus 25 canonical terminal
trades; those populations include other reporting/legacy work and must not be
described as 91 independent verified after-cost trade outcomes. Kraken has 87
canonical terminal trades with net results and linked reviews, and 88 runs overall.

Classification: review linkage fixed; known missing cost/net evidence persists.
Proposed action: explain the distinction clearly in Trader context and UI; determine
whether an authoritative account/activity cost source can establish fees for the
paper/live account. Keep estimates separately labelled. Do not rerun repairs or
invent fees merely to make the "complete" counter increase.

### 4. Currency separation works in new packets, not the legacy daily aggregate

broker_learning_packets explicitly separates Alpaca/USD from Kraken/GBP. The new
learning_screen also groups results by broker. However, api.daily_learning_update
sums PERFORMANCE_ATTRIBUTION.profit_loss across brokers into total_profit_loss,
largest gain/loss and shared counts without a currency or gross/net split.

Today's source aggregates are Alpaca -21.56 (USD gross, one row) and Kraken -1.196
(GBP recorded result, four rows). The legacy formula adds them to -22.756, which
is not a meaningful single-currency after-cost result. The function is included
in Trader context when the request has sufficient time, alongside the newer packet.

Classification: confirmed older contradictory reader, not a failure of the newer
broker-separated packet. Proposed action: one read-only, broker/currency/cost-basis
summary contract for chat and screen; no unlabelled pooled amount. Retain historical
records and add mixed-currency regression tests. No FX conversion unless rate and
timestamp provenance is explicitly supported.

### 5. Alpaca experiment intake: shared-cursor starvation plus sample selection

Four active Alpaca experiments share a broker decision batch, fetched using the
smallest cursor and LIMIT20. The reference-set experiment cursor is 42106; three
other experiment cursors are 42868. A read-only reconstruction of their next shared
batch returns decision IDs 42806–42868: zero new decisions for those three tests.
The reference test can preserve its cursor when its paid pair cannot be assessed;
today's proposal_attempt records the daily reference-pair reservation. One budget-
waiting test can therefore prevent independent tests from advancing.

Six later eligible decision rows (four unique proposals, IDs42907–42977) have no
active experiment observation. They are beyond the three cursors. Thus the evidence
does NOT show these later eligible rows were already processed and rejected by the
budget; the shared-feed blockage explains why they have not reached that stage.

There is also a separate selection issue: ten unique Alpaca opportunities already
consume the broker's daily share, and all 30 fan-out pairs are skipped for stops
being too tight. add_opportunity counts these against the same quota and advances
past budget rejections. Merely fixing cursor starvation would still leave the full
daily quota as a barrier. Skips also take the one-symbol/day slot.

Proposed action: independently advancing bounded streams (or grouped cursor batches)
so a waiting reference test cannot starve other tests. Keep waiting work explicit.
Within the existing total request/storage budget, distinguish inexpensive rejection
counters from comparison admission and reserve room for informative opportunities.
Freeze/document the selection rule to avoid hindsight selection or biased results;
do not silently raise the daily budget, remove risk blocks, or backfill old tests.
Tests: delayed reference assessment, mixed cursors, exhausted quota, eligible later
signals, duplicate symbol, fan-out fairness and resumable versus permanent rejection.

### 6. Kraken replacement intake is working; settlement evidence is pending

The three September 24 prospective replacements contain 27 observations across
nine distinct new source opportunities. All are capital-only rebased cases: 22
pairs await bars in both arms; five await a baseline bar with candidate skipped.
This is evidence that the new intake works, not completed or profitable comparisons.
Some report counters lag raw intake because settlement/report evaluation is daily.
Old observations remain separate. No new restart or research run is needed now.

Proposed action: show intake and last-settled report timestamps separately; observe
normal subsequent settlement. Do not inflate progress by calling awaiting pairs
completed. No new orders or accelerated research needed for verification.

### 7. Additional important boundary: chat can call a maintenance-capable summary

api._ask_context includes daily_learning_update when time permits. That function
calls update_calibration_from_attribution (database writes),
review_strategies_for_demotion (default apply=True), and resolve_shadow_trades.
Its returned note nevertheless says updates propose improvements only. This is
not a purely read-only reporting path, even if the chat endpoint is labelled read-only.

Confirmed by source tracing; no such call was made during this investigation and
no claim is made that a specific conversation caused a demotion. Proposed action:
separate read-only conversation projections from scheduled learning maintenance.
Keep approved scheduled learning intact. Add a no-write/no-settlement/no-demotion
test for building both fast and full chat context; show unavailable/freshness clearly.

## Recommended implementation packages, subject to discussion

1. Truthful, read-only evidence: per-coin PostgreSQL reader/error visibility; remove
   maintenance actions from chat context; consolidate currency and cost labels.
   Tests must cover the restored reader's influence on real proposal gating.
2. Experiment progress: fix independent cursor advancement and agree bounded,
   prospectively frozen opportunity selection. Preserve all old versions/evidence.
3. Capital reconciliation: resolve ledger/logical-trade/managed-exit differences,
   then approve the common capital contract. Do not choose a convenient larger
   denominator just to allow another trade.
4. Cost evidence: confirm supported authoritative Alpaca cost source and forward
   capture, with explicit historical limitations. Improve descriptions regardless
   of whether missing historical evidence can be recovered.

Start with code/projection fixes where possible; no new tables are established as
necessary yet. Any repair/migration must first dry-run on a bounded population,
preserve identities and old evidence, be idempotent, and have a rollback plan.
Rollback a faulty reader/scheduler release without deleting learning or relaxing
protective controls. Separate operational selection changes into explicit versions.

Cost expectation: removing repeated per-symbol reads and maintenance-from-chat
should reduce work, but no MB or dollar saving is established. Unblocking experiments
could increase useful simulation work, so preserve hard budgets and measure both
quality and traffic. No extra exchange or paid model allowance is proposed here.

After approved fixes: verify matching deployed API/worker versions, run read-only
acceptance checks, and make one budgeted Trader review using a dated evidence packet.
Ask for unresolved specific concerns, not a positive answer. Completed workflows,
simulation returns and satisfaction still do not demonstrate a trading edge.

## Source anchors

- src/ai_trader/api/__init__.py: _account_context_for_broker, _ask_context,
  daily_learning_update, _kraken_trading_allocation_gbp.
- src/ai_trader/kraken_reconciliation.py: kraken_capital_ledger_summary.
- src/ai_trader/symbol_track_record.py: symbol_track_record, all_symbol_track_records.
- src/ai_trader/broker_learning_packet.py: broker_learning_packets.
- src/ai_trader/learning_screen.py: _summary.
- src/ai_trader/experiment_worker.py: _decisions and tick shared decision_cache loop.
- src/ai_trader/experiments.py: add_opportunity daily/fan-out/symbol limits.
- src/ai_trader/reference_sets.py: pair budget reservation and no-assessment return.
- src/ai_trader/proposal_context.py and production_spine.py: historical analogue
  supply and post-trade review chain exist; supplied context is not proof of use.
- architecture/LEARNING_COMPLETION_SIX_ITEMS_2026-09-11.md: repaired canonical
  reviews and explicitly unresolved per-fill fees.

Pending limitations: no independent current broker order reconciliation, account
statement retrieval, device visual check, full test-suite run, production migration,
provider egress reconciliation or new paid Trader discussion in this investigation.
