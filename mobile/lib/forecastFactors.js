// AT-ED-016 Part 2: the multi-factor evidence layer behind the Forecast Centre and Investment
// Thesis's Positive/Negative Factors. Kept dependency-free of React/RN (only requires
// lib/founderPresentation.js's pure `riskTone` helper) - see forecastFactors.test.js.
//
// Each factor function is independent and single-purpose, and returns the same shape:
// { name, available, direction: 'positive'|'negative'|'neutral'|null, note }. A factor is only
// ever `available: true` when this app's real evidence surface actually supports a directional
// read - see Executive_Briefing_Evolution_Design_Review.md's evidence-availability audit for
// exactly which of the directive's 18 candidate signals have a real source here and which do
// not. Two requested signals (volatility, momentum) were found during that review to be
// hardcoded placeholder strings in lib/founderEvidenceMapping.js, not real data, and are
// deliberately NOT implemented as factors here - reading a fixed sentence as if it were live
// analysis is exactly the class of mistake the AT-ED-015.1 incident was about.

'use strict';

const { riskTone } = require('./founderPresentation');

function factorResult({ name, available, direction = null, note }) {
  return { name, available, direction, note };
}

// Reuses the Forecast Engine's own tradeStatistics() output (see lib/forecastEngine.js) so this
// factor's win rate can never disagree with the Forecast Centre's own base-case win rate.
function historicalPerformanceFactor(stats) {
  if (!stats || !stats.available) {
    return factorResult({ name: 'Historical Performance', available: false, note: (stats && stats.reason) || 'Not enough closed-trade history yet.' });
  }
  return factorResult({
    name: 'Historical Performance',
    available: true,
    direction: stats.winRate >= 0.5 ? 'positive' : 'negative',
    note: `${Math.round(stats.winRate * 100)}% historical win rate across ${stats.sampleSize} closed trades.`,
  });
}

function unrealizedPnlFactor(portfolio) {
  const positions = portfolio?.open_positions || [];
  const values = positions.map((position) => Number(position.unrealized_pl)).filter(Number.isFinite);
  if (!values.length) {
    return factorResult({ name: 'Unrealised P&L', available: false, note: 'No open positions with unrealised P&L evidence to evaluate.' });
  }
  const total = values.reduce((sum, value) => sum + value, 0);
  return factorResult({
    name: 'Unrealised P&L',
    available: true,
    direction: total > 0 ? 'positive' : total < 0 ? 'negative' : 'neutral',
    note: `Open positions currently show a combined unrealised ${total >= 0 ? 'gain' : 'loss'} of ${Math.abs(total).toFixed(2)}.`,
  });
}

// Concentration is approximated from unrealised-P&L magnitude, not market value - `symbol` and
// `unrealized_pl` are the only fields ever proven safe to read from portfolio.open_positions[]
// items anywhere in this codebase (see the AT-ED-016 design review's concentration caveat).
// 2% is a disclosed, arbitrary-but-stated threshold, matching lib/principalRisks.js's own
// disclosed-threshold convention for the same kind of judgement call.
function concentrationFactor(portfolio) {
  const positions = portfolio?.open_positions || [];
  const portfolioValue = portfolio?.portfolio_value;
  if (!positions.length || !portfolioValue) {
    return factorResult({ name: 'Portfolio Concentration', available: false, note: 'Not enough position or portfolio-value evidence to assess concentration.' });
  }
  const magnitudes = positions.map((position) => Math.abs(Number(position.unrealized_pl) || 0));
  const largest = Math.max(...magnitudes);
  const pct = largest / portfolioValue;
  return factorResult({
    name: 'Portfolio Concentration',
    available: true,
    direction: pct > 0.02 ? 'negative' : 'neutral',
    note: `The largest single position's unrealised result is approximately ${Math.round(pct * 100)}% of total portfolio value.`,
  });
}

function marketRegimeFactor(marketCentre) {
  if (!marketCentre?.market_health) {
    return factorResult({ name: 'Market Regime', available: false, note: 'No fresh market-health evidence recorded yet.' });
  }
  const tone = riskTone(marketCentre.market_health);
  if (tone === 'neutral') {
    return factorResult({ name: 'Market Regime', available: false, note: 'Market-health evidence does not currently read as clearly favourable or unfavourable.' });
  }
  return factorResult({
    name: 'Market Regime',
    available: true,
    direction: tone === 'good' ? 'positive' : 'negative',
    note: marketCentre.market_health,
  });
}

