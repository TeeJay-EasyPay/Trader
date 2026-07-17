# World-Class Trader Founder Briefing

Date: 2026-07-17

## 1. What AI Trader Can Now Genuinely Measure

It can measure broker connection state, broker trade/order rows recorded in SQLite, canonical lifecycle events, reconciliation runs, portfolio/cash values when brokers return them, and recommendation dossiers with bull/bear evidence.

## 2. What It Can Calculate Using Assumptions

It can calculate estimated capital in positions, exposure buckets when metadata exists, execution slippage when intended and actual prices exist, true R when entry/stop/quantity/P&L exist, and MAE/MFE when price observations exist.

## 3. What Remains Unavailable

Unavailable values include fields brokers do not return, fees not supplied by the exchange, correlation where history is too short, sector/country exposure where metadata is missing, and full learning confidence where closed-trade samples are small.

## 4. Why Some Values Are Unavailable

AI Trader now labels missing data with the reason and the requirement. For example, daily P&L needs a prior snapshot or broker value; correlation needs enough return history; closed-trade lessons need completed trades.

## 5. What Tests Prove

Focused tests prove lifecycle idempotency, invalid transition rejection, reconciliation mapping, true R, MAE/MFE, market-data validation, portfolio warnings, and governed learning proposals.

## 6. What Is Demonstrated With Historical/Paper Data

Strategy confidence, calibration, and learning remain sample-aware. They should not be trusted as a proven repeatable edge until enough closed trades and out-of-sample evidence exist.

## 7. Kraken

Kraken remains controlled live micro-trading only. Existing safeguards stay intact. Broker events can now feed canonical lifecycle records without weakening live controls.

## 8. Alpaca

Alpaca remains paper-controlled. Its broker events can now feed the same lifecycle and operational truth tables.

## 9. Validated Strategies

No strategy should be treated as fully production-validated solely from this sprint. The system distinguishes research, paper, live micro-capital candidate, and production evidence.

## 10. Strategies Under Research

Trend, momentum, breakout, pullback, crypto infrastructure trend, and related strategies remain under evidence collection and Strategy Lab validation.

## 11. What Can Be Safely Relied Upon Today

You can rely on the Orchestrator/Risk boundary, Kraken seatbelt model, Alpaca paper controls, broker-specific auto-trading permissions, recommendation bull/bear requirement, lifecycle idempotency, and plain-English unknown-value explanations.

## 12. What Must Not Yet Be Trusted With Increased Capital

Do not trust small-sample strategy performance, incomplete fee/slippage attribution, unproven correlation conclusions, or AI learning proposals as reasons to increase capital without governed approval.
