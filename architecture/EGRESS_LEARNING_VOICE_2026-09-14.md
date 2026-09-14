# Egress, proactive learning and conversational Trader

## Draft implementation checkpoint — not deployed

Worktree: `C:/Users/t_jeh/AppData/Local/Temp/trader-voice-release-20260914`.
Branch: `codex/egress-learning-voice-20260914`.

The scope is now FOUR areas: (1) reconcile existing local/committed/deployed work,
(2) reduce both database egress and OpenAI running costs without weakening decisions,
(3) proactive evidence-based learning, (4) conversational Trader voice.

API and active worker verified on `e4d7d2bda0cec559f5dd30a9c27fc208ef5cd0f7`.
Original uncommitted retention/approval/notification work remains preserved and excluded;
no retention, backup or live activation was enabled. Reconciliation requires a final
inventory and disposition of those files before release.

Offline tests: 16 reconciliation passed; 37 research/batch/routing passed; 55 combined
budget/research/routing/reconciliation passed. Broader selection: 104 passed, one
Standup placeholder wording assertion failed (investigate against baseline). Android
bundle export passed, but native APK has not been built or device-tested.

Read-only production comparison: identical 120-row candles for sampled symbol FORTH;
old JSON serialization 15,567 bytes. Conditional reads validate the database digest
each time and omit unchanged payloads. Not a measurement of total daily egress savings.

Real voice handshake blocked by HTTP 429 `credit_balance_exhausted` on the locally
configured OpenAI project. Two failed connection attempts, no successful response,
no microphone access. Do not retry paid checks until credits/project access is resolved.
Render may use a different key; do not infer its balance from the local key.

Remaining: cache invariance/corrections tests, full voice failure/UI interaction tests,
actual provider handshake, native APK build, cost evidence/report, source review,
commit/release and deployed version checks. These draft changes must NOT be described
as completed or deployed. The reference window and existing forecast reuse were already
implemented before this branch; do not count them as new savings.

- Reduce unnecessary database traffic without reducing decision evidence: use existing quiet-day query statistics, aggregate recurring summaries in SQL, preserve detailed drill-down, verify output parity and report measured versus estimated savings. No retention/deletion or protective-exit schedule changes.
- Give Trader an evidence-based improvement objective and proactive experiment workflow: one daily model proposal batch across schedule, evidence and chat inputs; five Alpaca and five Kraken slots; source/trigger labels; safe validation and explicit experiment IDs; daily progress without extra model calls; findings retrieved for future decisions. No automatic live activation, invented success, or arbitrary generated code execution.
- Add interruptible conversational voice only to Trader mode in Standup: visible start/mute/end and transcript; grounded backend evidence; server-side usage accounting and budget enforcement; stop on navigation/background/idle; text fallback. Group Standup and Claude remain unchanged. Initial voice budget: $10/month, separate from research. Verify actual usage rather than promise a fixed number of minutes.

## Release requirements

Preserve pre-existing local retention/notification work by using an isolated release worktree. Test negative paths, permission boundaries, budget races and fresh evidence. Commit and deploy only this scope; verify backend/worker versions and mobile publication. No real broker order is required for shadow comparisons. Report any access or platform constraint honestly rather than marking an incomplete feature complete.
