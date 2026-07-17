# Strategy Audit

## Formal Strategy Standard

For this audit, a real strategy requires:

- Defined market conditions.
- Entry rules.
- Exit rules.
- Stop method.
- Profit-taking method.
- Position-sizing method.
- Suitable timeframe.
- Suitable market regime.
- Failure conditions.

## Finding

AI Trader does not currently have a formal production-grade trading strategy.

It has:

- OpenAI-assisted equity proposal generation.
- A deterministic crypto positive-trend heuristic.
- Demo paper-trading proposal logic.
- Strong guardrails and execution validation.

It does not have a named strategy with fully defined conditions, backtest evidence, regime dependency, calibrated probabilities, or strategy-level performance tracking.

## Identifiable Strategy-Like Behaviours

### 1. OpenAI Conservative Equity Proposal

Asset class: equities.

Timeframe: not explicitly defined.

Entry rules:

- OpenAI is asked to propose only when setup is clear and conservative.
- It receives latest market/news/account context.
- No deterministic entry rule exists in code.

Exit rules:

- OpenAI must provide stop loss and take profit.
- Guardrails check directional correctness.

Stop logic:

- Proposed by OpenAI.
- Enforced by guardrails and orchestrator.

Take-profit logic:

- Proposed by OpenAI.
- Enforced by guardrails and orchestrator.

Position sizing:

- Proposed by OpenAI, then capped by capital allocation in orchestrator.

Required evidence:

- Alpaca latest bars.
- Alpaca news.
- Account context.

Market-regime dependency:

- None implemented.

Backtest evidence:

- None found.

Paper-trading evidence:

- Broker history exists, but no strategy-level attribution.

Live evidence:

- None for Alpaca; Alpaca is paper only.

Approval status:

- Allowed for paper trading subject to guardrails.

Classification:

- Strategy-like proposal generator, not a formal strategy.

### 2. Kraken Crypto Positive 7-Day Trend Heuristic

Asset class: crypto.

Timeframe:

- Uses 7-day trend score and current price.

Entry rules:

- `overall_due_diligence_score >= min_confidence`.
- `technical_trend_score > 0.5`.
- Current Kraken price available.
- Buy only.

Exit rules:

- Managed stop loss and take profit.

Stop logic:

- `entry_price * (1 - crypto_default_stop_loss_pct)`.

Take-profit logic:

- `entry_price * (1 + crypto_default_stop_loss_pct * 2)`.

Position sizing:

- `crypto_max_trade_amount / price`, then orchestrator and Kraken seatbelts.

Required evidence:

- Latest `CRYPTO_RESEARCH_SCORES`.
- Kraken current price.
- Kraken account allocation.

Market-regime dependency:

- None.

Backtest evidence:

- None found.

Paper-trading evidence:

- Not applicable to Kraken; Kraken live micro-trading only.

Live evidence:

- Broker trade history exists, but no strategy-level win-rate/profit-factor calibration.

Approval status:

- Can execute only if Kraken live switches and broker auto-trading are enabled.

Classification:

- Deterministic entry heuristic, not a complete strategy.

### 3. Demo 1R/2R Paper Validation Proposal

Asset class: equities.

Timeframe:

- None.

Entry rules:

- Always buy latest price in demo mode.

Exit rules:

- Stop at 1R, target at 2R.

Position sizing:

- Risk-limited quantity from account equity.

Backtest/live evidence:

- None. This is test/demo validation only.

Approval status:

- Demo only.

Classification:

- Validation fixture, not a production strategy.

## What Is Missing For A Real Strategy

The current code lacks:

- Strategy registry.
- Strategy IDs on recommendations.
- Market-condition eligibility.
- Explicit entry triggers.
- Signal invalidation conditions.
- Timeframe definition.
- Regime filters.
- Backtest and paper-performance evidence.
- Per-strategy performance attribution.
- Probability/expected value calibration.
