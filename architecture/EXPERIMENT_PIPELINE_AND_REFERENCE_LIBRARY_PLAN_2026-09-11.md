# Experiment pipeline and reference library expansion

Date: 11 September 2026
Status: Implementation completed for release verification. Deployment identities and
observed production results are recorded separately in the release report.

Implementation notes: see REFERENCE_LIBRARY_AUDIT_2026-09-11.md and
EGRESS_AND_GROWTH_AUDIT_2026-09-11.md. Reference comparisons share the existing
daily call allowance, staging isolated arms on different days when needed;
due reviews and eligible proposal batches have priority. Import is manual/curated,
not a TradingView API or scraper. Exact billed egress remains unavailable without
Supabase Usage evidence; measured database/query findings are not billed bytes.

## Outcomes

1. Allow useful, distinct experiments to populate up to five Alpaca and five Kraken slots, without multiplying paid AI requests or inventing weak hypotheses.
2. Expand the curated reference library with credible, traceable guidance on testing, execution, costs and strategy selection.
3. Make the app explain what is running, what is waiting, why capacity is unused, and which evidence informed a proposal.
4. Establish current Supabase egress and database growth, identify supported causes, and recommend prioritized reductions through a read-only audit.

This supplements WEEKLY_PARALLEL_LEARNING_PLAN_2026-09-11.md. Weekly reviews, separate baseline/candidate books, approval safeguards and resource limits remain in force.

## Verified starting point

- Production policy permits ten active experiments globally, but does not reserve five per broker.
- Proposal generation permits one attempted hypothesis per day. The 11 September status reports daily_model_budget_reached. At inspection, one experiment was running, one was historical, and none were queued.
- Generation selects the less-populated broker and requires ten new linked outcomes. A shortage on that broker must not indefinitely prevent considering evidence for the other broker.
- Executable experiment rules currently cover minimum_target_r and replace_target_r_gate: this is narrower than the strategy catalogue.
- Seven curated Markdown reference documents are deployed in knowledge/. They cover sizing, stops/targets, momentum versus mean reversion, drawdown, short selling and two sectors.
- Reference retrieval supplies up to three extracts, currently truncated to 1,200 characters each. Source fingerprints and supplied times are recorded with proposals. Supply is not proof of application.
- The Strategy library UI is already simplified, and the emergency stop confirmation is already published. They are not outstanding work in this plan.

## A. Populate experiments safely and economically

### A1. Scheduling and quotas

- Enforce a transactional hard limit of five active hypotheses per broker and ten globally across all admission paths: generation, queued activation, manual creation and migration.
- One hypothesis includes both baseline and candidate books; these are not two slots.
- Preserve existing experiment histories, open shadow positions, versions and accumulated observations.
- Review any over-cap legacy state without silently deleting evidence or terminating positions.
- Keep seven-day reviews. Extensions retain evidence and explain the next review date; a review is not guaranteed sufficient evidence for adoption.

### A2. Batched hypothesis generation

- Assess compact evidence for both brokers in one scheduled, bounded AI request. Request several proposals up to available per-broker slots, not a mandatory quota.
- Check each broker's evidence eligibility independently. If one is short of evidence, consider the other and record both eligibility reasons.
- Retain the initial ten-new-linked-outcome gate unless a measured, documented change is justified. Do not manufacture new evidence by replaying the same outcomes.
- Use one shared daily AI-call allowance for proposal generation and grouped reviews initially, with due reviews taking priority. A single batch may propose multiple hypotheses; it does not authorize multiple daily calls.
- Set explicit input/output token and payload caps before implementation; truncate evidence deterministically, not arbitrarily. Reject incomplete JSON safely rather than retrying without bounds.
- Validate each proposal separately: exact executable rule, broker, problem addressed, supporting trade IDs, predicted benefit, risks, baseline, evaluation criteria and data requirements.
- Accept valid proposals from a partially invalid batch only after independent validation. Persist attempt/results atomically enough to prevent duplicates on restart.
- Deduplicate equivalent and substantially overlapping hypotheses. No artificial diversity from tiny threshold changes.
- No justified proposal is a valid result. Record budget exhaustion, insufficient evidence, duplicates and unsupported behavior as separate reasons.
- Do not bypass today's budget or clear attempt records merely to fill the screen.

