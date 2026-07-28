# Critical Remediation Plan

Companion document to `CLAUDE_INDEPENDENT_ARCHITECTURE_REVIEW.md`. Ranked implementation plan using the required priority scheme:

- **P0** — blocks dependable operation or safety
- **P1** — blocks production confidence
- **P2** — important before larger capital
- **P3** — desirable later

Items are grouped by priority; within a priority, roughly in recommended implementation order (earlier items unblock or de-risk later ones). Every item traces to a specific finding in the six-part forensic investigation behind this review.

---

## Phase 0 status (2026-07-28)

All five P0 items below are **IMPLEMENTED, locally tested (185 tests passing), NOT YET HOSTED-PRODUCTION-VERIFIED**. Per the Founder's completion standard (`architecture/FOUNDER_IMPLEMENTATION_PLAN.md` approval), this status — not "complete" — is deliberate: this development environment has no Postgres/Docker access, so hosted evidence is required before Phase 0 can be declared done and Seven Pillars work begins. Full detail in `governance/IMPLEMENTATION_LOG.md`'s 2026-07-28 entry, including the exact hosted-evidence checklist still outstanding.

---

## P0 — Blocks dependable operation or safety

### P0-1: Verify `LOGICAL_TRADES` / `LOGICAL_TRADE_EVENTS` / `LOGICAL_TRADE_FILLS` actually exist on the live Postgres database

**Status: implemented, locally tested, pending hosted verification.** The schema-creation gap is fixed in code (unconditional on both backends, cached per-process). The original ask in this item — directly querying the live database to check whether the tables already existed out-of-band — was not done, since this development environment has no access to the live Postgres instance. This is now moot for going forward (the code guarantees creation from here on) but the open historical question ("did earlier production runs ever have this table, and if not what does that imply about any pre-2026-07-28 evidence") remains unanswered and should be checked directly against the database.

**Problem:** These are the tables that compute gross/net P&L, determine terminal state, and feed learning. No application code path creates their schema on Postgres.

**Root cause:** `canonical_trades.py:_ensure_canonical_trade_schema()` (lines 90-92) only calls `initialize_canonical_trade_schema()` when `not uses_postgres()`. Every other schema module in the codebase (`operational_truth.py`, `production_spine.py`, `multi_broker.py`, `sprint6.py`, `always_on.py`, `production_evidence.py`) unconditionally creates its tables on both backends — this is the one module that doesn't follow that pattern. `initialize_canonical_trade_schema` is also absent from `LocalApiService.__init__`'s startup schema-initialization list (`api.py:238-280`), and no Dockerfile step or migration script creates it either.

**Exact code areas:** `src/ai_trader/canonical_trades.py:90-92`, `src/ai_trader/api.py:238-280`, `src/ai_trader/kraken_reconciliation.py:160-165` (same guard pattern).

**Implementation approach:**
1. Before writing any code: connect directly to the live Supabase/Postgres database and check whether `logical_trades`, `logical_trade_events`, `logical_trade_fills` exist. This single query resolves whether this is a live production bug or dormant risk.
2. If the tables are missing: remove the `if not uses_postgres()` guard so `initialize_canonical_trade_schema()` runs unconditionally, following the same pattern already used by `operational_truth.py`/`production_spine.py`. Add the call to `LocalApiService.__init__`'s startup list.
3. If the tables exist (created out-of-band): still fix the code path, because it means schema creation is currently undocumented and unreproducible from a fresh deploy — a disaster-recovery risk in its own right.

**Dependencies:** None — this can and should be done first, before any other execution-path work, since every downstream fix in this plan assumes these tables are real.

**Acceptance evidence:** A fresh Postgres database, provisioned from scratch and pointed at by `DATABASE_URL`, has all three tables present after running `serve-api` or `run-worker` once, with no manual SQL required. A live `execution_intent` write (Stage 8 of the lifecycle trace) succeeds without a "relation does not exist" error.

**Regression risks:** Low — this is closing a gap, not changing existing behavior on backends where the tables already exist (SQLite dev/test is unaffected since it already creates them).

