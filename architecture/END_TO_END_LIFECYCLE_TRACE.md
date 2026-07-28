# End-to-End Lifecycle Trace: Market Data → Terminal Learning

Companion document to `CLAUDE_INDEPENDENT_ARCHITECTURE_REVIEW.md`. Traces the full required lifecycle (market data → research → recommendation → strategy maturity → Portfolio Manager → Risk Engine → Production Risk Sentinel → execution intent → broker submission → acknowledgement → fill → canonical position → managed exit → exit fill → canonical closed trade → fees/slippage → gross/net P&L → attribution → MAE/MFE → R multiple → automatic learning → Founder-visible explanation) stage by stage, with owning component, source/destination tables, canonical identifier, failure handling, retry behaviour, observability, and proof status.

Proof-status vocabulary used throughout: `NOT PROVEN`, `IMPLEMENTED BUT NOT END-TO-END PROVEN`, `HOSTED PRODUCTION PROVEN` — the last one only where `architecture/CURRENT_OPERATIONS_RECOVERY_REPORT_2026-07-27.md` or another dated architecture doc cites a specific persisted record (job ID, timestamp, count), not a prose assertion.

---

## Stage 1 — Market data

- **Owning component:** `alpaca.py` (`AlpacaPaperClient.get_latest_bars`), `broker_adapters.py` (`KrakenBrokerAdapter.current_prices`).
- **Source:** Alpaca Data API / Kraken public REST API.
- **Destination:** Not persisted independently — consumed in-process by `agent.py`'s proposal generation.
- **Canonical identifier:** None (transient input).
- **Failure handling:** 20-second `urlopen` timeout, **no retry, no backoff** (`alpaca.py:56`, `broker_adapters.py:395,418`).
- **Retry behaviour:** None.
- **Observability:** Only indirectly, via the enclosing job's completion/timeout status.
- **Proof status:** `IMPLEMENTED BUT NOT END-TO-END PROVEN` for a specific successful pull in the current reporting window; historically `HOSTED PRODUCTION PROVEN` for 2026-07-20 (`PRODUCTION_EVIDENCE_LIVE_VERIFICATION.md:40`: "four research runs, 36 assets analysed"), but that evidence is 7 days stale and predates the currently-reported research timeouts.
- **Known gap:** Called once per symbol rather than once per batch (`api.py:2026-2036`), multiplying external round-trips unnecessarily — see `PRODUCTION_TIMEOUT_ROOT_CAUSE_ANALYSIS.md`.

## Stage 2 — Research

- **Owning component:** `api.py:run_analysis` (equity) / `run_crypto_analysis` (crypto), calling into `agent.py:AITradingAgent.propose_trades`/`propose_crypto_trades`.
- **Source:** Market data (Stage 1) + news retrieval (`alpaca.py` news endpoint) + OpenAI proposal analysis (`ai.py`).
- **Destination:** `PRODUCTION_RESEARCH_EVIDENCE`, `RESEARCH_FUNNELS` (`production_evidence.py`, `always_on.py`).
- **Canonical identifier:** Job run ID (`SCHEDULED_JOB_RUNS.job_run_id`) links a research cycle to its evidence rows.
- **Failure handling:** Whole-job 180-second boundary (worker-loop path only — see Stage-scheduling note below); no internal per-stage checkpoint, so a mid-batch timeout discards all progress for that cycle.
- **Retry behaviour:** Next scheduled occurrence only; no immediate retry of a failed/timed-out cycle.
- **Observability:** `SCHEDULED_JOB_RUNS` row with `result` (`completed`/`timed_out`/`failed`).
- **Proof status:** `NOT PROVEN` for the current reporting window — the recovery report cites `premarket-equity` (Job 7950) and `overnight-crypto` (Job 7949) as `timed out` (`CURRENT_OPERATIONS_RECOVERY_REPORT_2026-07-27.md:165-166`), with no completed-research row cited anywhere in that report. Historically `HOSTED PRODUCTION PROVEN` for 2026-07-20 only.
- **Known gap:** Root cause of the timeout is a specific, fixable N+1 sequential external-call pattern — see `PRODUCTION_TIMEOUT_ROOT_CAUSE_ANALYSIS.md`. **Scheduling note:** this stage is also subject to duplicate triggering from both the Render cron service and the always-on worker's internal scheduler, which compute different idempotency keys and therefore do not deduplicate against each other (`render.yaml` vs. `cli.py:_due_worker_jobs`).