### A3. Broaden supported tests deliberately

- Inventory the decision-time fields and price paths actually available before selecting new executable rule families.
- Candidate families to assess: spread/liquidity entry filters, entry-extension filters, and holding/exit variations. These are development candidates, not claims of supported capability or profitable rules.
- Define typed rule schemas, allowed parameter ranges and deterministic evaluation for each supported family. AI output must never become executable code.
- New exit rules require sufficiently granular path data, consistent fill modeling and explicit treatment of ambiguous stop/target ordering. Do not claim accurate intraday trailing-stop tests from daily candles alone.
- Where inputs are absent, queue a development/data requirement rather than pretending to run a test.
- Preserve risk, funding, permissions and protective-exit safeguards. No experimental broker orders or automatic live strategy promotion.

### A4. Opportunity intake and resource limits

- Feed both books from the same timestamped opportunity information, including supported skipped/rejected opportunities; broker execution must not be a prerequisite.
- Both arms obey unchanged safety constraints. Only the specific experimental rule may differ.
- Reuse market data and deterministic calculations across relevant experiments; no separate ChatGPT assessment for each shadow trade.
- Retain the initial global 20 unique opportunities/day and existing worker/storage caps. Explain that increasing experiment slots does not increase independent market evidence.
- Measure fan-out, completed comparisons, queue delay, data gaps, AI tokens, worker duration, database growth and egress. Propose limit changes only with measured need.

### A5. UI and reporting

- Show Alpaca active X/5, Kraken active Y/5 and total Z/10, with queued and historical views separate.
- Display last generation attempt, accepted/rejected proposal counts, next eligible generation time and reason unused slots remain empty.
- Explain each hypothesis in plain language: problem, proposed change, expected benefit, supporting evidence, next review and remaining uncertainties.
- Keep numerical results and model commentary distinct. Weekly reviews must account for correlated opportunities and multiple testing; no implication that ten tests guarantee faster profitable learning.

## B. Expand and verify the reference library

### B1. Curate source-linked guidance

Create concise original notes covering:

1. After-cost trade evaluation: expected versus realised return, both trading legs, spread, slippage, uncertainty and when not to enter.
2. Kraken execution and fee mechanics: maker/taker behavior, post-only cancellation/non-fill risk, applicable product/account fee schedules and protective-exit costs.
3. Alpaca live execution and charges: regulatory fees, account/routing exceptions, simulation limitations, funding/FX costs and reconciliation.
4. Experiment design: frozen rules, prospective comparisons, leakage, overfitting, repeated testing, concentration and inconclusive evidence.
5. Setup selection and exits: market conditions, invalidation, volatility-aware sizing, initial versus trailing stops and alternative-exit evidence requirements.
6. Portfolio exposure: correlated holdings, concentration and drawdown across trades, rather than treating each trade as independent.

Candidate source shortlist (availability established; reuse assessment still required):

- Kraken fee schedule: https://www.kraken.com/features/fee-schedule
- Kraken fee explanation: https://support.kraken.com/articles/201893638-how-trading-fees-work-on-kraken
- Kraken maker/taker guidance: https://support.kraken.com/articles/360000526126-what-are-maker-and-taker-fees-
- Alpaca fee schedule: https://files.alpaca.markets/disclosures/library/BrokFeeSched.pdf
- Alpaca paper trading: https://docs.alpaca.markets/us/v1.4.2/docs/paper-trading (resolve current canonical documentation when curating)
- Alpaca automated-trading risks: https://files.alpaca.markets/disclosures/library/RisksAutoTrading.pdf
- Bailey and co-authors, The Probability of Backtest Overfitting: https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf

