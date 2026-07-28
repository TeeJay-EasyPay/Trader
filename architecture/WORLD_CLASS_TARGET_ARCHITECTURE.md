# World-Class Target Architecture

Companion document to `CLAUDE_INDEPENDENT_ARCHITECTURE_REVIEW.md`. Describes the simplest credible architecture that makes AI Trader world-class **for its actual purpose** — a single Founder's personally-supervised autonomous trading system — without unnecessary infrastructure cost.

## What "world class" means here (and doesn't)

Per the review brief, world class is explicitly **not**: more strategies, more AI agents, more brokers, expensive institutional market feeds, Kubernetes, high availability, complex microservices, more dashboards, or more visual polish. AI Trader does not need any of those to be excellent at its actual job.

World class **is**: one authoritative production truth; deterministic execution; no governance bypass; safe broker interaction; exact reconciliation; dependable P&L; automatic learning; bounded jobs; provider isolation; restart safety; idempotency; honest observability; clear operational ownership; minimal unexplained state; a complete audit trail; and Founder confidence that is based on evidence, not on the absence of visible errors.

By that standard, this review found that AI Trader is **closer to world class than its symptom history suggests** — the entry-order governance chain, the Kraken personal-holdings exclusion, and the learning-pipeline idempotency are already at or near the bar. What's missing is not more capability; it's closing a specific, small set of gaps (exit-order governance, duplicate scheduling, connection-per-row waste, dead push notifications, one unverified schema) that undermine the trustworthiness of everything else. The target architecture below is deliberately conservative: it is the current architecture with its real defects fixed, not a redesign.

---

## A. Required now to make the current system work

*(Dependable autonomous paper trading and truthful data representation — this is the P0/P1 set from `CRITICAL_REMEDIATION_PLAN.md`, restated here as an end-state description rather than a task list.)*

