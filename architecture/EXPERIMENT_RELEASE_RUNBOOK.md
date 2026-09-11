# Experiment release and operator runbook

## Safety and scope

This release is Alpaca long-equity paired daily-bar simulation. It does not place
shadow orders. It does not change Kraken, Standup, USD readiness or backup jobs.
First supported rule: minimum target/planned-risk ratio; this is NOT a forecast
probability or expected return. Unsupported behaviour still requires code.

Model output is an untrusted proposal, restricted to the allowlisted numeric rule
and exact supplied outcome identifiers. No arbitrary SQL, code or tool execution.
Default policy is disabled. Enabling the shadow pilot allows at most one active
experiment, one bounded model attempt/day (10,000 characters of evidence and 1,000
output tokens), 20 symbol-day opportunities/day, 24 experiments and a conservative
20 MB payload-plus-overhead allowance. Old evidence is never automatically deleted.

The worker is a separate low-priority thread; database statements time out after
two seconds, lock waits after half a second. Model calls time out after 20 seconds,
are reserved durably before the call and are not automatically retried that day.
Results are settled once daily after 09:00 UTC, using existing raw Alpaca IEX daily
bars in HISTORICAL_CANDLES, with no new market-data API calls. Missing history can
leave results incomplete. UI reads do not trigger model calls.

Both arms have $10,000 virtual starting equity, $25 planned risk per entry, a 10%
notional cap, five positions, estimated 10 basis points fee and 10 basis points
slippage per leg. These are frozen simulation assumptions, NOT verified Alpaca
charges or actual account limits. Entry at next daily open, exit stop/target or
10-calendar-day horizon; this standardised execution model is not a reproduction
of every current broker-managed exit. Results must be labelled accordingly.

The baseline copies recorded pre-execution eligibility; the candidate can only
reject additionally. Sampling is the first 20 distinct symbol-days, not all market
opportunities. A relevant simulator/guardrail/entry-check code change ends the
experiment as insufficient evidence; UI/docs-only deployments do not. Source and bar
inputs are saved compactly alongside each pair for replay.

Evaluation is frozen for 60 days, with at least 60 usable pairs and 40 symbol-days,
positive candidate net results, a conservative descriptive lower bound above zero,
limited winner concentration and no higher drawdown than baseline. These checks
are screening criteria, not a statistical guarantee. Ambiguous candles are excluded;
unresolved outcomes prevent recommendation. Sparse evidence can finish insufficient
after the final holding-window grace period. No live adoption from this simulator.

## Approvals

Single-owner application: existing authenticated Founder API token is the trust
boundary. Owner names in request bodies are ignored. New Supabase tables have RLS
enabled and are private to the backend. Approval binds exact version and revision;
idempotency prevents double-tap duplicates. Notification text is not authority.

Approve library does not enable orders. Approve implementation authorises only the
specified development request. Supported paper activation is additionally blocked
unless EXPERIMENT_PAPER_ADOPTION_ENABLED=true is configured by the operator after
verification; this release leaves that interlock off. It also requires an owner
approval with per-order USD cap and expiry within 30 days. The paper hook can only
add a rejection, and cannot override any original risk check. It never affects live
or Kraken paths. Live activation API always refuses in this rollout: execution
validation and a separate approved pilot are prerequisites.

Learning, Executive Briefing and Notifications read the same experiment/request ID.
History retains approvals and development progress. The developer queue can be read
on request; there is no automatic Codex wake-up. Developer completion requires test
evidence and matching 40-character commit/deployment identifiers; it still does not
activate a strategy. Operator-attested deployment evidence is not independently
verified by accepting a text field; the developer must check the actual deployment.

## Commands (run with repository virtualenv)

- `python tools/experiment_admin.py audit`: compact source and database footprint check.
- `python tools/experiment_admin.py migrate`: create private tables; initially disabled.
- `python tools/experiment_admin.py status`: deployed API and worker revisions, policy and health.
- `python tools/experiment_admin.py enable-shadow`: enable the bounded simulation-only pilot.
- `python tools/experiment_admin.py disable-shadow`: pause new experiments and processing without deleting data.
- `python tools/experiment_admin.py queue`: needs-attention and approved work.
- `python tools/experiment_admin.py implementation --id ID --version HASH --revision N --status ready_for_activation --commit SHA --tests REPORT --deployment SHA`: record verified development completion.

If a simulation fault occurs, pause experiments rather than disrupt trading. Keep
failed/insufficient reports. For a paper variant use Suspend; expired approval
blocks additional paper entries under that variant until suspended or reviewed.
Existing exits remain under their original safety controls.

## Acceptance audit

Run `tests/test_experiments.py` plus learning, governance and API regression tests.
Verify mobile export from the committed checkout (not the dirty backup branch),
publish the matching runtime/channel, then check the deployed API and worker SHA.
Do not report profitability improvement until prospective results exist. The first
production review may legitimately conclude no justified experiment; do not seed a
fabricated successful strategy or fake test trades just to populate the UI.
