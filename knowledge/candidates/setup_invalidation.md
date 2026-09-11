---
title: "Setup invalidation and exit evidence"
topics: [stop_loss, take_profit, risk_management, execution]
applies_to: [stock, crypto]
sectors: []
version: 2026-09-11
status: shadow_only
accessed_at: 2026-09-11
review_due: 2026-10-11
publication_date: unknown
usage_basis: original_summary_and_links_no_full_source_copy
freshness: broker_facts_require_current_account_verification
---

## Application guidance

Record why an entry is justified and what would invalidate it before the trade. Initial stops and trailing stops are different controls: a trailing rule may cause an earlier exit. Preserve original values, amendments, activation times and actual broker events.

Do not infer an exit error from a losing trade alone. Testing alternative exits requires the intervening price path and realistic fills. Daily candles cannot establish which of two intraday levels was reached first. Enlarging stop distance without resizing can increase money at risk. Longer profitable holds do not establish that delaying losing exits would help.

## Source and limitations

Original application-specific engineering/risk checklist; not an independently validated trading strategy. Supporting simulation limitations: Alpaca, Risks of Automated Trading, https://files.alpaca.markets/disclosures/library/RisksAutoTrading.pdf . Accessed 2026-09-11. No full external document copied. Existing seven notes should not be treated as primary authority for these claims.
