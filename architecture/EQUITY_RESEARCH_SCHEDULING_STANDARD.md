# Equity Research Scheduling Standard

## Schedule

AI Trader supports four named equity jobs:

- `premarket-equity`
- `market-open-equity`
- `midday-equity`
- `market-close-equity`

Each job is executed by:

```text
python -m ai_trader run-job <job-name>
```

## Responsibilities

Premarket:

- Update universe.
- Review overnight information.
- Identify event risk.
- Prepare watchlist.

Market open:

- Refresh prices and volume.
- Assess opening conditions.
- Create shadow decisions.
- Create paper candidates when valid.

Mid-session:

- Update setups.
- Invalidate stale ideas.
- Identify new opportunities.

Market close:

- Reconcile positions.
- Update shadow outcomes.
- Generate attribution.
- Prepare next-session watchlist.

## Non-Trading Hours

Outside equity market hours:

- Crypto research may continue.
- Historical research may continue.
- Shadow outcome monitoring may continue.
- Equity market orders must not be submitted outside allowed hours.

