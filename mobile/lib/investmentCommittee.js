// AT-ED-014 Section 5: represents AI Trader as an investment organisation - Research -> Learning
// -> Market Intelligence -> Strategy -> Risk -> Execution -> Chief Investment Officer. Kept
// dependency-free (no React/RN imports), matching every other lib/*.js convention - see
// investmentCommittee.test.js.
//
// Each department's "conclusion" is built from a real field this app already reads elsewhere
// (Research from operations_health, Learning from dailyLearning's evidence_summary, Market
// Intelligence from market_intelligence_centre, Strategy from the recommendation summary, Risk
// from connection_readiness, Execution from activity.summary.execution, CIO from the executive
// headline) - not a new per-department scoring model. A department with no evidence reports that
// honestly rather than inventing a conclusion.
//
// AT-ED-014 Section 12 (Future Ready Architecture): this returns a plain array, not a fixed set
// of named JSX slots - a future specialist committee (e.g. Global Macro) is just one more entry
// appended by whatever screen renders this, with no change required to this module's shape.

'use strict';

function departmentConclusion(name, hasEvidence, conclusion, emptyReason) {
  return { name, hasEvidence, conclusion: hasEvidence ? conclusion : emptyReason };
}

function buildInvestmentCommittee({ operationsHealth, learningSummary, marketCentre, recommendationSummary, connectionReadiness, activitySummary, executiveHeadline }) {
  const research = operationsHealth?.last_research_run || operationsHealth?.last_equity_research || operationsHealth?.last_crypto_research;
  const departments = [
    departmentConclusion(
      'Research',
      Boolean(research),
      `Latest research: ${research?.broker || research?.summary || 'recorded'}, ${research?.assets_analysed || 0} asset(s) reviewed.`,
      'No research run recorded yet in current evidence.'
    ),
    departmentConclusion(
      'Learning',
      Boolean(learningSummary && learningSummary.hasEnoughEvidence),
      `${learningSummary?.completedTradesReviewed || 0} closed trade(s) reviewed; latest lesson: ${learningSummary?.latestLesson || 'none recorded'}.`,
      learningSummary?.missingEvidence || 'Not enough closed, reconciled trades to report yet.'
    ),
    departmentConclusion(
      'Market Intelligence',
      Boolean(marketCentre?.market_health),
      marketCentre?.market_health,
      'No fresh market-health evidence recorded yet.'
    ),
    departmentConclusion(
      'Strategy',
      Boolean(recommendationSummary && (recommendationSummary.active || recommendationSummary.expired)),
      `${recommendationSummary?.active || 0} active recommendation(s) currently under evaluation.`,
      'No recommendation evidence recorded yet.'
    ),
    departmentConclusion(
      'Risk',
      Boolean(connectionReadiness),
      connectionReadiness?.trade_ready
        ? 'All governance and broker readiness checks currently pass.'
        : (connectionReadiness?.note || 'One or more readiness checks require attention.'),
      'No readiness evidence recorded yet.'
    ),
    departmentConclusion(
      'Execution',
      Boolean(activitySummary && (activitySummary.orders_submitted !== undefined)),
      `${activitySummary?.orders_submitted || 0} order(s) submitted in this period.`,
      'No execution evidence recorded yet in this period.'
    ),
    departmentConclusion(
      'Chief Investment Officer',
      Boolean(executiveHeadline),
      executiveHeadline,
      'No executive synthesis is available yet.'
    ),
  ];
  return departments;
}

module.exports = {
  buildInvestmentCommittee,
};
