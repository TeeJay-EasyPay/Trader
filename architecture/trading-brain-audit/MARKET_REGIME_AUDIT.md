# Market Regime Audit

## Finding

AI Trader does not currently implement market regime detection.

## Conditions Requested

| Regime / Condition | Current Status | Evidence |
|---|---|---|
| Trending | `PARTIAL` | Crypto has `technical_trend_score` from 7d price change. No broader trend regime. |
| Ranging | `NOT_IMPLEMENTED` | No range detector. |
| Bull market | `NOT_IMPLEMENTED` | No bull market classifier. |
| Bear market | `NOT_IMPLEMENTED` | No bear market classifier. |
| High volatility | `PARTIAL` | Crypto volatility stored from 30d absolute change. No regime use. |
| Low volatility | `PARTIAL` | Implied by crypto volatility score, not used for strategy selection. |
| Risk-on | `NOT_IMPLEMENTED` | No macro/risk-on classifier. |
| Risk-off | `NOT_IMPLEMENTED` | No macro/risk-off classifier. |
| Liquidity stress | `NOT_IMPLEMENTED` | Liquidity exists for crypto as volume/market cap; no stress regime. |
| Crypto rotation | `NOT_IMPLEMENTED` | No sector/category rotation logic. |
| News-driven disorder | `NOT_IMPLEMENTED` | News can be passed to OpenAI, but no disorder detector blocks or changes strategy. |

## Regime Evidence Used

Current evidence that resembles regime input:

- `MARKET_THEMES` in `intelligence.py`.
- Crypto volatility/liquidity/trend fields.
- Benchmark trader market lessons.
- Alpaca news sent to OpenAI.

However, these are not combined into an explicit market regime state.

## Strategy Selection By Regime

Not implemented.

The code does not choose between different strategies based on market regime because no formal strategy registry or regime classifier exists.

## Confidence Changes By Regime

Not implemented as a regime-aware function.

Confidence can be affected indirectly when OpenAI reads news/market context or when crypto volatility affects risk score, but there is no explicit regime multiplier.

## Execution Blocked By Regime

Not implemented.

Execution can be blocked by market hours, broker availability, risk limits, drawdown, due diligence, confidence, and broker-specific seatbelts. It cannot currently be blocked by risk-off regime, high-volatility regime, news disorder, or liquidity-stress regime.

## Required Next Step

Add a `MarketRegimeEngine` that produces a persisted regime snapshot per market/broker/asset class, then require strategies to declare allowed regimes and regime-specific thresholds.
