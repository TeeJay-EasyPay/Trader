// Plain Node assert-based tests for forecastEngine.js - run with `node lib/forecastEngine.test.js`.

'use strict';

const assert = require('assert');
const {
  HORIZONS,
  MIN_SAMPLE_SIZE,
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

// --- tradeStatistics ---

test('tradeStatistics: fewer than MIN_SAMPLE_SIZE dated trades is honestly unavailable, never extrapolated from too little evidence', () => {
  const trades = [closedTrade(10, 1), closedTrade(-5, 2)];
  const result = tradeStatistics(trades);
  assert.strictEqual(result.available, false);
  assert.strictEqual(result.sampleSize, 2);
  assert.ok(result.reason.includes(String(MIN_SAMPLE_SIZE)));
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

test('confidenceFromSampleSize: scales with real sample size, capped at three named tiers', () => {
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
