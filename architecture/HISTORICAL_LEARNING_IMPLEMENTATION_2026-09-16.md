# Historical screening and measurable learning — implementation

## What this release adds

- The existing daily proposal batch now runs bounded historical screening with no
  additional model calls. It shares one recorded dataset per broker across at most
  ten proposals. Each supported candidate gets chronological early/later checks,
  doubled-cost stress and nearby-threshold sensitivity checks (up to five replays).
- Replay reuses `experiments.step`, the forward simulator's next-bar fills,
  portfolio constraints, cost accounting and conservative ambiguous-bar handling.
  It does not reuse the older backtest's fixed fee and independent-trade assumptions.
- Weak historical candidates are recorded and rejected before queuing. Missing
  historical evidence can still queue a clearly labelled forward data-collection
  experiment. This is deliberately not treated as historical qualification.
- The worker saves one compact measurement snapshot daily. Daily, weekly and
  monthly comparisons require the same experiment ID/version, remain separate
  by currency, and never sum overlapping hypotheses into an app return.
- Experiments displays screening coverage/results and an “Is Trader improving?”
  panel. Learning findings distinguish historical development from executed trade
  reviews. Existing strategy approvals, paired-reference experiments and broker
  execution checks remain the mechanisms for subsequent testing and adoption.

## Boundaries and findings from the implementation audit

The older `backtest.py` uses recorded crypto scores and daily candles, with a dated
fixed round-trip fee and independent overlapping trade replays. Those results must
not be relabelled as the paired portfolio's evidence. Reusing the forward engine
avoids silently comparing different accounting models. Its source files and baseline
fingerprint are unchanged, so this release does not restart existing shadow tests.

The initial historical universe is **recorded assessments and shadow opportunities**, not years of
every market opportunity. Both accepted and rejected recorded opportunities can be
inputs where prices exist. Missing past AI/news context is not fabricated. Historical
reference-set reassessment is unsupported. Historical data coverage has not been
assumed or invented from the age of the application.

At most 64 distinct shadow source records per broker are read, excluding records larger
than 8,192 characters. A bounded journal sample selects up to four small record IDs
per day before parsing at most 256 dossiers server-side, returning at most 64 narrow
projections and retaining one valid assessment per day. Existing source-qualified
prices add at most 640 bars across eight symbols per broker; no market download is
triggered. An initial query that parsed all candidate dossiers hit the existing
two-second timeout in production; the ID-first bounded version passed without
increasing the timeout. This bounds response payloads but is not a measurement of
billed network bytes. Dataset coverage and the selection limitation are displayed.
These reads happen only with a proposal batch, not on UI refresh. A content-addressed
host cache holds inputs once per dataset, capped at 10 MiB. Set
`AI_TRADER_RESEARCH_CACHE_DIR` to a persistent research volume if archival replay
across deployments is required. Cache exhaustion blocks screening and is reported;
it does not delete prior evidence. Ephemeral Render storage is not permanent storage.

Early/later historical windows have a holding-period purge. They are labelled
**development robustness checks**, not an untouched holdout: the model may already
have seen historical outcomes while proposing its hypothesis. Unchanged subsequent
forward prices provide the genuinely fresh evaluation. No historical pass is a
live-edge claim. Repeated historical use is not independent validation.

Daily snapshots do not start backdated weekly comparisons. The first week needs a
real week of snapshots. Realised changes may reflect closure timing; open positions,
estimated costs, sample counts and execution uncertainty must still be reviewed.
Actual account results remain in the existing Learning/Portfolio summaries. This
release does not claim that a lesson caused those results, nor silently increase
AI spending for new lesson-on/off assessments.

## Safety and operational checks

- No broker clients or order paths in research/measurement modules.
- No changes to live flags, stops, exit cadence, paper approval or active-test limits.
- No new market-data subscription or historical download job.
- Reserve a historical batch once/day before work; failures do not cause paid retries.
- All numerical replay checks are deterministic and versions are saved with results.
- Thirty recent compact screening batches and 35 daily measurement snapshots are
  retained, in the existing experiment control store and its existing storage cap.
- Unrelated paused maintenance changes in the primary checkout are excluded.

## Remaining empirical work, not promised results

Verify production history coverage and the first actual worker run after release.
If it says `data_required`, that is a real data limitation, not a broken success
indicator. A wider licensed market-history importer, full-universe strategy search,
new point-in-time AI reconstruction and statistically calibrated causal inference
are not implemented by this bounded release. They require separate data/support
decisions; no test is presented as running when it is not supported.

Success is faster rejection of weak supported candidates and honest prospective
measurement. Six or seven weeks is not a guarantee of improvement or profitability.

## Verification record

- Production read-only bounded sample on 16 September: Alpaca 19 signals across
  eight dates, zero available replay bars; Kraken four non-conflicting signals
  across three dates, three available replay bars. Neither qualifies for a
  historical pass. This sample is not a count of all market history or all trades.
- Dedicated historical tests: 14 passed; final related backend/voice selection: 99
  passed; mobile evidence/learning rendering checks: 16 passed. These overlap with
  broader selections and are not additive unique-test totals.
- Broad runs reached 1,037 and then 1,407 passing tests before their three-failure
  stop limits. Six crypto-proposal fixture failures across those runs reproduce
  against the pre-change application: their proposals fail the existing fee hurdle.
  No trading/fee safeguard was changed to satisfy them. Full suite is not claimed green.
- A later broad selection hit missing Node dependencies in the isolated worktree;
  the voice tests passed after providing the existing dependency directory. A legacy
  Standup layout assertion also failed outside the changed screens; it is not hidden
  by claiming a clean full-suite result.
- Production worker was still on the prior release at the readiness audit. Deployment
  and publication, if subsequently performed, require separately recorded verification.

## Release verification — 16 September

- Implementation commit: `82995a9a0082034216ba37a6e20141a5ab503d6b`, fast-forwarded
  into the main checkout and pushed. The four paused maintenance files remain modified
  and excluded; their supporting untracked work was preserved.
- Authenticated production API health and the worker heartbeat both report the
  implementation commit. Live activation remains disabled in experiment health.
- An operator-initialised measurement snapshot at 20:11 UTC records eight experiment
  versions. Daily/weekly/monthly comparison states correctly say collecting baseline.
  This initialization used ordinary database calculations, no model or broker calls.
- Authenticated Experiments GET returned HTTP 200 with the new measurement data,
  seven running experiments and zero fabricated historical trials; response body was
  24,380 bytes for this sample, not a claim of total daily egress.
- Android runtime 1.0.4, hosted-preview update group
  `16b8da9a-a211-474a-9689-5aef1c037b13` published successfully. No native rebuild.
  The EAS dirty marker was a test-mutated `unused.sqlite3` in the isolated checkout;
  all published JavaScript was committed and no maintenance work was included.
- No extra paid proposal batch was forced. Historical screening waits for the next
  normal evidence-eligible batch. Existing experiments are not relabelled as backtested.
- Publication and hosted verification do not prove the handset has downloaded the
  update. Reopen the installed app to allow its normal update flow.
