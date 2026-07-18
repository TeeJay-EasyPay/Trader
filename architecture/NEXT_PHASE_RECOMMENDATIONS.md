# Next Phase Recommendations

## Phase 6 Priority

Complete the shared production datastore migration.

Recommended order:

1. Broker runtime and broker history.
2. Canonical lifecycle and reconciliation cases.
3. Recommendations and proposal state.
4. Managed exits and order intent locks.
5. Experience, learning, and reports.
6. Portfolio and market intelligence evidence.

## Production Worker Enablement

Enable Render worker and cron services only after shared datastore verification.

Required proof:

- `/phase5-status` no longer reports critical unmigrated runtime families;
- `/operations-health` shows current worker heartbeats;
- scheduled job rows appear without opening the phone app;
- operations incidents appear when workers or jobs fail.

## Reconciliation Expansion

Add broker-specific reconciliation adapters for:

- Alpaca order replacement and bracket relationships;
- Kraken trade IDs, transaction IDs, fees, and closed order mapping.

## Closed-Loop Automation

Trigger `run_closed_loop_learning` automatically when reconciliation marks a logical trade terminal.

## Portfolio Authority Integration

Make Portfolio Manager approval mandatory in the Investment Orchestrator before any auto-executable recommendation.

## Strategy Gate Enforcement

Block automatic execution unless the selected strategy has the required maturity stage for the requested broker/mode.

