# Learning completion — six-item implementation

## Scope

Implements the six approved follow-ups. Shadow jobs never submit orders. Kraken
live stops, trading settings, USD expansion and paused backups are untouched.
No strategy is activated by this release. Deployment verification is recorded below.

1. **Simulation versus broker:** daily, bounded, exact-proposal comparisons of
   baseline entry/exit prices, duration and costs. Multiple matching outcomes stay
   ambiguous. Frozen tolerances: 50 bps entry/exit, 24 hours duration, 25 bps costs;
   at least 20 matches and 90% within all tolerances, without missing/ambiguous
   matches. These are screening thresholds, not proof that paper fills equal live.
   Unknown fees fail cost validation. Results and examples appear in the report.
2. **Rejected opportunities:** `replace_target_r_gate` can replace only the exact
   recorded `reward_risk_below_minimum` reason in simulation. No other risk, cost,
   data or permission rejection can be overridden. The original stricter filter
   remains supported. Neither rule modifies production safeguards.
3. **Kraken shadow:** separate GBP books, fractional hypothetical quantities,
   explicit GBP decision prices, exact-pair daily candles, 80 bps/leg fee scenario
   plus 10 bps slippage. These are estimates, not verified fill costs. Daily bars
   do not reproduce broker trailing-stop behaviour. Missing data remains visible.
   Public GET-only fallback is capped at two pair requests/day; no order client.
4. **Pipeline:** validated, versioned queued proposals include problem, hypothesis,
   intended benefit and priority. A test's start/cursor/deadline freeze when its
   slot opens, not while queued. At most one active test per broker, within the
   configured global cap. One model attempt/day remains the global limit. The
   existing 20 observations/day are shared, not multiplied per experiment.
5. **Evidence:** historical Alpaca activity fills can repair uniquely owned complete
   canonical closures only with explicit exit-order links and matching cumulative
   quantities. Previous fill rows are retained in repair events. Missing identities,
   legacy extra fills and unknown fees remain unresolved rather than guessed.
   Background historical repair is ten candidates/day with a durable cursor;
   operator replay is separately bounded. Exit order types include verified bracket
   take-profits and stop variants. Coverage is displayed separately by broker.
6. **Adoption and monitoring:** exact-version paper approvals require simulator
   validation. Only supported Alpaca tightening filters can activate through the
   existing interlock; Kraken and replacement rules remain shadow/development-only.
   Decision journal and canonical learning context record the approved variant.
   Daily monitoring attributes outcomes and suspends the variant on expiry,
   baseline/version change, missing completed-outcome costs, the approved loss
   budget (5% of per-order cap), or bounded review capacity (200 decisions).
   Suspension returns new decisions to the unchanged approved baseline; it never
   cancels protective exits. Notifications expose suspended records for review.

## Important measurement boundaries

- Simulation agreement and profitable strategy performance are separate tests.
- Broker comparison cannot verify hypothetical trades that the broker never made.
- Historical Alpaca fills inspected on this date have no explicit fee fields.
- Canonical and reporting reviews are separate record types, not additional trades.
- Engine/eligibility changes preserve the old experiment and queue a fresh,
  prospective comparison. Never combine results from different simulator versions.
- The proposed benefit is a hypothesis, not a finding. Rejected/insufficient tests
  remain visible. Queued tests have no promised start date.
- The OpenAI Docs guidance informed strict application-side validation of model
  output: malformed or unsupported proposals are rejected, not executed.

## Verification commands

`python tools/learning_completion_audit.py` is read-only.
`python tools/learning_completion_audit.py --repair` uses retained evidence only;
it does not call a broker or AI, submit trades, or run backups.

Run experiment, assurance, canonical-Alpaca, reconciliation, learning and governance
regressions, plus mobile experiment/timeline tests. Publish mobile only from a
clean committed checkout so paused backup work is excluded.

## Release verification

Broad regression: 171 tests and 19 subtests passed. Mobile components/timeline:
9 tests passed. The focused assurance/canonical suites also cover exact identity,
unknown costs, rejected opportunity isolation, queues, expiry and GET-only data.

Retained production evidence audit: 307 activity fills, 136 orders, 62 reporting
outcomes, no unmatched FIFO quantity. Explicit fee fields: zero. Recorded exit
order types explain 61 outcomes; reporting now has one unknown exit label. Seven
uniquely linked complete Alpaca trades were restored to canonical closure and
queued for learning. Older missing parent/exit links were not fabricated.

Commit/deployment and mobile publication verification follows in the handoff.
