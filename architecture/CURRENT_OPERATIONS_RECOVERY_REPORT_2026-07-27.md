# AI Trader Current Operations Recovery Report

**Report date:** 27 July 2026  
**Environment:** Render production, Supabase/Postgres, Android Founder app  
**Current deployed recovery commit:** `c67b22f93bb1cfd8d45e138f5fb9b1a4b4844b1c`  
**Report purpose:** Explain what has been investigated, what has been changed, what production evidence proves, what remains unresolved, and what should happen next.

## 1. Executive Summary

AI Trader's Render background worker is now alive, supervised, connected to the shared Postgres database, and continuing to run when the mobile application is closed.

The most important recovery achieved on 27 July is that a slow or stalled job can no longer permanently freeze the entire worker. Kraken startup reconciliation exceeded its 180-second execution boundary, was recorded as timed out, and the worker then continued to managed-exit monitoring and broker polling.

This proves that the autonomous process is now resilient enough to continue after an individual job timeout. It does not yet prove that the complete autonomous investment cycle is healthy.

The remaining production problem is now narrower and visible:

- broker polling completes;
- managed-exit monitoring completes;
- auto-execution evaluation completes with no action;
- the worker heartbeat remains healthy;
- equity research, crypto research, and evidence-snapshot jobs are exceeding their three-minute execution boundaries;
- consequently, new intelligence, recommendations, learning evidence, and Founder-screen data may remain incomplete or stale;
- no new trade should be expected until research completes and produces an opportunity that passes every execution gate.

The platform is therefore **operating with material warnings**, rather than fully healthy or completely stopped.

## 2. What Was Investigated

The investigation used persisted production evidence rather than source-code presence or API availability alone.

Evidence sources included:

- Render background-worker deployment status;
- protected `/operations-health` output;
- protected `/scheduler-status` output;
- protected `/job-runs` output;
- worker heartbeat records stored in Postgres;
- scheduled job records stored in Postgres;
- Render deployment commit identifiers;
- Render worker logs;
- the supplied PowerShell output containing recent job history.

The investigation specifically distinguished between:

1. the API responding;
2. the worker process being alive;
3. the worker heartbeat being current;
4. scheduled jobs actually starting;
5. scheduled jobs completing;
6. the full research-to-execution workflow producing usable evidence.

This distinction matters because a healthy API does not prove that autonomous research or trading is functioning.

## 3. Root Cause Found

### 3.1 Original worker failure mode

The background worker previously ran long operations directly within its main process. When an operation stalled, the entire worker stopped progressing. Repeated worker failures caused Render to suspend the service.

The first recovery isolated normal worker jobs in child processes with a configured 180-second execution boundary. A timed-out job would be terminated and persisted without killing the supervisor.

### 3.2 Remaining startup blockage

After the initial isolation fix was deployed, production evidence showed:

- the worker heartbeat was current;
- deployment `0f063e02dcafb335a900ef90286c550d135885df` was live;
- the worker remained indefinitely in `kraken-startup-reconciliation`;
- no new scheduled job rows appeared after 26 July;
- the worker never reached its normal managed-exit, broker-polling, research, evidence, execution, and learning loop.

Kraken startup reconciliation was still running directly before the bounded job loop. It was therefore able to block the entire worker despite the earlier job-isolation work.

## 4. Recovery Implemented

Commit `c67b22f9` changed Kraken startup reconciliation into a durable named worker job executed inside the same bounded child-process mechanism as other autonomous jobs.

The recovery provides these behaviours:

- startup reconciliation receives a 180-second execution boundary;
- the job creates a persisted `SCHEDULED_JOB_RUNS` record;
- a timeout is recorded rather than disappearing;
- the supervisor remains alive;
- managed exits continue;
- broker polling continues;
- research can be attempted;
- evidence snapshots can be attempted;
- auto-execution evaluation can continue;
- learning and reporting are no longer permanently blocked by startup replay;
- Kraken entries remain paused if reconciliation is incomplete;
- existing broker permissions and trading guardrails remain unchanged.

Files changed by the recovery:

- `src/ai_trader/cli.py`
- `src/ai_trader/always_on.py`
- `tests/test_production_completion.py`
- `architecture/JOB_AND_WORKER_RECOVERY_STANDARD.md`
- `governance/IMPLEMENTATION_LOG.md`

Transfer archive:

- `ZIP-Updates/2026-07-27-startup-reconciliation-isolation.zip`

## 5. Test Evidence

Before deployment:

- Python compilation passed.
- Focused worker, operations, and Kraken reconciliation tests passed: **31 passed**.
- Complete Python test suite passed: **180 passed**.
- No trading permission, allocation, stop-loss, take-profit, position-limit, portfolio, or Risk Engine rule was weakened.

The tests prove the intended control flow and regression protection in the repository. They do not replace hosted production verification.

## 6. Hosted Production Verification

### 6.1 Deployment verification

Render subsequently reported the new full commit:

`c67b22f93bb1cfd8d45e138f5fb9b1a4b4844b1c`

This confirmed that the worker was no longer running only the previous `0f063e02` release.

