# AT-ED-002 v2.0 Founder Briefing — Restore Continuous Autonomous Operation

Plain English. Governing directive:
`engineering-directives/implementation/AT-ED-002_v2.0_INSTITUTIONAL_EDITION.md.txt`, scoped per
your explicit clarification to restoring/verifying continuous operation, Alpaca paper trading,
and Kraken governed live trading — not the full four-part institutional vision document.

## Executive Summary

The platform's continuous research, learning, and reporting machinery was already substantially
built (most of it by the Phase 1 session earlier today). What was actually stopping it from being
a genuinely autonomous trading organisation was two things, both now fixed:

1. **Autonomous execution was switched off entirely** in the hosted configuration — for both
   Alpaca (paper money) and Kraken (real money). You explicitly authorized turning both on, with
   Kraken's existing size/count guardrails left exactly as they were.
2. **A second, deeper gap I found while making that first change**: even with the switches on,
   every autonomous Kraken order would still have been silently rejected by the governance layer,
   because no strategy was actually entitled for real-money execution. I traced this, proved it
   empirically, and fixed it narrowly — for the one strategy you've already been trading live via
   the app, not as a blanket loosening.

Both fixes are implemented, tested, and verified against real code paths — not just described.
Neither has been deployed. That step is yours.

## Implementation Summary

**1. Enabled autonomous execution (`render.yaml`).** Flipped exactly six flags from `"false"` to
`"true"`: `AUTO_PAPER_TRADING`, `ALPACA_AUTO_TRADING`, `KRAKEN_AUTO_TRADING`,
`KRAKEN_TRADING_ENABLED`, `KRAKEN_LIVE_TRADING_APPROVED`, `KRAKEN_SUBMIT_REAL_ORDERS`. Every
Kraken size/count/allocation guardrail (`KRAKEN_MAX_ORDER_GBP=5`, `KRAKEN_MIN_ORDER_GBP=1`,
`KRAKEN_MAX_OPEN_TRADES=1`, `KRAKEN_TRADING_ALLOCATION_GBP=100`, `KRAKEN_ALLOWED_PAIRS`) is
untouched — confirmed via `git diff`, not just by intent. Coinbase/Binance/IBKR auto-trading
remain off (not requested, and those brokers have no credentials configured anyway).

**2. Found and closed the Kraken entitlement gap.** `orchestrator.py` routes every non-Alpaca
broker through the same governance chain with `mode="micro_live"`. Every strategy's registry
entitlement is deliberately capped below that (a safety decision from the Phase 1 session, so
evidence-based promotion can never silently reach real capital on its own). I proved empirically
that this meant Kraken orders would have been rejected with "not permitted for micro_live
execution" regardless of the flags above. I added a distinct, explicit authorization mechanism —
separate from the automatic evidence-based promotion path — and applied it to exactly one
strategy: `crypto_trend_following_2r`, the only one your own strategy definitions already label
`founder_controlled_live_kraken`. The other 8 strategies capable of generating a crypto proposal
remain correctly blocked from real money, because your own code already labels them
`research_only`. This was a deliberate, narrow decision, not a blanket loosening — the "guard
rails limiting size and number of trades" you referred to are exactly what's still standing here,
untouched.

**3. Verified — with evidence, not assertion — every item on your Required End State list.** See
the Verification Evidence section below.

**4. Corrected one documentation-vs-code drift found along the way**: `KRAKEN_SANDBOX_MODE` is
described in `architecture/ENVIRONMENT_VARIABLE_AUDIT.md` as an active safety guard. It is not —
no Python code reads it. Real-order blocking is enforced entirely by the three flags this session
changed, and separately by `KrakenAdapter`'s own guardrail checks. Corrected the doc; did not
change the variable, since it does nothing either way.

**5. Deliberately not attempted** (per your explicit scope instruction): the Knowledge Graph, the
Investment Committee workflow, Monte Carlo infrastructure, and the `investment-governance/`
documentation set. Not placeholder-implemented either — see Recommendations.

