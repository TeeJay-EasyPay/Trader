# Learning Pipeline Production Flow

The worker continues to invoke the governed learning processor. Each completed learning cycle is projected to `PRODUCTION_LEARNING_EVIDENCE` with a deterministic key, completion time, review count, proposal count, status, summary and structured payload.

The Learning screen uses this shared evidence to show when learning last ran and what durable work it completed. Strategy quality, prediction accuracy and calibration are shown only when their source records contain sufficient outcomes. A completed scheduler job alone is not presented as improved trading skill.

Learning remains governed:

- no learning result can change broker permissions;
- no result can modify guardrails silently;
- no strategy is promoted directly from an AI explanation;
- proposals remain versioned suggestions requiring the existing approval path;
- missing sample sizes are reported as insufficient evidence.

Closed-loop trade learning still depends on terminal, reconciled trade evidence. Open trades cannot produce a final profitability lesson.