### 6.2 Startup timeout and recovery

Persisted production jobs showed:

| Job ID | Job | Result | Meaning |
|---|---|---|---|
| 7923 | `kraken-startup-reconciliation` | `timed_out` | Startup replay exceeded the 180-second boundary and was terminated safely. |
| 7924 | `managed-exits` | `completed` | The supervisor continued after the startup timeout. |
| 7925 | `broker-poll` | `started` | Normal worker processing resumed. |

This is direct production proof that the startup blockage no longer freezes the autonomous worker.

### 6.3 Continued autonomous operation

A later production query showed job IDs had advanced to 7951 while the phone was not responsible for triggering them.

The current production state returned:

- overall operations: `attention_needed`;
- API health: `available`;
- worker health: `healthy`;
- requested database backend: `postgres`;
- active database backend: `postgres`;
- scheduler status: `active`;
- worker status: `running`;
- worker deployment: `c67b22f9...`;
- worker last error: empty;
- current job at the time of observation: `managed-exits`;
- last successful high-level job: `background-cycle`.

Recent persisted evidence included:

| Job ID | Job | Result |
|---|---|---|
| 7951 | `managed-exits` | started |
| 7950 | `premarket-equity` | timed out |
| 7949 | `overnight-crypto` | timed out |
| 7948 | `auto-execution` | completed with no action |
| 7947 | `evidence-snapshot` | timed out |
| 7946 | `broker-poll` | completed |
| 7945 | `managed-exits` | completed |
| 7944 | `auto-execution` | completed with no action |
| 7943 | `evidence-snapshot` | timed out |
| 7942 | `broker-poll` | completed |
| 7941 | `managed-exits` | completed |
| 7940 | `auto-execution` | completed with no action |
| 7939 | `evidence-snapshot` | timed out |
| 7938 | `broker-poll` | completed |
| 7937 | `managed-exits` | completed |

## 7. What Is Working Now

### 7.1 Always-on worker

The worker continues operating independently of the mobile application. The phone can be closed without stopping the Render worker.

### 7.2 Durable shared state

The API and worker report Postgres as both the requested and active backend. Worker heartbeats and job runs are visible through the hosted API from shared persisted state.

### 7.3 Heartbeats and supervision

The worker maintains a current heartbeat. Its health is derived from durable evidence rather than merely assuming that a Render service marked Live is doing useful work.

### 7.4 Job isolation

A timed-out job no longer destroys or indefinitely blocks the supervisor. Subsequent jobs are attempted and persisted.

### 7.5 Managed-exit monitoring

Managed-exit jobs are completing. This is important even when new entries are paused because existing AI-managed positions must continue to receive exit protection.

### 7.6 Broker polling

Broker polling is completing repeatedly. This provides the foundation for retrieving broker activity and reconciling orders and positions.

### 7.7 Execution evaluation

Auto-execution evaluation is running and returning `completed_no_action`.

This means the engine performed an execution evaluation but did not find an eligible action. It does not mean that an order was submitted or that a trade occurred.

## 8. Current Issues

### 8.1 Equity research timeout

`premarket-equity` exceeded the 180-second execution boundary.

Impact:

- fresh equity evidence may not be completed;
- no new Alpaca candidate may reach strategy qualification;
- the app may show stale or unavailable equity intelligence;
- Alpaca paper execution cannot occur from a research cycle that did not complete.

### 8.2 Crypto research timeout

`overnight-crypto` exceeded the 180-second execution boundary.

Impact:

- fresh crypto research may not complete;
- no new Kraken opportunity may be produced;
- Kraken execution cannot be justified from incomplete research;
- crypto learning inputs remain limited.

### 8.3 Evidence-snapshot timeout

`evidence-snapshot` repeatedly exceeded the execution boundary.

Impact:

- Founder screens may not receive current consolidated evidence;
- portfolio, market, learning, activity, and recommendation summaries may remain incomplete;
- the worker may be doing some work that is not being translated into a timely mobile read model;
- activity can be present in operational tables while the app still displays unavailable values.

### 8.4 Startup reconciliation remains incomplete

The startup reconciliation timeout is now contained, but its underlying slowness or blockage remains unresolved.

Impact:

- Kraken startup history cannot be declared fully reconciled;
- Kraken new entries should remain paused;
- deterministic linkage of historical Kraken fills, exits, P&L, and learning may remain incomplete;
- existing holdings must not be mistaken for AI Trader-managed positions.

### 8.5 Overall status is correctly `attention_needed`

The system must not be labelled fully healthy while research and evidence jobs are timing out.

The current truthful classification is:

- API: healthy;
- worker: healthy;
- scheduler: active;
- database: Postgres and available;
- managed exits: operating;
- broker polling: operating;
- auto-execution evaluation: operating with no action;
- research: attempted but timing out;
- evidence publication: attempted but timing out;
- complete autonomy: not yet proven.

### 8.6 Trading is not currently proven

No recent production evidence cited in this report proves that a new broker order was submitted or filled.

`completed_no_action` means no eligible order was created during that evaluation. Possible valid causes include:

