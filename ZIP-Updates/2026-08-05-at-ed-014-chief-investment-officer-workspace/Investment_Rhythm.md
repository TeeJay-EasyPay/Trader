# Investment Rhythm — Design Note

## The Published Schedule vs. Real Evidence

`mobile/lib/investmentRhythm.js` defines the six stages from Section 4 exactly as specified:

```
05:00 Research Complete
05:30 Learning Complete
06:00 Strategy Committee
06:15 Risk Committee
06:30 Chief Investment Officer Review
07:00 Founder Morning Brief Available
```

These times are AI Trader's **published daily schedule** — a description of how the organisation
operates, not a live evidence claim. `scheduledCurrent`/`scheduledNext` are derived purely by
comparing the clock (UTC) to that schedule, and are always computable regardless of what evidence
exists — this is describing the org's rhythm, not asserting anything happened.

**Separately, and never confused with schedule position**, each stage also carries its own
evidence-backed completion status, and this is where "never fabricate completion" is enforced
literally:

- **Research** — `completed` only when `operations_health.last_equity_research` or
  `.last_crypto_research` has a real `completed_at` timestamp.
- **Chief Investment Officer Review** and **Founder Morning Brief Available** — `completed` only
  when a real Founder brief has been generated (`founderBrief.brief.created_at`).
- **Learning**, **Strategy Committee**, **Risk Committee** — always `not_tracked`. This backend
  has no separately-timestamped evidence for these three: learning has no per-run timestamp
  distinct from the day's `generated_at`, and governance runs per-recommendation through
  guardrails, not as a scheduled daily batch committee. Rather than pick an arbitrary evidence
  proxy and imply a false precision, these three are always shown as not tracked, with the reason
  named.

## Why UTC

The schedule times are compared against `now.getUTCHours()`/`getUTCMinutes()`, not local device
time — a fixed reference frame so the "current stage" reading never silently drifts depending on
which timezone the phone or the Render server happens to be running in. This is a known
simplification (the schedule doesn't yet account for the Founder's actual local timezone) worth
revisiting if the Founder finds the displayed "current stage" doesn't match their own clock.

## Tests

7 tests in `lib/investmentRhythm.test.js`: the six stages in schedule order; research/CIO-review/
founder-brief completion only with real timestamps (never fabricated); Learning/Strategy
Committee/Risk Committee always `not_tracked` with a non-empty reason; `scheduledCurrent`/
`scheduledNext` derived correctly from the clock, including the before-the-first-stage case
(`scheduledCurrent` is `null`, never fabricated).
