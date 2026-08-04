// AT-ED-014 Section 5 / AT-ED-016 Part 1 Section 10: represents AI Trader as an investment
// organisation - the departments that contribute to the CIO's briefing, not the CIO itself (the
// CIO synthesises these, it is not one more department reporting to itself - AT-ED-016 drops the
// standalone "Chief Investment Officer" entry AT-ED-014 originally included here). Kept
// dependency-free (no React/RN imports), matching every other lib/*.js convention - see
// investmentCommittee.test.js.
//
// AT-ED-016 extends the original seven departments (Research/Learning/Market Intelligence/
// Strategy/Risk/Execution/CIO) to the nine the directive names, in its stated order: Market
// Intelligence, Research, Learning, Forecast Engine, Risk Committee, Strategy Committee,
// Execution, Broker Monitoring, Portfolio Intelligence. Each department's conclusion is still
// built from a real field this app already reads elsewhere - Forecast Engine from
// lib/forecastEngine.js's own tradeStatistics() availability, Broker Monitoring from the same
// brokerPanels every other screen already renders, Portfolio Intelligence from
// world_class_evidence.portfolio_intelligence (already read by Portfolio.js). A department with
// no evidence reports that honestly rather than inventing a conclusion.
//
// AT-ED-014 Section 12 (Future Ready Architecture): this returns a plain array, not a fixed set
// of named JSX slots - a future specialist committee (e.g. Global Macro) is just one more entry
// appended by whatever screen renders this, with no change required to this module's shape.

'use strict';

function departmentConclusion(name, hasEvidence, conclusion, emptyReason) {
  return { name, hasEvidence, conclusion: hasEvidence ? conclusion : emptyReason };
}

function buildInvestmentCommittee({
  operationsHealth,
  learningSummary,
  marketCentre,
  recommendationSummary,
  connectionReadiness,
  activitySummary,
  forecastStats,
  brokerPanels,
  portfolioIntelligence,
}) {
  const research = operationsHealth?.last_research_run || operationsHealth?.last_equity_research || operationsHealth?.last_crypto_research;
  const connectedBrokers = (brokerPanels || []).filter((broker) => String(broker.connection_status).toLowerCase() === 'connected');
  return [
    departmentConclusion(
      'Market Intelligence',
      Boolean(marketCentre?.market_health),
      marketCentre?.market_health,
      'No fresh market-health evidence recorded yet.'
    ),
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
      'Forecast Engine',
      Boolean(forecastStats && forecastStats.available),
      `Projecting from ${forecastStats?.sampleSize || 0} closed trade(s) at a ${Math.round((forecastStats?.winRate || 0) * 100)}% historical win rate.`,
      (forecastStats && forecastStats.reason) || 'Not enough closed-trade evidence to forecast yet.'
    ),
    departmentConclusion(
      'Risk Committee',
      Boolean(connectionReadiness),
      connectionReadiness?.trade_ready
        ? 'All governance and broker readiness checks currently pass.'
        : (connectionReadiness?.note || 'One or more readiness checks require attention.'),
      'No readiness evidence recorded yet.'
    ),
    departmentConclusion(
      'Strategy Committee',
      Boolean(recommendationSummary && (recommendationSummary.active || recommendationSummary.expired)),
      `${recommendationSummary?.active || 0} active recommendation(s) currently under evaluation.`,
      'No recommendation evidence recorded yet.'
    ),
    departmentConclusion(
      'Execution',
      Boolean(activitySummary && (activitySummary.orders_submitted !== undefined)),
      `${activitySummary?.orders_submitted || 0} order(s) submitted in this period.`,
      'No execution evidence recorded yet in this period.'
    ),
    departmentConclusion(
      'Broker Monitoring',
      Boolean((brokerPanels || []).length),
      `${connectedBrokers.length} of ${(brokerPanels || []).length} broker connection(s) currently confirmed connected.`,
      'No broker evidence recorded yet.'
    ),
    departmentConclusion(
      'Portfolio Intelligence',
      Boolean(portfolioIntelligence?.plain_english),
      portfolioIntelligence?.plain_english,
      'No portfolio intelligence evidence recorded yet.'
    ),
  ];
}

module.exports = {
  buildInvestmentCommittee,
};
