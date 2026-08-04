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
  const ordersSubmitted = activitySummary?.orders_submitted;
  const activeIdeas = recommendationSummary?.active || 0;
  return [
    departmentConclusion(
      'Market Intelligence',
      Boolean(marketCentre?.market_health),
      marketCentre?.market_health,
      'No fresh view on markets to share yet.'
    ),
    departmentConclusion(
      'Research',
      Boolean(research),
      research?.assets_analysed ? `Completed overnight research across ${research.assets_analysed} companies.` : 'Completed overnight research.',
      'No research completed yet today.'
    ),
    departmentConclusion(
      'Learning',
      Boolean(learningSummary && learningSummary.hasEnoughEvidence),
      learningSummary?.latestLesson || 'No meaningful new behavioural improvements identified this period.',
      'Not enough completed trades yet to draw a lesson from.'
    ),
    departmentConclusion(
      'Forecast Engine',
      Boolean(forecastStats && forecastStats.available),
      'Producing live forecasts from real trade history.',
      'Not enough trade history yet to produce a forecast.'
    ),
    departmentConclusion(
      'Risk Committee',
      Boolean(connectionReadiness),
      connectionReadiness?.trade_ready
        ? 'Portfolio remains within acceptable limits.'
        : (connectionReadiness?.note || 'A few checks need a closer look.'),
      'No readiness check completed yet.'
    ),
    departmentConclusion(
      'Strategy Committee',
      Boolean(recommendationSummary && (recommendationSummary.active || recommendationSummary.expired)),
      activeIdeas ? `${activeIdeas} idea${activeIdeas === 1 ? '' : 's'} currently under review.` : 'No ideas currently under review.',
      'No new ideas generated yet.'
    ),
    departmentConclusion(
      'Execution',
      Boolean(activitySummary && (ordersSubmitted !== undefined)),
      ordersSubmitted ? `Placed ${ordersSubmitted} order${ordersSubmitted === 1 ? '' : 's'} today.` : 'No new trades were placed today.',
      'No execution activity recorded yet.'
    ),
    departmentConclusion(
      'Broker Monitoring',
      Boolean((brokerPanels || []).length),
      `${connectedBrokers.length} of ${(brokerPanels || []).length} broker connection${(brokerPanels || []).length === 1 ? '' : 's'} working normally.`,
      'No broker evidence recorded yet.'
    ),
    departmentConclusion(
      'Portfolio Intelligence',
      Boolean(portfolioIntelligence?.plain_english),
      portfolioIntelligence?.plain_english,
      'No portfolio commentary available yet.'
    ),
  ];
}

module.exports = {
  buildInvestmentCommittee,
};
