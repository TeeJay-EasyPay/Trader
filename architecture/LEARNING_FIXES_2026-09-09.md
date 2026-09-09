# Learning reliability fixes — 9 September 2026

Status: committed and pushed as `0c073e2cc4ec2ea6e6f23517551d1b120576d2f7`.
Production background-worker heartbeat reports that commit, running at
2026-09-09 12:46:30 UTC. First live corrected learning outcome remains unverified.
This is not model-weight training and does not establish increasing profitability.

## Changes

1. Alpaca normalization no longer replaces governed proposal/trade identity with
   the broker order ID. Lookup is broker-scoped and prefers governed records.
   Submission links explicit bracket children as exits. Polling can recover a
   child from its broker-reported parent, including a previously unowned child.
   Exits are never paired to entries merely by matching the symbol.
2. Only individual Alpaca activity fills update quantities; cumulative order
   snapshots cannot double-count executions. Partial exits do not close a trade.
   Duplicate fill IDs and the existing learning outbox remain idempotent.
3. The existing orders request includes nested bracket/OTO legs, flattened with
   parent IDs. The existing 100-event budget is retained, reserving up to 50
   activity fills; child links are processed first. One broker request, not one
   per order. API reference: https://docs.alpaca.markets/us/docs/orders-at-alpaca
4. Review classification separates decision evidence from net results. Missing
   guardrails/arguments mean unknown, not poor. Explicit failed guardrails remain
   poor. Net loss cannot be rescued by gross profit; zero remains breakeven.
   Unknown/estimated fees cannot imply after-fee success. Stored committee and
   guardrail evidence reaches reviews. Existing review JSON records version
   `net-evidence-v2`; historical reviews are not overwritten.
5. Missing Alpaca fill fees remain missing. Legacy NOT NULL fee totals retain
   their schema, but net P&L and net R remain unknown instead of assuming no fees.
6. `tools/learning_daily_audit.py` executes two read-only grouped queries for
   broker coverage, known net-result counts and workflow status. No schema
   bootstrap, per-asset queries, history export or trading action.

## Tests

The first full run had 1,814 passes and three failures: two SQL guards caught a
literal LIKE pattern in the monitor; one canonical fixture used order statuses
as individual fills. The monitor now binds its pattern. The fixture now uses
activity statuses and explicit zero fees, preserving every quantity, net-P&L and
duplicate assertion. The focused 76-test regression set then passed, followed by
a fresh full run: **1,820 passed, 21 subtests passed**. Final parent-link recovery,
standalone OCO visibility and missing-fee label hardening were additionally checked
in the final focused run: **96 passed** (the full run preceded those last edits).
`git diff --check` reports no whitespace errors.

New tests follow a governed Alpaca entry through partial/final exits, original
proposal identity, a single learning run and replay. They cover manual same-symbol
trades, recovery of explicit parent links, missing fees, malformed/nested decision
evidence, gross-positive/net-negative results, zero and non-finite values. The
client test verifies nested order flattening requires just one request.
Standalone OCO exit legs remain visible but are not mislabelled as children of an
entry. Unknown-fee metadata also keeps the cost record itself unavailable rather
than displaying a misleading confirmed zero.

## Live baseline — 9 September, approximately 12:23 UTC

One aggregate-only production audit returned:

- Kraken: 27 canonical terminal trades, 27 learning runs; 23 completed and four
  completed with insufficient evidence; 22 linked experience/review pairs;
  zero reviews using the new classification version.
- Historical canonical net outcomes: 10 positive, 17 negative. These counts say
  nothing about the effect of this unreleased patch.
- No Alpaca canonical terminal group. This does NOT mean Alpaca made no trades:
  the earlier audit found reporting outcomes without canonical learning linkage.

No production rows were changed and no history was backfilled.

## Egress and monitoring

No additional application polling loop, mobile endpoint or research feed. Existing
changed-event detection and the 100-event ceiling remain. Nested legs reuse the
same Alpaca request, not Supabase reads. Identity/role lookup selects narrow fields.

Zero extra egress is NOT established: restoring missed learning entails some
existing learning reads/writes, and parent recovery can add a bounded lookup.
Daily monitoring returns only a few grouped rows, not raw JSON histories. This
is not a measurement of total Supabase wire traffic. Compare equal steady-state
windows after release, annotated with starts, closes and research cycles. Do not
slow protective exits or omit required evidence to lower egress.

Daily 09:00 local monitoring was created in this Codex task as
`ai-trader-daily-learning-check`. It records small dated aggregates locally and
notifies on meaningful changes/failures. It must not assume fixes are deployed.
The workspace/runtime and read-only credentials must be available for it to run.

## Remaining gates and limitations

- Worker release is verified; a genuine closed governed Alpaca trade reaching
  exactly one learning run/review/experience is still outstanding. Do not force a trade.
- Orphaned historical fills outside the bounded broker window are not repaired.
  Recovery requires a bounded identity-verified replay, never symbol-based guesses.
- Unknown actual fees require authoritative evidence, not an assumed zero.
- Retrieval of prior results/library evidence proves access, not influence.
  Durable lesson-to-decision attribution and a prospective frozen-baseline
  comparison remain OPEN. The monitor reports improvement as not established.
- Evaluate held-out decisions with/without learning context using identical dated
  inputs. Separate broker, strategy, model version, costs and market period;
  report sample counts, net expectancy, calibration and downside. Do not choose
  favourable windows or automatically change live risk limits.
- No Standup/Trader question was submitted: the existing emulator was not
  controllable. No Expo setup/replacement emulator was attempted. Self-assessment
  would supplement, not replace, evidence that the learning path works.

Related: `LEARNING_AND_EGRESS_AUDIT_2026-09-09.md`.
