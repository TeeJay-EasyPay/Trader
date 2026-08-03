# Shared Context

This file holds durable, stable context for the AI collaboration. It is not
a transcript dump and should not be updated for daily status changes — use
`CURRENT_HANDOFF.md` for that.

## Project purpose

AI Trader is an autonomous/semi-autonomous trading system with real broker
integrations (Alpaca, Kraken), a founder-facing mobile app, and a research
and learning engine. Safety controls (kill switch, reconciliation, capital
isolation, broker authorisation) are treated as first-order constraints on
any implementation work.

## Current architecture workstream

AI Trader modularisation: decomposing large, monolithic files (application
code and mobile `App.js`) into smaller, behaviour-preserving modules, in
phased, reviewable steps.

## Approved role split

See `README.md` in this folder for the full role definitions. In summary:
ChatGPT is CTO/architecture authority and independent reviewer; Claude is
primary implementation agent; Codex is a supporting implementation agent;
the Founder holds final authority.

## Location of key documents

- Modularisation discovery pack: [`architecture/AI_TRADER_MODULARISATION_DISCOVERY_PACK_2026-08-02.md`](../../architecture/AI_TRADER_MODULARISATION_DISCOVERY_PACK_2026-08-02.md)
- Modularisation architecture: [`architecture/AI_TRADER_MODULARISATION_ARCHITECTURE_2026-08-02.md`](../../architecture/AI_TRADER_MODULARISATION_ARCHITECTURE_2026-08-02.md)
- Current-state snapshot for redesign: [`architecture/CURRENT_STATE_FOR_REDESIGN_2026-08-02.md`](../../architecture/CURRENT_STATE_FOR_REDESIGN_2026-08-02.md)
- Implementation log: [`governance/IMPLEMENTATION_LOG.md`](../IMPLEMENTATION_LOG.md)

## Current checkpoint rule

Modularisation Phases 0-7 may proceed under the existing approval before a
formal checkpoint. Phase 8 requires a ChatGPT review of the Phases 0-7 work
and an explicit Founder go/no-go decision before it begins.

## Safety principle

Execution logic is the final and highest-risk extraction in this
modularisation effort. It must be handled with the most conservative
process, the most explicit evidence, and the latest checkpoint in the
sequence, not the earliest.

## Source of truth

Application code, tests, and observed runtime behaviour remain the
technical source of truth. This governance structure records decisions and
coordination; it does not substitute for reading the code or the
implementation log.
