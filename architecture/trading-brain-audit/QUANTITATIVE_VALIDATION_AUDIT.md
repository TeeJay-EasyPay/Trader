# Quantitative Validation Audit

| Capability | Classification | Evidence |
|---|---|---|
| Backtesting | `ABSENT` | No backtest engine, historical dataset runner, or strategy simulation found. |
| Out-of-sample testing | `ABSENT` | No train/test split or OOS evaluation. |
| Walk-forward testing | `ABSENT` | No walk-forward framework. |
| Shadow trading | `PARTIAL` | Alpaca paper trading exists. Kraken has real micro-trading, not shadow mode. No formal shadow-vs-live comparison. |
| Strategy-level paper performance | `ABSENT` | Trades are not labelled by formal strategy. |
| Benchmark comparison | `PARTIAL` | Benchmark trader lessons exist, but no quantitative benchmark comparison. |
| Slippage modelling | `ABSENT` | No slippage model. |
| Fee modelling | `PARTIAL` | Fees can appear in raw broker payloads; not modelled in recommendations or EV. |
| Survivorship-bias control | `ABSENT` | No historical universe management. |
| Look-ahead-bias control | `ABSENT` | No backtest engine, so no look-ahead controls. |
| Parameter overfitting control | `ABSENT` | No parameter optimization framework. |
| Probability calibration | `ABSENT` | Confidence scores are not calibrated against historical outcomes. |
| Expected-value analysis | `ABSENT` | No expected value formula combining win probability, reward, risk, fees, and slippage. |
| Profit-factor analysis | `PARTIAL` | Reports can summarize P&L where attribution exists; no strategy-level profit factor. |
| Maximum-drawdown analysis | `PARTIAL` | Runtime drawdown guardrail exists through snapshots; no strategy backtest drawdown analysis. |

## Conclusion

The platform has validation tests for software behaviour and guardrails. It does not yet have quantitative strategy validation. This is the largest gap between the current system and a world-class autonomous trading platform.
