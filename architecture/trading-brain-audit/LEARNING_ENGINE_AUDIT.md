# Learning Engine Audit

## What Is Stored

Learning-related evidence is stored in:

- `trade_audit`
- `BROKER_TRADE_HISTORY`
- `PERFORMANCE_ATTRIBUTION`
- `ORCHESTRATOR_DECISIONS`
- `AUTO_TRADE_EVENTS`
- `RESEARCH_RUNS`
- `BENCHMARK_DAILY_RESEARCH`
- `TRADING_REPORTS`
- `daily_briefings`

## Completed Trade Outcomes

Closed trade attribution is stored in `PERFORMANCE_ATTRIBUTION` when managed exits can link entry and exit data. `close_managed_exit_and_record` calculates P&L as:

```text
profit_loss = (exit_price - entry_price) * quantity * direction_multiplier
```

where direction multiplier follows the original position direction.

Limitation:

- Raw broker fills in `BROKER_TRADE_HISTORY` do not always become complete attribution rows.

## Daily Learning Updates

`LocalApiService.daily_learning_update` reads closed attribution, rejections, benchmark notes, and reports lessons/recommendations. It explicitly says learning updates propose improvements only and do not change strategy, guardrails, or execution logic automatically.

## Benchmark Learning

Benchmark trader records are available as context and report inputs. They do not automatically change scoring or selection.

## Recommendation History

Recommendation history is stored and displayed. It does not currently train a model or recalibrate future scores.

## Does Past Performance Change Future Decisions?

| Area | Classification | Evidence |
|---|---|---|
| Future confidence | `REPORTING_ONLY` | No function adjusts future confidence from historical win/loss outcomes. |
| Asset selection | `AVAILABLE_AS_CONTEXT` | Watchlists and crypto master influence universe; outcomes do not automatically promote/remove assets. |
| Strategy selection | `NOT_USED` | No strategy registry exists. |
| Entry timing | `NOT_USED` | No timing model learns from past entries. |
| Stop distance | `NOT_USED` | Defaults/policies control stops; past stop-outs do not alter stop distance automatically. |
| Position size | `NOT_USED` | Sizing follows policy/allocation caps; no performance-based sizing adaptation. |
| Holding period | `REPORTING_ONLY` | Holding period is calculated after trades close. |
| Market-regime interpretation | `NOT_USED` | No regime engine exists. |
| Recommendations/explanations | `AVAILABLE_AS_CONTEXT` | Ask AI and reports can reference stored outcomes and benchmark lessons. |

## Bottom Line

AI Trader currently learns in the human sense of recording evidence and producing lessons. It does not yet learn in the autonomous quantitative sense of adapting models, strategies, thresholds, timing, stops, or sizing from outcomes.
