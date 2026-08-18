// Plain Node assert-based tests for forecastEngine.js - run with `node lib/forecastEngine.test.js`.

'use strict';

const assert = require('assert');
const {
  HORIZONS,
  MIN_SAMPLE_SIZE,
  isTerminalTrade,
  normalizeClosedTradesFromAttribution,
  tradeStatistics,
  confidenceFromSampleSize,
  projectHorizon,
  projectPortfolioHorizons,
} = require('./forecastEngine');

let passed = 0;
function test(name, fn) {
  try {
    fn();
    passed += 1;
    console.log(`ok - ${name}`);
  } catch (err) {
    console.error(`FAIL - ${name}`);
    console.error(err);
    process.exitCode = 1;
  }
}

function closedTrade(profitLoss, daysAgo) {
  return { profitLoss, closedAt: new Date(Date.now() - daysAgo * 86400000).toISOString() };
}

// --- normalizeClosedTradesFromAttribution ---

test('normalizeClosedTradesFromAttribution: only counts real terminal-status trades, matching Learning\'s own closed-trade filter', () => {
  const result = normalizeClosedTradesFromAttribution([
    { status: 'closed', profit_loss: 10, closed_at: '2026-08-01T00:00:00Z' },
    { status: 'open', profit_loss: null, created_at: '2026-08-01T00:00:00Z' },
    { status: 'target_exit', profit_loss: 5, created_at: '2026-08-02T00:00:00Z' },
  ]);
  assert.strictEqual(result.length, 2);
});

test('normalizeClosedTradesFromAttribution: falls back to created_at when closed_at is absent', () => {
  const result = normalizeClosedTradesFromAttribution([{ status: 'closed', profit_loss: 10, created_at: '2026-08-01T00:00:00Z' }]);
  assert.strictEqual(result[0].closedAt, '2026-08-01T00:00:00Z');
});

// --- isTerminalTrade ---
// 2026-08-17 hosted finding: Alpaca's order lifecycle only ever reaches 'filled', never the
// 'closed'/'target_exit'/'stop_exit'/'manual_exit' words Kraken's managed exits report - a real
// exit (a confirmed ~$639 CSL profit) was invisible everywhere in the app because the status
// check alone could never recognise it. This confirms the fix: an Alpaca sell fill counts, an
// Alpaca buy fill (an entry, not an exit) does not, even though both report the same status.

test('isTerminalTrade: recognises an Alpaca sell fill as closed even though its status is "filled", not "closed"', () => {
  assert.strictEqual(isTerminalTrade({ status: 'filled', side: 'sell' }), true);
});

test('isTerminalTrade: an Alpaca buy fill (an entry) is never counted as closed, despite sharing the exact same status word', () => {
  assert.strictEqual(isTerminalTrade({ status: 'filled', side: 'buy' }), false);
});

test('isTerminalTrade: still recognises Kraken\'s own explicit terminal status words', () => {
  assert.strictEqual(isTerminalTrade({ status: 'target_exit', side: 'sell' }), true);
  assert.strictEqual(isTerminalTrade({ status: 'stop_exit' }), true);
});

test('isTerminalTrade: an open/pending status is never counted as closed', () => {
  assert.strictEqual(isTerminalTrade({ status: 'new', side: 'buy' }), false);
  assert.strictEqual(isTerminalTrade({ status: 'partially_filled', side: 'sell' }), false);
});

test('normalizeClosedTradesFromAttribution: an Alpaca sell fill is included via isTerminalTrade, an Alpaca buy fill is not', () => {
  const result = normalizeClosedTradesFromAttribution([
    { status: 'filled', side: 'sell', profit_loss: 639.12, closed_at: '2026-08-12T13:33:46Z' },
    { status: 'filled', side: 'buy', profit_loss: null, closed_at: '2026-07-03T13:50:55Z' },
  ]);
  assert.strictEqual(result.length, 1);
  assert.strictEqual(result[0].profitLoss, 639.12);
});

// --- tradeStatistics ---

test('tradeStatistics: zero dated trades is honestly unavailable, never extrapolated from no evidence at all', () => {
  const result = tradeStatistics([]);
  assert.strictEqual(result.available, false);
  assert.strictEqual(result.sampleSize, 0);
  assert.ok(result.reason.includes(String(MIN_SAMPLE_SIZE)));
});