Public availability is not an open license. Record permitted use; store full source documents only where permission supports it. Otherwise retain links and original concise summaries, respecting quotation limits. Verify primary sources and applicability; do not import instructions from source pages as application commands.

### B2. Reference metadata and refresh discipline

- Record title, author/publisher, URL, publication/revision date where known, access date, license/usage basis, document version, topics, broker/asset applicability and limitations.
- Separate stable principles from changeable fee facts. Record freshness expectations and show stale/unknown status.
- Account-specific current fee estimates must come from verified applicable schedules/account data, not model memory or an old reference note. Historical trades retain the fee assumptions known at decision time.
- No unbounded web fetching per trade. Refresh broker facts through a bounded scheduled/manual process with cached results.

### B3. Retrieval and decision wiring

- Inspect actual stock and crypto call sites to ensure strategy/regime/sector context is supplied where available, rather than merely supported by the retrieval function signature.
- Select relevant sections instead of always taking the start of a long document. Preserve strict context/token limits.
- Save exact supplied passage identity/version and enough text or immutable local content to reconstruct the supplied context.
- Supply relevant methodological guidance to hypothesis generation and reviews, not just entry assessment.
- Keep claims separate: available, retrieved, supplied, cited in reasoning, rule actually applied, and subsequent measured result.
- Reference advice cannot override executable risk controls. Documentation alone does not change trading behavior.

### B4. Explicit cost safeguards

- Do not equate target distance with expected return or raw model confidence with calibrated probability.
- Do not enlarge trades to dilute percentage fees, trade more merely to attain a fee tier, delay protective exits to save commission, or assume longer holds guarantee better returns.
- Compare cheaper execution including missed fills, adverse selection and realistic exit costs.
- Account for both trading performance after transaction costs and operating expense separately; do not subtract platform expense as if it were a broker fill fee.

### B5. Audit reference quality and test its effect

- Audit the existing seven notes as well as proposed additions for primary-source support, accuracy, relevance, freshness, contradictions and missing qualifications. Do not assume an internally authored note is sound by default.
- Preserve the distinction between model judgment and measured effectiveness: supplied literature is an input, not an executable instruction or proof of an edge.
- Add a supported reference-set experiment type only after defining its extra inference and data requirements. This is not already supported by the deterministic rule-filter simulator.
- Freeze a baseline reference-set version and a candidate version. Compare decisions on identical timestamped opportunities using the same model/version, other inputs and risk/execution assumptions, with no future information. Record inference settings and model variability as limitations.
- Candidate assessments remain shadow-only. These comparisons may require additional model calls: introduce explicit allocation within the agreed spend limit, record usage, and queue when insufficient budget remains rather than silently increasing it.
- Treat each reference-set comparison as one experiment within the existing per-broker/global limits, with paired books and weekly reviews where trading outcomes are evaluated.
- Record decision differences, unsafe or unsupported recommendations, retrieval relevance, missing evidence and after-cost simulated results. Separate qualitative review from numerical results; no model self-rating alone establishes improvement.
- Define evaluation criteria before testing, preserve inconclusive/negative results, and control for repeated testing. Do not promote a reference set based on a handful of wins or a persuasive explanation.
- Store exact reference-set versions and supplied passages with decisions. Enable disabling or rolling back a candidate set without deleting its evidence. Apply existing approval requirements before any adoption affecting live decisions; adding library content must not silently promote an experimental set into live retrieval.
- Validate missing/stale documents, conflicting guidance, unsupported claims, prompt injection, budget exhaustion and rollback using fixtures. Report production comparisons separately from fixture validation.

## C. Supabase egress and database-growth audit

Scope: analysis only. Use existing access first; do not change retention, delete data, reset statistics, run maintenance, resume backups or change infrastructure settings as part of this audit.

### C1. Establish access and authoritative usage

