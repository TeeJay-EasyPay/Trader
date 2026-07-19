# Market Intelligence Production Flow

## Production flow

```text
Worker research bucket
  -> configured equity or crypto universe
  -> provider retrieval and freshness checks
  -> due diligence and recommendation generation
  -> persisted research evidence
  -> persisted recommendation evidence
  -> Founder Market and Recommendations read models
```

`PRODUCTION_RESEARCH_EVIDENCE` records broker/asset scope, job name, timing, requested and processed assets, recommendations created, result status, primary reason and the structured source payload. `PRODUCTION_RECOMMENDATION_EVIDENCE` records the recommendation identity, broker, symbol, status, confidence, thesis, strongest argument for and against, and creation/expiry times.

The Market screen is evidence-driven. It may report completed cycles, reviewed assets, freshness and conclusions. It must not turn static company master data into a current-market claim. If a provider failed, no observations were returned or a cycle did not run, the screen states that condition.

## Freshness

Freshness is based on persisted completion and observation timestamps. The API never substitutes the mobile refresh time for the market observation time. Old recommendations remain historical records and are not executable merely because they are visible.

## No-trade evidence

The activity read model uses job results, research funnels and recommendation outcomes to explain whether no order resulted from no opportunity, governance rejection, execution blocking or an operational failure.
