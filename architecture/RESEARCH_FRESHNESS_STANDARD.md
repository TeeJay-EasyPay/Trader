# Research Freshness Standard

## Principle

Static reference data must never be displayed as current research.

## Data Types

- Static reference data: `COMPANY_MASTER`, seed themes, benchmark records.
- Refreshed market observations: prices, candles, market timestamps.
- Refreshed news and catalysts: current retrieved articles/events.
- Derived intelligence: scores and conclusions produced from refreshed evidence.
- Stale evidence: any record past its accepted freshness window.

## Required Research Cycle Fields

Each research cycle should persist:

- provider;
- symbol;
- latest market timestamp;
- retrieval timestamp;
- candle count;
- timeframe coverage;
- news count;
- stale/fresh status;
- data-quality outcome;
- research conclusion.

## Founder UX

Never show old research as current just because a row exists.

Use labels such as:

- Fresh.
- Stale.
- Static reference only.
- Awaiting live provider.
- Research did not run.

