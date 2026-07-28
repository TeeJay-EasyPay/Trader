# Founder Truth Report

Plain English. This is the document to read if you only read one. Everything here is backed by specific code citations in the companion documents (`CLAUDE_INDEPENDENT_ARCHITECTURE_REVIEW.md`, `END_TO_END_LIFECYCLE_TRACE.md`, `PRODUCTION_TIMEOUT_ROOT_CAUSE_ANALYSIS.md`, `CRITICAL_REMEDIATION_PLAN.md`, `WORLD_CLASS_TARGET_ARCHITECTURE.md`).

---

**1. Is AI Trader currently trading autonomously?**

No, not in any proven sense. The worker is alive and cycling through its jobs, but no document, log, or persisted record examined in this review shows a single order being submitted, acknowledged, filled, or resulting in a closed position, at any point in time, for any date. The recovery report from today says the same thing explicitly. This isn't a guess — it's the absence of evidence where evidence would exist if it had happened.

**2. Is it currently capable of doing so reliably?**

Not yet, and this review found the specific reasons why, which is different from the vague "something's not quite right" pattern in past cycles. Research jobs are timing out for identifiable, fixable code reasons (unbatched external calls, a duplicate-scheduling bug, a database connection anti-pattern) — not because the underlying trading logic is broken. Once research can complete, the execution pipeline underneath it is largely sound for entries, but has a real gap on exits (no duplicate-order protection) and one unverified assumption (whether the P&L tables even exist on your live database) that needs to be checked before anything downstream of it can be trusted.

**3. Is Postgres truly the only production source of truth?**

Yes, by design and by configuration — this part is genuinely solid. Every Render service is locked to Postgres, and the code refuses to run in a hosted environment on anything else. The one open question is whether every table the application expects to exist on Postgres actually does — one table family (the one that computes your P&L) has no code path that creates it there, and this review could not check your live database directly. This is the single most important thing to verify next, and it's a five-minute check, not a project.

**4. Does one mandatory execution path exist?**