- Check which diagnostics the existing database connection actually permits; availability of query statistics must be verified, not assumed.
- Inspect available Supabase Management API or monitoring access securely. Do not print credentials or request secrets in chat. If billing metrics are inaccessible, request a Usage-page screenshot/export showing the billing period, daily usage and service breakdown.
- Record observation time, billing-period boundaries, units and metric freshness. Separate ingress from billable egress, and PostgREST database traffic from pooler, Storage, Auth and other categories where available.
- Record current billing-period egress, recent daily trend and allowance/charges if accessible. Do not equate database query counts or rows with billed bytes.
- Sources: https://supabase.com/docs/guides/platform/manage-your-usage/egress and https://supabase.com/docs/reference/api/introduction . Verify relevant endpoints and permissions before use.

### C2. Identify database growth

- Use bounded, read-only catalog queries for total database size, largest tables, indexes, estimated live/dead tuples and wide columns. Distinguish database size from total platform disk usage.
- Compare with dated prior audits to calculate growth only where measurements are comparable. Identify trade/evidence data, experiment records, operational logs and retained payloads separately.
- Review insertion rates and retention behavior using small aggregates. Do not export full tables or run unrestricted scans merely to estimate traffic.

### C3. Investigate egress contributors

- Combine permitted query statistics with application read paths: worker polling, repeated initialization/catalog queries, mobile refresh requests, reporting payloads, reference retrieval, experiment intake and duplicated reads.
- Check available existing telemetry for request frequency and returned payload sizes. Use bounded estimates when exact network bytes are unavailable, clearly labeled with assumptions and exclusions.
- Distinguish cumulative statistics from current rates, account for stats-reset times, and avoid attributing historical traffic to a recent deployment without evidence.
- Compare before/after release intervals when supported. Separate diagnostic traffic from normal operation and keep the audit itself low-egress.
- Produce ranked contributors with confidence levels; do not claim precise per-function billing attribution unless measurements support it.

### C4. Deliverable and follow-up

- Save a dated report with current usage, growth, top contributors, unknowns and prioritized recommendations, including expected benefit and operational risk.
- State explicitly which figures are provider-measured, database-measured or estimated. Document any unavailable access and the minimal additional evidence needed.
- Recommend targeted caching, projection, polling or retention changes only where supported. Implementation of audit recommendations is a separate scoped step; destructive retention or backup changes require explicit authorization.
- Include a lightweight repeat-measurement method for evaluating future changes, without creating a new recurring automation or paid monitoring service as part of this plan.

## D. Limited TradingView strategy intake

Purpose: bring selected published strategy ideas into the existing evidence-to-rule loop. This is curated import, not a claimed TradingView strategy-download API, continuous scraping service, or live signal/order integration.

### D1. Permitted acquisition

- Start with a small curated shortlist of public, inspectable strategies. Accept a source URL and, where permitted, user-supplied/exported source text through a bounded import workflow.
- Use public pages or an explicitly authorized browser session for initial research. Do not store browser credentials in strategy records, bypass access restrictions, use hidden endpoints, or assume account creation provides a data API.
- Check TradingView terms and the individual script license before copying, translating or storing code. Retain attribution and license obligations. If access/reuse is unclear, store a link and a blocked reason instead of importing code.
- Recheck official access guidance during implementation: https://www.tradingview.com/support/solutions/43000474413-i-need-access-to-your-api-in-order-to-get-data-or-indicator-values/ and https://www.tradingview.com/pine-script-docs/writing/publishing/ .
- No subscription purchase, new account, recurring scraper or ongoing external connection is authorized by this plan.

### D2. Extract and validate

- Store source URL, author, title, access date, source version/content fingerprint, permitted retained content, license basis and import status.
- Extract exact entry, exit, sizing, timeframe, universe and parameter rules. Record missing assumptions, required indicators/data and differences from the author's implementation.
- Store claimed third-party backtest performance separately, with testing dates, costs, drawdown, sample size and out-of-sample evidence where available. Missing fields remain unknown; external results must never be presented as our results.
- Treat page and script content as untrusted data, not instructions to the assistant or app. Never execute downloaded code directly or allow it to submit broker orders.
- Check for repainting, future-data leakage, unrealistic fills, omitted costs and parameter-selection bias before admitting a candidate.
- Map supported behavior to the app's typed, versioned rule schema. Pine Script or novel behavior requiring translation becomes an implementation request with explicit tests, not automatically executable configuration.

