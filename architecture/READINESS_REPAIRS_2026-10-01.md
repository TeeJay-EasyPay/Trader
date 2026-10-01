# Readiness repairs and egress review — 1 October 2026

## Activation update — 1 October, 15:45 UTC

Founder confirmed October spend USD0 and supplied the provider screenshot:
October spend USD0, project budget USD30, prepaid credit USD9.91 after a USD10
top-up. These are separate measures. Render access restored; its API logs show
HTTP429 at 09:47 UTC, without the provider error body (cause not conclusively
identified). Existing API model verified as gpt-4.1-mini.

Initialized only EXPERIMENT_CONTROL/openai_budget_policy through the production
service at 15:45 UTC: start_month 2026-10, opening_micro_usd 0. Transaction used
the budget advisory lock and asserted both policy and October ledger absent;
no usage was reset. No trading/risk settings changed. Release verification follows;
the earlier blocked-state notes below describe the pre-activation investigation.

Release 344f6d24 pushed to master. API served new operational evidence and shared
allowance. Two small synthetic provider checks via production budget transport
succeeded (Luna explanation, Sol structured review); both refused to treat unknown
fees or completed simulations as verified profit/improvement/live approval.
Conservative ledger USD0.001241, no pending requests or unknown bills afterward;
not a provider invoice or a representative trading-quality evaluation.

Android runtime 1.0.4 OTA published on both existing channels from 344f6d24:
hosted-preview group eb24238f-1873-4925-b12f-fe58ad58e337;
preview group a1a65f0c-9d54-4a49-9124-d81652826395. Device receipt unverified.

Live acceptance exposed a 2-second health-query timeout. Changed its date predicate
to the existing COALESCE(started_at,scheduled_for) index while explicitly excluding
unstarted jobs. Read-only production EXPLAIN verified index scan replacing full
scan; aggregate completed within unchanged timeout. Seven focused tests passed.
Returned pre-release failures include three Kraken timeouts on October 1 and the
September 30 strategy-lab error; historical screening/model review still require
fresh scheduled evidence. No claim that release alone fixes past outcomes.

## Release gate

Implementation in the existing release worktree, based on 16c9a0e0 (pending
OpenAI budget/model-routing release). Production API and worker were both checked
and remain on 37863068. Root-checkout edits and unrelated unused.sqlite3 are not
part of this release. No trading settings, broker orders, or risk limits changed.

The October opening OpenAI spend is not verified. No paid validation calls have
been made. The budget release fails closed without an opening policy; deploying
it without resolving that gate would block paid reasoning, not fix it. Requested
the opening spend from the founder. Browser tooling reports no available browser,
so Render logs/manual release controls are unavailable in this session. Do not
claim this release deployed or the provider failures fixed.

## Fresh production evidence

- API healthy; worker heartbeat current. No Kraken auto-execution timeout in the
  latest 24 hours (48 runs); latest recorded timeout September 29 at 18:42 UTC.
  Earlier timeouts remain unexplained without stage logs, not proven resolved.
- Historical screening October 1: seven invalid trials, all blocked at the
  10 MiB frozen-dataset cache limit, despite a top-level completed status.
- Strategy-lab September 30 still fails on PostgreSQL CASE WHEN smallint.
- Latest self-assessment remains evidence_fallback / HTTPError. Read-only model
  metadata requests succeed for the local configured model, Luna and Sol. This
  proves access to metadata, not successful inference or available credits.
- All seven current forward experiments now have informative completions:
  six report three each; one reports one. Samples overlap and must not be summed
  as independent trades. This supersedes the September 29 zero-comparison finding.
- Alpaca: 47 account-fee records, USD3.74 net debits, latest dated September 29.
  A bounded fresh sample of three broker FEE activities has no order_id or
  trade_id. Do not allocate these as verified per-trade charges. Gross outcomes,
  estimated net and account fees remain separate; actual individual net is unknown.

## Implemented changes and remaining acceptance checks

