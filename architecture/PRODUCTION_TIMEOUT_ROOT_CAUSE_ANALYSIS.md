# Production Timeout Root-Cause Analysis

Companion document to `CLAUDE_INDEPENDENT_ARCHITECTURE_REVIEW.md`. Covers the four jobs reported as exceeding their 180-second execution boundary in `architecture/CURRENT_OPERATIONS_RECOVERY_REPORT_2026-07-27.md`: `premarket-equity`, `overnight-crypto`, `evidence-snapshot`, and Kraken startup reconciliation. Per the review brief, timeouts are **not** treated as "raise the limit" problems — each is traced to its actual internal stages and external dependencies, with root causes ranked by evidence.

A cross-cutting scheduling defect affects all four and is documented once, up front, because it changes how the individual root causes should be read.

---

## Cross-cutting issue: two independent schedulers trigger the same jobs, and the deduplication key does not work across them

`render.yaml` defines standalone Render **cron services** for `premarket-equity`, `market-open-equity`, `midday-equity`, `market-close-equity`, and `overnight-crypto` (each `python -m ai_trader run-job <name>`). Separately, the always-on **worker's own internal loop** (`cli.py:_due_worker_jobs`, lines 653-679) independently decides when to run jobs with the *same names*, using its own time-bucket logic.

The intended safeguard — `SCHEDULED_JOB_RUNS.idempotency_key = f"{job_name}:{scheduled_for}"`, `UNIQUE`-constrained (`always_on.py:28,146`) — does not actually deduplicate between these two triggers, because they compute `scheduled_for` differently:

- The cron-triggered `run-job` CLI path never passes `--scheduled-for`, so it defaults to the literal wall-clock timestamp at container start (`cli.py:100`, `always_on.py:321`).
- The worker-loop path computes a fixed daily bucket string, e.g. `f"{day}T08:00:00-04:00"` for `premarket-equity` (`cli.py:672`), or a rolling bucket for `overnight-crypto` (`cli.py:665,687-690`).

These two strings essentially never match, so `claim_scheduled_job` sees two distinct idempotency keys and **runs both**. `architecture/JOB_AND_WORKER_RECOVERY_STANDARD.md:34`'s claim that "duplicate jobs are skipped" is true only *within* one scheduler's own repeated bucket — it provides no protection between the cron service and the worker loop.

**Consequence for this analysis:** some of what the recovery report observes as "one job, timing out" may actually be **two overlapping executions of the same nominal job contending for the same database rows and the same broker/API rate limits**, which independently degrades latency on top of each job's own internal cost. `overnight-crypto` is the clearest case — see below.

**Second consequence:** the cron-triggered `run-job` path has **no timeout wrapper at all**. The 180-second child-process boundary only applies via `_run_worker_cycle_job(..., restart_worker_on_timeout=True)`, which is exclusively used by the worker loop's `_run_pulsed_job` (`cli.py:586-595`). A cron-triggered run of the same job can hang indefinitely, bounded only by whatever limit Render's cron infrastructure itself imposes (not visible from this repository). So "the same job" currently has two different reliability contracts depending on which scheduler triggered it.

**This is not a new infrastructure requirement to fix** — see `CRITICAL_REMEDIATION_PLAN.md` P0-3: either delete the overlapping cron services (the worker loop already covers these jobs) or make the two schedulers compute the same idempotency key.

---

## Job 1: `premarket-equity` (and identically-structured `market-open-equity`, `midday-equity`, `market-close-equity`)

### Call graph
`cli.py:_run_named_job` → `api.py:run_analysis` (lines 1933-2109) → `agent.py:AITradingAgent.propose_trades`, called once **per symbol** (`api.py:2026-2036`).

### Stage-by-stage timing hypothesis