function learningConfidenceFactor(winRate) {
  if (typeof winRate !== 'number' || !Number.isFinite(winRate)) {
    return factorResult({ name: 'Learning Engine Confidence', available: false, note: 'Not enough completed, reconciled trades for the learning engine to report a win rate yet.' });
  }
  return factorResult({
    name: 'Learning Engine Confidence',
    available: true,
    direction: winRate >= 0.5 ? 'positive' : 'negative',
    note: `Learning reports a ${Math.round(winRate * 100)}% win rate across reviewed trades.`,
  });
}

function researchConvictionFactor(averageConfidence) {
  if (averageConfidence === null || averageConfidence === undefined) {
    return factorResult({ name: 'Research Conviction', available: false, note: 'Not enough active recommendations to average confidence yet.' });
  }
  return factorResult({
    name: 'Research Conviction',
    available: true,
    direction: averageConfidence >= 70 ? 'positive' : 'negative',
    note: `Current recommendations average ${averageConfidence}% confidence.`,
  });
}

// A real proxy for execution effectiveness this backend supports: how many recommendations
// expired unused vs. were acted on, from the same recommendation_summary.active/expired counts
// every other screen already reads - not a submitted-vs-rejected ratio, since no rejected-order
// count exists anywhere in this app's evidence.
function opportunityCaptureFactor(recommendationSummary) {
  const active = Number(recommendationSummary?.active);
  const expired = Number(recommendationSummary?.expired);
  const total = (Number.isFinite(active) ? active : 0) + (Number.isFinite(expired) ? expired : 0);
  if (!total) {
    return factorResult({ name: 'Opportunity Capture', available: false, note: 'No recommendation evidence recorded yet in this period.' });
  }
  const expiredRatio = (Number.isFinite(expired) ? expired : 0) / total;
  return factorResult({
    name: 'Opportunity Capture',
    available: true,
    direction: expiredRatio < 0.5 ? 'positive' : 'negative',
    note: `${Math.round(expiredRatio * 100)}% of recommendations expired unused in this period.`,
  });
}

function riskReadinessFactor(connectionReadiness) {
  if (!connectionReadiness || connectionReadiness.trade_ready === undefined) {
    return factorResult({ name: 'Risk Readiness', available: false, note: 'No readiness evidence recorded yet.' });
  }
  return factorResult({
    name: 'Risk Readiness',
    available: true,
    direction: connectionReadiness.trade_ready ? 'positive' : 'negative',
    note: connectionReadiness.trade_ready ? 'All governance and broker readiness checks currently pass.' : (connectionReadiness.note || 'One or more readiness checks require attention.'),
  });
}

function evaluateFactors({ stats, portfolio, marketCentre, learningWinRate, averageConfidence, recommendationSummary, connectionReadiness }) {
  return [
    historicalPerformanceFactor(stats),
    unrealizedPnlFactor(portfolio),
    concentrationFactor(portfolio),
    marketRegimeFactor(marketCentre),
    learningConfidenceFactor(learningWinRate),
    researchConvictionFactor(averageConfidence),
    opportunityCaptureFactor(recommendationSummary),
    riskReadinessFactor(connectionReadiness),
  ];
}

// Reconciles the factor list into real counts only - never a synthesized "score". Used both to
// strengthen the Investment Thesis's Evidence Strength field and as an additional, disclosed
// input alongside sample size to the Forecast Centre's overall confidence read.
function summarizeFactors(factors) {
  const list = factors || [];
  const directional = list.filter((factor) => factor.available && factor.direction && factor.direction !== 'neutral');
  return {
    consideredCount: list.length,
    availableCount: list.filter((factor) => factor.available).length,
    positiveCount: directional.filter((factor) => factor.direction === 'positive').length,
    negativeCount: directional.filter((factor) => factor.direction === 'negative').length,
  };
}

module.exports = {
  historicalPerformanceFactor,
  unrealizedPnlFactor,
  concentrationFactor,
  marketRegimeFactor,
  learningConfidenceFactor,
  researchConvictionFactor,
  opportunityCaptureFactor,
  riskReadinessFactor,
  evaluateFactors,
  summarizeFactors,
};
