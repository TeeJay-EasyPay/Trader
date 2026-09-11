# Reference audit and experiment intake — 11 September 2026

## What changed

The existing seven documents are internally curated notes, not a complete library
of trading textbooks. They remain educational inputs, not proof of an edge.
The audit corrected a concrete arithmetic error ($50 risk / $150 reward is 3R),
qualified stop-fill guarantees, and corrected correlation wording: five positions
each risking 1% have 5% planned aggregate risk; correlation increases the chance
of simultaneous losses, while gaps can exceed planned losses. Universal claims
about sizing, short-selling behaviour, momentum and sector signals were qualified.

Remaining strategy heuristics are not independently validated facts. None of the
seven notes is certified profitable. The reference effectiveness experiment is
designed to investigate decision differences, not let the model certify itself.

Six original, source-linked additions live in `knowledge/candidates/`: after-cost
evaluation, Kraken execution, Alpaca execution, experiment validity, setup
invalidation, and portfolio evidence. They are excluded from normal live-reference
discovery. Links and concise original summaries are retained, not copied papers
or broker manuals. Public availability is not asserted to be an open licence.
Each note records an access date, version, review date and use limitations. Exact
account fee rates are intentionally omitted: current applicable account/schedule
data must supply those. A monthly review date is a freshness reminder, not proof
that a broker fact remains current.

## Wiring and limitations

- Retrieval ranks relevant sections within the existing three-passage/1,200-character
  bounds and stores exact supplied text, hashes, topics and metadata.
- Crypto review now passes its already-resolved strategy and market regime.
- Stock entry assessment occurs before strategy selection in the current call
  sequence; those fields are genuinely unavailable at that point. It keeps
  asset-level retrieval rather than pretending a future strategy is already known.
- Hypothesis batches and grouped reviews receive bounded methodological material
  with provenance. This adds no separate proposal/review request.
- Reference-set tests freeze two versions and use separate inference calls on
  identical saved facts, keeping safety eligibility intact. Under one call/day,
  the arms are assessed on separate days. Simulation starts only after both
  assessments complete, so results concern delayed-input shadow decisions, not
  an exact replica of contemporaneous broker decisions. Model stochasticity and
  provider model-alias changes remain limitations. No automatic reference promotion.
- Reference comparisons share experiment slots and the daily inference allowance.
  Due weekly reviews retain priority; exhausted budget and failed assessments
  remain visible. They can be queued from an existing experiment's detail screen.
  Eligible hypothesis batches also have priority, so reference assessments may
  wait longer than two days. This small-budget diagnostic does not promise enough
  observations for a statistically persuasive trading result within twelve weeks.

Exact passage storage adds at most roughly 3,600 characters plus metadata per
proposal. That is a deliberate provenance/storage trade-off, not an egress saving.
The candidate notes are local deployed files, not fetched over the internet per trade.

## Supported experiments and unavailable inputs

The available journal provides planned entry, stop, target, eligibility and
rejection reasons. This release adds a planned-target-move filter in basis points,
distinct from target/risk ratio. Neither metric is an expected return.
Spread/depth, indicator histories and intraday exit paths are not consistently
present in this intake, so general spread, indicator and trailing-exit strategies
are not falsely labelled executable. Novel imported rules remain development
requests with exact-version implementation approval.

## External-source intake

The TradingView workflow is manual/curated: reviewed public URL, attribution,
permitted content, exact rules, assumptions and checks. It does not scrape charts,
run Pine code, purchase an account or connect TradingView to brokerage orders.
Supported imports can queue shadow tests without fabricated completed-trade IDs.
Third-party backtest claims stay separate from our simulation results.

An initial public lead is jdehorty's **Backtest Adapter**:
https://www.tradingview.com/script/Pu38F2pB-Backtest-Adapter/ . It is an adapter,
not a standalone strategy: a separate signal stream is required. Its description
does not justify importing it as a working strategy. Retain the link for review;
do not copy code or present it as a running/profitable experiment.

Official access/reuse guidance checked during curation:
https://www.tradingview.com/support/solutions/43000474413-i-need-access-to-your-api-in-order-to-get-data-or-indicator-values/
and https://www.tradingview.com/pine-script-docs/writing/publishing/ .

## Operational validation

Fixtures verify batching, broker caps, imported-rule mapping, approval, shared
budgets and paired reference isolation. Fixtures are not production trading
evidence. Real experiments must accumulate prospective outcomes and pass existing
cost, uncertainty, independence and risk checks before any recommendation.

The OpenAI Docs evaluation guidance informed the distinction between model
judgment and measured outcomes, and the explicit variability limitation:
https://developers.openai.com/api/docs/guides/evaluation-best-practices .