- no completed fresh research;
- no valid opportunity;
- strategy maturity gate not passed;
- portfolio rejection;
- risk rejection;
- broker permission disabled;
- global trading pause;
- stale evidence;
- incomplete reconciliation.

The exact no-trade reason must come from the persisted execution funnel rather than assumption.

### 8.7 API token exposure

The Founder command token was pasted into the conversation during manual PowerShell testing.

Impact:

- the token should be treated as exposed;
- it must eventually be rotated in Render and the mobile application together;
- rotation must be coordinated to avoid causing another unauthorized mobile/backend mismatch;
- the replacement token must not be pasted into chat, screenshots, source control, or documentation.

## 9. Why This Is Progress but Not Completion

Previously, one stalled startup operation could stop every autonomous capability. The platform could appear alive while doing no further work.

Now:

- the stall is persisted;
- the stall has a bounded duration;
- the worker survives;
- later jobs run;
- operational evidence keeps advancing;
- the exact failing stages are visible.

This moves the platform from an opaque total stoppage to a recoverable, observable partial operation.

It does not yet deliver a fully operational investment loop because the jobs responsible for producing fresh research and Founder-facing evidence are still too slow or blocked.

## 10. Required Next Remediation

The next work must focus on the timed-out jobs rather than adding features or raising the timeout indiscriminately.

### Step 1: Instrument stage-level duration

Add persisted duration and outcome evidence for each internal stage of:

- `premarket-equity`;
- `overnight-crypto`;
- `evidence-snapshot`.

The evidence must identify whether time is spent in:

- broker calls;
- market-data calls;
- news retrieval;
- OpenAI calls;
- database reads;
- database writes;
- recommendation generation;
- portfolio calculation;
- evidence aggregation;
- serialization.

### Step 2: Apply provider timeouts

Every external network dependency must have its own timeout shorter than the worker job boundary. One provider must not consume the entire job allowance.

### Step 3: Split large jobs into bounded stages

Separate discovery, retrieval, analysis, persistence, and publication where appropriate. Each stage should be independently retryable and idempotent.

### Step 4: Use incremental evidence snapshots

The evidence API should read bounded, indexed summaries rather than reconstructing the entire production history for every snapshot.

### Step 5: Verify database query plans and indexes

Inspect Postgres queries used by research and Founder evidence. Add indexes only where measured query evidence justifies them.

### Step 6: Preserve partial-provider operation

If one optional provider fails, record the missing evidence and continue with an honest degraded result where governance permits. Mandatory missing data must still block a recommendation.

### Step 7: Verify research completion

After remediation, production must show:

- completed equity research;
- completed crypto research;
- assets analysed;
- research conclusions persisted;
- recommendations or explicit no-opportunity reasons;
- fresh timestamps in the Founder app.

### Step 8: Verify the execution funnel

For each completed research cycle, verify:

- assets examined;
- adequate-data count;
- candidates;
- valid strategies;
- Portfolio Manager decisions;
- Risk Engine decisions;
- broker eligibility;
- orders submitted or exact no-trade reason.

### Step 9: Verify Kraken reconciliation and learning

Before unpausing Kraken entries:

- reconstruct AI-managed entry and exit pairs;
- calculate realized P&L and costs;
- complete terminal learning reviews;
- keep pre-existing Founder holdings separate;
- prove the GBP allocation boundary;
- obtain explicit Founder approval to resume.

## 11. Acceptance Evidence for the Next Recovery

The next recovery should not be considered complete until production proves:

1. the worker heartbeat remains current for at least several cycles;
2. job IDs continue advancing;
3. broker polling completes;
4. managed-exit monitoring completes;
5. equity research completes within its boundary;
6. crypto research completes within its boundary;
7. evidence snapshots complete within their boundary;
8. the mobile app displays those persisted results;
9. no-trade outcomes identify the actual gate that rejected or blocked action;
10. any submitted order is confirmed by broker evidence;
11. any terminal trade creates attribution and learning;
12. Kraken remains paused until reconciliation is sufficiently complete.

## 12. Founder Guidance

At present, the Founder can rely on the following:

- Render is running the worker independently of the phone.
- Postgres is the active shared production database.
- Worker heartbeats are current.
- Jobs are being persisted.
- A stalled startup reconciliation no longer freezes the worker.
- Broker polling and managed-exit monitoring are running.
- Auto-execution evaluation is occurring.

The Founder should not yet rely on:

- fresh equity intelligence;
- fresh crypto intelligence;
- complete recommendation updates;
- complete Founder evidence snapshots;
- new autonomous trade creation;
- complete Kraken historical attribution;
- complete learning from earlier Kraken losses;
- increased live capital.

## 13. Current Operational Conclusion

**AI Trader is alive and autonomously cycling, but it is not yet completing the full research-to-learning investment workflow.**

The critical worker freeze has been fixed and verified in production. The next blocking issue is the duration or internal blockage of equity research, crypto research, and evidence-snapshot jobs.

The correct next action is to instrument and divide those jobs, preserve the worker's bounded execution architecture, and prove fresh research and Founder-visible evidence from production before considering any change to trading permissions.
