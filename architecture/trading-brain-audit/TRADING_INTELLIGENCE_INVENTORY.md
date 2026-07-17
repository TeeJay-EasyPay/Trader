# Trading Intelligence Inventory

Classification key:

- `FULLY_IMPLEMENTED`: operationally used with clear logic.
- `PARTIALLY_IMPLEMENTED`: present and used, but shallow or incomplete.
- `STORED_BUT_NOT_USED`: stored in schema but not materially used in trading decisions.
- `DISPLAY_ONLY`: shown to user but not used for decisions.
- `PLACEHOLDER`: planned/scaffolded but not functional.
- `NOT_IMPLEMENTED`: no meaningful implementation found.

| Concept | Classification | Evidence |
|---|---|---|
| Trend | `PARTIALLY_IMPLEMENTED` | Crypto uses `technical_trend_score`; CoinGecko maps 7d price change through `_pct_to_unit_score`; crypto proposal requires `trend > 0.5` in `propose_crypto_trades`. Equity trend can appear in OpenAI text but no deterministic trend formula exists. |
| Momentum | `PARTIALLY_IMPLEMENTED` | Crypto stores `momentum_score` from 24h change. It is displayed in `technical_summary` but proposal gating only checks overall score and 7d trend. |
| Volatility | `PARTIALLY_IMPLEMENTED` | Crypto volatility = abs(30d change)/100 capped at 1. Risk score = 1 - volatility. Used in crypto score storage, indirectly through overall if overall is computed. |
| Volume | `PARTIALLY_IMPLEMENTED` | CoinGecko `total_volume` contributes to liquidity = volume / market cap. No volume breakout/relative-volume strategy exists. |
| Support/resistance | `NOT_IMPLEMENTED` | No source code calculates support or resistance levels. |
| Breakouts | `NOT_IMPLEMENTED` | No breakout rule or trigger found. |
| Mean reversion | `NOT_IMPLEMENTED` | No mean-reversion rule found. |
| Moving averages | `STORED_BUT_NOT_USED` | `CRYPTO_RESEARCH_SCORES.moving_average_position` exists, but CoinGecko metrics do not populate it and proposals do not use it. |
| RSI | `STORED_BUT_NOT_USED` | `CRYPTO_RESEARCH_SCORES.rsi` exists and tests may insert it; no calculation or decision use found. |
| MACD | `STORED_BUT_NOT_USED` | `CRYPTO_RESEARCH_SCORES.macd` exists; no calculation or decision use found. |
| ATR | `NOT_IMPLEMENTED` | No ATR calculation found. |
| Liquidity | `PARTIALLY_IMPLEMENTED` | Crypto computes liquidity from volume/market cap and stores it. Kraken checks GBP balance and pair allowed. No spread/order-book liquidity check. |
| Spread | `NOT_IMPLEMENTED` | No bid/ask spread check found. |
| Multi-timeframe analysis | `NOT_IMPLEMENTED` | Crypto uses 24h/7d/30d public changes but no multi-timeframe confluence model. Equity uses latest bars only unless OpenAI infers from supplied market payload. |
| Market structure | `STORED_BUT_NOT_USED` | `CRYPTO_RESEARCH_SCORES.market_structure` exists but is not computed by current CoinGecko path and not used in proposal gating. |
| Market regime | `NOT_IMPLEMENTED` | No regime classifier or strategy switch found. |
| Relative strength | `NOT_IMPLEMENTED` | No asset-relative benchmark or cross-sectional ranking used for execution. |
| Position sizing | `PARTIALLY_IMPLEMENTED` | Demo and crypto calculate quantity from risk/notional. Orchestrator caps notional through `calculate_capital_allocation`. Kraken has max/min/allocation checks. |
| Reward-to-risk | `PARTIALLY_IMPLEMENTED` | Demo and crypto use 2R take profit vs 1R stop. Guardrails require take profit and stop direction. No EV/probability-adjusted reward-to-risk model. |
| Stop placement | `PARTIALLY_IMPLEMENTED` | Crypto uses fixed default stop percentage. Equity OpenAI proposes stop. Orchestrator enforces stop presence and max stop percentage. No structural stop logic. |
| Take-profit placement | `PARTIALLY_IMPLEMENTED` | Crypto uses 2x default stop distance. Equity OpenAI proposes target. Orchestrator requires take profit. No target model based on resistance/volatility/regime. |
| Expected holding period | `DISPLAY_ONLY` | Freshness lifetime exists for recommendation expiry; holding period is reported after trade, not used to select trades. |
| Catalyst analysis | `PARTIALLY_IMPLEMENTED` | Equity prompt includes news. Company knowledge has thesis/caution/news summaries. No catalyst parser or catalyst-event trade rules. |
| News | `PARTIALLY_IMPLEMENTED` | Alpaca news is passed into OpenAI proposal prompt and stored in proposal summaries. Crypto news tables exist but no provider-backed crypto news integration. |
| Sentiment | `PARTIALLY_IMPLEMENTED` | OpenAI can produce market sentiment summary. Crypto sentiment field exists; fallback may seed 0.55; provider-backed sentiment not implemented. |
| Order book | `NOT_IMPLEMENTED` | No order-book depth or microstructure logic. |
| Fees | `PARTIALLY_IMPLEMENTED` | Raw Kraken payload includes fees in trade history, but proposal logic and EV do not model fees. |
| Slippage | `NOT_IMPLEMENTED` | No slippage model. |
| Portfolio exposure | `FULLY_IMPLEMENTED` for guardrail, not strategy | Orchestrator checks current exposure, max concurrent exposure, capital allocation, and position count. |
| Duplicate prevention | `FULLY_IMPLEMENTED` | Guardrails block duplicate long positions; `ORDER_INTENT_LOCKS` blocks duplicate submissions. |
| Managed exits | `PARTIALLY_IMPLEMENTED` | Kraken managed exits monitor stop/take-profit/trailing data via polling. This is risk management, not strategy intelligence. |

## Bottom Line

The system contains several trading concepts, but most are either shallow heuristics, stored fields, or risk controls. The strongest implemented trading concepts are position sizing, stop/take-profit enforcement, recommendation freshness, and broker/risk validation. The weakest areas are strategy definition, regime detection, signal calibration, and trade timing.
