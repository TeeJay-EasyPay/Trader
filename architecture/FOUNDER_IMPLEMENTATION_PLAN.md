# AI Trader — Founder Implementation Programme: Implementation Plan

**Status: AWAITING FOUNDER APPROVAL. No implementation has begun. This document is Step 5 of the requested six-step process.**

**Authority:** `AI_TRADER_FOUNDING_PRINCIPLES_ARCHITECTURE_CONSTITUTION_v1.0.md` (already present in `architecture/`, confirmed unchanged). This plan is subordinate to it.

**Basis:** The six documents from the 2026-07-27 independent operational review (`CLAUDE_INDEPENDENT_ARCHITECTURE_REVIEW.md` and siblings) plus three new deep-dive investigations run for this plan, covering Pillars 2–7 specifically (Pillar 1 was already covered exhaustively). Every claim below traces to a specific file:line citation gathered in those investigations.

---

## Read First: A Recommendation That Changes the Proposed Sequencing

The Programme document says Operational Excellence "may be completed first, but the remaining pillars must be designed and implemented together." Before mapping principles and pillars to code, I want to flag something the Pillar 2–7 investigation surfaced that the Programme document couldn't have anticipated, because it wasn't yet known: **this codebase does not mostly need new capability. It needs wiring.**

Across every one of Pillars 2 through 6, the same pattern repeats: a real, often well-engineered subsystem exists, is unit-tested, and has zero callers anywhere in the production path. Concretely:

- A genuine no-look-ahead backtester and a genuine rolling walk-forward validator (`trading_intelligence.py:1276-1433`) — never called outside tests.
- The strategy-promotion gate that would apply the Constitution's own maturity criteria (`production_spine.py:751-795`) — zero callers anywhere.
- A second-generation regime classifier that blends volatility/breadth/liquidity/macro (`market_intelligence_platform.py:283-325`) — zero production callers.
- A real Pearson-correlation portfolio check (`portfolio_intelligence.py:206-221`) — wired into the live governance chain, but its one input (`return_series`) is never populated by any caller, so it always returns "insufficient history."
- Real sector/country/theme exposure bucketing (`portfolio_intelligence.py:155-203`) — its data source (`upsert_asset_metadata`) is never called outside tests, so every position falls into "Unknown."
- The 14-strategy scoring engine (`trading_intelligence.py:2174-2386`) computes a genuinely differentiated strategy per proposal — but `TradeProposal` has no field the governance layer can read it from, so the maturity gate that actually controls execution treats every idea as the same undifferentiated bucket, frozen at its seed values since day one.

This is not a criticism of past work — several of these subsystems (the backtester, the correlation math, the calibration/Brier-score logic) are genuinely well built and shouldn't be redone. It is a specific, evidenced observation: **a large fraction of what Pillars 2, 3, 4, and 6 ask for already exists in this codebase and is currently inert, not missing.**