| Stage | External dependency | Timeout | Retry | Cost pattern |
|---|---|---|---|---|
| Symbol universe read | Postgres (`COMPANY_MASTER`) | DB statement timeout (~8s default) | N/A | One bounded query — cheap |
| Per symbol (×30 max), sequential: | | | | |
| — market data | Alpaca bars API | 20s, `alpaca.py:56` | **None** | Called once per symbol, not batched, despite the underlying method accepting a symbol list |
| — news | Alpaca news API | 20s, `alpaca.py:56` | **None** | Same N+1 pattern |
| — proposal analysis | OpenAI (`gpt-4.1-mini`) | 30s, `ai.py:50` | **None**, no backoff | Same N+1 pattern; this is the single most expensive call per symbol |
| — intelligence evaluation | In-process | — | — | Not externally bound, low cost |
| — audit write | Postgres | DB statement timeout | — | Cheap, bounded |
| After loop: auto-execution | Broker calls per approved proposal | 20s each | None | Proportional to how many proposals clear guardrails |
| Evidence writes | Postgres | DB statement timeout | — | Bounded |

**Worst case per symbol: 20s + 20s + 30s = 70s.** For up to 30 symbols run **sequentially**, a single slow-but-not-dead response anywhere in the batch compounds directly into the total. The job has **no cumulative elapsed-time budget check inside the per-symbol loop** — it does not notice it is running out of time and stop early with partial results; it simply runs until the external 180-second child-process boundary kills the whole process.

### Ranked root causes

1. **(Primary, high confidence) Unbatched, sequential, per-symbol external calls with no internal time budget or checkpointing.** `get_latest_bars`/`get_news`/`propose_trades` all accept a symbol list, but the caller (`api.py:2026-2036`) invokes them once per symbol anyway. A single slow response 5–9 symbols into a 30-symbol batch can exhaust the entire budget, and because there is no partial-completion checkpoint, the *entire* cycle's progress is discarded when the child process is killed — the next cycle starts the batch over from symbol 1, not from where it left off.
2. **(Secondary) Zero retry/backoff on any external call.** A single transient 5xx or slow response from OpenAI or Alpaca consumes its full timeout allowance with no resilience, directly compounding cause 1.
3. **(Minor) Auto-execution re-fetches broker account context per approved proposal**, adding further sequential broker calls proportional to how many proposals clear guardrails that cycle.

### Remediation (see `CRITICAL_REMEDIATION_PLAN.md` for full detail)

Batch the market-data/news calls (already supported by the underlying client methods) so the whole symbol universe is fetched in 2 calls instead of 2×N; keep the OpenAI call per-symbol (unavoidable for per-symbol analysis) but add a cumulative elapsed-time guard inside the loop that stops the batch early and persists an honest `partially_completed` result (a status the schema already supports) rather than losing all progress to a hard kill. **Expected result after remediation:** external call count drops from ~90 (30 symbols × 3 calls) to ~32 (2 batch calls + 30 OpenAI calls); combined with a time-budget early-exit, the job should reliably complete or gracefully partially-complete within 180s even under degraded upstream latency. **Should the job be split?** Not architecturally necessary — batching plus a time budget should be sufficient; splitting into "fetch" and "analyze" sub-jobs is a reasonable P2 follow-up if batching alone proves insufficient after measurement, not a prerequisite.

---

## Job 2: `overnight-crypto`

### Call graph
`cli.py:_run_named_job` → `api.py:run_crypto_analysis` (lines 389-523) → `agent.py:propose_crypto_trades` (lines 159-271).

### Stage-by-stage timing hypothesis

| Stage | External dependency | Timeout | Retry | Cost pattern |
|---|---|---|---|---|
| Symbol universe | Fixed, small: `KRAKEN_ALLOWED_PAIRS=XBTGBP,ETHGBP,SOLGBP` (3 pairs) | — | — | Trivial |
| Per pair (×3), sequential | Kraken public price API | 20s, `broker_adapters.py:395,418` | None | Same N+1 pattern as equities, but N=3 |
| Scoring | In-process, deterministic (no OpenAI call for crypto) | — | — | Cheap |
| Auto-execution (if any proposal clears) | Broker calls | 20s each | None | Same pattern as equities |

**Worst case for a single isolated run: 3 × 20s = 60s, well under the 180s boundary.** Per-call cost alone does not explain repeated timeouts for this job.

### Ranked root causes