## Stage 3 — Recommendation

- **Owning component:** `agent.py` (proposal construction), persisted via `api.py`.
- **Source:** Research output (Stage 2).
- **Destination:** `PRODUCTION_RECOMMENDATION_EVIDENCE`, proposal store consumed by `orchestrator.py`.
- **Canonical identifier:** `proposal_id` (fresh UUID per proposal, `models.py:68`) — this is the identifier that (mostly) threads through the rest of the lifecycle.
- **Failure handling:** N/A — a recommendation is a data artifact, not an external call.
- **Retry behaviour:** N/A.
- **Observability:** `PRODUCTION_RECOMMENDATION_EVIDENCE` rows, surfaced via `/founder-evidence`.
- **Proof status:** `NOT PROVEN` for the current reporting window (no recommendation ID/count cited in the 2026-07-27 report). Historically `HOSTED PRODUCTION PROVEN` for 2026-07-20 ("24 recommendations," `PRODUCTION_EVIDENCE_LIVE_VERIFICATION.md:40`).
- **Known gap:** Because `proposal_id` is a fresh random UUID with no content-based fingerprint, two independently-generated proposals for the same underlying signal (e.g. from duplicate-scheduled research runs) are not recognized as duplicates by any downstream code path.

## Stage 4 — Strategy maturity

