# Portfolio trend charts — 9 September 2026

> Release authorisation update: the Founder subsequently instructed commit and
> deployment first, then verification in the existing emulator app. The earlier
> release gate and blockers below describe the prior attempt, not a current veto.

## Requested experience and local implementation

Two cards beneath Portfolio's existing balance summary and above positions: Kraken
and Alpaca. Each contains an account-value line and daily/weekly win/loss bars.
Shared 7/30/90-day controls operate entirely on the downloaded summary; the
Executive Briefing has a button opening Portfolio. The existing briefing already
provides the concise balance/performance summary, so charts are not duplicated.

Native React Native Views render the charts without a new charting dependency.
Date/value labels, count labels, bar details, horizontal history scrolling, missing
history states, unknown outcomes and break-even counts are included.

## What the data means

- Kraken value is the stored AI ledger's cash + deployed capital + unrealised P&L.
  Personal holdings are never substituted. Missing marked-to-market values remain
  gaps, even when the whole Kraken account has a known balance.
- Kraken allocation changes are yellow markers, calculated from adjacent stored
  cumulative allocations. The chart does not call those changes trading profit.
  Changes within the same day may net off; the first observation is a baseline,
  not an invented deposit.
- Alpaca value is the broker account value, in USD, not an invented GBP conversion.
  Deposits/withdrawals are not reliably identified in stored history; a visible
  warning says value changes are not necessarily trading profit.
- Value histories don't stitch together paper and live account modes.
- Kraken completed outcomes come from `KRAKEN_RECONCILED_RESULTS`, after recorded
  fees. Open/unfilled exits are excluded.
- Alpaca completed results come from `PERFORMANCE_ATTRIBUTION`, deduplicated using
  the reconciliation key (broker/symbol/close time). The canonical logical-trade
  table has no closed Alpaca rows in the inspected production snapshot; using it
  would falsely show no historical outcomes.
- Alpaca reconstruction does not establish all fees. Its wins/losses and P&L are
  explicitly **provisional, before unreconciled fees**, not falsely labelled net.
  Recorded Alpaca trades may include earlier account modes/unlinked origins; the
  chart does not claim all records have verified AI ownership.
- Daily buckets use UTC; first/current weeks can be partial. Missing P&L is
  unknown, never a loss or zero. Fees need a separate reconciliation improvement
  before Alpaca can honestly offer verified after-fee win counts.

## Supabase egress

`GET /portfolio-trends` is a read-only projection, not a new worker. Three SELECTs:
at most 180 daily value records (two brokers x 90 days), plus at most 90 daily
outcome aggregates per broker. Full snapshot JSON remains in Postgres; only four
AI ledger scalar fields are extracted. No trade dossiers cross the wire.

Both client and server cache for ten minutes. Client requests are single-flight;
changing period or day/week mode makes no request. No chart polling, migrations,
new history tables, historical backfill or live exchange calls were introduced.
The feature necessarily adds one small on-demand history read; it cannot promise
zero additional bytes. The separate cycle fixes reduce polling and duplicate
research, but total Supabase billed egress must be measured after release.

Read-only production check: 32 snapshot days per broker, 19 usable Kraken value
points, 32 Alpaca value points, nine Kraken outcome days and twelve Alpaca outcome
days. The complete JSON response was 9,964 bytes at inspection. Historical gaps
are shown rather than fabricated. SQL was checked through the actual Postgres
compatibility layer, including unique aliases for every computed output column.

## Verification and release gate

Local targeted backend/egress tests: 23 passed. Node suite: 70 passed. Changed app
files compile with the Expo Babel preset. Full backend run: 1,798 passed plus 21
subtests, one failed (Windows temporary-directory cleanup in the existing
`test_a_background_request_answers_with_an_id_not_an_answer`). That test returns
without awaiting its background worker before deleting the temporary directory.
The complete background-turn suite plus final chart/egress tests passed on rerun:
61 passed. This is not recorded as a clean full-suite run. No unrelated test was
weakened or changed. `git diff --check` passed.

**Not committed, pushed or deployed.** The Founder authorised release only after
the emulator check looked correct. That check is blocked:

- Cached Expo Go APK installation failed with `INSTALL_FAILED_INSUFFICIENT_STORAGE`.
  Existing Pixel 9 emulator data was not erased.
- The command starting the local Expo preview was denied by the tool policy.
- The existing emulator window capture was black and activation failed; no chart
  render, scrolling or navigation success can be claimed from that observation.

`tools/portfolio_readonly_preview.py` provides a loopback-only preview gateway:
production GETs may be read; all POSTs are rejected; chart SQL uses a connection
with default read-only transactions and a statement timeout. It does not start
the trading API or workers. It is a developer tool, not a deployed service.

Next: resolve the emulator/preview environment, inspect both cards and all period
controls, verify navigation and scrolling, then commit the combined changes and
release the backend and the installed app's matching Expo update channel. Verify
deployed revision and chart endpoint afterward. No extra live trading cycle is
needed for this UI acceptance check.