test('tradeStatistics (AT-ED-017 Founder request): a single closed trade is available with a real result, but pace is honestly null, never fabricated from one point', () => {
  const result = tradeStatistics([closedTrade(42, 3)]);
  assert.strictEqual(result.available, true);
  assert.strictEqual(result.sampleSize, 1);
  assert.strictEqual(result.averagePnl, 42);
  assert.strictEqual(result.spanDays, null);
  assert.strictEqual(result.tradesPerDay, null);
});

test('tradeStatistics: two dated trades now compute a real (if noisy) pace, not honestly unavailable', () => {
  const result = tradeStatistics([closedTrade(10, 1), closedTrade(-5, 3)]);
  assert.strictEqual(result.available, true);
  assert.strictEqual(result.sampleSize, 2);
  assert.ok(Number.isFinite(result.tradesPerDay));
});

test('tradeStatistics: computes a real win rate and average P&L once enough evidence exists', () => {
  const trades = [closedTrade(10, 1), closedTrade(10, 2), closedTrade(-5, 3), closedTrade(10, 4), closedTrade(-5, 5)];
  const result = tradeStatistics(trades);
  assert.strictEqual(result.available, true);
  assert.strictEqual(result.sampleSize, 5);
  assert.strictEqual(result.winRate, 0.6);
  assert.strictEqual(result.averagePnl, 4);
});

test('tradeStatistics: ignores trades with no finite P&L or no closed date', () => {
  const trades = [closedTrade(10, 1), closedTrade(10, 2), { profitLoss: NaN, closedAt: '2026-08-01' }, { profitLoss: 5, closedAt: null }];
  const result = tradeStatistics(trades);
  assert.strictEqual(result.sampleSize, 2);
});

// --- confidenceFromSampleSize ---

test('confidenceFromSampleSize: scales with real sample size, capped at four named tiers', () => {
  assert.strictEqual(confidenceFromSampleSize(3).level, 'Very Low');
  assert.strictEqual(confidenceFromSampleSize(10).level, 'Low');
  assert.strictEqual(confidenceFromSampleSize(20).level, 'Medium');
  assert.strictEqual(confidenceFromSampleSize(50).level, 'High');
});

// --- projectHorizon ---

test('projectHorizon: unavailable stats produce an honest, unavailable horizon with a named reason', () => {
  const result = projectHorizon({ stats: { available: false, reason: 'not enough evidence' }, horizon: HORIZONS[0], currentPortfolioValue: 1000 });
  assert.strictEqual(result.available, false);
  assert.strictEqual(result.reason, 'not enough evidence');
});

test('projectHorizon: a real projection extrapolates trade pace and average result over the horizon, with confidence/evidence/assumptions/risks/alternative all present', () => {
  const stats = { available: true, sampleSize: 20, winRate: 0.6, averagePnl: 10, spanDays: 20, tradesPerDay: 1 };
  const result = projectHorizon({ stats, horizon: { key: 'sevenDay', label: '7 Days', days: 7 }, currentPortfolioValue: 1000 });
  assert.strictEqual(result.available, true);
  assert.strictEqual(result.expectedChange, 70); // 1 trade/day * 7 days * £10 average
  assert.strictEqual(result.expectedValue, 1070);
  assert.strictEqual(result.confidence, 'Medium');
  assert.ok(result.evidence.length > 0);
  assert.ok(result.assumptions.length > 0);
  assert.ok(result.principalRisks.length > 0);
  assert.strictEqual(result.alternativeScenario.expectedValue, 1000);
});

test('projectHorizon: a missing portfolio value never produces a fabricated expectedValue', () => {
  const stats = { available: true, sampleSize: 20, winRate: 0.6, averagePnl: 10, spanDays: 20, tradesPerDay: 1 };
  const result = projectHorizon({ stats, horizon: HORIZONS[0], currentPortfolioValue: null });
  assert.strictEqual(result.expectedValue, null);
  assert.strictEqual(result.alternativeScenario.expectedValue, null);
});

