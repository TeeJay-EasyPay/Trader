# Governance Reference

Governance documents are stored under `governance/`. They define founder intent, architecture decisions, risk boundaries, validation history, and operating constraints.

## Primary Governance Documents

| Document | Purpose |
|---|---|
| `INVESTMENT_POLICY_STATEMENT.md` | Core investment policy. Defines permitted behavior, risk limits, broker policy, auto-trading boundaries, and founder approval constraints. |
| `RISK_MANAGEMENT_POLICY.md` | Risk management policy for position sizing, loss limits, drawdown, stop loss, take profit, and emergency behavior. |
| `BROKER_EXECUTION_POLICY.md` | Broker execution rules, including broker separation, validation, paper/live permissions, and execution controls. |
| `AI_LEARNING_POLICY.md` | Defines what AI learning may and may not do. AI may learn and recommend; it must not change governance or strategy automatically. |
| `TRADING_LOG.md` | Append-only human-readable trading journal. |
| `DECISION_REGISTER.md` | Architecture and product decision record. |
| `IMPLEMENTATION_LOG.md` | Chronological implementation history. |
| `STATUS.md` | Current project status and validation state. |

## Architecture And Design Documents

| Document | Purpose |
|---|---|
| `ARCHITECTURE_DESIGN.md` | Original architecture design. |
| `ARCHITECTURE_ASSESSMENT.md` | Architecture review and assessment. |
| `DESIGN_REPORT.md` | Design report for implementation decisions. |
| `ENGINEERING_REVIEW_REPORT.md` | Engineering review findings and release considerations. |
| `FOUNDATION_SPRINT_IMPLEMENTATION_PLAN.md` | Foundation sprint plan. |

## Founder Documents

| Document | Purpose |
|---|---|
| `FOUNDER_BRIEF.md` | Founder briefing content. |
| `FOUNDER_BRIEFING_TEMPLATE.md` | Template for daily founder briefing. |
| `FOUNDER_RELEASE_BRIEF.md` | Release briefing for founder review. |
| `EXECUTIVE_FOUNDER_BRIEF_FOUNDATION_SPRINT.md` | Foundation sprint founder summary. |

## Intelligence Governance

| Document | Purpose |
|---|---|
| `INVESTMENT_INTELLIGENCE_SCHEMA.md` | Investment intelligence schema documentation. |
| `BENCHMARK_INTELLIGENCE_SCHEMA.md` | Benchmark trader intelligence schema. |
| `KNOWLEDGE_ENGINE_REPORT.md` | Knowledge engine report. |
| `INVESTMENT_UNIVERSE.md` | Approved investment universe context. |

## Validation And Risk Documents

| Document | Purpose |
|---|---|
| `VALIDATION_REPORT_2026-07-02.md` | Validation sprint report. |
| `SAFETY_ASSESSMENT.md` | Safety review and risk posture. |
| `REMAINING_RISKS.md` | Known residual risks. |

## Governance Control Model

Governance controls AI Trader in three ways:

1. Human-readable policy documents define founder intent.
2. Environment variables and SQLite policy rows make selected controls executable.
3. The orchestrator enforces rules before broker submission.

The AI can:

- Read evidence.
- Generate proposals.
- Explain decisions.
- Recommend improvements.

The AI must not:

- Change governance documents.
- Change broker permissions.
- Raise position size or allocation caps.
- Disable guardrails.
- Modify execution logic.
- Submit directly to brokers.

## Required Governance Discipline

Future changes should update:

- Relevant architecture document.
- `DECISION_REGISTER.md` for significant decisions.
- `IMPLEMENTATION_LOG.md` for implementation work.
- `STATUS.md` for release status.
- Policy documents if risk or broker behavior changes.

This handover pack does not replace governance. It indexes and explains the live system.
