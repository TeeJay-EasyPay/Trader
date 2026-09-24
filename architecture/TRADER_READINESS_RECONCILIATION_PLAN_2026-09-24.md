# Trader readiness reconciliation — discussion plan

Date: 24 September 2026. Status: proposed; no implementation authorised by this plan.

## Objective

Give Trader accurate, consistent information and working trading/learning tools so
it can operate within approved capital, risk and spending limits without avoidable
technical blockers. Ask Trader whether its specific concerns are resolved, but
verify that answer against records. Satisfaction is feedback, not proof of
correctness or profit. A legitimate decision not to trade is not a failure.

## 1. Reconcile existing work before proposing repairs

For each concern, map the earlier requirement, fix/commit, deployed API and worker
version, current records, displayed view and exact context supplied to Trader.
Classify it: already fixed; stale/misleading context; regression; missing evidence;
or genuinely unfinished. Produce a short issue/evidence/action matrix. Do not
assume older documents describe current behaviour or repeat earlier migrations.

Starting evidence includes ARCHITECTURE_DELTA.md's financial terminology audit,
the August capital-isolation documentation, LEARNING_LINK_REPAIR_2026-09-10.md,
LEARNING_COMPLETION_SIX_ITEMS_2026-09-11.md and the September 24 release report.
These establish prior work, not present-day correctness of every consumer.

## 2. Trace capital accounting through one consistent example

Follow configured ring-fenced capital, ledger available cash, managed positions,
realised/unrealised results and personal holdings through sizing, exposure checks,
portfolio display and Trader's context. Account for pending orders where relevant.
Explain the current cash-capped allocation calculation and identify any difference
from the intended ring-fenced policy. Test buys, sells and changing cash with
personal holdings excluded. Do not replace the existing ledger, increase approved
capital, relax caps or treat whole-account equity as Trader's budget.

Deliverable: a clear money reconciliation and any narrowly scoped proposed fix.
Any unresolved policy choice comes back to the founder before implementation.

## 3. Reconcile trade outcomes, costs and learning reports

- Alpaca: separate canonical closures, reporting reviews, simulations and records
  with verified actual costs. Trace what the earlier repairs restored and what
  remains unknown. Unknown fees are not zero; simulations are not real closures.
- Per-coin history: compare the same broker, ownership, symbol, time window and
  outcome type across storage, summaries and Trader context. Identify filters,
  linkage or freshness differences before declaring records missing.
- Currency: trace GBP/USD units end to end. Report separately unless a documented
  conversion rate and time support aggregation. Do not change historical values
  silently or add cross-currency profit figures without conversion.
- Learning: verify completed outcomes reach reviews and that relevant recorded
  lessons reach future decision context. Distinguish supplied lessons, applied
  changes and independently demonstrated improvement.

## 4. Verify experiment opportunity flow and Trader's understanding

For each active version, reconcile eligible opportunities, blockers, entries,
settlements and informative baseline/candidate comparisons. Check why later
eligible Alpaca decisions were absent from the retained sample (including time,
cursor, broker, supported rule and capacity restrictions). Verify September 24
Kraken replacements prospectively without pooling old evidence or restarting
experiments for unrelated changes. Insufficient observations stay insufficient.

Check that Trader receives dated, broker-specific summaries with explicit
definitions and limitations. Propose source/context fixes where the capability
already works but Trader cannot see it. Do not prompt it to agree or remove valid
safeguards to make it satisfied.

## Discussion and implementation gate

First deliver the issue/evidence/action matrix, prioritised minimal changes,
regression tests, migration/rollback needs and estimated operating-cost impact.
Discuss and obtain approval before code/database changes, paid Trader reviews,
deployment or new exchange integration. Current work only creates this plan and
inspects existing documentation/code and public exchange documentation.

After an approved implementation: test, commit, deploy, verify matching versions,
then give Trader a current evidence packet and ask which concerns remain, with
record references. Close verified issues; retain genuine blockers visibly.
Acceptance requires consistent capital figures, correctly labelled costs/currency,
traceable learning and valid experiment flow—not profits or forced trading.

## Cost and safety boundaries

Use bounded aggregate/read-only diagnostics first; fetch a small linked sample
only where essential. Reuse results, avoid full histories and repeated polling.
Record diagnostic traffic separately from normal workload. Preserve protective
exits, reconciliation, budget limits, personal holdings and old experiment evidence.
No automatic research cycle or broker orders for verification. Compare provider
egress on a complete post-release day; no savings claim from code changes alone.

## Optional exchange feasibility (not part of approved implementation)

Two documented candidates, checked 24 September 2026:

- Gemini Sandbox: test funds and exchange functionality, with REST sandbox API.
  Verify UK sandbox eligibility, liquidity/feed realism, supported order types,
  costs and reset/history behaviour before choosing it. Sandbox results are not
  evidence of real-market execution quality.
  https://support.gemini.com/hc/en-us/articles/29118543562139-What-is-Sandbox
  https://developer.gemini.com/rest
- OKX: documented demo-trading API, but the UK product-availability page marks
  Demo Trading and API unavailable. Not currently a recommendation for a UK
  account; do not bypass regional restrictions.
  https://www.okx.com/docs-v5/en/
  https://www.okx.com/en-gb/help/okx-what-can-i-use-in-the-united-kingdom

Any integration needs a separate proposal: demo-only credentials/endpoints,
hard exclusion of live ordering, bounded data/call budget, order reconciliation,
and compatibility with existing learning. Start with one venue, not two new
always-on workers. Confirm account eligibility before requesting credentials.
