# AI Collaboration Decision Register

Register created: 2026-08-03. This register is append-only and records
decisions specific to the AI executive collaboration protocol (this folder),
separate from the project-wide register at
[`governance/DECISION_REGISTER.md`](../DECISION_REGISTER.md).

The decisions below were already agreed by the Founder prior to this
register's creation; this entry formalises them under stable IDs rather than
proposing them fresh. The date recorded is the date they were formalised
here, not necessarily the date each was first agreed.

| Decision ID | Date | Decision | Rationale | Decided By | Related Files | Status |
| --- | --- | --- | --- | --- | --- | --- |
| AI-COLLAB-001 | 2026-08-03 | AI Trader will use a repository-based AI collaboration protocol. | Keeps coordination between Founder and AI agents auditable and durable instead of living in separate chat histories. | Founder | `README.md` | ACTIVE |
| AI-COLLAB-002 | 2026-08-03 | ChatGPT acts as overall CTO and independent reviewer. | Provides an independent architecture and review authority distinct from the implementation agents. | Founder | `README.md` | ACTIVE |
| AI-COLLAB-003 | 2026-08-03 | Claude acts as the primary technical implementation agent. | Claude is doing the substantial modularisation implementation work. | Founder | `README.md`, `CURRENT_HANDOFF.md` | ACTIVE |
| AI-COLLAB-004 | 2026-08-03 | Codex may perform isolated non-conflicting support tasks. | Allows supporting work without risking collisions with Claude's active implementation. | Founder | `README.md` | ACTIVE |
| AI-COLLAB-005 | 2026-08-03 | Modularisation Phases 0-7 may proceed before a formal checkpoint. | Keeps low-risk, behaviour-preserving phases moving without blocking on review for each one. | Founder | `checkpoints/2026-08-02_MODULARISATION_PHASES_0_TO_7_CHECKPOINT_PENDING.md` | ACTIVE |
| AI-COLLAB-006 | 2026-08-03 | Phase 8 requires ChatGPT review and explicit Founder go/no-go approval. | Phase 8 (execution logic) is the highest-risk extraction and needs an explicit gate. | Founder | `checkpoints/2026-08-02_MODULARISATION_PHASES_0_TO_7_CHECKPOINT_PENDING.md`, `SHARED_CONTEXT.md` | ACTIVE |
| AI-COLLAB-007 | 2026-08-03 | Repository files and Git history are the shared source of truth. | Avoids divergent, unverifiable accounts of what was done between AI agents. | Founder | `README.md` | ACTIVE |
| AI-COLLAB-008 | 2026-08-03 | No AI agent may store credentials or secrets in handoff files. | Basic operational security for a repository that multiple agents read and write. | Founder | `README.md`, `HANDOFF_TEMPLATE.md`, `INSTRUCTION_TEMPLATE.md` | ACTIVE |
