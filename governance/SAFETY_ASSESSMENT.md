# Safety Assessment - Autonomous Trading Readiness Sprint

Date: 2026-07-07

## Safety Verdict

The system has enough mechanical controls for observed, capped Kraken micro-live testing. It does not yet justify unattended scale-up.

## Mechanical Seatbelts Implemented

- Broker-specific auto-trading enablement.
- Separate Kraken live approval and real-order submission switches.
- Kraken dry-run validate mode by default.
- Maximum and minimum Kraken order sizes.
- Maximum Kraken open managed trades.
- Allowed Kraken pair list.
- Duplicate order-intent locks.
- Required stop loss and take profit.
- Managed exit records created after accepted entries.
- Continuous stop-loss/take-profit monitoring.
- Optional trailing stops from governed policy.
- Startup reconciliation for stuck order locks.
- P&L attribution on closed managed exits.
- Hosted API without an auth token is read-only: status/recommendation GETs can load, but POST trading/control commands are rejected.
- Constant-time API token comparison and source-IP lockout.

## Guardrails Confirmed

- Minimum confidence.
- Maximum risk per trade.
- Daily, weekly, and monthly loss limits.
- Maximum drawdown.
- Maximum position size and exposure.
- Maximum concurrent positions.
- No duplicate positions or duplicate order intents.
- Stock market-hours validation for equities.
- Crypto 24/7 trading allowed by design.

## Safety Boundaries

- Kraken has no broker-native paper mode. `KRAKEN_SUBMIT_REAL_ORDERS=false` is a dry-run validation mode; real trading begins only when this is explicitly set to true.
- Disabling broker auto trading stops new entries but existing managed exits continue to be monitored and closed.
- Mobile push notifications are not end-to-end verified until a rebuilt app registers a device token.