1. AI failures: small sanitized HTTP status/code/type/parameter receipts without
   prompts or response prose. Grouped reviews reject omitted evidence and recover
   failed interpretations on later days, at most three attempts, under the same
   once-daily/shared-dollar gate. Budget/model routing from 16c9a0e0 is included in
   the branch. NEED: confirmed opening balance, deployment, bounded successful
   assessment/review and provider-code diagnosis if they still fail.
2. Historical cache: new datasets use verified lossless gzip; old JSON evidence
   remains intact. Host-only storage capped at 128 MiB with an 80% warning. No
   automatic deletion of source evidence. Per-broker cache failures are remembered
   inside a batch so each candidate does not repeat the same failed download.
   All-invalid batches now report failed, mixed batches partial. NEED: successful
   production batch and host persistence check; no claim of indefinite retention.
3. Strategy SQL: portable CASE WHEN ? = 1; PostgreSQL read-only expression check
   passed. NEED: actual scheduled strategy review on deployed code.
4. Execution: adapt next-candidate time headroom to the slowest observed candidate
   evaluation; do not interrupt or retry submissions. Existing idempotency and
   protection remain. This is mitigation, not a verified root-cause resolution.
   NEED: earlier Render stage logs and a subsequent full runtime window.
5. Fee evidence: freshly checked source limitation, added explicit net-coverage
   health warning. No fabricated attribution or backfill. A broker-identified
   trade-cost source is still required for verified Alpaca per-trade net.
6. Forward evidence: reuse already-downloaded verified host bars for settlement,
   completed bars only; conflicting OHLC stops settlement rather than silently
   choosing a source. No experiment version, rule, quota, or risk gate changed.
   Read-only operational-health output separates failed/stale research, model
   fallbacks, cost coverage and informative comparisons from worker liveness.
   Trader's assessment inventory receives that health evidence.
7. Egress: project proposal-history reports to exactly the consumed fields;
   conditionally transfer broker-history identity rows only when changed;
   retain 256 rather than 48 lossless projection partitions with a 64 MiB total
   logical-byte bound (disposable cache only). This targets symbol-cache churn.
   Fix family budget warnings to compare daily bytes, not three days against a
   daily threshold. Compact health output omits reference-library prose.

## Egress baseline and limitations

Worker telemetry published October 1 at 00:00 UTC reports September 30 consumed
row values 178,902,910 bytes versus September 29 212,321,804. These are NOT Supabase
billed egress. Its multi-day family totals rank rule_experiments (70.8 MB),
experience_records (68.4 MB), broker_trade_history (66.8 MB) highest. Do not call
those individual daily totals. No provider-chart measurement was available and
no percentage saving is claimed. Compare an AI-Trader-only full provider day
after release, along with identical telemetry windows and deployment boundaries.

## Verification

- Initial targeted tests: 75 passed.
- Broader targeted regression: 119 passed (budget, transfer, execution, strategy).
- Latest historical/learning/readiness subset: 37 passed.
- Full suite: 2,058 passed, 21 subtests passed, one skipped; eight previously
  documented failures (six crypto fee-hurdle fixtures, two Standup copy fixtures).
  This is not an all-green suite. Additional tests/edits after that run require
  the final focused run recorded below.
- No live order or paid AI evaluation used as a test.
- Final combined focused run: 118 passed. Subsequent scheduler/readiness checks:
  13 passed. Mobile conversation-floor tests: 5 passed. Counts overlap; do not
  sum them as unique tests. Scheduler now records invalid historical batches and
  fallback-only model assessments as failures, retaining their evidence rather
  than reporting job completion as successful reasoning.

## Required inputs before production activation

Confirm October spend already incurred (provider dashboard), then initialize the
shared opening allowance without resetting it. Reconnect Render for original
timeout-stage logs and controlled deployment verification. Git remains available,
but pushing to the production branch with an uninitialized budget policy would
disable paid AI across the app; do not do that silently. A release commit is not
evidence of successful deployment or completed acceptance checks.

Official OpenAI model compatibility reference used:
https://developers.openai.com/api/docs/models/gpt-6-luna
