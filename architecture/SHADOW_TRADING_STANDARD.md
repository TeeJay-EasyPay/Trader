# Shadow Trading Standard

## Purpose

Shadow trading records what AI Trader would have done without submitting broker orders.

It exists so AI Trader can learn when:

- Alpaca auto trading is disabled;
- Kraken live trading is disabled;
- a Founder has not opened the app;
- a recommendation is interesting but not executable.

## Required Fields

Each shadow trade records:

- symbol;
- asset type;
- intended broker;
- strategy;
- regime;
- decision status;
- intended entry;
- stop loss;
- take profit;
- quantity or notional;
- probability;
- expected R;
- strongest argument for;
- strongest argument against;
- reason for waiting or rejection;
- market evidence snapshot;
- portfolio snapshot;
- data-quality snapshot;
- expiry;
- simulated cost assumptions.

## Decision Statuses

- `shadow_candidate`
- `shadow_wait`
- `shadow_rejected`
- `shadow_insufficient_evidence`
- `shadow_no_valid_strategy`
- `shadow_portfolio_rejected`
- `shadow_risk_rejected`
- `shadow_approved`

## Boundary

Shadow trades never submit broker orders.

## Outcome Tracking

Outcomes may be updated with:

- theoretical fill price;
- stop or target outcome;
- expiry outcome;
- gross R;
- estimated net R;
- MAE;
- MFE;
- holding time.

If market data is stale or missing, outcome status must remain pending or blocked with an explanation.