**Recommendation:** Insert a phase between "fix Pillar 1's P0 safety bugs" and "build new Pillar 2–7 capability" whose entire purpose is connecting what already exists. This phase is lower-risk than new development (no new external dependencies, the hard algorithmic work is done and tested), higher-leverage (each connection can unlock a whole subsystem), and directly consistent with the Constitution's own Implementation Requirements ("where good architecture already exists, extend it... avoid unnecessary rewrites") and Principle 10 (long-term thinking over short-term convenience). Building new macro-data ingestion or an academic-literature corpus before wiring in the backtester that's already sitting there would be building new tasks on top of old, unconnected tasks — exactly what Principle 9 says not to do ("features are added because they strengthen the platform," not because they're the next item on a list).

I am not proposing to skip or defer any pillar. I'm proposing to resequence the *first* work within each pillar toward "connect what exists" before "build what doesn't," and to treat Pillar 1's P0 items as a hard gate before any of this, for the reason already established in the operational review: an execution pipeline that can lose orders and cannot alert the Founder should not have new capability layered onto it, regardless of how good that capability is, because it repeats the exact "stuck again" pattern this whole programme exists to end.

This is explained in more detail in "Proposed Implementation Order" below. **I'm asking you to confirm or push back on this resequencing specifically before I finalize the plan**, since it's the one place I'm recommending a different approach than the Programme document as written.

---

## Founding Principles → Current State

| Principle | Current state | Evidence |
|---|---|---|
| 1. Truth Above Everything | **Partially upheld.** The `/founder-evidence` model is honest about staleness server-side; several places are not — `/status`/`/developer-status`'s `engine_health` field always reports "not initialized" in the deployed Postgres config regardless of real health, and the mobile "Last refreshed" header doesn't reflect actual data age. | `CLAUDE_INDEPENDENT_ARCHITECTURE_REVIEW.md` Hidden Gaps |
| 2. Evidence Before Opinion | **Upheld where evidence exists, violated by omission elsewhere.** `estimate_probability()` genuinely blends historical win-rate evidence into new estimates. But `STRATEGY_MATURITY_REGISTRY` has never been updated from evidence since its seed, and `strategy_promotion_decision()` — the function built to enforce this principle — has no caller. | Pillar 4 findings below |
| 3. Scientific Thinking | **Infrastructure exists, is not exercised.** A real backtest/walk-forward engine with explicit `bias_controls` exists and is well-designed for this exact principle. It has never run in production. | Pillar 4 findings below |
| 4. Continuous Learning | **Narrow.** Learning from the platform's own trades is real, automatic, and durable. Learning from historical markets not traded, academic/professional literature, or public case studies beyond a 4-row static seed does not exist. | Pillar 5 findings below |
| 5. Safety Before Profit | **Mostly upheld, one real gap.** Entry-order governance is strong. Exit orders bypass all of it and lack duplicate-order protection — already flagged P0 in the prior review. | `CRITICAL_REMEDIATION_PLAN.md` P0-2 |
| 6. Explainability | **Genuinely strong for "why no trade," weak for "why this strategy."** The gate-reason system is specific and honest. But because the strategy-scoring output never reaches the governance layer, the system cannot currently explain which of its 14 strategies actually governed a given decision. | Pillar 2 findings below |
| 7. One Source of Truth | **Violated in one specific, documented way.** Three overlapping trade-lifecycle tables, two independent P&L calculators, unverified schema existence for the tables that matter most. | `CLAUDE_INDEPENDENT_ARCHITECTURE_REVIEW.md` Critical Findings #5, #6 |
| 8. One Investment Lifecycle | **The taxonomy is right; the enforcement is missing.** Every stage name from the Constitution exists as a string in the code (`STRATEGY_STAGES`, canonical lifecycle stages). No strategy has ever been observed moving through the stages based on evidence — one static seed row governs everything. | Pillar 4 findings below |
| 9. Disciplined Evolution | **This plan's central recommendation exists to protect this principle** — see the resequencing note above. |  |
| 10. Long-Term Thinking | **The broker abstraction is a genuine example of this principle done right** (a real Protocol, placeholder adapters already committed) — one small, well-contained fix needed. The AI-provider layer and international-market handling are not yet built to this standard. | Pillar 7 findings below |

---

## Pillar-by-Pillar Assessment

### Pillar 1 — Operational Excellence

Already assessed exhaustively in the six 2026-07-27 review documents. Not re-litigated here. **Status: production-ready in parts (data architecture, entry-order governance, learning-pipeline idempotency), with five specific P0 gaps that must close before this pillar can be called complete** — see `CRITICAL_REMEDIATION_PLAN.md`. This pillar gates everything else in this plan.

### Pillar 2 — Trading Intelligence

**What exists:** A real, computed technical toolkit (SMA crossover, momentum, ATR-based volatility, support/resistance, volume trend, gap/breakout/mean-reversion flags — `trading_intelligence.py:536-603`), 14 named strategy definitions each with distinct entry logic, a genuine empirical-Bayesian probability blend that reuses historical regime/strategy/signal win rates (`:780-839`), and a real calibration engine (Brier score, calibration-error-by-bucket, `:1458-1511`) already invoked in production via the daily learning report.

**What needs extending:** The indicator set is genuinely narrow (no RSI/MACD/Bollinger/order-flow signals) and the strategy scores are hand-tuned constants, not fitted/calibrated weights — extending this is legitimate new work, not a wiring fix.

**What needs replacing/connecting (higher priority than extending):** `TradeProposal` has no field that carries the selected strategy's identity to the governance layer, so `sprint6._strategy_id()` always falls back to a single generic bucket — the entire 14-strategy engine's output is currently invisible to the gate that actually controls execution. This is a small, precise fix (add/flatten a `strategy_id` field) with a large effect (it's the prerequisite for Pillar 4's maturity ladder meaning anything). `STRATEGY_REGISTRY`'s "historical_edge" fields are also literal static strings that should either be computed from real backtest output (once Pillar 4's engine is wired in) or explicitly relabeled as placeholders — the Constitution's Truth Above Everything principle applies to internal knowledge tables, not just Founder-facing screens.

