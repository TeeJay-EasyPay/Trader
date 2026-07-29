# Integrated Implementation Status

Living tracking document required by the Founder's approval of `FOUNDER_IMPLEMENTATION_PLAN.md` ("maintain one integrated implementation plan showing: each pillar, dependencies, current status, code affected, tests completed, hosted-production evidence, unresolved risks"). Updated throughout the programme, not just at milestones. Pillars 1–7 rows are seeded and will be filled in as that work begins (post-Phase-0, per the approved dependency-aware parallel model).

**Completion standard in force for every row below** (per the Founder's approval): a pillar/item is not "complete" merely because code exists or unit tests pass. Completion requires production wiring, real callers, verified storage, integration testing, hosted-production evidence where applicable, truthful Founder visibility, and documentation matching the implemented code.

---

## Phase 0 — Mandatory safety gate

| Item | Status | Code affected | Tests completed | Hosted-production evidence | Unresolved risks |
|---|---|---|---|---|---|
| P0-1: `LOGICAL_TRADES` schema on Postgres | Implemented, locally tested | `canonical_trades.py`, `kraken_reconciliation.py`, `api.py` | Full suite (185 tests) passes; no dedicated Postgres test (none available in this environment) | **Outstanding** — confirm tables exist on live Postgres after deploy | Whether any pre-2026-07-28 production evidence was ever written against a schema that didn't exist is unknown and unrecoverable from this repo |
| P0-2: exit-order duplicate-order protection | Implemented, locally tested | `api.py` (`monitor_managed_exits`, `force_managed_exit`), `multi_broker.py` (`release_order_intent_lock`) | 4 new tests added (happy path, duplicate-lock refusal, shared lock between automatic/forced exit, release-on-rejection retry) | **Outstanding** — real duplicate-attempt drill against deployed worker | None identified beyond the already-documented residual gap of no broker-side idempotency key for either broker (P2-2/P2-1) |
| P0-3: duplicate scheduling (cron vs. worker loop) | Implemented | `render.yaml` | Not unit-testable (deployment topology); existing scheduling tests unaffected | **Outstanding** — `SCHEDULED_JOB_RUNS` query post-deploy showing one execution per job per cadence window | None identified; the removed cron services' Render dashboard visibility is a cosmetic-only change |
| P0-4a: Kraken reconciliation connection-per-row | Implemented, locally tested (behavior-preserving) | `canonical_trades.py` (new `_connection` helper threaded through 7 functions), `kraken_reconciliation.py` (threaded through `replay_kraken_evidence` and its full call graph) | Full suite passes; `test_kraken_reconciliation.py`'s existing idempotency/duplicate/ledger tests exercise the refactored code paths unchanged | **Outstanding** — measure actual job duration and connection count after deploy | Deferred: incremental cursor for `BROKER_TRADE_HISTORY` scan (documented as an intentional, lower-risk-first sequencing decision, not an oversight) |
| P0-4b: evidence-snapshot sequential/redundant calls | Implemented, locally tested | `api.py` (`capture_production_broker_snapshots`, `_exchange_portfolio`), `broker_adapters.py` (`get_positions` account reuse) | Full suite passes; concurrency path explicitly gated to Postgres-only so SQLite test runs exercise the unchanged sequential path | **Outstanding** — measure actual job duration after deploy | None identified |
| P0-5: push notifications unreachable in production | Implemented, locally tested | `cli.py` (`_run_named_job`, worker loop, heartbeat payload) | 1 new test (job dispatch); existing push-send tests unchanged | **Outstanding** — real device receives a test notification without opening the app | None identified |

**Phase 0 exit criteria (from the Founder's approval): all of the above move from "Outstanding" to confirmed hosted-production evidence before Seven Pillars implementation work begins.**

---

## Pillar 1 — Operational Excellence

Status: the P0 items above are Pillar 1's remaining gaps as identified in the 2026-07-27 review. P1–P3 items from `CRITICAL_REMEDIATION_PLAN.md` (two independent trade-lifecycle tables, two independent P&L calculators, mobile staleness/timeline contract bugs, token rotation, etc.) are not yet started — approved for parallel work alongside the other six pillars once Phase 0 is hosted-verified, per the dependency-aware model.

## Pillars 2–7 — Trading Intelligence, Market Research, Strategy Laboratory, Learning Engine, Portfolio Intelligence, Platform Evolution

Status: assessed (see `FOUNDER_IMPLEMENTATION_PLAN.md` for the detailed current-state mapping). On
2026-07-29 the Founder directed this work to proceed despite Phase 0's hosted-evidence gate still
being open (see below) - the "Phase 1: connect what already exists" item list from
`FOUNDER_IMPLEMENTATION_PLAN.md`'s Proposed Implementation Order is now implemented and locally
tested. Phase 2 (extend what's thin) and Phase 3 (build what's genuinely new) remain not started.

**Outstanding, unresolved as of 2026-07-29:** Phase 0's five P0 items are still hosted-production-
evidence outstanding (unchanged from the table above - this session had no Postgres/Render access
to close them). The Founder explicitly chose to proceed with Phase 1 anyway, accepting this as a
tracked risk. It should still be closed at the next opportunity with real hosted access.

### Phase 1 — Connect what already exists (2026-07-29)

Plan: `architecture/PHASE_1_INTEGRATED_IMPLEMENTATION_PLAN.md`. Full detail in
`governance/IMPLEMENTATION_LOG.md`'s 2026-07-29 entry.

| Item | Status | Code affected | Tests | Hosted-production evidence |
|---|---|---|---|---|
| (a) `strategy_id` reaches governance layer | Implemented, locally tested | `models.py`, `agent.py` | New: strategy_id flows end-to-end (`test_end_to_end.py`); every named strategy entitled (`test_sprint6_institutional_spine.py`) | **Outstanding** - real proposal in hosted logs carries a real strategy_id, not the generic bucket |
| (b) `STRATEGY_MATURITY_REGISTRY` per-strategy seeding | Implemented, locally tested | `sprint6.py` | New: all 14 strategies registered and entitled | **Outstanding** - hosted registry table has 15 rows (generic + 14), not 1 |
| (c) Historical-candle ingestion (equity only) | Implemented, locally tested | `alpaca.py` (`get_daily_bars`), `api.py` (`refresh_strategy_lab`) | New: mocked Alpaca bars ingestion, unavailable-symbol handling | **Outstanding** - `HISTORICAL_CANDLES` has real rows after a hosted `strategy-lab-refresh` run |
| (d) Backtest/walk-forward scheduling | Implemented, locally tested | `api.py`, `cli.py` (job registration + daily schedule) | New: `refresh_strategy_lab` evaluates every stock strategy end-to-end | **Outstanding** - `STRATEGY_BACKTEST_RESULTS`/`STRATEGY_LAB_RUNS` populated by a real scheduled run |
| (e) Promotion decision + write-back, Founder-approval gate above Paper | Implemented, locally tested | `sprint6.py` (`refresh_strategy_maturity`) | New: hold on thin evidence, applied promotion at/below Paper, gated (not applied) promotion at Micro Live/Production | **Outstanding** - a real hosted run producing a `pending_founder_approval` result, reviewed by the Founder |
| (f) Portfolio correlation `return_series` | Implemented, locally tested | `trading_intelligence.py` (`load_return_series`), `sprint6.py` | New: correlation status flips from insufficient_history to complete once candles exist | **Outstanding** - a real hosted decision packet shows `correlation.status == "complete"` |
| (g) `upsert_asset_metadata` wiring | Implemented, locally tested | `api.py` (`_refresh_asset_metadata_from_company_master`, called from `run_analysis`) | New: metadata copied, exposure stops defaulting to Unknown | **Outstanding** - a real hosted exposure snapshot shows real sector/country buckets |
| (h) Broker governance capability flag | Implemented, locally tested | `broker_adapters.py`, `orchestrator.py` | New: default-true regression guard; hypothetical ungoverned broker now correctly routed and rejected; fixed 2 pre-existing test fixtures the change correctly broke | **Outstanding** - no behavioural change expected for alpaca/kraken in production; confirm no regression in hosted decision logs |

**Not attempted this session (Phase 2/3):** fitted/calibrated strategy weights; Founder-facing
learning-proposal approval mechanism; regime-aware/correlation-influenced portfolio decisioning;
AI-provider abstraction; hardcoded market-hours gate; Kraken/crypto historical-candle ingestion;
sector-rotation/macro/earnings ingestion; cross-broker capital view. Regime 2.0 / multi-timeframe
engine remain built-but-disconnected (documentation corrected in `MARKET_INTELLIGENCE_PLATFORM.md`
to say so; connecting it was not in the approved Phase 1 item list).
