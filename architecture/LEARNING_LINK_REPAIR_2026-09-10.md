# Learning evidence repair — 10 September 2026

Standup routing, trading rules and schedules are unchanged. Backup/retention work remains paused.

## Verified live repairs

Fourteen completed Kraken runs were linked to their existing experiences by the exact immutable hash stored in the run payload, with broker and review/proposal identity checks. Run and review payload pointers were updated in the same transaction. No experiences were invented or deleted.

Run/review/experience IDs: 27/23/104, 28/24/110, 29/25/111, 30/26/112, 31/27/113, 32/28/114, 33/29/115, 34/30/116, 35/31/117, 36/32/118, 37/33/119, 38/34/120, 39/35/124, 40/36/125.

Verification: zero completed learning runs with missing experience IDs.

Runs 1–4 retain insufficient-evidence status. Exact managed-entry broker order links recovered the original proposals, but stored attribution follows the sell-side exit direction rather than the original position direction. Each run now carries a blocked_attribution_reconciliation repair assessment. Full round-trip reconciliation is required before replay; original expectations must not be invented.

62 Alpaca reporting outcomes were captured as outcome_only experiences (126–187). Unknown fees, stops and decision context remain unknown. These are not full governed-trade reviews and are excluded from historical precedent counts. Future reconciliation captures only previously uncaptured source attribution IDs in bounded batches.

## Forward code repairs

- Experience insert IDs resolved by immutable_hash for both new and duplicate inserts, independent of PostgreSQL lastrowid emulation.
- Lifecycle insert IDs resolved by idempotency_key.
- Compact source body/passage hashes, title and supplied timestamp retained in proposal and canonical decision context. This proves supplied material, not compliance or profitable application.
- Placeholder exit reasons count as missing evidence.
- Health report separates canonical coverage, all learning-run stages, incomplete experiences and proven improvement (not established).

## Remaining work — not claimed complete

- Reconcile and replay the four old Kraken cases only from verified round-trip records.
- Restore exact Alpaca decision/exit links where possible; 49 of the 62 source records lacked proposal links at inspection. Outcome-only capture does not repair these.
- Reconcile actual Alpaca costs and stop/exit history; never infer zero fees or triggers from profit signs.
- Prospective baseline comparisons remain gated on reliable evidence. No live strategy change or improved profitability is claimed.

Validation: 95 tests passed across identity, outcome evidence, Alpaca reconciliation/canonical learning, context, production spine, review quality, egress audit, knowledge and crypto review tests. No paid model calls were used.
