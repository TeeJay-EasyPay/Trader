# Engineering Directives

This folder contains version-controlled Engineering Directives for Claude
Code, Codex, and future AI engineering agents working on AI Trader.

## Purpose

Engineering Directives replace long, ad-hoc clipboard prompts wherever
practical. Instead of pasting a large mission brief into a chat session, the
brief is written once as a directive file, committed to the repository, and
referenced or reused going forward.

## Governance vs. Directives

- **Governance documents** (`governance/`, `architecture/`) define how the
  project is governed: the Constitution, policies, standards, and the
  authoritative record of what has been built and decided.
- **Engineering Directives** (this folder) define specific missions for AI
  agents: what to implement, review, or verify in a given working session.

Directives operate within the boundaries governance sets. They do not
override the Constitution or any governance document.

## Required Review Before Executing a Directive

Before executing any directive in this folder, an agent must review:

- the governing Constitution
  (`architecture/AI_TRADER_FOUNDING_PRINCIPLES_ARCHITECTURE_CONSTITUTION_v1.0.md`);
- relevant governance documents (`governance/`);
- relevant architecture documents (`architecture/`);
- the implementation log (`governance/IMPLEMENTATION_LOG.md`) and any other
  relevant implementation history, to understand what has already been done
  and what remains.

## Folder Structure

- `implementation/` — directives that authorize and scope a build/integration
  session.
- `architecture/` — directives scoped to architectural design or review work.
- `operations/` — directives scoped to operational, deployment, or production
  verification work.
- `reviews/` — directives that authorize an independent review or audit.
- `templates/` — reusable templates for writing new directives.

## Audit Trail

Completed directives are **not deleted or moved**. They remain in the
repository as part of the project's permanent audit trail, alongside the
implementation log entries and reports that resulted from executing them.