## Outstanding Issues

- **Nothing in this session has been deployed.** `render.yaml` and the two authorization-related
  code files are changed locally only. Autonomous trading remains off in your actual hosted
  environment until you deploy this.
- **Hosted verification is still required after deployment**, per the project's standing
  evidence standard — everything below is proven at the code level (real execution paths, real
  tests, no mocked business logic), not yet proven against your live Render/Postgres/Alpaca/Kraken
  environment. Specifically confirm after deploy: a real Kraken order is actually submitted (or
  correctly held) by the worker; the `STRATEGY_MATURITY_REGISTRY` row for
  `crypto_trend_following_2r` shows `current_stage = 'Micro Live'` on your live database; a real
  Alpaca paper order appears in your Alpaca paper account.
- **The Phase 0 hosted-evidence gap from 2026-07-28 remains open** — unchanged by this session,
  still tracked in `architecture/INTEGRATED_IMPLEMENTATION_STATUS.md`.
- **Crypto historical-candle ingestion (Kraken OHLC) remains deferred** from Phase 1 — no Kraken
  price-history client exists yet, so Kraken strategies still cannot be backtested the way equity
  strategies now can.
- **`unused.sqlite3` will keep reappearing** in your working tree every time the local test suite
  runs — it's a pre-existing test side effect (`test_production_completion.py`), not something
  this session's changes cause or something worth changing the test for.

## Recommendations for the Next Engineering Directive

In priority order, matching your stated preference for information quality over framework code:

1. **Kraken historical-price ingestion** (deferred from Phase 1) — needed before Kraken strategies
   can be backtested/promoted the way equity strategies now can.
2. **Order books and funding rates** (Kraken has public endpoints for both) — directly relevant to
   the one strategy currently trading with real money; would improve entry/exit quality evidence
   without needing a paid provider.
3. **Macroeconomic and central-bank data** (rates, inflation, employment) — genuinely valuable per
   AT-ED-002 Part 2, but requires a paid/keyed provider (e.g. FRED) this environment has no
   credentials for and cannot test blind. Needs explicit provider approval before scoping, per
   your own prior "no paid data sources without Founder approval" instruction.
4. **Market sentiment and academic/quantitative research ingestion** — same caveat as above;
   genuinely new integration work, not a wiring fix.
5. Only once 1–2 are real: **revisit whether any other strategy besides
   `crypto_trend_following_2r` has earned real evidence-based promotion** via
   `refresh_strategy_maturity()` — that mechanism already exists and is already gated correctly to
   require your explicit approval before crossing into real capital.

Institutional-scale items from AT-ED-002 Parts 2–4 (Investment Committee, Knowledge Graph, Monte
Carlo validation, the full `investment-governance/` policy set) remain valid long-term direction
but were explicitly out of scope this session and should only be scoped once they'd measurably
improve trading performance, per your own instruction.

## Testing

Full suite: **215 passed, 0 failed** (up from 210 before this session). 6 new tests added,
specifically proving: the Kraken entitlement gap exists before the fix and is closed after it, for
exactly the authorized strategy; a research-only strategy remains correctly blocked; the API
startup wiring applies the authorization only when `KRAKEN_AUTO_TRADING` is actually on; the fix
is idempotent; and the full `InvestmentOrchestrator.evaluate_recommendation()` path behaves
correctly end-to-end, not just the underlying function in isolation.

## Files Changed

`render.yaml`, `src/ai_trader/sprint6.py`, `src/ai_trader/api.py`,
`tests/test_sprint6_institutional_spine.py`, `tests/test_orchestrator.py`,
`governance/IMPLEMENTATION_LOG.md`, `architecture/ENVIRONMENT_VARIABLE_AUDIT.md`, this briefing.
Nothing committed — working tree only, per standing instruction to commit only when asked.
