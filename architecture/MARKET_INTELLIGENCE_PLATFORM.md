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

## Founder Meaning

Technical conclusions are not shown without data-health context. If data is stale or incomplete, the UI should say why and what is needed.
