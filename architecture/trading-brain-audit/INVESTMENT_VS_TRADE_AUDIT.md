# Investment Versus Trade Audit

## Finding

AI Trader currently mixes investment quality and trade quality into one recommendation/execution pipeline. It can store long-term investment context and short-term trade fields, but it does not cleanly classify an asset as:

- good investment only;
- good trade only;
- both;
- neither.

## Investment Evidence

Implemented investment evidence:

- `COMPANY_MASTER.investment_thesis`
- `COMPANY_MASTER.reasons_for_caution`
- `INVESTMENT_WATCHLIST.current_investment_philosophy_fit`
- `MARKET_THEMES`
- `INVESTMENT_POLICIES`
- `INVESTMENT_SCORES`
- `DUE_DILIGENCE_ASSESSMENTS`

This supports long-term investment review.

## Trade Evidence

Implemented trade evidence:

- Entry price.
- Stop loss.
- Take profit.
- Position size.
- Risk percentage.
- Technical summary.
- Recommendation freshness.
- Crypto trend/momentum/volatility/liquidity score fields.
- Broker current price for Kraken.

This supports a trade proposal but is not yet a full trade-quality model.

## Scoring Mix

`calculate_investment_score` combines:

- fundamental score;
- technical score;
- market score;
- macro score;
- behavioural score;
- investment policy score;
- risk score.

The resulting `overall_confidence` is used by the orchestrator as part of execution validation.

This means investment evidence and trade evidence are blended into one score. A high-quality long-term company can help the recommendation appear attractive even if the short-term trade timing is weak, depending on the proposal source. Conversely, a short-term crypto move can score well without long-term investment-grade analysis.

## Holding Period

Trade proposals do not contain a formal expected holding period. Reports can calculate time held after the fact. Recommendation freshness is not the same as expected holding period; it is an expiry window for acting on an idea.

## UI Representation

The UI shows investment thesis, confidence, technical score, stop loss, take profit, and broker information in the same recommendation card. It does not currently separate:

- investment case;
- trade setup;
- execution readiness;
- expected holding period;
- strategy type.

## Database Representation

The database contains both investment and trade fields, but there is no canonical distinction between:

- `investment_score`
- `trade_setup_score`
- `execution_score`
- `strategy_score`

## Conclusion

Current scoring mixes investment quality and trade quality. A world-class trading layer should split these into separate dimensions and only combine them at a final decision stage with explicit weights.
