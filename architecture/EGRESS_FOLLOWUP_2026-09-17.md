# Supabase egress follow-up — 17 September 2026

## Measurement status

The clean read-only counter window ran from 16 September 23:20 UTC to
17 September 20:22 UTC (21.0 hours) and contained one worker restart. It measured
59.0 MB of returned SQL row data, equivalent to approximately **67 MB/day** at the
observed rate. This is a query-ranking estimate, not Supabase's billed network total.
The in-app Supabase session was signed out, so a provider-reported figure for the same
window could not be recorded here.

The previous comparable SQL estimate was 178 MB/day. The current 67 MB/day rate is
approximately 62% lower, supporting the Founder's observation that egress has improved.
Provider billing must still be compared over complete, deployment-free days.

## Current measured composition

| Read family | Estimated SQL row MB/day | Share |
| --- | ---: | ---: |
| Trade-reason reconstruction | 15.4 | 22.9% |
| Trading-intelligence evidence | 7.8 | 11.6% |
| Experiment state and learning | 6.9 | 10.3% |
| Broker polling | 5.5 | 8.2% |
| Worker health and job history | 5.2 | 7.7% |
| App/briefing production evidence | 5.1 | 7.6% |
| Alpaca reconciliation | 3.8 | 5.6% |
| Schema/catalogue compatibility | 3.2 | 4.8% |
| Other individually smaller families | 14.1 | 21.3% |

## Implemented locally in this follow-up

Alpaca reconciliation intentionally revisits historical fill pairs so corrections are
not missed. It was nevertheless re-downloading two wide historical fields on every
stable cycle:

- all matching `DUE_DILIGENCE_ASSESSMENTS.reasoning_json` rows, even though an existing
  completed attribution did not need its entry rationale again; and
- `PERFORMANCE_ATTRIBUTION.primary_factors_json` for every historical outcome, even when
  no repair was required.

The revised path now:

1. loads the narrow attribution identity/status set once per reconciliation cycle;
2. fetches diligence rationale only for a new outcome or a legacy outcome whose proposal
   link is genuinely missing; and
3. fetches `primary_factors_json` lazily only when an exact evidence repair will be made.

It does not change polling cadence, fill pairing, P&L, fee handling, stop evidence,
idempotency or any trading decision.

## Expected reduction from this change

The observed pre-change queries annualised to the following daily rate:

| Changed path | Before | Expected steady state after | Expected reduction |
| --- | ---: | ---: | ---: |
| Diligence rationale reloads | 10.12 MB/day | near zero except new/repair outcomes | about 10.1 MB/day |
| Existing attribution lookup | 3.76 MB/day; 9,104 calls/day | about 1.8 MB/day; roughly 100–140 batched calls/day | about 2.0 MB/day and ~98.5% fewer calls |
| **Combined** | **13.88 MB/day** | **about 1.8 MB/day plus exceptional repairs** | **about 12.1 MB/day** |

If workload remains comparable, the current 67 MB/day SQL-row estimate should move toward
approximately **55 MB/day**. This is not a promise of an equal reduction in the Supabase
billed chart because protocol, Pooler and other service traffic are not included.

## Remaining opportunities, in order

1. **Experiment state projection:** separate small current/checkpoint views from the
   10–18 KB historical control documents so frequent status reads never fetch histories.
2. **Worker and briefing versions:** fetch a small version first and return detailed job or
   evidence history only when it changed or the Founder opens that detail.
3. **Connection reuse investigation:** the window contained about 4,799 Pooler authentication
   calls (about 5,500/day at this rate). Measure a bounded API/worker connection pool before
   changing connection lifecycle; transaction isolation and recovery must be proven.
4. **Timezone catalogue attribution:** 103 calls returned 123,188 timezone rows in the
   window, approximately 1.8 MB/day. It remains unexplained and should be attributed from
   service/application logs rather than guessed.
5. **Trading intelligence projection:** the orchestrator currently retains full evidence in
   its decision context. Build a compact decision-time projection before narrowing this read;
   do not simply discard signals or lifecycle evidence.

Safety-critical open-position, open-order, stop-protection and recent-fill polling retains
its existing cadence. Historical-market-data backfill must use the Render-side research
cache described in the learning action plan so it does not reverse these savings through
Supabase.

## Verification

- Focused and egress regression suites: **81 passed**.
- Final focused suite after the explicit stable-cycle test: **55 passed**.
- Release `6a47b978` is deployed on the Render API and background worker. The projected
  reduction still requires a clean post-release measurement window; deployment itself is
  not evidence that Supabase's provider-level chart has fallen by the same amount.