- **Owning component:** `sprint6.py:strategy_entitlement_decision`.
- **Source:** `STRATEGY_MATURITY_REGISTRY`.
- **Destination:** `STRATEGY_ENTITLEMENT_DECISIONS`.
- **Canonical identifier:** `proposal_id` / strategy name.
- **Failure handling:** Fail-closed by default — the seeded registry defaults to `"Paper"` stage with `permitted_modes=["shadow","paper","manual"]`, which does **not** include `"micro_live"` (Kraken's real-money mode), so real Kraken trading is blocked by default until the registry is explicitly promoted through a documented, evidence-based process.
- **Retry behaviour:** N/A (synchronous gate).
- **Observability:** Decision row with pass/fail reason.
- **Proof status:** `IMPLEMENTED BUT NOT END-TO-END PROVEN` against a real recommendation in the current window (no research completing means no recommendation reaches this gate to observe).
- **Known gap:** Only applied inside the `orchestrator.py` alpaca/kraken allowlist branch — a hypothetical future broker adapter would not automatically pass through this gate; today this is a latent, not live, risk since no other adapter implements live order placement.

## Stage 5 — Portfolio Manager

- **Owning component:** `production_spine.py:portfolio_manager_decision`.
- **Source:** Current positions, allocation limits, proposal.
- **Destination:** `PORTFOLIO_MANAGER_DECISIONS`.
- **Canonical identifier:** `proposal_id`.
- **Failure handling:** Failure folds into the orchestrator's `failures` list, forcing `decision_text="rejected"` — cannot be silently skipped for entries on alpaca/kraken.
- **Retry behaviour:** N/A.
- **Observability:** Decision row, surfaced in evidence.
- **Proof status:** `IMPLEMENTED BUT NOT END-TO-END PROVEN` for the current window (same reasoning as Stage 4).
- **Known gap:** **Not applied to exit orders at all** — `monitor_managed_exits`/`force_managed_exit` bypass this component entirely (see Critical Finding #1 in the main review).

## Stage 6 — Risk Engine

- **Owning component:** `guardrails.py:validate_trade_proposal`, invoked both directly by the orchestrator and inside `sprint6.pre_execution_decision_packet`.
- **Source:** Proposal, account state, risk config (`MAX_RISK_PER_TRADE_PCT`, `MAX_DAILY_LOSS_PCT`, `MAX_OPEN_POSITIONS`).
- **Destination:** In-line rejection reason attached to the decision packet.
- **Canonical identifier:** `proposal_id`.
- **Failure handling:** Fail-closed; a rejection blocks the orchestrator from proceeding to broker submission.
- **Retry behaviour:** N/A.
- **Observability:** Rejection reason string in the decision packet, surfaced in `/founder-evidence`'s "why no trade" reasoning.
- **Proof status:** `IMPLEMENTED BUT NOT END-TO-END PROVEN` for the current window.
- **Known gap:** Same exit-order bypass as Stage 5, partially mitigated for Kraken specifically by a narrower, hardcoded adapter-level check inside `place_order` (stop-loss/take-profit presence, pair allowlist, GBP notional caps) — but that is not the Risk Engine itself.

## Stage 7 — Production Risk Sentinel

- **Owning component:** `sprint6.py:production_risk_sentinel_decision`.
- **Source:** Kill switch state, account equity, market-data quality flags, open incidents on broker/reconciliation/database/market-data components.
- **Destination:** In-line pass/fail in the decision packet.
- **Canonical identifier:** `proposal_id`.
- **Failure handling:** Fail-closed for entries.
- **Retry behaviour:** N/A.
- **Observability:** Decision reason surfaced in evidence.
- **Proof status:** `IMPLEMENTED BUT NOT END-TO-END PROVEN` for the current window.
- **Known gap:** The kill switch and this Sentinel **cannot stop an exit order** — `monitor_managed_exits`/`force_managed_exit` never consult it. This is arguably intentional (a kill switch shouldn't trap a position open), but it means "kill switch" does not mean "no order flow to the broker," only "no new entries."

## Stage 8 — Execution intent

- **Owning component:** `canonical_trades.py:register_execution_intent`, called from `orchestrator.py:254`.
- **Source:** A proposal that has passed Stages 4–7.
- **Destination:** `LOGICAL_TRADES` (state `execution_intent`).
- **Canonical identifier:** `logical_trade_id` (set equal to `proposal_id` at this stage — the point where the lifecycle's canonical ID is actually born).
- **Failure handling:** No try/except around this call in `orchestrator.py` — an exception here (e.g. a missing table) would propagate up into the enclosing job's exception handler, recorded as a job failure/incident, not silently swallowed.
- **Retry behaviour:** Governed by the enclosing job's own retry semantics, not this stage individually.
- **Observability:** `LOGICAL_TRADES` row.
- **Proof status:** `NOT PROVEN` — no execution intent has been cited with a specific record in any reviewed document. **Highest-priority open verification item from the entire review:** this table's schema is never created on Postgres by any application code path (see Critical Finding #6 in the main review) — whether it exists in the live Supabase database at all is unverified from this repository and should be checked directly before relying on anything downstream of this stage.

## Stage 9 — Broker submission

- **Owning component:** `broker_adapters.py` (`AlpacaBrokerAdapter.place_bracket_order`, `KrakenBrokerAdapter.place_order`), reached via `orchestrator.py:292` for entries.
- **Source:** Execution intent (Stage 8) + a DB-enforced duplicate-order lock (`multi_broker.py:acquire_order_intent_lock`, acquired *before* this call).
- **Destination:** Broker API (external).
- **Canonical identifier:** `client_order_id` (= `proposal_id`), sent to Alpaca; **not** sent by the Alpaca adapter in practice (finding: `broker_adapters.py:90-98` builds the payload without a `client_order_id` field despite one being available upstream — the broker-side idempotency net Alpaca offers is not actually used). Sent to Kraken as `userref`, which Kraken does **not** treat as a server-side dedupe key.
- **Failure handling:** 20-second timeout, no retry.
- **Retry behaviour:** None at this layer; the DB-level intent lock prevents the *application* from retrying a duplicate, but does not protect against a genuine ambiguous-response scenario (order accepted by the broker, response lost before the app records it).
- **Observability:** `ORDER_INTENT_LOCKS` row.
- **Proof status:** `NOT PROVEN` — explicitly, the recovery report states "no recent production evidence... proves that a new broker order was submitted or filled" (`CURRENT_OPERATIONS_RECOVERY_REPORT_2026-07-27.md:277`).
- **Known gap:** The exact window between broker acceptance and the local ownership-linking write (Stage 10) is where an order can become permanently orphaned — see Critical Finding #2 in the main review.

## Stage 10 — Broker acknowledgement

- **Owning component:** `orchestrator.py:294-354` (`link_broker_order`, `register_kraken_order_ownership`, `complete_order_intent_lock`, `record_managed_trade_exit`).
- **Source:** Broker's synchronous order-placement response.
- **Destination:** `KRAKEN_AI_ORDER_OWNERSHIP` / `LOGICAL_TRADES` update / `MANAGED_TRADE_EXITS`.
- **Canonical identifier:** `broker_order_id` (now linked to `logical_trade_id`).
- **Failure handling:** **No fencing/versioning on this write; if the process dies between Stage 9's broker response and this write completing, the order becomes untracked (Critical Finding #2).**
- **Retry behaviour:** None — this is a one-shot write with no idempotent replay path that specifically targets a missing ownership record (`bootstrap_kraken_order_ownership` explicitly excludes rows with no `result_order_id`).
- **Observability:** `KRAKEN_AI_ORDER_OWNERSHIP` row.
- **Proof status:** `NOT PROVEN`.
- **Known gap:** As above — this is the single most consequential unhandled restart-safety gap found in the review.

## Stage 11 — Fill (partial and complete)

- **Owning component:** `canonical_trades.py:_record_fill_if_present`, fed by `sprint6.py:normalize_broker_events` (non-Kraken) or `kraken_reconciliation.py:replay_kraken_evidence` (Kraken), both triggered by the `broker-poll` job.
- **Source:** `BROKER_TRADE_HISTORY` (itself populated by polling the broker's activity/trade-history endpoint).
- **Destination:** `LOGICAL_TRADE_FILLS`.
- **Canonical identifier:** `UNIQUE(broker, broker_fill_id)` — genuine fill-level idempotency, preventing double-counting of a re-polled fill.
- **Failure handling:** Individually committed inserts; a crash mid-loop leaves already-committed fills intact and simply resumes on the next poll (no double-counting on resume).
- **Retry behaviour:** Effectively continuous — every `broker-poll` cycle (default 600s) re-reads and re-reconciles.
- **Observability:** `LOGICAL_TRADE_FILLS` rows.
- **Proof status:** `NOT PROVEN` for the current window.
- **Known gap:** `AlpacaPaperClient.get_activities()` and Kraken's `get_trade_history()` both fetch a single page only (no pagination/cursor) — if the worker is down long enough for more than one page of fills to accumulate, older fills can roll off the window and be **permanently** unrecorded, never becoming a terminal trade and never triggering learning. Structural gap, not yet observed at current trading volumes.

## Stage 12 — Canonical position

- **Owning component:** `canonical_trades.py:_refresh_trade_aggregate`.
- **Source:** `LOGICAL_TRADE_FILLS` (entry-side).
- **Destination:** `LOGICAL_TRADES` (running `entry_filled_quantity`, `avg_entry_price`).
- **Canonical identifier:** `logical_trade_id`.
- **Failure handling:** Recomputed fully from fills on every call — self-healing, not incrementally stateful in a way that can drift.
- **Retry behaviour:** N/A (pure recomputation).
- **Observability:** `LOGICAL_TRADES` row.
- **Proof status:** `NOT PROVEN` for the current window.
- **Known gap:** This table's own existence on Postgres is unverified (Stage 8's gap applies here too — same table family).

## Stage 13 — Managed exit

- **Owning component:** `api.py:monitor_managed_exits` (worker job `managed-exits`) / `force_managed_exit` (Founder manual).
- **Source:** `MANAGED_TRADE_EXITS` rows with `status='open'`, current price vs. stop-loss/take-profit.
- **Destination:** Broker exit order + `MANAGED_TRADE_EXITS.status='exit_submitted'`.
- **Canonical identifier:** `managed_exit_id`, `client_order_id=f"exit-{managed_exit_id}-{reason}"`.
- **Failure handling:** **No governance chain (Stages 5–7 do not apply), no duplicate-order lock (unlike Stage 9's entry path) — Critical Finding #1.**
- **Retry behaviour:** Re-evaluated every `managed-exits` cycle; combined with the missing lock, this is a genuine re-submission risk after a timeout-kill.
- **Observability:** `MANAGED_TRADE_EXITS` row, job-run completion status. **`HOSTED PRODUCTION PROVEN`** that this job *runs* and *completes* repeatedly (Job IDs 7924, 7937, 7941, 7945 all cited as `managed-exits: completed`, `CURRENT_OPERATIONS_RECOVERY_REPORT_2026-07-27.md:137,170,174,178`) — but the report itself clarifies this proves exit-*monitoring* ran, not that any exit actually occurred.
- **Proof status:** Job execution `HOSTED PRODUCTION PROVEN`; an actual exit event `NOT PROVEN`.

## Stage 14 — Exit fill

- **Owning component:** Same fill-recording path as Stage 11, applied to exit-side fills.
- **Source:** `BROKER_TRADE_HISTORY`.
- **Destination:** `LOGICAL_TRADE_FILLS` (`fill_role='exit'`).
- **Canonical identifier:** `UNIQUE(broker, broker_fill_id)`.
- **Failure handling / retry:** Same as Stage 11.
- **Observability:** `LOGICAL_TRADE_FILLS` rows; `kraken_reconciliation.py` explicitly distinguishes a Kraken `closed_order` status (order no longer working) from an actual fill, correctly refusing to treat the former as a position close.
- **Proof status:** `NOT PROVEN`.

## Stage 15 — Canonical closed trade

- **Owning component:** `canonical_trades.py:_refresh_trade_aggregate`, `terminal` flag.
- **Source:** Matched entry/exit fills.
- **Destination:** `LOGICAL_TRADES.terminal=True`.
- **Canonical identifier:** `logical_trade_id`.
- **Failure handling:** Conservative by design — requires `exit_qty >= entry_qty`, so a partial exit correctly does not prematurely close the trade.
- **Retry behaviour:** N/A (recomputed).
- **Observability:** `LOGICAL_TRADES.terminal`.
- **Proof status:** `NOT PROVEN` — `IMPLEMENTED BUT NOT END-TO-END PROVEN` in the current window; the report explicitly lists "position closed" evidence as absent.

## Stage 16 — Fees and slippage

- **Owning component:** `operational_truth.py:calculate_execution_costs`.
- **Source:** Broker fee data from fills.
- **Destination:** `TRADE_EXECUTION_COSTS`.
- **Canonical identifier:** `logical_trade_id` / broker order reference.
- **Failure handling:** Not deep-dived at the numerical-correctness level in this review.
- **Known gap:** `cost_currency` defaults to a fixed `"account"` value with **no currency-conversion logic anywhere** — correct only because current Kraken pairs are GBP-quoted, matching the account currency; would silently miscompute if that configuration changed.
- **Proof status:** `NOT PROVEN`.

## Stage 17 — Gross and net P&L

- **Owning component:** `canonical_trades.py:_refresh_trade_aggregate` (authoritative, fill-weighted-average) **and independently** `multi_broker.py:close_managed_exit_and_record` (a second, separate single-price calculation feeding `PERFORMANCE_ATTRIBUTION`).
- **Source:** Matched fills (weighted-average path) or single entry/exit price (attribution path).
- **Destination:** `LOGICAL_TRADES.gross_pnl/net_pnl` and, separately, `PERFORMANCE_ATTRIBUTION.profit_loss`.
- **Canonical identifier:** `logical_trade_id` (first path) — `PERFORMANCE_ATTRIBUTION` is not keyed by the same ID family, which is itself part of the gap.
- **Failure handling / retry:** N/A (derived computation).
- **Observability:** Both tables, surfaced separately (`/performance-attribution` reads the second one).
- **Proof status:** `NOT PROVEN` for the current window; one historical, stale (2026-07-20) data point exists — a net realized P&L of "-0.54616884, consisting of known fees against zero matched realised trade P&L" (`PRODUCTION_EVIDENCE_LIVE_VERIFICATION.md:42`) — i.e. the calculation pathway has been observed to run, but with a trivial value (pure fee drag, no actual matched trade), and it has not been reconfirmed since.
- **Known gap:** These two calculations can diverge under partial fills, with no cross-check (Critical Finding #5 in the main review).

## Stage 18 — Attribution

- **Owning component:** `production_spine.py` / `multi_broker.py:PERFORMANCE_ATTRIBUTION`.
- **Proof status:** `NOT PROVEN`. Same duplication caveat as Stage 17.

## Stage 19 — MAE and MFE

- **Owning component:** `operational_truth.py:calculate_mae_mfe`.
- **Destination:** `TRADE_EXCURSIONS`.
- **Proof status:** `NOT PROVEN` — not independently observed in any cited production evidence.

## Stage 20 — R multiple

- **Owning component:** `operational_truth.py:calculate_r_multiple`.
- **Destination:** `TRADE_R_MULTIPLES`.
- **Proof status:** `NOT PROVEN`.

## Stage 21 — Automatic learning

- **Owning component:** `sprint6.py:enqueue_learning_workflow` → `process_learning_outbox` → `production_spine.py:run_closed_loop_learning`.
- **Source:** A terminal `LOGICAL_TRADES` row (Stage 15) plus its cost/attribution/MAE-MFE/R-multiple inputs (Stages 16–20).
- **Destination:** `SPRINT6_WORKFLOW_OUTBOX` → `CLOSED_LOOP_LEARNING_RUNS` → `EXPERIENCE_ENGINE` records / strategy & regime statistics.
- **Canonical identifier:** `logical_trade_id`, doubly enforced `UNIQUE` (outbox idempotency key and run table).
- **Failure handling:** Bounded retries (3 attempts), then marked `failed` — but **not escalated to an operational incident**, so a permanently-failed learning run does not surface on the primary Founder health screen.
- **Retry behaviour:** 10-minute claim-lease reclaim on worker restart mid-processing — genuinely restart-safe.
- **Observability:** `CLOSED_LOOP_LEARNING_RUNS` row; `OPERATIONAL_EVENTS` on failure (not `OPERATIONS_INCIDENTS`).
- **Proof status:** `NOT PROVEN` — the recovery report explicitly lists "complete learning from earlier Kraken losses" as something the Founder should not yet rely on.
- **Known gap:** This is the best-engineered stage in the entire lifecycle from a pure idempotency/durability standpoint; its only real weakness is upstream (it can only learn from what actually reaches terminal state, and Stages 2, 9, 10, 13 all have gaps that can prevent a trade from ever getting there).

## Stage 22 — Founder-visible explanation

- **Owning component:** `production_evidence.py:_why_no_trade`, `founder_evidence_payload`, rendered by `mobile/App.js`.
- **Source:** All prior stages' evidence tables.
- **Destination:** Mobile app screens (Dashboard, Activity, Recommendations, Portfolio, Market, Learning).
- **Canonical identifier:** N/A (presentation layer).
- **Failure handling:** Snapshot-based with a computed staleness flag; degrades status honestly when the refresh job stops running.
- **Retry behaviour:** N/A.
- **Observability:** This *is* the observability layer.
- **Proof status:** `IMPLEMENTED BUT NOT END-TO-END PROVEN` as fully truthful — the "why no trade" reasoning is genuinely specific and honest, but the mobile app's own "Last refreshed" header does not consume the backend's staleness computation (decoupled from actual data age), the Activity screen's evidence drill-down renders placeholder `"undefined #undefined"` text due to a contract mismatch, and the Learning/Market screens contain permanently-empty hardcoded UI sections. See the main review's "Hidden Gaps" section.

---

## Summary Table

| Stage | Proof status (current, 2026-07-27) |
|---|---|
| 1. Market data | IMPLEMENTED BUT NOT END-TO-END PROVEN (current); HOSTED PRODUCTION PROVEN (2026-07-20, stale) |
| 2. Research | NOT PROVEN (current, contradicted — timed out); HOSTED PRODUCTION PROVEN (2026-07-20, stale) |
| 3. Recommendation | NOT PROVEN (current); HOSTED PRODUCTION PROVEN (2026-07-20, stale) |
| 4. Strategy maturity | IMPLEMENTED BUT NOT END-TO-END PROVEN |
| 5. Portfolio Manager | IMPLEMENTED BUT NOT END-TO-END PROVEN |
| 6. Risk Engine | IMPLEMENTED BUT NOT END-TO-END PROVEN |
| 7. Production Risk Sentinel | IMPLEMENTED BUT NOT END-TO-END PROVEN |
| 8. Execution intent | NOT PROVEN (schema existence on Postgres itself unverified) |
| 9. Broker submission | NOT PROVEN |
| 10. Broker acknowledgement | NOT PROVEN |
| 11. Fill | NOT PROVEN |
| 12. Canonical position | NOT PROVEN |
| 13. Managed exit | Job execution HOSTED PRODUCTION PROVEN; actual exit event NOT PROVEN |
| 14. Exit fill | NOT PROVEN |
| 15. Canonical closed trade | NOT PROVEN |
| 16. Fees/slippage | NOT PROVEN |
| 17. Gross/net P&L | NOT PROVEN (current); one stale trivial-value data point (2026-07-20) |
| 18. Attribution | NOT PROVEN |
| 19. MAE/MFE | NOT PROVEN |
| 20. R multiple | NOT PROVEN |
| 21. Automatic learning | NOT PROVEN |
| 22. Founder-visible explanation | IMPLEMENTED BUT NOT END-TO-END PROVEN (partially honest, partially contract-mismatched) |

**No stage from 8 through 21 — the entire order-to-learning core of the investment lifecycle — has ever been demonstrated with a specific persisted production record, for any date, in any document reviewed.** This is the single most important fact in this review: the system has repeatedly proven it is *alive* (infrastructure layer) without ever proving it has *completed an investment* (business layer), and this gap predates the July 27 recovery — it is not a new regression, it is a lifecycle that has not yet been observed completing even once with cited evidence.
