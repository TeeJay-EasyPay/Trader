# Market Intelligence Platform

Date: 2026-07-17

## Objective

The market intelligence platform records where market data came from, whether it is usable, and what technical/regime conclusions can honestly be drawn.

## Provider-Neutral Observations

`MARKET_DATA_OBSERVATIONS` stores provider, original symbol, normalized symbol, exchange, asset type, timeframe, observation time, retrieval time, freshness, completeness, adjusted status, source-quality status, provenance, OHLCV, and raw payload.

## Data Quality

The validator identifies duplicate candles, missing OHLC, impossible OHLC, negative volume, time-order errors, missing data, and stale data. Conclusions are marked `pass`, `warn`, or `reject`.

## Intelligence Outputs

- Multi-timeframe conclusion separates long, medium, and short timeframe evidence.
- Regime 2.0 keeps supporting and contradictory evidence visible.
- Fundamental, macro/event, and news/catalyst evidence have separate source-aware tables.

**Status note (added 2026-07-29, per `architecture/FOUNDER_IMPLEMENTATION_PLAN.md` Pillar 3
findings):** the code for the items above (`market_intelligence_platform.py:283-325`'s Regime 2.0
classifier and the multi-timeframe reconciliation function) exists and is unit-tested, but as of
this date has zero production callers - the live proposal path still uses the simpler regime
classifier in `trading_intelligence.py`. This section previously read as describing live
production behaviour; it describes built-but-disconnected capability instead. Connecting it was
out of scope for the Phase 1 "connect what exists" session that added this note (Phase 1 was
scoped to the eight items in `FOUNDER_IMPLEMENTATION_PLAN.md`'s Proposed Implementation Order,
which did not include this item) and remains available Phase 2/3 work.

## Founder Meaning

Technical conclusions are not shown without data-health context. If data is stale or incomplete, the UI should say why and what is needed.
