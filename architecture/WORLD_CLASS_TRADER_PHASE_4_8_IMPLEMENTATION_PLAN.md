# World-Class Trader Transformation Programme Phase 4-8 Implementation Plan

Date: 2026-07-17

## Governing Principle

Every new capability must answer at least one of these questions:

1. Does it help AI Trader make a better investment decision?
2. Does it help the Founder make a better decision?
3. Does it help AI Trader learn to make better decisions in the future?

Capabilities that do not meet this test should not be implemented.

## Current Broker Boundary

Connected brokers:

- Alpaca
- Kraken

Future or disconnected brokers:

- Coinbase
- Binance
- Interactive Brokers
- Saxo
- any other broker adapter not configured with live credentials

Founder interfaces must prioritise Alpaca and Kraken. Disconnected brokers must be shown only as compact future/not-connected entries and must not be represented as healthy or active.

## Non-Negotiable Architecture

- The Investment Orchestrator remains the only execution authority.
- The Risk Engine and guardrails remain mandatory.
- Kraken live micro-trading safeguards remain intact.
- Alpaca remains paper-trading controlled unless governance changes.
- Learning, Strategy Lab, and AI commentary cannot silently change broker permissions, risk limits, position limits, strategy production state, or guardrails.
- Missing facts remain unavailable with an explanation.
- "Do nothing" is a valid recommendation.

## Delivery Strategy

The full requested programme is broad. Implementation will proceed through five internal workstreams and use additive SQLite migrations only.

Each workstream must:

- add or migrate schema safely;
- add deterministic backend logic;
- expose API evidence for the mobile app;
- add focused tests;
- update documentation;
- pass its decision gate before being marked complete.

## Workstream 1: Operational Truth

### Scope

Create a broker-neutral canonical lifecycle and reconciliation spine for Alpaca and Kraken.

### Deliverables

- Canonical lifecycle schema.
- Legal transition map.
- Idempotent lifecycle event recording.
- Broker trade/order reconciliation into lifecycle events.
- Execution cost calculation.
- True gross/net R calculations.
- MAE/MFE calculation with data-quality notes.
- Reconciliation health summary for Founder interfaces.

### Decision Gate

Passes only when tests prove:

- duplicate broker events are idempotent;
- invalid transitions are rejected and logged;
- Alpaca/Kraken raw broker rows can enter the lifecycle;
- actual fill prices and fees are captured where supplied;
- gross/net R are calculated from initial monetary risk;
- MAE/MFE are calculated with confidence notes.

## Workstream 2: Market Intelligence

### Scope

Create provider-neutral market observations and data-quality standards using available candles and existing intelligence sources.

### Deliverables

- Market data observation schema.
- Data quality validation for candles.
- Multi-timeframe intelligence summary.
- Fundamental/macro/event/news evidence schemas.
- Source-aware news clustering where evidence exists.
- Market Regime 2.0 evidence and contradiction summary.

### Decision Gate

Passes only when tests prove:

- stale/missing/impossible candles are identified;
- multi-timeframe agreement and disagreement are described;
- regime explanation includes supporting and contradictory evidence;
- technical conclusions include data-health context.

## Workstream 3: Portfolio Intelligence

### Scope

Normalize asset metadata and portfolio exposure so recommendations are not assessed in isolation.

### Deliverables

- Asset metadata schema.
- Exposure calculation by broker, asset class, sector, country, currency, theme, and crypto.
- Correlation warnings where enough history exists.
- Marginal risk contribution.
- Stress scenario summaries.
- Recommendation portfolio-impact decision labels.

### Decision Gate

Passes only when tests prove:

- concentration is visible;
- missing metadata is explained;
- correlation warning is generated from enough history;
- portfolio-based rejection/wait guidance can be produced.

## Workstream 4: Experience Engine and Governed Learning

### Scope

Capture immutable decision context, closed-trade reviews, analogues, calibration, and versioned learning proposals.

### Deliverables

- Experience records.
- Post-trade review generation.
- Analogue search.
- Segmented calibration.
- Versioned learning proposal schema and statuses.
- Strategy Lab validation-state expansion.

### Decision Gate

Passes only when tests prove:

- historical context is immutable;
- every closed trade can produce a review;
- good decision versus good outcome is distinguished;
- learning proposals cannot change production state silently.

## Workstream 5: Founder AI and Executive Decision Support

### Scope

Upgrade the Founder-facing API/UI evidence model while preserving read-only AI boundaries.

### Deliverables

- Founder AI evidence grounding.
- Daily executive brief.
- Decision dossier standard.
- Data availability explanations.
- Five-interface progressive disclosure:
  - Dashboard
  - Recommendations
  - Portfolio
  - Market
  - Learning

### Decision Gate

Passes only when tests and Expo validation prove:

- all five tabs load with partial payloads;
- disconnected brokers do not appear active;
- unavailable values explain why;
- Ask AI remains read-only;
- "do nothing" can be recommended.

## Deployment Gate

Before release:

- `py_compile` must pass.
- Focused tests must pass.
- Full Python suite must pass.
- Expo Doctor must pass.
- Render startup must initialise all schemas.
- Render `/healthz` must respond.
- Protected API routes must use the same token contract as Expo.
- Expo OTA must be published for runtime-compatible mobile changes.
- Git worktree must be clean.

