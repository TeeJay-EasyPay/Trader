// Plain Node assert-based tests for forecasting.js - run with `node lib/forecasting.test.js`.

'use strict';

const assert = require('assert');
const {
  FORECAST_LAYER,
  AUTO_TRADE_CONFIDENCE_THRESHOLD,
  deriveConviction,
  autoTradeScenario,
  portfolioForecast,
} = require('./forecasting');

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

// --- deriveConviction ---

test('deriveConviction: fewer than two signals is honestly Not Established, never guessed', () => {
  const result = deriveConviction({ marketHealthTone: null, averageConfidence: null, winRate: null });
  assert.strictEqual(result.level, 'Not Established');
});

test('deriveConviction: all-agreeing real signals produce High, with the reason naming each one', () => {
  const result = deriveConviction({ marketHealthTone: 'good', averageConfidence: 82, winRate: 0.6 });
  assert.strictEqual(result.level, 'High');
  assert.ok(result.reason.includes('favourable'));
  assert.ok(result.reason.includes('strong'));
  assert.ok(result.reason.includes('net positive'));
});

test('deriveConviction: all-disagreeing real signals produce Low', () => {
  const result = deriveConviction({ marketHealthTone: 'danger', averageConfidence: 40, winRate: 0.3 });
  assert.strictEqual(result.level, 'Low');
});

test('deriveConviction: mixed signals produce Medium, not silently rounded to High or Low', () => {
  const result = deriveConviction({ marketHealthTone: 'good', averageConfidence: 40, winRate: null });
  assert.strictEqual(result.level, 'Medium');
});

// --- autoTradeScenario ---

test('autoTradeScenario: no active recommendations is honest, not fabricated', () => {
  const result = autoTradeScenario([]);
  assert.strictEqual(result.available, false);
});

test('autoTradeScenario: uses the real 85% threshold to count real eligible recommendations', () => {
  const result = autoTradeScenario([
    { confidence: 0.9, freshness_status: 'Fresh' },
    { confidence: 0.7, freshness_status: 'Fresh' },
    { confidence: 0.99, freshness_status: 'Expired' },
  ]);
  assert.strictEqual(result.available, true);
  assert.strictEqual(result.eligibleCount, 1);
  assert.strictEqual(result.activeCount, 2);
  assert.ok(result.statement.includes(`${Math.round(AUTO_TRADE_CONFIDENCE_THRESHOLD * 100)}%`));
});

test('autoTradeScenario: zero eligible is stated plainly, not hidden', () => {
  const result = autoTradeScenario([{ confidence: 0.5, freshness_status: 'Fresh' }]);
  assert.strictEqual(result.eligibleCount, 0);
  assert.ok(result.statement.includes('None of the'));
});

// --- portfolioForecast ---

test('portfolioForecast: facts are passed straight through, unmodified', () => {
  const result = portfolioForecast({
    portfolio: { portfolio_value: 1000, cash_available: 200, deployed_capital: 800, open_positions: [{ symbol: 'AAA' }] },
    recommendations: [],
  });
  assert.strictEqual(result.facts.layer, FORECAST_LAYER.FACT);
  assert.strictEqual(result.facts.portfolioValue, 1000);
  assert.strictEqual(result.facts.openPositionCount, 1);
});

test('portfolioForecast: value/drawdown/volatility are always unavailable with a named reason - no time-series model exists', () => {
  const result = portfolioForecast({ portfolio: {}, recommendations: [] });
  assert.strictEqual(result.valueProjection.available, false);
  assert.strictEqual(result.expectedDrawdown.available, false);
  assert.strictEqual(result.expectedVolatility.available, false);
  assert.ok(result.expectedDrawdown.reason.length > 0);
  assert.ok(result.expectedVolatility.reason.length > 0);
});

test('portfolioForecast: an injected valueProjection (from lib/cio.js) is used instead of a second, separate reason', () => {
  const injected = { available: false, reason: 'injected reason from lib/cio.js' };
  const result = portfolioForecast({ portfolio: {}, recommendations: [], valueProjection: injected });
  assert.strictEqual(result.valueProjection.reason, 'injected reason from lib/cio.js');
});

console.log(`\n${passed} passed`);
if (process.exitCode) {
  console.error('Some forecasting tests failed.');
}