---

### P0-2: Add duplicate-order protection to the exit-order path

**Status: implemented and locally tested**, including the specific acceptance test this item calls for (kill-mid-flight simulation) plus two additional tests (shared lock between the automatic and founder-forced exit paths; lock release on definite rejection so a legitimate retry is never permanently blocked). Hosted-production confirmation (a real duplicate-attempt drill against the deployed worker) is still outstanding.

**Problem:** `monitor_managed_exits` and `force_managed_exit` call `adapter.place_exit_order` directly, with no equivalent of the `acquire_order_intent_lock` that protects entry orders. Combined with the worker's own SIGTERM→SIGKILL timeout-kill mechanism, a process killed between broker acceptance and the local `mark_managed_exit_submitted` write leaves the position `status='open'`, which the next cycle will re-evaluate and can re-submit. Kraken's `userref` is a client-side tag only, not an exchange-side idempotency key — this is not backstopped at the broker.

**Root cause:** The exit path was implemented as a direct broker call without carrying over the intent-lock pattern already proven correct on the entry path.

**Exact code areas:** `src/ai_trader/api.py:2695-2792` (`monitor_managed_exits`), `src/ai_trader/api.py:2794-2859` (`force_managed_exit`), compare to the protected pattern at `src/ai_trader/orchestrator.py:268-290`, and the lock primitive itself at `src/ai_trader/multi_broker.py:688-712`.

**Implementation approach:** Before calling `adapter.place_exit_order`, acquire a DB-level lock keyed on `(broker, client_order_id)` using the same `acquire_order_intent_lock`/`ORDER_INTENT_LOCKS` mechanism entries already use, with `client_order_id` derived deterministically from `managed_exit_id` (already computed at `api.py:2753`/`api.py:2822`). Only proceed to the broker call if the lock is acquired; release/complete it after the broker responds, mirroring `orchestrator.py:267-290`'s sequencing exactly.

**Dependencies:** None.

**Acceptance evidence:** A test that starts an exit, kills the process after the mock broker call succeeds but before the DB write, restarts, and verifies the next `managed-exits` cycle does NOT resubmit — mirroring the existing `test_orchestrator.py:test_approve_and_execute_style_call_blocks_duplicate_order_intent` pattern but for the exit path. In hosted production: a job-run history showing no two `exit_submitted` broker calls for the same `managed_exit_id`.

**Regression risks:** Must confirm this does not delay or block a genuinely time-critical stop-loss exit (e.g. lock acquisition failing open vs. closed needs an explicit decision — recommend failing closed with an immediate retry on the next cycle rather than skipping the exit entirely, since a missed exit is worse than a delayed one).

---

### P0-3: Eliminate duplicate scheduling between Render cron services and the always-on worker loop

