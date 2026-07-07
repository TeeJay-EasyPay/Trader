# Engineering Review Report - Autonomous Trading Readiness Sprint

Date: 2026-07-07

Reviewer: Codex acting as Principal Software Reviewer and Release Manager.

## Verdict

Conditionally approved for controlled Kraken micro-live testing after Founder environment approval.

The sprint closes the major blockers that previously made Kraken autonomous trading mostly theoretical: crypto proposals can now be generated, routed through the Investment Orchestrator, submitted through Kraken in validate/live mode, monitored for exits, and recorded for performance attribution.

This is not approved as a fully unattended, hands-off investment system. It is approved for tightly capped, observed, small-balance operation with the mechanical seatbelts already implemented.

## Findings Closed During Review

- Kraken order submission now defaults to dry-run validate mode when `KRAKEN_SUBMIT_REAL_ORDERS` is unset.
- Manual approval now routes through the Investment Orchestrator, so it receives the same due diligence, policy, capital allocation, and duplicate-order lock as autonomous execution.
- Kraken crypto proposals now exist; previously the Kraken execution path could not be reached by research because no crypto proposal generator existed.
- Crypto trading is no longer blocked by US equity market-hours validation.
- Kraken live accounts are no longer incorrectly rejected by the paper-trading-only guardrail, while stock trading remains paper-only.
- Weekly/monthly loss, drawdown, and exposure checks are enforced from portfolio snapshot history.
- Managed exits and broker order polling now run automatically in background worker loops.
- Managed-exit close bookkeeping now records P&L with the original position direction, preventing a stop-loss loss from being recorded as a gain.
- Mobile global controls were clarified as all-broker Resume/Emergency Stop controls, with normal enable/disable controls kept broker-specific.

## Verification

- `python -m compileall -q src tests`: passed.
- `python -m unittest discover -s tests`: 66 tests passed.
- `git diff --check`: passed.
- `npx expo-doctor`: 17/17 checks passed.

## Release Classification

Release type: controlled operational sprint.

Recommended rollout:

1. Keep `KRAKEN_SUBMIT_REAL_ORDERS=false` until the Founder is ready to observe a first micro-order.
2. Enable only one broker at a time.
3. Keep `KRAKEN_MAX_OPEN_TRADES=1` and `KRAKEN_MAX_ORDER_GBP` small for the first live observation window.
4. Watch notifications, broker panels, managed exits, and `PERFORMANCE_ATTRIBUTION` after the first trade.

