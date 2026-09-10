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

## Follow-up — 11 September

- First two commits verified on production worker: 4f5c957d and aeb2e9b1.
- All four old Kraken runs replayed from deduplicated broker fill IDs, executed costs and recorded fees. Original decision identity matched by entry order. Original insufficient-evidence payload preserved, not deleted. New experience IDs 188–191; all 40 Kraken runs now have reviews and experiences.
- Corrected four net results: -0.06764823, +0.07991, +0.12207, +0.05485 GBP. These are review-source corrections, not a claim that every historical reporting table has been rewritten.
- Alpaca exact broker-order fallback recovered 44 additional proposal links. Five single-entry outcomes have no exact stored decision mapping; same-symbol/date inference was rejected. CSL combines multiple entry decisions and must not be assigned exclusively to the first proposal; its individual proposal IDs are preserved in reporting metadata.
- 44 Alpaca exits have matching recorded broker stop-order types. Remaining exit reasons are not inferred from outcomes or limit prices.
- Reporting outcomes with original stop/entry decision evidence can enter a separate, labelled reporting-review path. These do not assert canonical closure or verified fees. Forward reviews are queued through the existing idempotent work queue, not executed on every reconciliation poll.
- Missing historical fees, expectations and stop activation remain unknown. No live trading rule changes or baseline-test results were invented. After-cost improvement and calibrated entry expectations remain unproved; prospective changes must remain tests until their evidence criteria pass.

The replay utility defaults to preview; --apply only addresses the four identified runs and preserves prior payloads. Tests include replay idempotency, duplicate-fill ID semantics, exact order linkage and unknown-cost reporting reviews.

### Final verification snapshot

- Kraken: 40 runs, 40 experiences linked, 40 reviews linked; four historical workflow statuses reconciled to completed, with their prior status recorded.
- Alpaca: 62 reporting outcomes; 56 single-decision links, one multi-decision outcome with source IDs preserved, five unknown. 44 recorded stop-order exits. 44 reporting reviews with linked experiences, distinct from the 62 outcome-only snapshots.
- Canonical Alpaca closure and after-cost performance remain unverified. Historical fee assumptions were not found for the reviewed stock decisions. Five unmatched entry orders also lacked exact proposal matches in the September 1 audit records and client-order-ID check; symbol/time matching was rejected.
- No strategy changes were deployed. Controlled after-cost improvement is not established; missing costs/expectations and canonical closure must not be disguised by review counts.
- 102 tests passed. A direct production PostgreSQL health read caught and fixed bound-LIKE-pattern and duplicate aggregate-column-name issues; the regression test now exercises mapping-row semantics.
- Public API health returned HTTP 200. Worker deployment is checked separately by deployment_commit.
