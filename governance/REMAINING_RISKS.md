# Remaining Risks - Autonomous Trading Readiness Sprint

Date: 2026-07-07

## High Priority

- **Resolved 2026-09-24 — Experiment continuity:** the baseline fingerprint now changes only
  when trading decisions, risk rules, cost assumptions, market-data interpretation or
  simulation outcomes can change. UI wording, mobile layout, observability, logging and
  egress-only optimisations do not invalidate otherwise comparable evidence. A one-time
  compatibility migration preserves evidence collected under the former operational hash.
- **Resolved 2026-09-24 — Faster evidence without weaker safeguards:** the research path now
  generates point-in-time historical opportunities by replaying a frozen market-only rule
  over cached data, exposes an explicitly provisional stage after a smaller broker-appropriate
  sample, retains the full gate before recommending or adopting any rule, uses separate Kraken
  and Alpaca evidence requirements, and prioritises fewer, higher-value experiments. Provisional
  findings are labelled clearly and cannot change trading behaviour automatically. Final
  recommendation still requires the larger broker-specific prospective evidence gate.
- Native mobile push token registration is not implemented in the client. Backend push dispatch exists, but the physical phone app must be rebuilt with `expo-notifications` before end-to-end push delivery can be trusted.
- Render route stability is not fully green: hosted `/healthz` and `/status` are healthy after deploy, but `/notifications`, `/performance-attribution`, and unauthenticated POST verification were unstable externally and need Render log review.
- Kraken managed exits are app-managed. If the backend is down, exits are not checked until the backend is running again. Keep order sizes small until uptime is proven.
- CoinGecko public API availability and rate limits can interrupt crypto research. The system records this as a research failure, but data freshness still depends on that feed.

## Medium Priority

- `api.py` should be decomposed before adding more live broker adapters.
- Coinbase, Binance, and IBKR are UI/governance-ready but not execution-ready.
- On-chain, news, and sentiment scores are not yet connected to a real provider.
- Render environment variables still require Founder review before live operation.

## Operational Actions Before First Live Kraken Micro-Trade

- Confirm `AI_TRADER_API_TOKEN` is set in Render.
- Confirm `KRAKEN_ALLOWED_PAIRS` is narrow.
- Confirm `KRAKEN_MAX_ORDER_GBP` is acceptable for a first live test.
- Confirm `KRAKEN_MAX_OPEN_TRADES=1`.
- Confirm Kraken API key has no withdrawal permission.
- Confirm the mobile app points at the hosted Render API, not `127.0.0.1`.