### Pillar 3 — Market Research

**What exists:** A real per-symbol regime classifier reused across proposals (`trading_intelligence.py:606-663`, persisted to `MARKET_REGIME_SNAPSHOTS` and genuinely queried back later), live news retrieval feeding both a proposal-level catalyst score and an LLM sentiment summary.

**What needs extending:** Sector rotation, macroeconomic trends, and earnings data have no ingestion pipeline at all — this is genuine new-build work, not a wiring gap, and should be scoped deliberately (see Risks — external data sources typically carry ongoing subscription cost).

**What needs replacing/connecting:** A second, more capable regime engine (`market_intelligence_platform.py:283-325`, blending volatility/breadth/liquidity/macro) and a multi-timeframe reconciliation function already exist, are tested, and are never called in production — `architecture/MARKET_INTELLIGENCE_PLATFORM.md` currently describes this dead code as a live capability, which itself needs correcting under Principle 1. The benchmark-trader research (4 traders, 4 static rows, one seed date) needs a refresh mechanism — the append-only write path already exists (`_append_research`); it just has no caller with new content.

### Pillar 4 — Strategy Laboratory

**What exists:** This is the strongest hidden asset found across the whole investigation. A real no-look-ahead backtester with transaction-cost/slippage modeling, and a real rolling walk-forward validator with explicit `no_look_ahead_bias`/`out_of_sample_only_for_validation` flags and a benchmark (buy-and-hold) comparison (`trading_intelligence.py:1276-1433`). The strategy-promotion gate correctly encodes the Constitution's own criteria (≥100 samples, positive expectancy, profit factor ≥1.2, drawdown ≤15%, calibration ≤10% — `production_spine.py:751-795,972-985`).

**What needs replacing:** Nothing — the algorithms are sound.

**What needs connecting (this is the single highest-leverage item in this entire plan):** `record_historical_candle()` — the only writer of the historical price data the backtester needs — is never called in production, so `HISTORICAL_CANDLES` is permanently empty; the backtester and walk-forward validator are never scheduled to run; `strategy_promotion_decision()` has no caller; and `STRATEGY_MATURITY_REGISTRY` has exactly one static row that has never been updated. Fixing Pillar 2's `strategy_id` gap plus scheduling a historical-data ingestion job plus scheduling the existing validator plus wiring the existing promotion gate plus adding the missing `UPDATE STRATEGY_MATURITY_REGISTRY` write-back would make this entire pillar real using code that already exists and is already tested.

### Pillar 5 — Learning Engine

**What exists:** A carefully designed Experience Engine — immutable, hashed experience records, good/bad-decision-vs-good/bad-outcome classification, historical-analogue matching with an explicit low-confidence threshold, sample-size-gated learning proposals that are correctly prevented from silently changing production behavior.

**What needs extending (genuine new build, Constitution-mandated, currently absent):** Learning from historical markets not traded, from academic/professional literature, and from public trading case studies beyond the tiny static benchmark seed does not exist in any form today.

**What needs connecting:** The same historical-data/backtest wiring described under Pillar 4 would, as a direct side effect, give this pillar its first non-trade-outcome learning source — historical out-of-sample performance could feed the same probability/calibration mechanisms that currently only learn from live trade outcomes. `LEARNING_PROPOSALS` are created but nothing ever reads an approval and applies it — this is correctly gated per the Constitution's caution against silent production changes, but the Founder-facing approval mechanism itself doesn't exist yet and should be built deliberately, not left implicit.

### Pillar 6 — Portfolio Intelligence