1. **(Primary) Frequency and overlap, not per-call latency.** The always-on worker loop runs this job **every hour, 24 hours a day**, gated only by `worker_research_enabled` — the "overnight" name is stale; there is no time-of-day gate at all (`cli.py:665`). This is stacked on top of the Render cron service's own every-2-hours schedule (`render.yaml:162-168`). Given the cross-cutting scheduling defect above, this job's actual production run frequency is roughly double what either schedule alone implies, with **overlapping/concurrent executions plausibly contending for the same database rows and the same Kraken API rate limits** — a far more consistent explanation for repeated timeouts than per-call cost, given the small worst-case budget (60s) for a single isolated run.
2. **(Secondary) Same single-pair-per-call N+1 pattern as equities**, low individual impact here purely because N is tiny.
3. **(Tertiary) Auto-execution re-invoked identically to the equity path** for any crypto proposal that clears guardrails.

### Remediation

This is the clearest case where **fixing the scheduling defect is the primary fix**, not adding timeout budget: collapse to one scheduler (recommend: delete the Render cron service, let the worker loop own this job, and add an explicit hourly-or-slower cadence that matches the job's actual intended frequency rather than firing unconditionally every cycle). Batch the 3 price calls into one request as a secondary, low-effort improvement. **Expected result:** eliminating overlap should resolve the majority of the reported timeouts for this specific job without any other change, since the per-call cost math does not support "slow calls" as the primary explanation.

---

## Job 3: `evidence-snapshot`

### Call graph
`cli.py:_run_named_job` → `api.py:capture_production_broker_snapshots` (lines 2946-2977).

### Stage-by-stage timing hypothesis

| Stage | External dependency | Timeout | Retry | Cost pattern |
|---|---|---|---|---|
| Alpaca portfolio | `get_account()`, `get_positions()`, `get_orders(status="all", limit=10)`, `get_activities("FILL")` | 20s each, `alpaca.py:56` | None | **4 sequential calls** |
| Kraken portfolio | `get_account()` (private), `get_positions()` → **internally calls `get_account()` again** (redundant, `broker_adapters.py:212-213`), `get_orders()` (private), `get_trade_history()` → **2 private calls** (`ClosedOrders` + `TradesHistory`) | 20s each | None | **≈5 sequential calls, one confirmed redundant** |
| Snapshot refresh (`refresh_founder_evidence_snapshots`) | Postgres only | DB statement timeout | — | Bounded, indexed reads across 4 periods (24h/1h/7d/30d), `LIMIT 100`/`50` with matching indexes — **not** a likely primary contributor |

**Worst case: 4 × 20s (Alpaca) + 5 × 20s (Kraken) = 180s — this alone equals the entire child-process boundary before any database work happens.** Any real-world latency short of a full timeout (i.e. "slow but responding") pushes this over budget directly; this job does not need every call to fail, it only needs the sum of response times across 9 sequential round-trips to exceed 180 seconds.

### Ranked root causes

1. **(Primary, high confidence) Unbatched, sequential broker/portfolio calls — up to 9 sequential external HTTP round-trips, each individually allowed up to 20s, with no overall per-job time budget.** This is a purely additive latency problem: nothing needs to be broken for this job to time out, ordinary network variance across 9 sequential calls is sufficient.
2. **(Secondary, easy fix) Redundant duplicate `get_account()` call inside Kraken's `get_positions()`** (`broker_adapters.py:212-213`) — the account payload is already available from the earlier direct call; this is one call that can be eliminated with no loss of information.

### Remediation

Fetch each broker's account/positions/orders/trade-history data with the account payload passed through once (removing the confirmed redundant Kraken call) and run the Alpaca and Kraken portfolio fetches **concurrently** rather than sequentially — they are independent brokers with no data dependency between them. **Expected result after remediation:** worst case drops from ~180s (9 sequential calls) to roughly the slowest single broker's ~4-5 sequential calls (~80-100s) run in parallel with the other broker, comfortably inside the 180s boundary even under degraded latency; removing the one redundant call trims one call's worth of margin on top of that.

---

## Job 4: Kraken startup reconciliation (`replay_persisted_kraken_evidence`)

### Call graph
`cli.py` (`run-worker` startup, lines 230-260) → `kraken_reconciliation.py:replay_persisted_kraken_evidence` (lines 443-472) → `replay_kraken_evidence` (lines 334-421).

### Stage-by-stage timing hypothesis

| Stage | External dependency | Cost pattern |
|---|---|---|
| Schema init | Postgres | Cheap, re-executed per fresh child process (per-process module cache, not persisted) |
| `bootstrap_kraken_order_ownership` | Postgres | Reads `ORDER_INTENT_LOCKS`/`MANAGED_TRADE_EXITS`, then **opens a fresh connection per row** via `register_kraken_order_ownership` |
| History read | Postgres | `SELECT ... FROM BROKER_TRADE_HISTORY WHERE broker='kraken' ORDER BY trade_history_id LIMIT 1000` — **no incremental cursor; re-reads up to 1,000 historical rows from scratch on every restart** |
| Per event (×up to 1,000): ownership check, canonical event record, fill record, aggregate refresh, case record, ledger fill | Postgres, **multiple fresh connections per event** | `_ownership()`, `reconcile_canonical_broker_event` (which itself opens several more connections internally via `record_canonical_event`, `_record_fill_if_present`, `_refresh_trade_aggregate`), `_record_case()`, `_record_ledger_fill()` |
| Per terminal trade found | Postgres | `_refresh_reconciled_result`, `_mark_managed_exit_reconciled`, `enqueue_learning_workflow` — further connections |

**This job makes zero live Kraken API calls** — `kraken_reconciliation.py:340` explicitly documents "no broker client or order path," confirmed by reading the function body. **Its cost is entirely database-connection overhead, not broker-API latency.**

### Ranked root causes

1. **(Primary, high confidence) Severe N+1-connections-per-row anti-pattern against a remote Postgres database.** Every helper in this call graph opens its own fresh `connect(db_path)` → `psycopg.connect(...)` rather than sharing one connection across the replay loop. Conservatively, each of up to 1,000 historical events triggers on the order of 5-8 separate physical TCP+TLS connection setups to the remote Supabase/Postgres instance. Even at a modest 20-50ms per connection setup over the network, 1,000 rows × ~6 connections is easily several thousand round trips — very plausibly the dominant, previously undiagnosed cost driver, independent of any external API.
2. **(Secondary) Full-history re-scan with no incremental cursor.** `LIMIT 1000` with no `WHERE updated_at > last_reconciled_at`-style filter means cost is proportional to *cumulative* trade history, not to *new* activity since the last run — and it grows with every trade the account ever makes. Because every worker restart computes a fresh scheduling bucket for this job (by design, so reconciliation re-validates on every deploy), **this full cost is paid on every single Render restart/deploy**, not periodically.
3. **(Tertiary) Redundant ownership bootstrap runs unconditionally on every replay call**, even though most of its writes are idempotent no-ops on repeat runs — it still pays full connection/query cost every time.

### Remediation

Thread a single open connection through the entire replay loop (and its helper functions) instead of opening a fresh connection per row per helper — this is a pure refactor within the existing architecture, requires no new infrastructure, and is very likely the single highest-leverage fix in this entire timeout investigation given it is pure overhead with zero corresponding external-latency benefit. Add a `last_reconciled_row_id`/timestamp cursor so restarts process only new rows since the last successful reconciliation, not the full history every time. **Expected result after remediation:** with connection reuse alone, 1,000-row reconciliation should drop from several thousand network round-trips to a handful (one connection, ~1,000 queries over it) — plausibly a 10-50x reduction in wall-clock time, very likely resolving the timeout without needing the cursor fix, though the cursor fix should still be done because the cost will otherwise grow unboundedly with trading history and re-pay itself on every restart.

---

## Summary: none of these four jobs require a longer timeout to fix

| Job | Primary root cause | Fix category | New infrastructure required? |
|---|---|---|---|
| `premarket-equity` | Unbatched sequential per-symbol calls, no time budget | Batching + elapsed-time guard | No |
| `overnight-crypto` | Duplicate scheduling causing overlap, not per-call cost | Scheduling fix (delete duplicate cron trigger) | No |
| `evidence-snapshot` | Unbatched sequential broker calls (9 round-trips), one redundant call | Parallelize + remove redundant call | No |
| Kraken startup reconciliation | Connection-per-row anti-pattern, no incremental cursor | Connection reuse + cursor | No |

Every root cause identified here is a code-level defect fixable within the existing single-API/single-worker/Postgres-backed architecture. Raising the 180-second boundary would mask all four of these without fixing any of them, and would directly contradict the review brief's explicit instruction not to recommend that.