For opening new positions, yes — manual approval and autonomous execution both go through the identical chain of checks (strategy maturity, portfolio limits, risk limits, a final safety sentinel) before anything reaches a broker. For closing positions (stop-loss/take-profit exits), no — that's a separate, simpler path that skips those checks. That's a defensible design choice on its own (you don't want a risk gate blocking you from getting out of a losing position), but that same path is also missing the safeguard that stops the same order from being submitted twice, which is not defensible and should be fixed.

**5. Can any execution path bypass governance?**

For entries into Alpaca or Kraken specifically — the only two brokers actually capable of placing a live order today — no, the governance chain cannot be bypassed. For exits, yes, by design, though the risk that creates is duplication, not ungoverned risk-taking. The "Ask AI Trader" chat feature is correctly read-only and cannot place trades.

**6. Is trade-level P&L dependable?**

Not fully. There are two separate places in the code that calculate profit and loss for a trade, using two different methods, and nothing checks that they agree. For a simple trade (one entry, one exit) they should match. For anything with partial fills or scaling in/out, they can diverge, and you'd have no way of knowing which number is right just by looking at the app.

**7. Is learning fully automatic?**

Yes — this is the best-engineered part of the system. Once a trade is genuinely closed, learning is triggered without any human action, cannot be triggered twice for the same trade, and survives a worker crash mid-processing. The only real weakness is upstream of learning itself: if a trade never cleanly reaches "closed" (see the exit-order and orphaned-order issues above), it simply never gets learned from, silently.

**8. Why are the main jobs timing out?**

Four specific, different reasons, none of which are "the timeout is too short":
- The equity and crypto research jobs make their external calls (market data, news, AI analysis) one symbol at a time, in sequence, instead of in batches — a single slow response partway through a 30-symbol list can eat the whole time budget.
- The evening/overnight crypto job is being triggered twice by two different schedulers that don't know about each other, so it's often doing double the work it needs to.
- The evidence-snapshot job (the one that feeds your app's dashboard) makes up to nine separate calls to your brokers, one after another, when they could run at the same time.
- The Kraken startup check — which re-validates your trade history every time the worker restarts — opens a fresh database connection for nearly every single historical record it processes, which is enormously wasteful and gets slower as your trade history grows.

None of these require more powerful infrastructure. They require the code to batch its calls, stop double-scheduling itself, and stop opening thousands of unnecessary database connections. Full technical detail is in `PRODUCTION_TIMEOUT_ROOT_CAUSE_ANALYSIS.md`.

**9. What are the five most important remaining blockers?**

1. Exit orders have no protection against being submitted twice, and the worker's own timeout-kill mechanism creates exactly the conditions where that could happen.
2. A live order can, in a narrow window, become permanently "lost" by the system — not tracked, not exit-managed, not learned from — and be silently mistaken for a personal trade you made by hand.
3. Two schedulers are stepping on each other's jobs, which is directly responsible for several of the reported timeouts and would become a duplicate-order risk the moment auto-trading is switched on.
4. The system currently has no way to proactively tell you anything is wrong — every alert it generates is recorded in the database but never actually pushed to your phone, because of one environment flag that quietly disables the code path that would send it.
5. It is unverified whether your live database even has the tables that calculate P&L and drive learning — everything downstream of that is unproven until this is checked.

**10. What should be fixed before any new feature work?**

All five items above, plus rotating the exposed command token. These are the P0 items in `CRITICAL_REMEDIATION_PLAN.md`. None of them require new infrastructure or new capability — they are fixes to what's already built. Building anything new on top of this foundation before these are fixed would repeat the exact pattern that's caused the repeated "stuck again" cycles: new work layered on an unverified base.

**11. What should be fixed before larger capital?**

Everything in P0 and P1, plus: make the broker-side order protections actually work (right now one of your two brokers doesn't even receive the ID field that would let it reject a duplicate order on its own side), prove the orphaned-order recovery actually works via a real drill rather than just existing in theory, collapse the two conflicting P&L calculations into one, and rotate the token again specifically at the moment you decide to flip Kraken from dry-run to real orders — treat that switch as a new trust boundary, not a config change.

**12. What claims from earlier reports were overstated?**

The clearest one: `JOB_AND_WORKER_RECOVERY_STANDARD.md` states that duplicate jobs from different schedulers are automatically skipped. That's not true — it's true only within one scheduler's own repeat cycle, not between the cron jobs and the worker's internal schedule, and this gap is a real contributor to the timeouts you've been chasing. Separately, the architecture documentation describes "one" canonical trade lifecycle; the code actually has three overlapping representations of trade state that don't cross-check each other. Neither of these is a case of someone lying to you — they read as claims made in good faith at the time, about a mechanism that was reasonable in isolation but didn't hold up once the whole system was traced end to end, which is exactly the kind of gap this review was commissioned to find.

**13. What has Codex genuinely done well?**

Several things that deserve real credit, not faint praise:
- The database design is disciplined — one connection path for the whole app, and it refuses to run on the wrong database in production rather than silently falling back to something unsafe.
- Job isolation is real: a stuck job gets killed cleanly in its own process without taking down the whole worker, which is exactly what saved the system from total lockup on July 27.
- The logic that keeps your personal Kraken holdings separate from AI-managed trades is careful and specific — it doesn't just assume ownership from a matching symbol, it requires an explicit order-ID match, and explicitly excludes anything it can't prove.
- The system never mistakes "we bought something" for "the trade is closed" — closing requires the exit to actually match the entry quantity in real fills, not just an order being accepted.
- Learning is durable, automatic, and can't double-fire, which is a genuinely hard thing to get right and it's been gotten right here.
- The newer "why didn't it trade" explanation shown in the app is honest and specific — it doesn't just say "no action," it tells you which gate blocked it.

**14. What should Codex implement next?**

In order: verify the P&L tables exist on your live database; add the missing duplicate-order lock to exits; fix the double-scheduling; wire up push notifications so the system can actually reach you; fix the four timeout root causes (batch the calls, stop the redundant connections); then move to the P1 items. `CRITICAL_REMEDIATION_PLAN.md` has this laid out with exact files and line numbers so this doesn't require rediscovering any of it.

**15. Would you personally trust the current architecture with your own meaningful capital? Explain why.**

No, not yet — but the reasons are specific and fixable, not a fundamental design failure. I would not trust it today because: I cannot currently prove a single trade has ever completed the full journey from recommendation to learning; the exit path (the part that protects you when a trade goes wrong) is the least protected part of the entire order-submission system; and the system cannot currently tell you when something goes wrong without you opening the app and checking. Those three facts together mean that if something did go wrong with real money, you might not find out promptly, and the part of the system responsible for limiting the damage is the part with the weakest safety net.

I would trust it once: the P&L tables are confirmed to exist and be correct on your live database; exits have the same duplicate-order protection entries already have; the two schedulers are no longer fighting each other; push notifications actually reach your phone; and — most importantly — you can point to one real, complete, evidenced trade that went from recommendation through execution through learning, with every step backed by an actual record, not a "should have worked." None of that is far away. It's a focused list, not a rebuild.

---

## Final Question

> **What is the shortest credible path from the current system to a dependable, world-class autonomous paper trader with truthful Founder visibility and no known hidden architectural gaps?**

Fix the five P0 items in `CRITICAL_REMEDIATION_PLAN.md`, in this order, verifying each in hosted production before moving to the next — not just passing locally:

1. Confirm the P&L/execution-intent tables exist on the live Postgres database (or create them if they don't) — a direct database check, resolvable in under a day.
2. Add the missing duplicate-order lock to the exit path, mirroring the pattern that already works for entries.
3. Collapse the duplicate job scheduling to one scheduler per job.
4. Fix the four timeout root causes (batch external calls in research and evidence-snapshot; remove the connection-per-row pattern in Kraken reconciliation).
5. Wire push notifications into the worker's own job loop so incidents actually reach the Founder.

Each of these is a bounded, well-defined code change with an exact file and line number already identified — none require new infrastructure, new services, or architectural redesign. After all five are deployed, the acceptance bar is not "the tests pass" and not "the deploy succeeded" — it is one real, hosted-production-proven trade cycle: a specific recommendation that led to a specific submitted order, a specific fill, a specific closed position, a specific P&L number, and a specific learning record, each with a citable timestamp and ID, observed directly from the live system rather than inferred from an earlier stage succeeding. That single proven cycle — not a passing test suite, not a clean deploy log, not another architecture document — is what should end the cycle of repeated "stuck again" discoveries, because it is the one thing that has never yet been shown to happen at all.