**What exists:** A real gate in the live governance chain (`portfolio_manager_decision`, `production_spine.py:618-693`) with one genuine portfolio-level circuit breaker (aggregate open-risk ratio > 8% → wait), real Pearson-correlation math, and real sector/country/theme bucketing logic.

**What needs replacing:** The decision function itself is currently two static thresholds wearing a sophisticated name — extending it into a genuine multi-factor evaluation (regime-aware throttling, correlation actually influencing the decision rather than only being logged) is real design work, not just wiring.

**What needs connecting first:** Correlation always returns "insufficient history" because `return_series` is never populated by any caller — populate it from the market-data layer already used elsewhere. Sector/country/theme exposure is always "Unknown" because `upsert_asset_metadata()` is never called outside tests despite the source data (sector/country) already sitting in `COMPANY_MASTER` — call it from the existing intelligence-refresh cycle. These two fixes alone would take two already-built, currently-inert capabilities and make them real inputs, before any new portfolio-theory work is designed.

**What needs building (genuinely new):** Opportunity-cost modeling and a true cross-broker cash/capital view do not exist in any form — `multi_broker.py` has no function that aggregates buying power across brokers into a single capital pool.

### Pillar 7 — Platform Evolution

**What exists:** The strongest piece of forward-looking architecture found in this investigation — a genuine `BrokerAdapter` Protocol with six concrete/placeholder implementations already committed and registered generically (`broker_adapters.py:18-33`, `api.py:3213-3218`). The Postgres-backed data layer already uses DB-level locking rather than process-level locking, meaning the single-worker topology is a deployment choice, not an architectural constraint on future distributed processing.

**What needs replacing:** The one real piece of debt — `orchestrator.py:202`'s hardcoded `{"alpaca", "kraken"}` allowlist gates the entire governance chain by broker name rather than by adapter self-declaration. A new broker implementing the Protocol correctly would still silently skip Portfolio Manager/Strategy Entitlement/Sentinel unless a human separately remembers to edit this unrelated line. Fix: a `requires_production_governance` capability flag on the Protocol, defaulted `True`, replacing the literal set. Small, contained, high-value given it closes a real safety gap in the extensibility story.

**What needs building:** The AI/LLM integration has no provider abstraction at all (direct hardcoded OpenAI calls, three call sites) — worth adding a thin interface now while the surface area is small, per the Constitution's explicit ask to prepare for "additional AI models" without fully building them yet. The US-equity-market-hours gate (`guardrails.py:78-93`) is hardcoded and would actively misfire — not just need extending — the day a second equity market connects; worth fixing now as cheap insurance even with no second market planned yet. Alternative asset classes (options, futures) have zero scaffolding anywhere and are correctly the lowest priority per the Constitution's "do not fully implement future capabilities now."

---

## Proposed Implementation Order

**Phase 0 — Pillar 1 P0 safety fixes (hard gate, already fully specified).** The five P0 items in `CRITICAL_REMEDIATION_PLAN.md`: verify the P&L/execution-intent schema exists on live Postgres, add duplicate-order protection to exits, eliminate duplicate job scheduling, fix the two highest-confidence timeout root causes, wire push notifications into a reachable code path. **No Phase 1 work should begin until these are deployed and hosted-production-verified** — not merely tested locally — for the reason given in the resequencing note above.

**Phase 1 — Connect what already exists (the resequencing recommendation).** In rough dependency order: (a) give `TradeProposal` a real `strategy_id` field reaching the governance layer; (b) seed one `STRATEGY_MATURITY_REGISTRY` row per actual strategy instead of one generic bucket; (c) schedule historical-price ingestion (`record_historical_candle`) for the tradeable universe; (d) schedule the existing backtest/walk-forward validator against that history; (e) wire `strategy_promotion_decision()` into a scheduled job with the missing registry write-back; (f) populate `return_series` so the existing correlation check activates; (g) call `upsert_asset_metadata()` from the existing intelligence-refresh cycle so sector/country exposure activates; (h) add the `requires_production_governance` broker capability flag. Every item in this phase connects code that already exists and is already tested — it is the lowest-risk, highest-leverage phase in this plan.

