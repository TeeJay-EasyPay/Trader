# Data Availability and Unknown Values Standard

Date: 2026-07-17

## Rule

Generic "Not available" is not sufficient for Founder-facing decisions. Missing values should explain:

1. Why unavailable.
2. What is required to make it available.
3. Whether this is expected or an error.

## Examples

- Not available - no closed trades yet.
- Not available - this broker is not connected.
- Unknown - market data is stale.
- Awaiting broker reconciliation.
- Insufficient history for correlation.
- No fee data was returned by Kraken.
- Alpaca paper account does not report this value.

## API Support

`/world-class-evidence` exposes an `unavailable` list with `field`, `why`, `required`, and `expected_or_error`.