- **Database boundaries:** Postgres is already correctly the sole production runtime database, enforced fail-closed by `database.py`. The one thing missing is that *every* schema module must unconditionally create its tables on Postgres, with no silent per-module exceptions — verified by a startup self-check that fails loudly (not silently) if any expected table is absent, rather than allowing an execution-path write to fail deep inside a job with no clear signal.
- **Worker and job design:** One worker process remains correct and sufficient. The target state is: exactly one scheduler (the always-on worker's internal loop) owns all recurring jobs; Render cron services are reserved only for genuinely independent, infrequent jobs the worker doesn't cover. Every job — cron-triggered or worker-loop-triggered — gets the same child-process timeout treatment, so there is one reliability contract per job, not two. Jobs that make multiple independent external calls (broker portfolios, per-symbol research) fetch in batches or in parallel rather than sequentially, and long-running jobs track a cumulative time budget internally so they degrade to an honest partial result instead of being hard-killed with zero progress recorded.
- **Execution authority:** Entry orders already have the right shape (one mandatory pipeline: Strategy → Portfolio → Risk → Sentinel → intent-lock → broker). The target state extends the *same* shape to exit orders — governance is not required for a stop-loss/take-profit exit (arguably it correctly shouldn't be, so a kill switch can't trap an open position), but duplicate-order protection is required for every order type, no exceptions.
- **Reconciliation:** One canonical trade-lifecycle representation, not three. The fill-based terminal-state determination and the Kraken personal-holdings exclusion logic are already correct and should not be redesigned — they should be made the *only* representation, with the currently-separate `operational_truth.CANONICAL_TRADE_LIFECYCLE` state machine either merged into or explicitly subordinated to `canonical_trades.LOGICAL_TRADES`.
- **Learning:** Already close to the target state — fully automatic, doubly idempotent, restart-safe. The only gap is visibility: a permanently-failed learning run must raise an operational incident, not just a log entry, so it surfaces on the primary health screen.
- **API read models:** The `/founder-evidence` snapshot design is the right pattern (worker-owned projection, explicit staleness computation, bounded queries) and should become the *only* pattern — the legacy `/status`/`/brokers` live-fan-out endpoints either retired or rebuilt to read the same cached snapshot, so there is one way the system computes "is it healthy," not two that can silently disagree.
- **Mobile contracts:** The mobile app should consume every field the backend already computes for exactly this purpose (staleness age, not just a boolean) — the target state is that no screen can visually look healthier than the underlying data actually is, which requires the client to use the server's own freshness computation rather than substituting its own weaker proxy (HTTP call success).
- **Observability:** Every incident the system already detects and records (stale heartbeat, duplicate worker, orphaned order, failed learning run) reaches the Founder proactively, not only on request. This is the single highest-leverage fix in the whole plan, because it converts every other safeguard in the system from passive to active.
- **Failure handling:** Every order-submission code path (entry and exit) has a DB-level intent lock acquired before the broker call, and every reconciliation/recovery function is checked against the specific failure mode it's meant to catch (the orphaned-order recovery function must not exclude the exact row shape it exists to recover).

---

## B. Required before meaningful live capital

*(Beyond dependable paper trading — what's needed before increasing Kraken allocation or trusting the system with material funds.)*

- **Broker-side idempotency, not just application-side.** Both Alpaca (`client_order_id`, currently unsent despite being available) and Kraken (`userref`, which Kraken does not treat as a dedupe key) should have their exchange-side idempotency properly used or explicitly acknowledged as unavailable, so the system's actual duplicate-order defense-in-depth is understood and not overstated.
- **A verified, tested orphaned-order recovery path**, not just detection. P2-2 in the remediation plan (periodic scan for Kraken positions with no matching ownership record) should exist and be proven, via a real drill, to actually recover a position into managed-exit monitoring — not just raise an incident that a human then has to manually resolve.
- **A single, audited P&L number**, with the two currently-divergent calculations (fill-weighted `LOGICAL_TRADES` vs. single-price `PERFORMANCE_ATTRIBUTION`) collapsed into one, and a reconciliation test that specifically exercises partial fills — the exact case where they can currently disagree.
- **A real security rotation**, not just a fix: the exposed token rotated, the disclosure vector (the `-ShowToken` script flag) closed, and — specifically before Kraken's `KRAKEN_SUBMIT_REAL_ORDERS`/`KRAKEN_LIVE_TRADING_APPROVED` flags are ever flipped to `true` — a fresh rotation performed as a deliberate trust-boundary step, not an afterthought.
- **A demonstrated, not just architected, restart-safety story for order submission.** The narrow window between broker acceptance and local ownership-linking (Critical Finding #2) should be closed and then *tested* under an actual simulated process-kill at that exact point, not merely reasoned about.
- **A test suite that exercises the actual production database and actual concurrency**, at least for the highest-stakes paths (order submission, exit monitoring, reconciliation). This does not require a fundamentally different test architecture — it requires a subset of the existing tests to run against a real (even if ephemeral/local) Postgres instance and to include at least one genuine concurrent-worker test, not just sequential calls with different worker IDs.
- **Explicit, evidenced sign-off criteria for resuming Kraken new entries**, matching what `KRAKEN_RECONCILIATION_AND_LEARNING_RECOVERY.md` already describes as required (reconstructed entry/exit pairs, realized P&L, completed terminal learning reviews, proven GBP allocation boundary, explicit Founder approval) — this review found no evidence that gate has been passed, and it should not be passed by declaration; it should be passed by producing exactly the persisted evidence `END_TO_END_LIFECYCLE_TRACE.md` shows is currently missing (a proven order → fill → position → close → P&L → learning chain, with real record citations).

---

## C. Desirable later

*(Scalability, maintainability, high availability, institutional feeds, more advanced security, architectural refinement — genuinely optional, not blocking anything above.)*

- Retiring genuinely dead code surface (`/status`'s ~1,000+ lines of parallel Founder-experience computation, `trading_intelligence.TRADE_LIFECYCLE` if fully subsumed elsewhere) to reduce the amount of logic that must be kept consistent by hand.
- Pagination/cursor support for broker activity fetches (P3-1) — worth doing before trading volume grows enough to make single-page fetches a real data-loss risk, not urgent today.
- A more structured schema-migration framework (e.g. versioned up/down migrations) to replace the current "CREATE TABLE IF NOT EXISTS at every startup" pattern — valuable for long-term maintainability, not a correctness requirement today since the pattern is additive-safe.
- Currency-conversion handling in cost/fee calculations, currently hardcoded to a single implicit currency — correct today only because Kraken pairs happen to be GBP-quoted matching the account currency; worth generalizing if the trading universe ever expands to mixed-currency pairs.
- Broader token-rotation tooling (scheduled rotation, not just incident-driven) — reasonable hygiene, not required for a single-Founder app at this scale.
- Deeper backtesting against real historical data (the existing test suite's trading-intelligence tests use synthetic linear-uptrend candles) — valuable for strategy confidence, orthogonal to the operational-correctness focus of this review.

None of category C should be started before category A is complete and verified in hosted production, and category B should not be started before Kraken live trading is actually being considered — doing otherwise repeats the pattern this review was commissioned to break: new capability layered on top of an unverified foundation.
