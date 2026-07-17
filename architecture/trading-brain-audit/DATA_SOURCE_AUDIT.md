# Data Source Audit

## Alpaca

Provider: Alpaca Paper/Data API.

Used for:

- Account.
- Positions.
- Orders.
- Fills/activities.
- Latest bars.
- News.
- Market clock.
- Asset availability.

Frequency:

- On demand through API screens and research.
- Broker polling every 60 seconds in hosted worker.

Freshness:

- Latest available from Alpaca at request time.

Reliability:

- External API dependency; failures fall back to cached snapshots in some UI paths.

Historical depth:

- Limited by API calls and stored SQLite history.

Missing-data behaviour:

- Missing bars skip proposal.
- Missing credentials block analysis/execution.

## Kraken

Provider: Kraken API.

Used for:

- Balances.
- Open orders.
- Closed orders.
- Trade history.
- Current ticker prices.
- AddOrder for live micro-orders.

Frequency:

- On demand.
- Broker polling every 60 seconds.
- Managed exit monitoring every 60 seconds.

Freshness:

- Current at request/poll time.

Reliability:

- External API dependency. Authentication failures return explicit status/reason.

Historical depth:

- Limited by Kraken API response and stored broker history rows.

Missing-data behaviour:

- Unconfigured adapter returns not configured.
- Price missing skips crypto proposal or managed exit check.
- Real orders require multiple env switches.

## CoinGecko

Provider: CoinGecko public markets API.

Used for:

- Top market-cap crypto.
- AI crypto category.
- Privacy/security crypto category.
- Price change, market cap, volume.

Frequency:

- Crypto refresh worker interval: max(300 seconds, research interval minutes * 60).

Freshness:

- Public market data at fetch time.

Reliability:

- Public API, rate-limit and availability risk.

Historical depth:

- Current snapshot only in implemented path.

Missing-data behaviour:

- If unavailable, fallback can seed from `KRAKEN_ALLOWED_PAIRS`.

## OpenAI

Provider: OpenAI Responses API.

Used for:

- Equity proposal generation when configured.
- Read-only Ask AI explanations.

Frequency:

- On demand during equity analysis or Ask.

Freshness:

- Depends on supplied context. OpenAI does not fetch broker data directly.

Reliability:

- External API dependency; timeouts/errors fall back to deterministic Ask summary.

Missing-data behaviour:

- Equity analysis without OpenAI does not produce deterministic production equity trades.

## Local Intelligence Tables

Provider:

- Seeded local data in `intelligence_data.py` and refresh inputs.

Used for:

- Watchlist.
- Company profiles.
- Themes.
- Investment thesis and caution.

Frequency:

- Seed at startup.
- Manual/scheduled refresh scripts.

Freshness:

- Depends on refresh process.

Missing-data behaviour:

- Missing symbols means no equity analysis universe.

## Benchmark Trader Records

Provider:

- Seeded public benchmark data in `benchmark_data.py`.

Used for:

- Behavioural context.
- Learning reports.
- Ask AI context.

Frequency:

- Seed at startup; not live-scraped.

Missing-data behaviour:

- Missing benchmark context causes behavioural due diligence to be insufficient.

## Portfolio Snapshots

Provider:

- Internal snapshots from broker polling/status.

Used for:

- P&L.
- Drawdown.
- Reports.
- Command screen.

Missing-data behaviour:

- Day/week P&L unavailable if no prior snapshot exists.

## Broker Trade History

Provider:

- Alpaca and Kraken broker history APIs.

Used for:

- Trade History screen.
- Notifications.
- Reports.

Missing-data behaviour:

- Raw rows may lack entry/exit mapping, producing unavailable P&L or reasons.

## Serious Trading System Gaps

- High-quality historical candles by timeframe.
- Intraday multi-timeframe data.
- Bid/ask spread and order book depth.
- Slippage estimates.
- Fee normalization by broker.
- Corporate actions and survivorship-bias controls.
- Economic/calendar data.
- Regime data.
- News sentiment provider.
- Crypto on-chain provider.
- Strategy-labelled outcome database.
- Backtesting dataset.