**Status: implemented via the primary recommended approach** (deleted the six overlapping cron services from `render.yaml` rather than the alternative of unifying idempotency-key computation). Cannot be locally tested (it's a deployment-topology change); hosted confirmation is a `SCHEDULED_JOB_RUNS` query after deploy showing exactly one execution per job per intended cadence window.

**Problem:** The same job names (`premarket-equity`, `overnight-crypto`, `market-close-equity`, `daily-report`) are independently triggered by both a Render cron service and the worker's internal scheduler, and the idempotency key does not collide between them because each computes a different `scheduled_for` string. Today this doubles API cost and produces confusing duplicate evidence; the moment any `*_AUTO_TRADING` flag is enabled, it becomes a duplicate-proposal / duplicate-live-order risk, because `proposal_id` is a fresh UUID with no content fingerprint and two independently-generated proposals for the same signal are not recognized as duplicates by any code path.

**Root cause:** Two independently-evolved scheduling mechanisms exist for historical reasons (cron services likely predate or were built in parallel with the always-on worker's internal scheduler) and were never reconciled.

**Exact code areas:** `render.yaml:130-176` (the five overlapping cron service definitions), `src/ai_trader/cli.py:653-679` (`_due_worker_jobs`), `src/ai_trader/cli.py:100` (`run-job` not passing `--scheduled-for`), `src/ai_trader/always_on.py:311-378` (`claim_scheduled_job`).

**Implementation approach (recommended, matches Founder's stated preference not to add infrastructure):** Delete the overlapping Render cron services (`ai-trader-premarket-equity`, `ai-trader-overnight-crypto`, `ai-trader-market-close-equity`) from `render.yaml` and let the always-on worker's `_due_worker_jobs` be the sole trigger for jobs it already covers, extending its window logic if any real cadence gap exists (e.g. `market-open-equity`/`midday-equity` if not already covered). Keep cron services only for jobs the worker loop does not schedule at all (`daily-learning`, `weekly-report`, `monthly-report`). **Alternative if cron must remain for operational-visibility reasons:** make `scheduled_for` bucketing identical between both callers — compute the time-bucket string server-side inside `claim_scheduled_job` itself rather than trusting the caller-supplied value, so the existing `UNIQUE` constraint actually deduplicates as the architecture docs already (incorrectly) claim it does.

**Dependencies:** Should be done alongside P0-4 (timeout parity) if the cron path is kept for any job.

**Acceptance evidence:** Over a 24-hour hosted production window, `SCHEDULED_JOB_RUNS` shows exactly one execution of each equity/crypto research job per intended cadence window, not two. `overnight-crypto`'s actual run frequency matches its configured cadence, not double it.

**Regression risks:** If cron services are deleted, confirm Render's cron-service deletion doesn't affect any monitoring/alerting the Founder currently relies on the cron service names for (e.g. Render dashboard visibility) — a cosmetic consideration, not a functional one.

---

### P0-4: Fix the two identified timeout root causes with the highest confirmed impact

**Status: implemented and locally tested (behavior-preserving on SQLite — full suite passes); wall-clock/connection-count improvement not measurable without a real Postgres instance.** (a) Connection reuse implemented across the entire `replay_kraken_evidence` call graph, including the shared `canonical_trades.py` reconciliation functions (threaded via an optional `conn` parameter, defaulting to the prior per-call-connection behaviour for every other caller, so this could not have regressed the Alpaca reconciliation path in `sprint6.py`). The secondary improvement (an incremental cursor so restarts don't reprocess full history) was deliberately deferred — connection reuse alone is expected to resolve the timeout per this document's own root-cause ranking, and adding a schema migration inside the P0 safety gate was judged higher regression risk than the value of doing it now; tracked as a P1/P2 follow-up. (b) Redundant Kraken `get_account()` call removed; Alpaca/Kraken snapshot fetch parallelized, gated to Postgres only so SQLite (local dev/tests) isn't exposed to lock-contention risk from concurrent writers.

**Problem:** See `PRODUCTION_TIMEOUT_ROOT_CAUSE_ANALYSIS.md` for full detail. Two fixes stand out as highest-confidence, lowest-effort, highest-impact:

**(a) Kraken startup reconciliation's connection-per-row anti-pattern.**
- **Root cause:** Every helper function in the replay loop (`_ownership()`, `record_canonical_event`, `_record_fill_if_present`, `_refresh_trade_aggregate`, `_record_case()`, `_record_ledger_fill()`) opens its own fresh `connect(db_path)` rather than sharing one connection across the loop, multiplying into thousands of network round-trips for a 1,000-row replay.
- **Exact code areas:** `src/ai_trader/kraken_reconciliation.py:334-421` (`replay_kraken_evidence`) and its called helpers; `src/ai_trader/database.py:39-53` (`connect()`).
- **Implementation approach:** Thread a single open connection as a parameter through the entire replay loop and its helper functions instead of each one calling `connect(db_path)` independently. Add a `last_reconciled_row_id`/timestamp cursor to `BROKER_TRADE_HISTORY` querying (`kraken_reconciliation.py:449-459`) so restarts process only rows since the last successful reconciliation, not the full history from scratch every time.
- **Acceptance evidence:** Kraken startup reconciliation completes within its 180s boundary in hosted production for at least 5 consecutive worker restarts, with a persisted duration metric confirming the improvement (see P1-1 for instrumentation).
- **Regression risk:** Low — pure refactor of connection lifecycle, no change to reconciliation logic or idempotency guarantees.

**(b) `evidence-snapshot`'s unbatched sequential broker calls.**
- **Root cause:** Up to 9 sequential broker HTTP round-trips (4 Alpaca + 5 Kraken, including one confirmed redundant duplicate `get_account()` call inside Kraken's `get_positions()`), each individually allowed 20s, with no overall job time budget — worst case alone equals the full 180s boundary.
- **Exact code areas:** `src/ai_trader/api.py:2946-2977` (`capture_production_broker_snapshots`), `src/ai_trader/api.py:3387-3527` (`_live_alpaca_portfolio`, `_exchange_portfolio`), `src/ai_trader/broker_adapters.py:212-213` (the redundant call).
- **Implementation approach:** Remove the redundant `get_account()` call inside `get_positions()` by passing the already-fetched account payload through. Fetch the Alpaca and Kraken portfolios concurrently (they are independent, no shared data dependency) rather than sequentially.
- **Acceptance evidence:** `evidence-snapshot` completes within its 180s boundary in hosted production for at least 5 consecutive cycles.
- **Regression risk:** Low — concurrency introduced only between two independent brokers' read-only calls; no shared mutable state between them at this stage.

**Dependencies:** None; can proceed in parallel with P0-1 through P0-3.

---

### P0-5: Wire push notifications into a code path the production topology actually runs

**Status: implemented and locally tested** (job dispatch verified via a direct unit test; the actual Expo push send itself was already tested previously and is unchanged). Hosted confirmation requires a real device with a registered push token and a deliberately-triggered notification after deploy.

**Problem:** `dispatch_pending_push_notifications` is fully implemented and correctly integrated with Expo push, but it is only registered inside the code branch that `AI_TRADER_DISABLE_API_BACKGROUND_WORKERS=true` (set identically on every Render service via the shared env anchor) disables. No other call site exists anywhere in the codebase. Every incident and notification is durably recorded in the database; none currently reach the Founder's phone proactively. For a system whose entire value proposition is autonomous, always-on operation, this means every other safeguard in this plan degrades from "the system will alert you" to "the system will tell you if you open the app and ask."

**Root cause:** The push-dispatch registration was written as part of the API service's own background-worker set (`api.py:4051-4109`), which made sense before `AI_TRADER_DISABLE_API_BACKGROUND_WORKERS` was introduced to prevent the API process from duplicating the dedicated worker's job execution — but push dispatch was never moved into the dedicated worker's own job table when that flag was set to `true` everywhere.

**Exact code areas:** `src/ai_trader/api.py:4051-4109` (dead branch in production), `src/ai_trader/multi_broker.py:655-671` (`send_expo_push`, the actual sender — unaffected, just unreached), `src/ai_trader/cli.py:_run_named_job` (the worker's job dispatch table, where a new job should be added).

**Implementation approach:** Add `push-dispatch` (or fold it into an existing frequent job, e.g. `broker-poll` or a new lightweight cycle) to the always-on worker's job table in `cli.py`, calling `dispatch_pending_push_notifications` on a short interval (30-60s is reasonable given it's a lightweight DB-scan-and-send operation). Remove or clearly mark as dead the now-redundant registration in `api.py:4051-4109` if `AI_TRADER_DISABLE_API_BACKGROUND_WORKERS` will remain `true` in every hosted environment going forward.

**Dependencies:** None.

**Acceptance evidence:** A deliberately-triggered test incident (e.g. force a broker outage in a controlled way, or use the existing `/force-managed-exit` on a test position) results in a push notification arriving on the Founder's device within the configured dispatch interval, without opening the app first. `NOTIFICATION_EVENTS` rows show `delivered_at` populated, not perpetually null.

**Regression risks:** Low — this activates dormant, already-tested sending logic; the main risk is notification volume/noise, which should be tuned via the existing severity filtering already present in `record_notification`.

---

## P1 — Blocks production confidence

### P1-1: Instrument stage-level duration for the previously-timing-out jobs

**Problem:** Without persisted stage-level timing, future regressions in these jobs will be as hard to diagnose as this one was.

**Exact code areas:** `src/ai_trader/api.py:run_analysis`, `run_crypto_analysis`, `capture_production_broker_snapshots`; `src/ai_trader/kraken_reconciliation.py:replay_kraken_evidence`.

**Implementation approach:** Record elapsed time for each external-call phase (market data, news, OpenAI, per-broker portfolio fetch, DB read/write) into the existing job-run evidence structure (`SCHEDULED_JOB_RUNS.payload_json` or a new `JOB_STAGE_TIMINGS` table), so a future timeout can be diagnosed from persisted evidence rather than requiring another full forensic pass.

**Dependencies:** Should land alongside or immediately after P0-4 so the fixes can be measured.

**Acceptance evidence:** A `job-runs` query for any of these four jobs shows a stage-by-stage duration breakdown, not just a single total duration and pass/fail result.

**Regression risks:** None if implemented as additive logging.

---

### P1-2: Reconcile the two independent canonical-trade-lifecycle subsystems

**Problem:** `canonical_trades.py` (`LOGICAL_TRADES`, written at order-placement time) and `operational_truth.py` (`CANONICAL_TRADE_LIFECYCLE`, written at reconciliation time) both claim to be the authoritative trade lifecycle, are populated from different entry points, and are never cross-checked. `trading_intelligence.py`'s `TRADE_LIFECYCLE` is a third, decision-stage-only log. The architecture documentation's claim of "one" canonical lifecycle does not match the code.

**Exact code areas:** `src/ai_trader/canonical_trades.py:15-81`, `src/ai_trader/operational_truth.py:77-96,204-328`, `src/ai_trader/trading_intelligence.py:97-114,1086-1131`.

**Implementation approach:** Decide which table is authoritative for lifecycle *stage* (recommend `operational_truth.CANONICAL_TRADE_LIFECYCLE`, since it has the real state-machine with legal-transition validation) versus which is authoritative for the *P&L aggregate* (recommend `canonical_trades.LOGICAL_TRADES`, since it's fill-weighted and feeds learning correctly). Add an explicit cross-reference (`LOGICAL_TRADES.canonical_lifecycle_id` or equivalent) and a periodic consistency check that raises an incident if the two disagree on whether a trade is open/closed. Retire or clearly deprecate `trading_intelligence.TRADE_LIFECYCLE` if its decision-stage logging is fully subsumed by the other two.

**Dependencies:** Should follow P0-1 (confirming `LOGICAL_TRADES` exists on Postgres).

**Acceptance evidence:** A single trade's lifecycle can be traced through one consistent state model, with a passing test that deliberately desynchronizes the two tables and confirms an incident is raised.

**Regression risks:** Medium — touches multiple call sites; should be done incrementally with the consistency check added first (non-invasive) before any consolidation of the tables themselves.

---

### P1-3: Reconcile the two independent P&L calculations

**Problem:** `multi_broker.close_managed_exit_and_record` computes P&L via single entry/exit price; `canonical_trades._refresh_trade_aggregate` computes it via fill-weighted average. These can diverge under partial fills, with no cross-check, and both are surfaced to the Founder (the former via `/performance-attribution`, the latter via `/founder-evidence`).

**Exact code areas:** `src/ai_trader/multi_broker.py:870-968` (`close_managed_exit_and_record`), `src/ai_trader/canonical_trades.py:447-503` (`_refresh_trade_aggregate`).

**Implementation approach:** Make `PERFORMANCE_ATTRIBUTION` a read of `LOGICAL_TRADES`' authoritative fill-weighted P&L rather than an independent recomputation — a single source of truth, one calculation, two consumers.

**Dependencies:** P0-1, P1-2.

**Acceptance evidence:** A test with multiple partial entries/exits confirms `/performance-attribution` and `/founder-evidence` report identical P&L for the same trade.

**Regression risks:** Low-medium — requires confirming no downstream consumer depends on `PERFORMANCE_ATTRIBUTION`'s specific (currently divergent) calculation method.

---

### P1-4: Fix the mobile app's staleness-blind "Last refreshed" header and the Activity timeline contract mismatch

**Problem:** The always-visible Dashboard header timestamp reflects HTTP fetch success time, not the age of the underlying worker-owned evidence snapshot the backend already computes (`snapshot.age_seconds`/`snapshot.stale`) — it can read as fresh while the data is many minutes stale. Separately, the Activity screen's timeline drill-down renders literal `"undefined #undefined"` and a hardcoded false "Raw Evidence: Not available" because the mobile app expects six fields (`detailed_reason`, `source_table`, `source_record_id`, `raw_evidence_available`, `founder_action_required`, `asset_or_symbol`) that `production_evidence.py:_timeline()` has never populated.

**Exact code areas:** `mobile/App.js:619,634,827` (header timestamp), `mobile/App.js:1141-1163` (timeline rendering), `src/ai_trader/production_evidence.py:517-557` (`snapshot` fields, already computed), `src/ai_trader/production_evidence.py:976-986` (`_timeline()`, missing fields).

**Implementation approach:** Have the mobile header read `evidence.snapshot.age_seconds`/`.stale` and display an explicit age (e.g. "42 minutes old") instead of client-fetch time. Extend `_timeline()` to populate the six fields the mobile UI already expects, or (if those fields are genuinely not meaningful for every event type) update the mobile UI to only render them when present, guarded by `notAvailable()`-style checks that actually catch the empty/placeholder case rather than an already-interpolated string.

**Dependencies:** None.

**Acceptance evidence:** Manually staling a snapshot (stop the worker, wait past the 15-minute threshold) shows a header that says "X minutes old," not "just now." No Activity timeline row renders the literal string "undefined."

**Regression risks:** Low — additive/corrective UI change.

---

### P1-5: Fix the portfolio-total silent-zero-on-broker-failure bug

**Problem:** `_portfolio_payload`'s aggregate sum guard checks whether the broker list is non-empty, not whether every broker in it actually reported a real value — a failed broker snapshot contributes an unflagged `$0` to the Founder-facing total.

**Exact code areas:** `src/ai_trader/production_evidence.py:900-909`.

**Implementation approach:** Change the aggregate to track and surface `partial: true`/a list of excluded brokers whenever any broker row lacks a `portfolio_value`/`cash` key, rather than silently summing `_number(None) or 0.0`.

**Dependencies:** None.

**Acceptance evidence:** A test that simulates one broker connection failure confirms the aggregate total is flagged incomplete, not silently understated.

**Regression risks:** Low.

---

### P1-6: Escalate permanently-failed learning workflows to an operational incident

**Problem:** A learning workflow that exhausts its 3 retries is only logged via `record_operational_event`, which never reaches `OPERATIONS_INCIDENTS` and therefore never flips the top-level "attention needed" status the Founder relies on.

**Exact code areas:** `src/ai_trader/sprint6.py:815-831`.

**Implementation approach:** Call `record_operations_incident` (not just `record_operational_event`) when a workflow is marked `status='failed'` after exhausting retries.

**Dependencies:** P0-5 (so the resulting incident actually gets pushed to the Founder, not just recorded).

**Acceptance evidence:** A deliberately-failing learning workflow (3 forced failures) results in an entry in `OPERATIONS_INCIDENTS` and a flipped `operations_health` status.

**Regression risks:** None.

---

### P1-7: Rotate the exposed Founder API token and close the disclosure vector

**Problem:** The Founder command token was disclosed during manual troubleshooting. Traced to `scripts/configure_control_token.ps1`'s `-ShowToken` switch, which prints the full raw token to the console by default when passed.

**Exact code areas:** `scripts/configure_control_token.ps1:94-97`, `render.yaml:9-10` (`AI_TRADER_API_TOKEN`), mobile build env (`EXPO_PUBLIC_AI_TRADER_API_TOKEN`).

**Implementation approach:** Regenerate the token via the script without `-ShowToken`; update the Render env var; redeploy; rebuild and redistribute the mobile app with the new token. Remove the `-ShowToken` switch from the script, or gate it behind an explicit additional confirmation that makes accidental use much harder.

**Dependencies:** None — can be done immediately, independent of all other items.

**Acceptance evidence:** The old token no longer authenticates against the API (`_authorized()` rejects it); the new token is not present in any chat transcript, screenshot, or committed file going forward.

**Regression risks:** None if the mobile app is rebuilt in lockstep with the rotation (a stale mobile build with the old token will simply fail auth until updated).

---

## P2 — Important before larger capital

### P2-1: Add `client_order_id` to Alpaca order payloads

**Problem:** `AlpacaBrokerAdapter.place_order`/`AlpacaPaperClient.place_bracket_order` never send `client_order_id` to the broker despite it being populated upstream and despite Alpaca supporting it as a genuine exchange-side idempotency key — the only protection today is the application's own DB lock, with no broker-side backstop.

**Exact code areas:** `src/ai_trader/broker_adapters.py:90-98`, `src/ai_trader/alpaca.py:101-120`.

**Implementation approach:** Include `client_order_id` in the outbound order payload.

**Acceptance evidence:** A captured outbound Alpaca request shows the field populated; a deliberate duplicate submission with the same ID is rejected by Alpaca itself, not just by the local lock.

**Regression risks:** Low.

---

### P2-2: Add a periodic scan for orphaned Kraken orders

**Problem:** If the process is killed between a Kraken order's broker acceptance and the local ownership-linking write, the order becomes permanently unmanaged, unmonitored for exits, and excluded from learning — and the existing recovery function (`bootstrap_kraken_order_ownership`) structurally cannot recover it, since its own filter excludes rows with no recorded broker order ID.

**Exact code areas:** `src/ai_trader/orchestrator.py:254-354`, `src/ai_trader/kraken_reconciliation.py:264-331` (`bootstrap_kraken_order_ownership`), `src/ai_trader/kraken_reconciliation.py:723-732` (`_ownership`).

**Implementation approach:** Add a reconciliation pass (can run as part of the existing `broker-poll` or `kraken-startup-reconciliation` job) that compares the broker's live open orders/positions against `KRAKEN_AI_ORDER_OWNERSHIP`/`MANAGED_TRADE_EXITS`, and raises an operational incident for any broker-side position with no matching ownership record — rather than silently classifying it `"unmanaged_excluded"` as if it were a pre-existing personal holding.

**Dependencies:** P0-2 (reduces how often this can happen going forward) and P0-5 (so the incident is actually surfaced).

**Acceptance evidence:** A deliberately-orphaned order (simulated in a test by writing a broker fill with no corresponding ownership row) is detected and raises an incident rather than being silently reclassified.

**Regression risks:** Low — additive detection only.

---

### P2-3: Fix `/status` and `/developer-status`'s structurally-wrong `engine_health`/`sqlite` fields

**Problem:** These fields check `settings.db_path.exists()`, which is meaningless in Postgres mode and will always report "Database not initialized" on every deployed Render instance, regardless of real database health.

**Exact code areas:** `src/ai_trader/api.py:735`, `src/ai_trader/api.py:1907,1915`.

**Implementation approach:** Replace the file-existence check with a real Postgres connectivity check (a lightweight `SELECT 1`) when the backend is Postgres.

**Acceptance evidence:** `/developer-status` reports accurate database health in the Postgres-backed deployment.

**Regression risks:** None.

---

### P2-4: Deprecate or fix the legacy `/status`/`/brokers` live-broker-fan-out endpoints

**Problem:** These endpoints perform the same expensive, unbatched, sequential live-broker-call pattern implicated in the `evidence-snapshot` timeout, on every request, and duplicate ~150 lines of Founder-experience business logic that also exists independently on the mobile client.

**Exact code areas:** `src/ai_trader/api.py:686-773` (`status()`), `src/ai_trader/api.py:2979-3486` (`broker_panels`, `_exchange_portfolio`).

**Implementation approach:** Since the shipped mobile app no longer calls these endpoints (confirmed — it exclusively uses `/founder-evidence`), either retire them or have them read from the same cached snapshot `/founder-evidence` uses rather than performing their own live fan-out.

**Dependencies:** None.

**Acceptance evidence:** No production code path performs the 9-sequential-broker-call pattern outside the now-optimized `evidence-snapshot` job itself.

**Regression risks:** Low — confirm no external tooling/scripts the Founder uses still depend on `/status`'s specific response shape before retiring it; safer to redirect it to the cached data first, remove later.

---

### P2-5: Populate or honestly hide the structurally-dead Learning/Market screen sections

**Problem:** Strategy rankings, signal rankings, sector rotation, and major themes are fully built UI sections that are permanently empty because the client-side derivation hardcodes empty arrays/nulls — not because there's no data yet.

**Exact code areas:** `mobile/App.js:394-418`.

**Implementation approach:** Either wire these fields to real backend data (if the underlying research/intelligence tables the review references — `market_intelligence_platform.py`, `portfolio_intelligence.py` — already compute equivalent data), or remove the dead UI sections so the Founder isn't shown permanently-empty panels that look like a loading/data problem.

**Acceptance evidence:** These sections either show real data or are removed from the shipped build.

**Regression risks:** None either way; this is a truthfulness fix, not a functional one.

---

## P3 — Desirable later

### P3-1: Paginate broker activity/trade-history fetches

**Problem:** `AlpacaPaperClient.get_activities()` and Kraken's `get_trade_history()` both fetch a single page only, with no cursor — a worker outage spanning more than one page of fills could permanently drop a trade from ever being learned from. Not yet a live risk at current trading volumes, but structural.

**Exact code areas:** `src/ai_trader/alpaca.py:73-81`, `src/ai_trader/broker_adapters.py:237-257`.

**Implementation approach:** Add cursor/pagination handling, or at minimum track a high-water mark per broker so a resumed poll after a long outage backfills correctly instead of silently starting from "now."

---

### P3-2: Add a database-level fencing check to prevent a late child-process completion from overwriting a parent-recorded timeout

**Problem:** A child job process can, in a narrow race window, write `status="completed"` to a `SCHEDULED_JOB_RUNS` row the parent has already marked `timed_out`, producing an inconsistent audit trail.

**Exact code areas:** `src/ai_trader/cli.py:466-472` (parent's timeout write), `src/ai_trader/cli.py:374,386` (child's completion write).

**Implementation approach:** Add an optimistic-concurrency check (e.g. `UPDATE ... WHERE status = 'running'`) so a write only succeeds if the row is still in the expected prior state.

---

### P3-3: Broaden `.gitignore` to cover root-level `*.sqlite3` files

**Problem:** `.gitignore` covers `data/*.sqlite3` but not root-level SQLite files, which is why `unused.sqlite3` (a confirmed local-dev/test artifact, not reachable from production) currently shows as untracked at the repo root.

**Implementation approach:** Add `*.sqlite3` (unscoped) to `.gitignore`.

---

### P3-4: Give the cron-triggered `run-job` path the same timeout wrapper as the worker-loop path

**Problem:** Only jobs triggered by the worker loop get the 180-second child-process boundary; cron-triggered jobs (if any cron services remain after P0-3) can hang indefinitely.

**Exact code areas:** `src/ai_trader/cli.py:347-396` (`run-job` handler, currently calls `_run_named_job` directly with no timeout wrapper).

**Implementation approach:** Route `run-job` through the same `_run_worker_cycle_job(..., restart_worker_on_timeout=True)` path the worker loop uses.

**Note:** Becomes lower priority if P0-3 removes the overlapping cron services entirely, but should still be done for any cron service that remains (`daily-learning`, `weekly-report`, `monthly-report`).
