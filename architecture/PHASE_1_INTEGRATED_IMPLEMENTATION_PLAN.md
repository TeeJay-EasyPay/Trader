# Phase 1 — Integrated Implementation Plan

Governing directive: `engineering-directives/implementation/PHASE_1_INTEGRATED_AUTONOMOUS_INTELLIGENCE.md`.
Authority: `AI_TRADER_FOUNDING_PRINCIPLES_ARCHITECTURE_CONSTITUTION_v1.0.md`, subordinate to it.
Basis: `FOUNDER_IMPLEMENTATION_PLAN.md` Phase 1 ("connect what already exists"), approved by the Founder
2026-07-28 alongside Phase 0 (see `governance/IMPLEMENTATION_LOG.md`).

This document is intentionally short. It exists to sequence implementation, not to re-litigate the
assessment already recorded in `FOUNDER_IMPLEMENTATION_PLAN.md`.

## Known risk carried into this session

`INTEGRATED_IMPLEMENTATION_STATUS.md` records all five Phase 0 items as **hosted-production evidence
outstanding** as of 2026-07-28. The Founder has explicitly directed this session to proceed into Phase 1
regardless of that gap, accepting it as a tracked risk rather than a blocker. It remains open and is
carried forward in this plan's risk list, not resolved by it — this session has no hosted Postgres/Render
access to close it.

## Current architecture (relevant to this session)

The investment lifecycle (Observe → Research → Understand → Estimate Probability → Evaluate Portfolio →
Apply Risk → Decide → Execute → Verify → Learn) is implemented end to end, but several already-built
subsystems are disconnected from the live path:

- `trading_intelligence.py` selects one of 14 named strategies per proposal (`select_strategy`) and
  returns it inside an `IntelligencePacket`, but the winning `strategy_id` never reaches the top-level
  `TradeProposal` the governance layer (`sprint6.py`) reads — `sprint6._strategy_id()` always falls back
  to a generic bucket.
- A real backtester + walk-forward validator (`trading_intelligence.py:1276-1433`) and a strategy
  promotion gate (`production_spine.py:751-795`) exist, are unit-tested, and have zero production
  callers, because the historical-candle writer (`record_historical_candle`) is itself never called.
- Portfolio correlation math (`portfolio_intelligence.py:206-221`) and sector/country exposure bucketing
  (`portfolio_intelligence.py:155-203`) are real but starved of input — `return_series` and
  `upsert_asset_metadata()` are never populated/called by any production caller.
- `orchestrator.py`'s governance-chain gate is keyed off a hardcoded broker-name allowlist rather than
  adapter self-declaration, so a correctly implemented new `BrokerAdapter` would silently bypass
  governance.

## Implementation order (dependency-aware, per `FOUNDER_IMPLEMENTATION_PLAN.md` Phase 1(a)-(h))

1. **(a) `strategy_id` on `TradeProposal`** — prerequisite for (b) and (e); every other item is independent
   of this one but (b)/(e) need it to mean anything.
2. **(b) Seed `STRATEGY_MATURITY_REGISTRY` per strategy** — depends on (a) existing so the ladder has
   something real to key against.
3. **(f) `return_series` for correlation** and **(g) `upsert_asset_metadata` wiring** — independent of
   (a)/(b), safe to do in parallel with them.
4. **(h) `requires_production_governance` capability flag** — independent, self-contained.
5. **(c) historical-candle ingestion job** — prerequisite for (d).
6. **(d) scheduled backtest/walk-forward run** — depends on (c).
7. **(e) `strategy_promotion_decision` scheduled + registry write-back** — depends on (b) and, for a
   real (non-empty) result, on (d).

Items whose "new modeling" component was explicitly flagged as Phase 2 (fitted strategy weights,
regime-aware portfolio decisioning) are out of scope for this session — this session is scoped strictly
to connection, per `FOUNDER_IMPLEMENTATION_PLAN.md` risk #4.

## Testing strategy

- Full existing suite (`pytest`) run after each wiring change and once at the end; regressions fixed
  before moving on.
- New tests added for each connected pathway (strategy_id flows to governance; maturity registry seeded
  correctly; correlation activates once `return_series` populated; exposure activates once metadata
  upserted; placeholder brokers still refuse to trade after the capability-flag change).
- No Postgres access in this environment — schema-affecting items are written to run correctly against
  both SQLite and Postgres code paths already in use elsewhere in the repo, but cannot be hosted-verified
  from here. Flagged explicitly per risk #2/#3 of `FOUNDER_IMPLEMENTATION_PLAN.md`.

## Production verification strategy

Every item below remains **IMPLEMENTED BUT NOT HOSTED-PRODUCTION-PROVEN** until confirmed with a citable
hosted record, per the project's standing verification standard. This session will state that
distinction explicitly for each item in the Founder brief rather than imply completion from passing
tests.
