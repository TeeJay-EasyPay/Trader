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
// projection says exactly that in its own `assumptions` and `principalRisks` fields. With zero
// dated, realised trades, every horizon honestly reports why it cannot say anything at all.
//
// AT-ED-017 (Founder request, 2026-08-05): MIN_SAMPLE_SIZE lowered from 5 to 1 - "even 1 trade
// can bring in substantial returns" and the Founder wants to know about it rather than be told
// "not enough evidence" until a fifth trade closes. This does NOT mean a single trade produces a
// fabricated trajectory: a pace (how often exits happen) genuinely cannot be measured from one
// dated point - there is no interval to observe. tradeStatistics() returns tradesPerDay/spanDays
// as null for exactly one trade, and projectHorizon() reports that one real result honestly
// instead of inventing a pace from it (see the `stats.tradesPerDay === null` branch below). From
// two trades onward, a real (if very noisy) pace exists and is used, with a new "Very Low"
// confidence tier making that thinness explicit rather than presenting it at the same confidence
// as a 14-trade sample.
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

const MIN_SAMPLE_SIZE = 1;

// The same terminal-trade statuses founderLearningForMobile() already uses to compute Learning's
// "Closed Trades"/"Win Rate" figures - reused here so this engine's sample size and win rate can
// never silently disagree with what the Learning screen tells the Founder about the same trades.
// Kraken's managed exits report one of these directly; Alpaca never does (its order lifecycle
// only ever reaches 'filled', never a distinct "closed" word) - isTerminalTrade() below is what
// actually recognises an Alpaca exit, this list alone would silently exclude every one of them.
const TERMINAL_STATUSES = ['closed', 'target_exit', 'stop_exit', 'manual_exit'];

// 2026-08-17 hosted finding: every Alpaca exit reports status='filled', the exact same status
// its own entry (buy) fill reports - TERMINAL_STATUSES alone can never tell an Alpaca exit from
// an Alpaca entry, so real closed trades (a confirmed ~$639 CSL profit) were silently excluded
// from every "closed trades" count in the app. A long-only account's sell fill is always an
// exit (this codebase has no short-selling path anywhere), so 'filled' + side='sell' is added as
// a second, Alpaca-shaped terminal signal alongside Kraken's own explicit status words.
function isTerminalTrade(trade) {
  const status = String(trade?.status || '').toLowerCase();
  if (TERMINAL_STATUSES.includes(status)) {
    return true;
  }
  return status === 'filled' && String(trade?.side || '').toLowerCase() === 'sell';
}

// performanceAttribution items (see lib/founderEvidenceMapping.js's productionTradeForMobile)
// carry `profit_loss` (from the backend's realized_pnl) and `created_at` (from observed_at); a
// `closed_at` field is preferred when present, matching lib/tradeHistory.js's own convention.
function normalizeClosedTradesFromAttribution(performanceAttribution) {
  return (performanceAttribution || [])
    .filter((item) => isTerminalTrade(item))
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
      reason: `No closed trades with a dated, realised profit or loss exist yet - at least ${MIN_SAMPLE_SIZE} is needed before AI Trader will report anything.`,
    };
  }
  const winningTrades = valid.filter((trade) => trade.profitLoss > 0);
  const losingTrades = valid.filter((trade) => trade.profitLoss < 0);
  const wins = winningTrades.length;
  const winRate = wins / valid.length;
  const averagePnl = valid.reduce((sum, trade) => sum + trade.profitLoss, 0) / valid.length;
  // AT-ED-016 Part 2: real per-trade averages restricted to only the winning / only the losing
  // trades in the same dated sample - the honest basis for a Bull/Bear case (never a fabricated
  // multiplier on the base case). null when there is no trade of that kind in the sample.
  const avgWinPnl = winningTrades.length ? winningTrades.reduce((sum, trade) => sum + trade.profitLoss, 0) / winningTrades.length : null;
  const avgLossPnl = losingTrades.length ? losingTrades.reduce((sum, trade) => sum + trade.profitLoss, 0) / losingTrades.length : null;
  const shared = { available: true, sampleSize: valid.length, winRate, averagePnl, avgWinPnl, avgLossPnl, winCount: wins, lossCount: losingTrades.length };
  // AT-ED-017: with exactly one dated trade there is no second point to measure an interval from
  // - a "pace" (trades per day) genuinely cannot be observed, only assumed, and this engine does
  // not assume. spanDays/tradesPerDay are honestly null; the real single-trade result is still
  // returned (winRate/averagePnl above), just not extrapolated into a trajectory.
  if (valid.length < 2) {
    return { ...shared, spanDays: null, tradesPerDay: null };
  }
  const closedMsValues = valid.map((trade) => trade.closedMs);
  const spanDays = Math.max(1, (Math.max(...closedMsValues) - Math.min(...closedMsValues)) / 86400000);
  return { ...shared, spanDays, tradesPerDay: valid.length / spanDays };
}

