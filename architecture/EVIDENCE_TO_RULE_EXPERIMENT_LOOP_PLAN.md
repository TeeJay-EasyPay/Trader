# Evidence-to-Rule Experiment Loop — implementation plan

Date: 11 September 2026
Status: Implemented and committed for the initial Alpaca shadow-only release; production verification is recorded in EXPERIMENT_RELEASE_RUNBOOK.md. Live activation remains disabled. This document itself does not enable trading.

## Outcome and boundaries

Turn completed-trade evidence into precise candidate rules, controlled prospective simulations, an evidence-backed strategy library and explicit adoption decisions. Results can be better, worse or insufficient; no profitability claim follows from building the system.

Initial scope is Alpaca equities, with the existing paper strategy unchanged. Experiments send no broker orders. Kraken live trading, USD expansion, three-way Standup and paused database backup/cleanup are outside this release. No automatic live activation. Existing unrelated working-tree changes must be preserved and excluded from commits unless deliberately integrated and tested.

## Current integration points and limitations

- `production_spine.py`, `experience_engine.py` and Alpaca learning capture provide evidence and reviews, not a complete prospective experiment loop.
- `learning_screen.py` and `mobile/screens/Learning.js` explicitly report that paired experiments are not connected. Replace that message only when actual experiment records exist.
- `mobile/screens/ExecutiveBriefing.js` has a founder-actions section for the existing What I need from you card.
- The local, uncommitted `mobile/screens/Notifications.js` currently handles database-maintenance requests only. It is not a verified general notification service. Extract/reuse presentation carefully; do not ship or activate paused backup functionality as a dependency.
- Historical Alpaca fee, decision-link and exit-evidence gaps remain. Gate affected analyses or mark unknown; do not invent historical facts or treat unknown costs as zero.

## Where it runs

Repository: develop and test code. Render background worker: scheduled bounded proposal and simulation jobs. Supabase: compact versioned evidence, portfolios, outcomes and approval records. Render API: authenticated read/action endpoints. Mobile: presentation and approvals only.

Before enabling jobs, measure worker headroom and scheduling isolation. Simulation must yield to order handling, reconciliation and protective exits; if those cannot be isolated reliably, leave simulation disabled until a separate worker is provisioned. The laptop is not required for deployed simulations.

## End-to-end flow

1. A bounded scheduled review checks a watermark for genuinely new, usable evidence; deterioration can request investigation but does not force a rule change.
2. Trader proposes one supported, executable rule change, citing outcome identifiers and a falsifiable hypothesis. No justified change is a valid result.
3. Validate against an allowlisted rule schema. Freeze baseline and candidate versions, data requirements, costs, risk limits, evaluation criteria and simulator version before testing.
4. Feed both virtual portfolios the same timestamped future opportunities, including rejected/skipped opportunities. Each independently evaluates entry, sizing and exits with the same execution model.
5. Record results, evidence quality and uncertainty. Evaluate after costs and comparable risk; count correlated/repeated signals appropriately and account for trying multiple hypotheses.
6. Store the report. Reject, continue for insufficient evidence, or recommend adoption. A recommendation is not activation.
7. Surface one adoption/implementation request in Learning, Executive Briefing and Notifications. An authenticated owner decision references the exact immutable version.
8. Implement supported configuration or necessary code, test and deploy. Separately activate only within the approved environment and capital/risk limits. Monitor and suspend/roll back when predefined conditions fail.

## Strategy storage and approvals

Automatically saving a draft and its test record is essential for auditability and does not need per-record approval. To support the requested approval for storing, offer **Approve for strategy library**: promotes a tested candidate to the accepted library, without authorising its use. Keep draft/rejected records distinguishable from accepted strategies.

| Action | Meaning | Does not authorise |
| --- | --- | --- |
| Run shadow test | Under an explicitly configured standing simulation policy and resource caps | Broker orders |
| Approve for strategy library | Accept this exact tested version into the reusable library | Paper or live activation |
| Approve implementation | Authorise the specified configuration/development work and tests | Live activation |
| Enable for Alpaca paper | Use supported version within approved paper limits | Live trading |
| Enable live pilot | Explicit approval for exact version, account, capital, risk and expiry | Broader strategy/account changes |

Default to manual paper promotion initially. Standing permission for automatic paper promotion is an optional, separately recorded policy, not inferred from this discussion. No repeated implementation approval is needed when a supported configuration needs no development; explain that plainly in the UI. Code deployment and strategy activation remain separate.

Use explicit states, not a single approved boolean: draft, validating, shadow_running, insufficient_evidence, rejected, recommended, library_approved, implementation_required, implementation_approved, implementing, ready_for_activation, paper_active, live_pilot_active, suspended, retired. Implementation and activation should be separate related records where needed rather than overloading one state.

Approvals bind owner, timestamp, proposal ID, version/hash, action, environment, scope and expiry. A changed version invalidates prior activation permission. Enforce transitions server-side with optimistic concurrency and idempotency. Double taps, stale pages or notification text must never bypass these checks.

## Data and API design

Add migrations for strategy versions, experiments, virtual portfolios, paired opportunities/outcomes, evaluation reports, approval requests, immutable approval events and activation records. Reuse existing identity/outbox conventions after inspection rather than duplicating infrastructure.