**Phase 2 — Extend what's thin.** Broaden the technical-indicator set and move strategy-scoring weights toward calibrated rather than hand-tuned values (Pillar 2); build the Founder-facing approval mechanism for learning proposals so Pillar 5's governed-learning loop has an actual "accept this lesson" action (Pillar 5); extend `portfolio_manager_decision` into a genuine regime-aware, correlation-influenced evaluation now that its inputs are real (Pillar 6); add the AI-provider abstraction and fix the market-hours gate (Pillar 7).

**Phase 3 — Build what's genuinely new.** Sector-rotation/macro/earnings data ingestion (Pillar 3); non-trade-outcome learning sources beyond the historical-backtest feed from Phase 1 — academic/professional literature ingestion, a real benchmark-research refresh mechanism (Pillars 3 & 5); cross-broker cash/capital view and opportunity-cost modeling (Pillar 6); alternative-asset scaffolding (Pillar 7). This phase involves genuine new external dependencies and the most implementation risk — recommend scoping and sequencing it in a follow-up plan once Phases 0–2 are complete and verified, rather than committing to specifics now.

---

## Major Architectural Risks

1. **Repeating the "stuck again" pattern by building on an unverified foundation.** This is the reason Phase 0 is a hard gate. Building Pillar 2–7 capability on an execution pipeline with unresolved P0 safety gaps would not be new — it would be the exact pattern this whole programme exists to end.
2. **Wiring in orphaned engines before confirming their storage layer is sound.** Several Phase 1 items write to tables in the same family the operational review flagged as having unverified Postgres schema existence (`LOGICAL_TRADES` and siblings). Phase 1 work should explicitly re-verify schema existence for every table it starts writing to, not assume it.
3. **No test coverage for any of this against real Postgres or under concurrency.** The operational review found the entire test suite runs against SQLite tempfiles with mocked brokers. Phase 1 wiring work is a natural opportunity to add the first Postgres-backed test in the suite, rather than compounding the existing gap.
4. **Scope creep disguised as "just wiring."** Several Phase 1 items are genuinely small (populate a field, add a scheduled call). Others (fitted/calibrated strategy weights, a genuine multi-factor portfolio optimizer) sound similar but are real design work — Phase 1 should be scoped strictly to connection, with anything requiring new modeling decisions deferred to Phase 2, to keep the lowest-risk phase actually low-risk.
5. **New external data dependencies carry real ongoing cost and new failure modes.** Phase 3's macro/earnings/academic-literature ingestion will add new provider dependencies, each needing the same timeout/retry/circuit-breaking discipline the operational review found missing elsewhere — this should not be added hastily once Phase 0 has just fixed exactly that class of problem for the existing providers.
6. **The broker-extensibility fix (Phase 1h) must not be read as "enabling" Coinbase/IBKR/Saxo.** Those adapters remain placeholders; the fix closes a governance-bypass risk for whenever a broker is genuinely activated, and should ship with tests confirming the placeholders still correctly refuse to trade.
7. **Documentation-vs-code drift will recur if not actively managed.** This investigation found multiple architecture docs describing capabilities (Regime 2.0, a richer portfolio-decision set, "daily" benchmark research) that don't match the shipped code. Each phase's completion should include correcting the relevant doc, not just shipping the code — per the Founder Communication requirements in the Programme.

---

## Approval Requested

Per Step 5 of the requested process, **implementation has not begun.** Specific decisions needed before I proceed:

1. **Confirm or adjust the resequencing recommendation** (Phase 0 hard gate, then Phase 1 "connect what exists" before Phase 2 "extend," before Phase 3 "build new") — this is the one place I'm recommending a different approach than "design and implement all pillars together," and I'd like your explicit view before locking it in.
2. **Confirm Phase 0 is unchanged from `CRITICAL_REMEDIATION_PLAN.md`** — I'm treating it as already-approved scope from the prior review unless you say otherwise.
3. **Confirm appetite for Phase 3's new external dependencies** (macro/earnings feeds, any academic-literature source) before I scope them in detail, since these carry ongoing cost and the Programme explicitly says not to over-invest in infrastructure before the app works.
4. Once 1–3 are confirmed, I'll begin Phase 0 implementation and keep the implementation log, architecture documentation, and Founder briefings updated throughout, as required.