// AT-ED-017: added a "Very Low" tier below the pre-existing Low/Medium/High boundaries (which are
// unchanged) so a 1-4 trade sample is never presented at the same confidence as a 5-14 trade one.
function confidenceFromSampleSize(sampleSize) {
  if (sampleSize < 5) {
    return { level: 'Very Low', description: `a very small sample of ${sampleSize} closed trade${sampleSize === 1 ? '' : 's'}` };
  }
  if (sampleSize < 15) {
    return { level: 'Low', description: `a small sample of ${sampleSize} closed trades` };
  }
  if (sampleSize < 30) {
    return { level: 'Medium', description: `a moderate sample of ${sampleSize} closed trades` };
  }
  return { level: 'High', description: `a substantial sample of ${sampleSize} closed trades` };
}

// AT-ED-016 Part 2: no time-series or volatility model exists in this backend (confirmed again
// this pass) - expected volatility and expected drawdown are always honestly unavailable, with
// one shared reason string so there is exactly one "no such model exists" statement across
// lib/forecasting.js and lib/forecastEngine.js, not two that could drift apart.
const NO_VOLATILITY_MODEL_REASON = 'AI Trader has no time-series or volatility model - only a single realised-P&L-per-trade distribution exists, which cannot honestly support a volatility or drawdown estimate.';

function caseValue({ tradesPerDay, horizonDays, perTradePnl, currentPortfolioValue }) {
  const hasPortfolioValue = typeof currentPortfolioValue === 'number' && Number.isFinite(currentPortfolioValue);
  const expectedChange = tradesPerDay * horizonDays * perTradePnl;
  return {
    expectedChange,
    // AT-ED-017 Part 2: this projection has only ever been built from trades that CLOSED (see
    // normalizeClosedTradesFromAttribution's TERMINAL_STATUSES filter) - expectedChange has
    // therefore always meant expected realised profit from the trades expected to close in this
    // window, never a mark-to-market/unrealised estimate. Exposed under its own name so callers
    // don't have to know that history to render it correctly as "expected realised profit".
    expectedRealisedProfit: expectedChange,
    expectedValue: hasPortfolioValue ? currentPortfolioValue + expectedChange : null,
    expectedReturnPct: hasPortfolioValue && currentPortfolioValue ? expectedChange / currentPortfolioValue : null,
  };
}