Store references to source trades, forecasts, costs, reference passages and data snapshots; retain enough point-in-time inputs to reproduce a decision. Store compact numerical inputs once per opportunity and share across arms. Do not duplicate full dossiers or prompts per simulated tick. Distinguish observed broker outcomes from simulated fills everywhere.

API capabilities: paginated experiment list/detail; paired results and evidence quality; paginated needs-attention/history; exact-version approval/rejection; implementation queue read/status update; activation/suspension. User ownership and action scope must be checked on every read/write. Reading screens never starts model calls, simulation or trading.

Implementation queue entries include approved requirements, evidence, acceptance tests, rollback, blockers and target environment. Developer completion attaches commit SHA, tests and verified deployment version. A user can ask Codex to inspect approved work; app approval alone does not wake or launch Codex. Automatic developer pickup is not part of this plan.

## Simulator and evaluator requirements

- Use deterministic code for simulation; model calls propose/explain, not process every price tick.
- Start with one existing supported rule family and one candidate at a time. Both arms use the same opportunity stream, point-in-time data, cost model and planned-risk policy.
- No future leakage: a signal cannot fill before its input was available. Missing quotes, ambiguous stop/target order, market gaps, partial fills and corporate actions need explicit handling or an uncertain/ineligible result.
- A candle touching a limit is not proof of a fill. Use conservative documented assumptions and mark uncertainty; obtain additional data only within approved budgets.
- Track separate balances, reservations, positions and exposure in both arms. Include mark-to-market open positions and drawdown, not just closed winners.
- Report net expectancy, paired difference, exposure, turnover, drawdown, fill/skip rates, uncertainty and concentration. Estimate all applicable costs; distinguish estimated from reconciled fees.
- Freeze evaluation criteria before the prospective test. Avoid repeated peeking and cherry-picking winners from many trials. Minimum usable sample requirements must reflect dependence and uncertainty, not a magic trade count.
- Maintain a reproducible evidence trail. Better than baseline can still mean losing money; show that distinction.

## UI

Learning: add an Experiments card with active count, status, baseline versus candidate, after-cost results and evidence quality. Detail shows the plain-English change, supporting records, locked rule versions, comparable risk, costs, progress, uncertainty, verdict and next action. Never label a strategy proven from a few outcomes.

Executive Briefing: add pending experiment requests inside the existing What I need from you card, linking to the same detail record. Do not add a competing approval workflow.

Notifications: generalise to typed, paginated Needs attention and History lists. Each item links to the same request ID and displays requested action, decision, implementation and activation outcome. Deduplicate repeated alerts by experiment/version/action; preserve history after approval or rejection.

Buttons should say what they do: Approve for library, Approve implementation, Enable paper, Review live pilot, Reject, Suspend. Before real-money approval show capital at risk, account, limits, evidence weaknesses and rollback conditions in plain English. Saving is never presented as trading activation.

## Resource controls

Start disabled; configure numerical daily model-call/token or cost caps, concurrent experiment cap, candidate rate, opportunities/day, maximum duration and storage/egress budgets before enabling. Initial design target is one concurrent experiment; actual budgets are set from measured current usage and user constraints.

Reuse current research and market-data ingestion, aggregate in the database, fetch only needed fields, cache unchanged UI summaries and paginate detail. Use durable bounded jobs with checkpoints, leases and retry ceilings so restart/retry cannot duplicate observations or paid calls. Keep notifications compact. If budgets are exceeded pause experiments, never protective trading checks. Backups and destructive retention remain paused; this release must not silently delete evidence to meet a budget.

## Delivery sequence and gates

1. Audit current source/readers, paper/live configuration, worker scheduling and baseline resource use. Resolve interface contracts and list evidence gaps; record exact supported first rule type.
2. Implement versioned schemas, validation, approval state machine and authenticated APIs behind disabled flags. Test permissions, stale versions, idempotency and no-order guarantees.
3. Implement deterministic paired simulator and replay fixtures, then bounded worker/outbox integration. Test restart recovery, temporal correctness, costs, skips and portfolio accounting.
4. Add proposal generation and evaluation using compact evidence. Test invalid/unsupported model proposals, insufficient evidence and budget exhaustion. Save failed tests too.
5. Build Learning card, shared request detail, Executive Briefing integration and generic notification history. Test loading/error/empty states, accessibility and navigation; preserve existing Standup.
6. Implement accepted library, development queue and supported paper activation behind permissions. Live activation remains disabled until a separately approved pilot; never enable live merely to test the feature.
7. Run end-to-end staging tests, then commit only scoped tested changes, deploy migrations/backend and required mobile update, verify exact running versions and UI-to-API behaviour. Enable a bounded shadow-only pilot only after configuration and budget checks.
8. Report observed resource use, paired coverage, evidence limitations and reproducibility. Enable paper promotion only under explicit recorded permission. Continue monitoring whether approved rules remain supported.

## Definition of done

A traceable completed-trade lesson creates a validated versioned hypothesis; both arms process the same new opportunity stream; results are reproducible and costs/uncertainty explicit; one request appears consistently across all three screens; owner approval is recorded against its exact version; developer completion records deployment; unsupported/stale/unapproved activation is rejected; and no shadow job can place broker orders. Tests and deployment are verified, not merely code committed.

Deliver a final checklist separating shipped capabilities, enabled capabilities, remaining data blockers and demonstrated trading results. Completion of this software is not evidence of improved profitability.
