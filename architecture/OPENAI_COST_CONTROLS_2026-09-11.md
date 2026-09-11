# OpenAI cost controls — 11 September 2026

User requested lower API usage without changing the model. GPT-6 retained.

## Changes

- Scheduled crypto research and market-open equity research use a minimum two-hour
  bucket (longer existing settings remain respected). Previously the hosted setting
  was hourly. Premarket/close reviews, data ingestion, broker polling, reconciliation,
  protective exits, chat and learning remain unchanged. This can delay new entries;
  it does not delay protective monitoring. Manual research remains explicitly callable.
- Each equity model request includes only that symbol's bars and history. Shared
  metadata and the batch news remain supplied; the original batch is not mutated.
  Previously the full watchlist history was repeated for every assessed symbol.
- Forecasts with exactly equal evidence, model, scope and asset type can reuse the
  existing unexpired result for at most 24 hours. No timestamps/expiry are refreshed,
  no old rows are copied, and changed evidence calls the model normally.
- Structured token-usage logs for equity proposals, crypto reviews and forecasts
  contain category/model/input/cached/output counts, never prompts or credentials.
  These logs are not a dollar-spend cap or a complete accounting of all API features.

## Baseline and verification

Aggregate production check from 10 September 09:00 UTC to approximately 11 September
09:15 UTC: 24 crypto-research jobs (456 assets processed); seven market-open equity
jobs (114), one premarket and one close job (19 each); four forecast refreshes and
84 stored forecasts (76 crypto, eight stock). Assets processed and job counts are
not exact OpenAI request counts. Experiment proposals have a separate one/day cap.

The research schedule reduces possible routine crypto cycles from 24 to 12/day.
No measured total dollar saving is claimed. Input savings depend on watchlist/history
size and forecast savings depend on unchanged evidence. Compare subsequent platform
usage over similar periods; user chat, other jobs, retries and varying tokens remain.

Focused and related tests: 118 passed; one pre-existing whole-repository SQL-pattern
guard fails on self_assessment.py:230 (unchanged by this release). No new model calls
or broker orders were made to test these changes. Paused backup changes are excluded.

## Experiment status at audit

One active experiment and no queued experiments: minimum target/stop distance ratio
2.5. Eight evaluated pairs, both arms with no positions and zero realised P&L;
these are skipped opportunities, not eight completed trades. Verdict insufficient
evidence; frozen evaluation date 10 November 2026 with minimum sample/quality checks.
The current engine proposes only when no test is active, using at least ten new
linked outcomes and a daily call cap. It does not maintain an unshown backlog of
arbitrary strategies. Open an experiment to see its hypothesis, source outcome IDs,
baseline/candidate results, uncertainty, evaluation date and approval history.
