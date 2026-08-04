// AT-ED-015 Section 4: the Forecast Intelligence Engine - real, evidence-based portfolio
// trajectory projections for Tomorrow / 7 Days / 30 Days / Quarter / Year End. Kept
// dependency-free (no React/RN imports), matching every other lib/*.js convention - see
// forecastEngine.test.js.
//
// This is a genuine step up from AT-ED-013/014's `portfolioProjection()`, which always reported
// "no forecasting model exists" - that was correct at the time (there was no model at all) and
// is still correct for a real time-series/volatility model, which this backend still does not
// have. What this module adds is a real, disclosed, evidence-based projection built from the
// one thing this backend genuinely does have a dated history of: closed, reconciled trades
// (`performanceAttribution`, the same evidence Learning's "Closed Trades"/"Win Rate" figures and
// Portfolio's trade history are already built from). It is a simple linear extrapolation of
// historical trade frequency and average realised result - not a sophisticated model, and every
// projection says exactly that in its own `assumptions` and `principalRisks` fields. With fewer
// than MIN_SAMPLE_SIZE dated, realised trades, every horizon honestly reports why it cannot
// project at all, rather than extrapolating from a handful of data points and calling it a
// forecast.
//
// Architecture note (directive: "improved forecasting models can later replace the current
// implementation without changing the UI"): every screen that renders a forecast consumes only
// the shape `projectPortfolioHorizons()` returns - `{ horizon, available, expectedValue,
// expectedChange, confidence, confidenceReason, evidence, assumptions, principalRisks,
// alternativeScenario }`. A future, more sophisticated model only needs to keep producing that
// same shape from `tradeStatistics()`/`projectHorizon()` - nothing in screens/ExecutiveBriefing.js
// needs to change.

'use strict';

const HORIZONS = Object.freeze([
  { key: 'tomorrow', label: 'Tomorrow', days: 1 },
  { key: 'sevenDay', label: '7 Days', days: 7 },
  { key: 'thirtyDay', label: '30 Days', days: 30 },
  { key: 'quarter', label: 'Quarter', days: 91 },
  { key: 'yearEnd', label: 'Year End', days: 365 },
]);

const MIN_SAMPLE_SIZE = 5;

// The same terminal-trade statuses founderLearningForMobile() already uses to compute Learning's
// "Closed Trades"/"Win Rate" figures - reused here so this engine's sample size and win rate can
// never silently disagree with what the Learning screen tells the Founder about the same trades.
const TERMINAL_STATUSES = ['closed', 'target_exit', 'stop_exit', 'manual_exit'];

// performanceAttribution items (see lib/founderEvidenceMapping.js's productionTradeForMobile)
// carry `profit_loss` (from the backend's realized_pnl) and `created_at` (from observed_at); a
// `closed_at` field is preferred when present, matching lib/tradeHistory.js's own convention.
function normalizeClosedTradesFromAttribution(performanceAttribution) {
  return (performanceAttribution || [])
    .filter((item) => TERMINAL_STATUSES.includes(String(item?.status || '').toLowerCase()))
    .map((item) => ({
      profitLoss: Number(item?.profit_loss),
      closedAt: item?.closed_at || item?.created_at || null,
    }));
}

function tradeStatistics(closedTrades) {
  const valid = (closedTrades || [])
    .filter((trade) => Number.isFinite(trade.profitLoss) && trade.closedAt)
    .map((trade) => ({ profitLoss: trade.profitLoss, closedMs: new Date(trade.closedAt).getTime() }))
    .filter((trade) => Number.isFinite(trade.closedMs));
  if (valid.length < MIN_SAMPLE_SIZE) {
    return {
      available: false,
      sampleSize: valid.length,
      reason: `Only ${valid.length} closed trade${valid.length === 1 ? '' : 's'} with dated, realised profit or loss exist - at least ${MIN_SAMPLE_SIZE} are needed before AI Trader will project a trajectory.`,
    };
  }
  const wins = valid.filter((trade) => trade.profitLoss > 0).length;
  const winRate = wins / valid.length;
  const averagePnl = valid.reduce((sum, trade) => sum + trade.profitLoss, 0) / valid.length;
  const closedMsValues = valid.map((trade) => trade.closedMs);
  const spanDays = Math.max(1, (Math.max(...closedMsValues) - Math.min(...closedMsValues)) / 86400000);
  return {
    available: true,
    sampleSize: valid.length,
    winRate,
    averagePnl,
    spanDays,
    tradesPerDay: valid.length / spanDays,
  };
}

function confidenceFromSampleSize(sampleSize) {
  if (sampleSize < 15) {
    return { level: 'Low', description: `a small sample of ${sampleSize} closed trades` };
  }
  if (sampleSize < 30) {
    return { level: 'Medium', description: `a moderate sample of ${sampleSize} closed trades` };
  }
  return { level: 'High', description: `a substantial sample of ${sampleSize} closed trades` };
}

function projectHorizon({ stats, horizon, currentPortfolioValue }) {
  if (!stats || !stats.available) {
    return { horizon: horizon.label, horizonKey: horizon.key, available: false, reason: stats ? stats.reason : 'No closed-trade evidence is available yet.' };
  }
  const expectedTrades = stats.tradesPerDay * horizon.days;
  const expectedChange = expectedTrades * stats.averagePnl;
  const hasPortfolioValue = typeof currentPortfolioValue === 'number' && Number.isFinite(currentPortfolioValue);
  const confidence = confidenceFromSampleSize(stats.sampleSize);
  return {
    horizon: horizon.label,
    horizonKey: horizon.key,
    available: true,
    expectedValue: hasPortfolioValue ? currentPortfolioValue + expectedChange : null,
    expectedChange,
    confidence: confidence.level,
    confidenceReason: `Based on ${confidence.description}, observed over the last ${Math.round(stats.spanDays)} day(s).`,
    evidence: [
      `${stats.sampleSize} closed trade(s) with realised profit or loss`,
      `${Math.round(stats.winRate * 100)}% historical win rate across those trades`,
      `Observed pace of roughly ${stats.tradesPerDay.toFixed(2)} closed trade(s) per day`,
    ],
    assumptions: [
      'Assumes the historical pace of closed trades and their average realised result persist unchanged over this horizon.',
      'Does not account for a change in capital deployed, strategy mix, or market regime.',
    ],
    principalRisks: [
      'A shift in market conditions could invalidate the historical averages this projection is built on.',
      horizon.days <= 7
        ? 'A short horizon like this one is especially sensitive to the outcome of just the next trade or two.'
        : 'Over a longer horizon, any drift between historical and future trade pace or outcome compounds.',
    ],
    alternativeScenario: {
      description: 'If no further trades close in this period, the portfolio remains at its current value.',
      expectedValue: hasPortfolioValue ? currentPortfolioValue : null,
    },
  };
}

function projectPortfolioHorizons({ closedTrades, currentPortfolioValue }) {
  const stats = tradeStatistics(closedTrades);
  return HORIZONS.map((horizon) => projectHorizon({ stats, horizon, currentPortfolioValue }));
}

module.exports = {
  HORIZONS,
  MIN_SAMPLE_SIZE,
  TERMINAL_STATUSES,
  normalizeClosedTradesFromAttribution,
  tradeStatistics,
  confidenceFromSampleSize,
  projectHorizon,
  projectPortfolioHorizons,
};
