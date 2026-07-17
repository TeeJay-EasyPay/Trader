# Knowledge Engine

## Purpose

The knowledge system gives AI Trader memory. It stores company knowledge, market themes, crypto research, public benchmark trader lessons, trade outcomes, and daily observations. This data supports recommendations, reports, and Ask AI explanations.

The knowledge engine is evidence storage and interpretation. It is not allowed to rewrite strategy or governance automatically.

## Investment Knowledge

Implemented by `InvestmentIntelligenceDatabase` in `intelligence.py`.

Tables:

- `COMPANY_MASTER`
- `COMPANY_FINANCIALS`
- `COMPANY_DAILY_UPDATES`
- `INVESTMENT_WATCHLIST`
- `MARKET_THEMES`

Responsibilities:

- Store the founder watchlist.
- Store company profiles.
- Store investment theses and caution notes.
- Store themes and macro narratives.
- Track daily company review updates.
- Provide context for research and due diligence.

## Crypto Knowledge

Crypto knowledge spans `foundation.py`, `operational.py`, `multi_broker.py`, and `api.py`.

Tables:

- `CRYPTO_MASTER`
- `CRYPTO_ASSET_MASTER`
- `CRYPTO_MARKET_DATA`
- `CRYPTO_RESEARCH_SCORES`
- `CRYPTO_DAILY_UPDATES`
- `CRYPTO_PROJECT_ANALYSIS`
- `CRYPTO_TOKENOMICS`
- `CRYPTO_ONCHAIN_METRICS`
- `CRYPTO_SENTIMENT`
- `CRYPTO_RISK`
- `CRYPTO_NEWS`
- `CRYPTO_BENCHMARK_ALIGNMENT`
- `CRYPTO_TRADING_HISTORY`

Current signals:

- Technical trend score.
- Momentum score.
- Volatility.
- Liquidity.
- Risk score.
- Overall due diligence score.
- Confidence score.

Current data source:

- CoinGecko public market API when available.
- Kraken approved pairs and current prices for tradeable context.

Important limitation:

On-chain activity, sentiment, and news are not fully wired to provider-grade sources. The system leaves those fields unavailable rather than inventing evidence.

## Benchmark Trading Knowledge

Implemented by `BenchmarkIntelligenceDatabase` in `benchmark.py`.

Tables:

- `BENCHMARK_TRADERS`
- `BENCHMARK_DAILY_RESEARCH`

Purpose:

- Monitor public benchmark trader information.
- Store public lessons about risk, positioning, patience, catalysts, concentration, and market context.
- Feed daily learning reports.

Rules:

- Use public information only.
- Do not fabricate private trades or undisclosed performance.
- Do not automatically copy benchmark traders.

## Learning Engine

Learning is currently implemented through reporting and evidence aggregation in `api.py`, supported by:

- `PERFORMANCE_ATTRIBUTION`
- `BROKER_TRADE_HISTORY`
- `ORCHESTRATOR_DECISIONS`
- `AUTO_TRADE_EVENTS`
- `BENCHMARK_DAILY_RESEARCH`
- `RESEARCH_RUNS`

The system can answer:

- What happened today?
- Which trades closed?
- Which trades are open?
- Which decisions were rejected?
- What caused losses or gains?
- What lessons were observed?
- What could be improved?

The system must not automatically change:

- Trading strategy.
- Guardrails.
- Broker permissions.
- Execution logic.
- Governance documents.

## Due Diligence

`create_due_diligence_assessment` records status for:

- Fundamental review.
- Technical review.
- Market review.
- Macro review.
- Behavioural review.
- Investment policy review.

The orchestrator requires due diligence to be complete for autonomous execution. Incomplete diligence can still produce visible recommendations, but execution is blocked.

## Recommendation Generation

Recommendation generation uses:

- Market and broker data.
- Knowledge tables.
- OpenAI proposal analysis when configured.
- Deterministic fallback scoring when OpenAI is unavailable.
- Crypto scoring from public market data and approved pairs.

Recommendations become `TradeProposal` objects and are persisted to SQLite. Saved recommendation sets are then used by the mobile UI and execution endpoints.

## Wisdom Storage

The app’s accumulated “wisdom” is stored in SQLite, not in the model itself. The main durable stores are:

- Company intelligence tables.
- Crypto research tables.
- Benchmark trader tables.
- Trade audit rows.
- Broker trade history.
- Performance attribution.
- Learning/report rows.
- Reports.

OpenAI provides reasoning at runtime. Unless a result is written to SQLite, the system does not retain it as durable platform knowledge.