function projectHorizon({ stats, horizon, currentPortfolioValue }) {
  if (!stats || !stats.available) {
    return { horizon: horizon.label, horizonKey: horizon.key, available: false, reason: stats ? stats.reason : 'No closed-trade evidence is available yet.' };
  }
  // AT-ED-017: exactly one closed trade has a real, dated result but no measurable pace (see
  // tradeStatistics() above) - reporting the real trade honestly instead of fabricating a
  // trajectory from a single point. This is not the same as "no evidence" (stats.available is
  // true, singleTradeOnly distinguishes it from the fully unavailable case above).
  if (stats.tradesPerDay === null) {
    const outcome = stats.averagePnl >= 0 ? 'a realised gain' : 'a realised loss';
    return {
      horizon: horizon.label,
      horizonKey: horizon.key,
      available: false,
      singleTradeOnly: true,
      reason: `Only one closed trade exists so far, with ${outcome} of ${Math.abs(stats.averagePnl).toFixed(2)}. That's a real result, but with no second dated exit yet I can't responsibly estimate how often exits happen, so I'm not projecting a trajectory from it. As soon as a second trade closes, I'll be able to start estimating a pace.`,
    };
  }
  const hasPortfolioValue = typeof currentPortfolioValue === 'number' && Number.isFinite(currentPortfolioValue);
  const confidence = confidenceFromSampleSize(stats.sampleSize);
  const baseCase = caseValue({ tradesPerDay: stats.tradesPerDay, horizonDays: horizon.days, perTradePnl: stats.averagePnl, currentPortfolioValue });
  // Bull/Bear use the real average of only the winning/only the losing trades in the same dated
  // sample as the per-trade result - never an arbitrary multiplier on the base case. Falls back
  // to the base case itself when the sample has no trade of that kind (e.g. a 100% win-rate
  // sample has no real losing-trade average to build a bear case from - reporting one anyway
  // would be a fabricated number, not evidence).
  const bullCase = caseValue({ tradesPerDay: stats.tradesPerDay, horizonDays: horizon.days, perTradePnl: stats.avgWinPnl ?? stats.averagePnl, currentPortfolioValue });
  const bearCase = caseValue({ tradesPerDay: stats.tradesPerDay, horizonDays: horizon.days, perTradePnl: stats.avgLossPnl ?? stats.averagePnl, currentPortfolioValue });
  const evidence = [
    `${stats.sampleSize} closed trade${stats.sampleSize === 1 ? '' : 's'} with a real result`,
    `a ${Math.round(stats.winRate * 100)}% win rate across those trades`,
    `roughly ${stats.tradesPerDay.toFixed(2)} closed trades a day, on average`,
  ];
  const assumptions = [
    'Assumes the historical pace of closed trades and their average realised result persist unchanged over this horizon.',
    'Does not account for a change in capital deployed, strategy mix, or market regime.',
    'Assumes new positions open at roughly the same pace as positions close, since AI Trader has no separate entry-rate model - only the pace of trades that have already closed is real, dated evidence.',
  ];
  const principalRisks = [
    'A shift in market conditions could invalidate the historical averages this projection is built on.',
    horizon.days <= 7
      ? 'A short horizon like this one is especially sensitive to the outcome of just the next trade or two.'
      : 'Over a longer horizon, any drift between historical and future trade pace or outcome compounds.',
  ];
  // AT-ED-017: with fewer than 5 trades (the new "Very Low" confidence tier), one more trade
  // outcome can swing the pace/average dramatically - said explicitly rather than only implied by
  // the confidence label.
  if (stats.sampleSize < 5) {
    principalRisks.push(`This is built from a very small sample (${stats.sampleSize} trade${stats.sampleSize === 1 ? '' : 's'}) - treat it as an early, rough indication, not a reliable pace yet.`);
  }
  // AT-ED-017 Part 2: the same closed-trade pace (stats.tradesPerDay) that already drives
  // expectedChange also implies how many exits to expect in this window, and roughly when the
  // next one lands - this was always latent in the sample but never surfaced as its own fact.
  // Expected new entries reuses the same pace under a disclosed assumption (this backend has no
  // separate entry-rate model - every closed trade in the sample had exactly one entry, so the
  // closed-trade pace is the only real, dated basis available for an entry estimate too).
  const expectedExitCount = Math.round(stats.tradesPerDay * horizon.days * 10) / 10;
  const nextExpectedExitInDays = stats.tradesPerDay > 0 ? Math.round((1 / stats.tradesPerDay) * 10) / 10 : null;
  return {
    horizon: horizon.label,
    horizonKey: horizon.key,
    available: true,
    // Kept at the top level (not just inside baseCase) for backward compatibility with existing
    // callers/tests that already read horizon.expectedValue/expectedChange directly.
    expectedValue: baseCase.expectedValue,
    expectedChange: baseCase.expectedChange,
    expectedReturnPct: baseCase.expectedReturnPct,
    expectedRealisedProfit: baseCase.expectedRealisedProfit,
    baseCase,
    bullCase,
    bearCase,
    // Exit count is the same regardless of bull/base/bear (those change the outcome per trade,
    // not the pace at which trades close), so it is reported once, not per case.
    expectedExitCount,
    expectedNewEntryCount: expectedExitCount,
    nextExpectedExitInDays,
    // AT-ED-016 Part 2: the historical win rate used as a simple, disclosed proxy for forward
    // likelihood - not a rigorously modelled probability. Labelled as exactly that wherever it
    // is rendered (see screens/ExecutiveBriefing.js).
    probability: stats.winRate,
    expectedVolatility: { available: false, reason: NO_VOLATILITY_MODEL_REASON },
    expectedDrawdown: { available: false, reason: NO_VOLATILITY_MODEL_REASON },
    confidence: confidence.level,
    confidenceReason: `Based on ${confidence.description}, observed over the last ${Math.round(stats.spanDays) === 1 ? 'day' : `${Math.round(stats.spanDays)} days`}.`,
    evidence,
    assumptions,
    principalRisks,
    explanation: `This comes from ${stats.sampleSize} closed trade${stats.sampleSize === 1 ? '' : 's'} with a ${Math.round(stats.winRate * 100)}% win rate - a real track record to extrapolate from. The upper and lower range simply show what happens if only the winning, or only the losing, trades keep happening at the same pace.`,
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
  isTerminalTrade,
  normalizeClosedTradesFromAttribution,
  tradeStatistics,
  confidenceFromSampleSize,
  projectHorizon,
  projectPortfolioHorizons,
};
