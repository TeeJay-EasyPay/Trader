# Four-part implementation release — 11 September 2026

Main implementation: `c59cf9969a48264bac60340a7d14fe1f1d44683e`.
API and background worker both reported this commit during release verification.
The follow-up commit containing this report retains legacy evidence watermarks
and includes historical experiment results in the batch context; no simulator
or mobile behaviour changes in that follow-up.

## Delivered

1. Five active Alpaca / five active Kraken limits, multi-proposal batching,
   independent broker eligibility, prior-result context, duplicate validation,
   visible unused capacity and shared daily model allowance. Supported typed
   rules include target/risk gates and a planned-target-move filter. This is not
   a general-purpose simulator for arbitrary strategies.
2. Audit of all seven existing notes, six source-linked candidate additions,
   section-based retrieval, exact passage provenance, methodological inputs to
   proposals/reviews, and isolated reference-set shadow comparisons. Candidate
   reference material is not automatically supplied to live entry decisions.
3. Read-only Supabase storage/query audit and ranked recommendations:
   [EGRESS_AND_GROWTH_AUDIT_2026-09-11.md](EGRESS_AND_GROWTH_AUDIT_2026-09-11.md).
   Billed egress totals remain unavailable, not zero. A provider Usage export or
   screenshot is the remaining external evidence needed for billing attribution.
4. Manual TradingView intake, permission/data/rule checks, exact source versions,
   supported-rule shadow queueing, and source implementation approval displayed
   through the existing notification/request surfaces. No scraper, Pine execution,
   new account, subscription or broker connection was added.

## Observed production state

- Existing experiment `74b3e56b-e146-47f8-9c43-74a5228f8cde` retained its books,
  observations and weekly schedule. Its previous specification/version is retained
  in a compatible-release event. No destructive restart or evidence deletion.
- Reference comparison `64492635-228b-4128-a7df-159c3c063c74` was queued through
  the authenticated production API with **zero observations** at creation.
  This is a real queued test, not a claim of completed reference validation.
- Both brokers pass the new-outcome gate at the bounded check: Alpaca 12 new
  linked outcomes; Kraken 30 in the capped sample. Today’s existing paid attempt
  remains consumed. No extra paid request was made to fill the slots.
- Real public TradingView lead `b11b36a50326b972bb1556b9eccd0f093ac6593b1cb45603aa8b61f2b1bd22d0`
  is saved as **reuse blocked**. It is a backtest adapter requiring another signal
  stream, not a validated standalone strategy. No third-party code was copied.
  Successful supported import-to-shadow mapping was demonstrated with clearly
  labelled deterministic fixtures, not invented public strategy results.
- Shadow scheduling was temporarily paused for migration, then restored to its
  original policy. Trading, protective exits, live activation and paused backup
  work were not changed. Existing daily call, observation and storage limits remain.

Reference tests share the daily allowance with reviews and eligible proposal
batches; separate arms may take more than two days. This low-budget diagnostic
does not guarantee enough observations for a conclusive trading-effect result.
Novel source strategies still require implementation before they can be simulated.

## Verification and mobile publication

- 126-test Python regression suite passed; ten focused intake/reference/batching
  tests passed after additional validation checks (overlapping suites).
- 20 mobile tests passed; Android production bundle exported successfully.
- AST checks confirmed legacy fill/exit transitions, market-data ingestion and
  risk controls were unchanged before preserving old simulation evidence.
- Mobile runtime: Android `1.0.3`, both channels published:
  - hosted-preview: `4010d268-91bb-4992-8b4d-c13268f29580`
  - preview: `2af7b27e-81fc-4942-9704-da1157eaf802`
- Phone-side visual inspection has not been performed on the user's handset.
  UI rendering tests and bundle publication are not a claim that the handset has
  already downloaded the update; reopen the app to load it.

See [REFERENCE_LIBRARY_AUDIT_2026-09-11.md](REFERENCE_LIBRARY_AUDIT_2026-09-11.md)
for source usage, available fields, model limitations and provenance/storage costs.
