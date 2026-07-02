# Decision Register

Date: 2026-07-02

| ID | Decision | Rationale | Status |
| --- | --- | --- | --- |
| DR-001 | Version 1 has exactly two runtime components: AI Trading Agent and Execution Engine. | Matches founder requirement and reduces complexity. | Accepted |
| DR-002 | The execution engine is deterministic and never uses AI. | Prevents AI from bypassing validation or broker controls. | Accepted |
| DR-003 | Guardrails are implemented once in shared code and invoked by both components. | Ensures both components enforce exactly the same rules. | Accepted |
| DR-004 | SQLite is the Version 1 audit database. | Simple, durable, local, and sufficient for personal paper trading. | Accepted |
| DR-005 | Historical audit records are append-only by convention. | Preserves traceability and prevents accidental loss of trade history. | Accepted |
| DR-006 | Alpaca integration uses paper trading endpoints only. | The project is explicitly paper trading only. | Accepted |
| DR-007 | Credentials are read only from environment variables. | Avoids hard-coded secrets and supports local secure configuration. | Accepted |
| DR-008 | The CLI is the primary interface for Version 1. | Keeps the first version small and testable. | Accepted |
| DR-009 | OpenAI analysis is optional; deterministic fallback is available. | Allows local testing without external AI calls while preserving the AI-ready boundary. | Accepted |
| DR-010 | The agent may recommend strategy improvements but never applies them automatically. | Keeps the founder in control of learning and strategy changes. | Accepted |

