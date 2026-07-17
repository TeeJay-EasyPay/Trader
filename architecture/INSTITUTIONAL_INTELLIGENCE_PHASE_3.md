# Institutional Intelligence & Founder Experience Phase 3

Date: 2026-07-17

## Purpose

Phase 3 moves AI Trader closer to a professional investment partner by improving two surfaces at the same time:

1. The trading brain must choose strategies from evidence, not from a fixed default.
2. The Founder experience must explain decisions, risks, learning, and portfolio state in plain English.

The long-term architectural principle for every new capability is:

- Does it help AI Trader make a better investment decision?
- Does it help the Founder make a better decision?
- Does it help AI Trader learn to make better decisions in the future?

If a capability does not satisfy at least one of those questions, it should not be added.

## Institutional Intelligence Changes

### Evidence-Driven Strategy Selection

`src/ai_trader/trading_intelligence.py` now selects a strategy after market intelligence and regime inference have been calculated.

The previous safe default remains available for demo/paper validation, but production recommendation intelligence now evaluates candidate strategies against:

- asset type;
- market regime;
- trend score;
- momentum score;
- breakout/breakdown evidence;
- mean-reversion evidence;
- volatility;
- crypto liquidity/risk evidence where available.

The selected strategy now records:

- `selection_reason`;
- `candidate_scores`;
- `rejected_strategies`;
- `production_ready`;
- `validation_status`.

This gives the Founder and future reviewers a visible answer to: "Why this strategy, and why not another one?"

### Strategy Lab

Phase 3 adds `run_walk_forward_validation`.

The Strategy Lab now supports:

- historical replay through existing backtest primitives;
- walk-forward validation;
- train/test windows;
- out-of-sample aggregation;
- transaction cost assumptions;
- slippage assumptions;
- buy-and-hold benchmark comparison;
- parameter optimisation records for review only;
- bias-control notes for look-ahead and survivorship risk.

Strategy Lab results are written to `STRATEGY_LAB_RUNS`.

Important governance rule: Strategy Lab output never changes production strategy, guardrails, sizing, or execution logic automatically. It creates evidence for Founder review.

### Portfolio Intelligence

Trade intelligence now has a richer portfolio-fit section:

- current exposure;
- proposed notional;
- prospective exposure;
- largest position;
- largest position percentage;
- proposed risk contribution;
- diversification status;
- sector/theme/currency/country notes;
- capital efficiency;
- liquidity evidence availability;
- risk-budget note.

Unknowns are deliberately labelled as unknown. The system should not pretend to know sector, correlation, or liquidity where the data provider is not configured.

## Founder Experience API

`GET /status` now includes a `founder_experience` object.

It is designed for mobile screens and executive reporting. It groups data into:

- `executive_dashboard`;
- `portfolio_command`;
- `market_intelligence_centre`;
- `learning_lab`;
- `architectural_principle`.

This payload is intentionally plain-English oriented. It keeps raw broker and intelligence payloads available elsewhere while giving the Founder a concise view of what matters.

## Mobile Experience

The mobile app now uses five Founder-facing screens:

1. Dashboard
2. Recommendations
3. Portfolio
4. Market
5. Learning

The app shell now uses a dark background with white decision cards. The intent is to make the app feel like an executive command centre rather than a raw database viewer.

### Dashboard

Answers:

- What do I need to know?
- What should I do?
- What should I worry about?

Shows:

- executive summary;
- portfolio health;
- overall AI confidence;
- market regime;
- recommendation count;
- risk;
- diversification;
- open positions;
- capital deployed;
- cash;
- learning progress;
- prediction accuracy;
- best and weakest strategies;
- committee confidence;
- connection and trading readiness;
- Founder actions.

### Recommendations

Recommendations remain grouped and expandable.

Each recommendation continues to show:

- strategy;
- market/regime evidence;
- signal evidence;
- bull case;
- bear case;
- committee review;
- probability;
- setup;
- guardrails;
- exit plan;
- manual approval controls.

No recommendation may be produced unless AI Trader can articulate both the strongest argument for the trade and the strongest argument against the trade.

### Portfolio

The previous command-centre detail is now reframed as a Portfolio Command Centre.

It shows:

- allocation;
- cash;
- deployed capital;
- diversification;
- portfolio risk;
- expected return caveat;
- exposure checks;
- rebalancing suggestions;
- broker panels;
- detailed trade history with expandable rows.

### Market

Shows:

- current market regime;
- market health;
- volatility explanation;
- momentum explanation;
- breadth availability;
- crypto health;
- sector rotation caveat;
- major themes;
- watch list;
- important news;
- upcoming risks;
- 24/7 research status;
- benchmark trader learning.

### Learning

Shows:

- learning progress;
- prediction accuracy;
- calibration;
- best/worst strategy;
- validation status;
- lessons learned;
- Founder suggestions;
- strategy rankings;
- backtest and walk-forward evidence;
- committee-performance caveat;
- signal rankings;
- read-only Ask AI Trader.

## Current Limits

Phase 3 improves structure and visibility, but it does not magically make the system institution-grade. Remaining gaps include:

- broader historical market data provider;
- reliable sector/country/correlation provider;
- market breadth provider;
- more closed trade samples for calibration;
- stronger mobile visual QA on physical devices;
- scheduled Strategy Lab automation;
- explicit approval workflow for promoting a validated strategy.

## Verification

Focused tests added to `tests/test_trading_intelligence.py` verify:

- evidence-driven strategy selection records alternatives;
- walk-forward validation writes Strategy Lab evidence;
- portfolio intelligence records exposure and diversification fields.

