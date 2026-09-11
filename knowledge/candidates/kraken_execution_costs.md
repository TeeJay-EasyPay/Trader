---
title: "Kraken execution and costs"
topics: [costs, execution, liquidity]
applies_to: [crypto]
sectors: []
version: 2026-09-11
status: shadow_only
accessed_at: 2026-09-11
review_due: 2026-10-11
publication_date: unknown
usage_basis: original_summary_and_links_no_full_source_copy
freshness: broker_facts_require_current_account_verification
---

## Mechanics

Fees depend on the applicable product and account tier. A limit order that immediately matches resting liquidity can incur taker fees. Post-only rejects/cancels an order that would take liquidity; it does not guarantee execution. Do not confuse consumer conversion pricing with API spot pricing.

## Test implications

Model missed and partial fills, delayed entries and adverse selection when testing maker entry. Include plausible taker costs for protective exits. Never disable or delay protection simply to obtain maker pricing. Verify actual fill fees against the stored decision-time estimate.

## Source and usage

Kraken, What are Maker and Taker fees? https://support.kraken.com/articles/360000526126-what-are-maker-and-taker-fees- . Fee schedule: https://www.kraken.com/features/fee-schedule . Accessed 2026-09-11. Original paraphrase of public factual documentation; no full document or third-party code copied. No open license asserted. Recheck broker facts before activation; exact rates are deliberately omitted.