// --- AT-ED-016 Part 2: Bull/Base/Bear cases, probability, explanation ---

test('projectHorizon: bull case uses the real average of only winning trades, bear case only losing trades', () => {
  const stats = tradeStatistics([
    closedTrade(20, 1), closedTrade(20, 2), closedTrade(-10, 3), closedTrade(20, 4), closedTrade(-10, 5),
  ]);
  const result = projectHorizon({ stats, horizon: { key: 'sevenDay', label: '7 Days', days: 7 }, currentPortfolioValue: 1000 });
  // tradesPerDay is 5 trades over 4 days = 1.25/day; avgWinPnl = 20, avgLossPnl = -10
  assert.ok(result.bullCase.expectedChange > result.baseCase.expectedChange);
  assert.ok(result.bearCase.expectedChange < result.baseCase.expectedChange);
  assert.strictEqual(result.bullCase.expectedValue > result.bearCase.expectedValue, true);
});

test('projectHorizon: no losing trades in the sample falls back the bear case to the base case, never a fabricated loss', () => {
  const stats = tradeStatistics([closedTrade(10, 1), closedTrade(10, 2), closedTrade(10, 3), closedTrade(10, 4), closedTrade(10, 5)]);
  const result = projectHorizon({ stats, horizon: HORIZONS[0], currentPortfolioValue: 1000 });
  assert.strictEqual(result.bearCase.expectedChange, result.baseCase.expectedChange);
});

test('projectHorizon: probability is the real historical win rate, not a fabricated figure', () => {
  const stats = tradeStatistics([closedTrade(10, 1), closedTrade(10, 2), closedTrade(-5, 3), closedTrade(10, 4), closedTrade(-5, 5)]);
  const result = projectHorizon({ stats, horizon: HORIZONS[0], currentPortfolioValue: 1000 });
  assert.strictEqual(result.probability, 0.6);
});

test('projectHorizon: expected volatility and drawdown are always honestly unavailable - no model exists', () => {
  const stats = tradeStatistics([closedTrade(10, 1), closedTrade(10, 2), closedTrade(-5, 3), closedTrade(10, 4), closedTrade(-5, 5)]);
  const result = projectHorizon({ stats, horizon: HORIZONS[0], currentPortfolioValue: 1000 });
  assert.strictEqual(result.expectedVolatility.available, false);
  assert.strictEqual(result.expectedDrawdown.available, false);
  assert.ok(result.expectedVolatility.reason.length > 0);
});

test('projectHorizon: every available forecast includes a written explanation naming the real sample size and win rate', () => {
  const stats = tradeStatistics([closedTrade(10, 1), closedTrade(10, 2), closedTrade(-5, 3), closedTrade(10, 4), closedTrade(-5, 5)]);
  const result = projectHorizon({ stats, horizon: HORIZONS[0], currentPortfolioValue: 1000 });
  assert.ok(result.explanation.includes('5 closed'));
  assert.ok(result.explanation.includes('60%'));
});

test('tradeStatistics: exposes real winCount/lossCount/avgWinPnl/avgLossPnl alongside the existing fields', () => {
  const stats = tradeStatistics([closedTrade(20, 1), closedTrade(20, 2), closedTrade(-10, 3), closedTrade(20, 4), closedTrade(-10, 5)]);
  assert.strictEqual(stats.winCount, 3);
  assert.strictEqual(stats.lossCount, 2);
  assert.strictEqual(stats.avgWinPnl, 20);
  assert.strictEqual(stats.avgLossPnl, -10);
});

// --- AT-ED-017 Part 2: expected realised profit, exit/entry pace, next exit timing ---

test('projectHorizon: expectedRealisedProfit is the same real number as expectedChange, under an explicit name', () => {
  const stats = { available: true, sampleSize: 20, winRate: 0.6, averagePnl: 10, spanDays: 20, tradesPerDay: 1 };
  const result = projectHorizon({ stats, horizon: { key: 'sevenDay', label: '7 Days', days: 7 }, currentPortfolioValue: 1000 });
  assert.strictEqual(result.expectedRealisedProfit, result.expectedChange);
  assert.strictEqual(result.baseCase.expectedRealisedProfit, result.baseCase.expectedChange);
});

