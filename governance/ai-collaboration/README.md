# AI Executive Collaboration Protocol

This repository is the shared source of truth between the Founder and the AI
agents working on AI Trader. Instructions, implementation responses, reviews,
and decisions are recorded as files here so that no context has to be
manually copied between separate AI conversations.

## Roles

**Founder**
- final authority;
- approves strategic decisions;
- approves movement into high-risk implementation phases;
- resolves disagreements between AI recommendations.

**ChatGPT**
- overall CTO and architecture authority;
- produces implementation instructions;
- independently reviews Claude and Codex outputs;
- provides go/no-go recommendations;
- does not silently approve high-risk changes.

**Claude**
- primary technical programmer for substantial implementation work;
- follows approved architecture and handoff instructions;
- provides evidence-based implementation checkpoints;
- stops at defined review gates.

**Codex**
- supporting repository and implementation agent;
- may perform isolated tasks that do not conflict with Claude;
- follows the same handoff and evidence standards;
- must not edit files currently owned by another active agent unless
  explicitly authorised.

## Core principles

- repository files are the shared institutional memory;
- Git history and tests are objective evidence;
- one active instruction per agent at a time;
- every handoff names the branch and source commit;
- agents must not overwrite each other's original handoffs;
- corrections are issued as new files;
- no secrets or credentials are stored here;
- no high-risk phase proceeds without Founder approval;
- the agent completing work must provide exact evidence and deviations;
- ChatGPT review is advisory until the Founder approves the next action.

## Folder structure

- `CURRENT_HANDOFF.md` — single quick-reference status file;
- `SHARED_CONTEXT.md` — durable, stable project context;
- `DECISION_REGISTER.md` — append-only log of collaboration-protocol decisions;
- `HANDOFF_TEMPLATE.md` — template for an implementation agent's response;
- `INSTRUCTION_TEMPLATE.md` — template for an instruction to an implementation agent;
- `chatgpt-to-claude/` — instructions from ChatGPT to Claude (`active/`, `completed/`, `archive/`);
- `claude-to-chatgpt/` — handoffs from Claude to ChatGPT (`active/`, `completed/`, `archive/`);
- `chatgpt-to-codex/` — instructions from ChatGPT to Codex (`active/`, `completed/`, `archive/`);
- `codex-to-chatgpt/` — handoffs from Codex to ChatGPT (`active/`, `completed/`, `archive/`);
- `checkpoints/` — checkpoint placeholders and gate records;
- `review-reports/` — ChatGPT review reports and go/no-go recommendations.

Handoff and instruction files should link to authoritative repository paths
(architecture docs, implementation log, source files) rather than duplicating
their content.

## Workflow example

1. ChatGPT creates an instruction under `chatgpt-to-claude/active/`.
2. Claude performs the work.
3. Claude creates a checkpoint under `claude-to-chatgpt/active/`.
4. `CURRENT_HANDOFF.md` is updated to show ChatGPT as the active reviewer.
5. The Founder asks ChatGPT to review the linked checkpoint.
6. ChatGPT produces a review report and a go/no-go recommendation.
7. The Founder authorises the next phase.
8. Completed handoffs are moved to `completed/`, then later to `archive/`.