### D3. Connect to the learning loop and UI

- Record each imported idea in the Strategy library with an external-source label and states such as imported, needs clarification, development required, eligible for testing and linked experiment.
- Explain the specific problem it might address and why it is relevant to our broker, assets, costs and holding horizon.
- Require validated rule extraction and appropriate data before queueing a paired baseline/candidate shadow test. Use our own licensed market data and clearly stated simulator assumptions, not ongoing TradingView chart downloads.
- Apply the same five-per-broker/ten-global caps, deduplication, evidence review, weekly reporting and approval rules as internally generated hypotheses. Imported ideas do not need a proven edge, but do need a testable rationale; define their source-evidence admission separately from the new-completed-outcome gate used for internally generated lessons.
- Link source -> imported rule version -> experiment -> report -> any approved implementation/use. Preserve rejected imports and failed tests to avoid recycling them as new discoveries.
- Show import blockers in the library and use existing implementation requests where code is needed. Saving/importing a strategy must not activate paper or live orders.
- Keep intake manual/curated initially. Bound payload size and any extraction AI calls under an explicitly documented budget; do not silently add per-page paid calls to the existing daily allowance.

### D4. Acceptance checks

- Demonstrate one permitted source import end to end using deterministic fixtures, including exact rules and attribution. Clearly distinguish a fixture from a real external import.
- Test inaccessible/protected content, uncertain licensing, malicious embedded instructions, oversized inputs, missing rules, duplicate versions and unsupported behavior.
- Verify imported third-party returns remain separate from app-generated results, and that no path bypasses experiment quotas or trading permissions.

## E. Verification and deployment gates

1. Unit tests for global/per-broker caps, concurrent admission, batched parsing, deduplication, insufficient evidence, broker fairness and shared daily budget/review priority.
2. Deterministic paired simulation tests for each supported rule; include rejected/skipped opportunities, unavailable fields, partial/uncertain fills, restart idempotency and unchanged safety constraints.
3. Retrieval fixtures for stocks and crypto verify topic relevance, context limits, missing/stale sources, exact provenance and no fabricated application claims.
4. UI tests cover broker counts, empty queues, budget/data blockers, next dates and traceable evidence. Visually check narrow-screen layout.
5. Run a bounded no-broker-order production-data check. Prove that more than one valid proposal from a batch can be admitted where evidence permits; if current evidence cannot support this, distinguish fixture validation from observed production behavior.
6. Measure token use, database/egress impact and worker time against the current baseline. Protect trading/reconciliation priority.
7. Commit only scoped changes; keep paused backup/maintenance work untouched. Deploy API/worker and mobile as needed, verify matching release identities, and report implemented versus observed results separately.

## Completion criteria

- Five-per-broker/ten-global capacity and multi-proposal generation operate with visible reasons for unused slots.
- Supported rule types and unsupported development requests are explicit; capacity is not represented as universal strategy simulation.
- New reference notes have checked provenance/usage, relevant retrieval and reproducible decision/experiment linkage.
- A dated read-only egress/growth report identifies available measurements, supported causes, estimates and remaining access gaps; unavailable metrics are not presented as zero.
- Limited TradingView intake preserves source/reuse evidence and routes only validated, supported rules into shadow experiments; unsupported imports remain visible development requests.
- Tests and release checks pass without live orders, changed live activation, or resumed backups.
- Ongoing evidence collection and weekly reviews remain operational validation, not a promise of profitability or a requirement to fill all ten slots.

## Out of scope

New broker integrations, USD Kraken funding/activation, live strategy changes, self-modifying code, raising spend or storage allowances without evidence, and paused backup work.