test('projectHorizon: expectedExitCount/expectedNewEntryCount extrapolate the real closed-trade pace over the horizon', () => {
  const stats = { available: true, sampleSize: 20, winRate: 0.6, averagePnl: 10, spanDays: 20, tradesPerDay: 2 };
  const result = projectHorizon({ stats, horizon: { key: 'sevenDay', label: '7 Days', days: 7 }, currentPortfolioValue: 1000 });
  assert.strictEqual(result.expectedExitCount, 14); // 2/day * 7 days
  assert.strictEqual(result.expectedNewEntryCount, 14);
});

test('projectHorizon: nextExpectedExitInDays is the real inverse of the closed-trade pace', () => {
  const stats = { available: true, sampleSize: 20, winRate: 0.6, averagePnl: 10, spanDays: 20, tradesPerDay: 0.5 };
  const result = projectHorizon({ stats, horizon: HORIZONS[0], currentPortfolioValue: 1000 });
  assert.strictEqual(result.nextExpectedExitInDays, 2); // one exit every 2 days at a 0.5/day pace
});

test('projectHorizon: assumptions disclose that expected new entries reuse the exit pace, not a separate entry model', () => {
  const stats = { available: true, sampleSize: 20, winRate: 0.6, averagePnl: 10, spanDays: 20, tradesPerDay: 1 };
  const result = projectHorizon({ stats, horizon: HORIZONS[0], currentPortfolioValue: 1000 });
  assert.ok(result.assumptions.some((item) => item.includes('no separate entry-rate model')));
});

test('projectHorizon (AT-ED-017 Founder request): a single closed trade reports the real result honestly instead of a fabricated trajectory', () => {
  const stats = tradeStatistics([closedTrade(42, 3)]);
  const result = projectHorizon({ stats, horizon: HORIZONS[0], currentPortfolioValue: 1000 });
  assert.strictEqual(result.available, false);
  assert.strictEqual(result.singleTradeOnly, true);
  assert.ok(result.reason.includes('42.00'));
  assert.ok(result.reason.includes('realised gain'));
});

test('projectHorizon: a single losing trade is named as a loss, not a fabricated gain', () => {
  const stats = tradeStatistics([closedTrade(-15, 1)]);
  const result = projectHorizon({ stats, horizon: HORIZONS[0], currentPortfolioValue: 1000 });
  assert.ok(result.reason.includes('realised loss'));
  assert.ok(result.reason.includes('15.00'));
});

test('projectHorizon: fewer than 5 trades adds an explicit small-sample caveat to principalRisks', () => {
  const stats = tradeStatistics([closedTrade(10, 1), closedTrade(-5, 3)]);
  const result = projectHorizon({ stats, horizon: HORIZONS[0], currentPortfolioValue: 1000 });
  assert.ok(result.principalRisks.some((item) => item.includes('very small sample')));
});

test('projectHorizon: 5 or more trades does not add the small-sample caveat', () => {
  const stats = tradeStatistics([closedTrade(10, 1), closedTrade(10, 2), closedTrade(-5, 3), closedTrade(10, 4), closedTrade(-5, 5)]);
  const result = projectHorizon({ stats, horizon: HORIZONS[0], currentPortfolioValue: 1000 });
  assert.ok(!result.principalRisks.some((item) => item.includes('very small sample')));
});

// --- projectPortfolioHorizons ---

test('projectPortfolioHorizons: returns exactly the five directive-named horizons, in order', () => {
  const result = projectPortfolioHorizons({ closedTrades: [], currentPortfolioValue: 1000 });
  assert.deepStrictEqual(result.map((item) => item.horizon), ['Tomorrow', '7 Days', '30 Days', 'Quarter', 'Year End']);
});

test('projectPortfolioHorizons: with insufficient evidence, every horizon is honestly unavailable, not partially guessed', () => {
  const result = projectPortfolioHorizons({ closedTrades: [], currentPortfolioValue: 1000 });
  result.forEach((item) => assert.strictEqual(item.available, false));
});

console.log(`\n${passed} passed`);
if (process.exitCode) {
  console.error('Some forecastEngine tests failed.');
}
