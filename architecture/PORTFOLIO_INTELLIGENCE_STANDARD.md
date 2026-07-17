# Portfolio Intelligence Standard

Date: 2026-07-17

## Objective

No recommendation should be assessed only in isolation. AI Trader must ask how a trade affects existing exposure, concentration, currency, broker allocation, and risk budget.

## Tables

- `ASSET_METADATA`: normalized metadata with source, timestamp, and confidence.
- `PORTFOLIO_EXPOSURE_SNAPSHOTS`: broker/all-broker exposure and plain-English warnings.
- `PORTFOLIO_CORRELATION_WARNINGS`: sample-aware correlation warnings.
- `PORTFOLIO_RISK_CONTRIBUTIONS`: stop-based and marginal risk contribution.
- `PORTFOLIO_STRESS_TESTS`: scenario impact with assumptions and uncertainty.

## Decisions

Portfolio impact can produce: buy, buy smaller, wait, reduce another exposure first, reject due to concentration, reject due to portfolio risk, or no action.

## Unknowns

Missing metadata, insufficient history, or unavailable broker position values must remain labelled. The system should explain what is needed to make each value available.
