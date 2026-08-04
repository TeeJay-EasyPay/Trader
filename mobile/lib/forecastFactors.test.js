// Plain Node assert-based tests for forecastFactors.js - run with `node lib/forecastFactors.test.js`.

'use strict';

const assert = require('assert');
const {
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
} = require('./forecastFactors');

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

// --- historicalPerformanceFactor ---

test('historicalPerformanceFactor: unavailable stats produce an honest, unavailable factor', () => {
  const result = historicalPerformanceFactor({ available: false, reason: 'not enough trades' });
  assert.strictEqual(result.available, false);
  assert.strictEqual(result.note, 'not enough trades');
});

test('historicalPerformanceFactor: real win rate drives direction', () => {
  assert.strictEqual(historicalPerformanceFactor({ available: true, winRate: 0.6, sampleSize: 10 }).direction, 'positive');
  assert.strictEqual(historicalPerformanceFactor({ available: true, winRate: 0.3, sampleSize: 10 }).direction, 'negative');
});

// --- unrealizedPnlFactor ---

test('unrealizedPnlFactor: no positions is honestly unavailable', () => {
  assert.strictEqual(unrealizedPnlFactor({ open_positions: [] }).available, false);
});

test('unrealizedPnlFactor: real combined sign drives direction', () => {
  const gain = unrealizedPnlFactor({ open_positions: [{ unrealized_pl: 10 }, { unrealized_pl: 5 }] });
  const loss = unrealizedPnlFactor({ open_positions: [{ unrealized_pl: -10 }, { unrealized_pl: 5 }] });
  assert.strictEqual(gain.direction, 'positive');
  assert.strictEqual(loss.direction, 'negative');
});

// --- concentrationFactor ---

test('concentrationFactor: missing evidence is honestly unavailable', () => {
  assert.strictEqual(concentrationFactor({ open_positions: [], portfolio_value: 1000 }).available, false);
  assert.strictEqual(concentrationFactor({ open_positions: [{ unrealized_pl: 10 }], portfolio_value: null }).available, false);
});

test('concentrationFactor: real percentage crossing the disclosed 2% threshold is flagged negative', () => {
  const elevated = concentrationFactor({ open_positions: [{ unrealized_pl: 50 }], portfolio_value: 1000 });
  const normal = concentrationFactor({ open_positions: [{ unrealized_pl: 5 }], portfolio_value: 1000 });
  assert.strictEqual(elevated.direction, 'negative');
  assert.strictEqual(normal.direction, 'neutral');
});

// --- marketRegimeFactor ---

test('marketRegimeFactor: no evidence is honestly unavailable', () => {
  assert.strictEqual(marketRegimeFactor({}).available, false);
});

test('marketRegimeFactor: real tone drives direction', () => {
  assert.strictEqual(marketRegimeFactor({ market_health: 'Healthy and ready' }).direction, 'positive');
  assert.strictEqual(marketRegimeFactor({ market_health: 'Requires attention' }).direction, 'negative');
});

// --- learningConfidenceFactor ---

test('learningConfidenceFactor: non-numeric win rate is honestly unavailable', () => {
  assert.strictEqual(learningConfidenceFactor(null).available, false);
  assert.strictEqual(learningConfidenceFactor(undefined).available, false);
});

test('learningConfidenceFactor: real win rate drives direction', () => {
  assert.strictEqual(learningConfidenceFactor(0.7).direction, 'positive');
  assert.strictEqual(learningConfidenceFactor(0.2).direction, 'negative');
});

// --- researchConvictionFactor ---

test('researchConvictionFactor: null confidence is honestly unavailable', () => {
  assert.strictEqual(researchConvictionFactor(null).available, false);
});

test('researchConvictionFactor: real confidence percentage drives direction', () => {
  assert.strictEqual(researchConvictionFactor(80).direction, 'positive');
  assert.strictEqual(researchConvictionFactor(40).direction, 'negative');
});

// --- opportunityCaptureFactor ---

test('opportunityCaptureFactor: no recommendation evidence is honestly unavailable', () => {
  assert.strictEqual(opportunityCaptureFactor({ active: 0, expired: 0 }).available, false);
});

test('opportunityCaptureFactor: real expiry ratio drives direction', () => {
  assert.strictEqual(opportunityCaptureFactor({ active: 8, expired: 2 }).direction, 'positive');
  assert.strictEqual(opportunityCaptureFactor({ active: 2, expired: 8 }).direction, 'negative');
});

// --- riskReadinessFactor ---

test('riskReadinessFactor: missing evidence is honestly unavailable', () => {
  assert.strictEqual(riskReadinessFactor(null).available, false);
});

test('riskReadinessFactor: real trade_ready boolean drives direction', () => {
  assert.strictEqual(riskReadinessFactor({ trade_ready: true }).direction, 'positive');
  assert.strictEqual(riskReadinessFactor({ trade_ready: false, note: 'Broker offline' }).direction, 'negative');
});

// --- evaluateFactors / summarizeFactors ---

test('evaluateFactors: returns exactly the eight implemented factors', () => {
  const result = evaluateFactors({});
  assert.strictEqual(result.length, 8);
});

test('summarizeFactors: counts only real, directional (non-neutral) available factors', () => {
  const factors = [
    { available: true, direction: 'positive' },
    { available: true, direction: 'positive' },
    { available: true, direction: 'negative' },
    { available: true, direction: 'neutral' },
    { available: false, direction: null },
  ];
  const summary = summarizeFactors(factors);
  assert.strictEqual(summary.consideredCount, 5);
  assert.strictEqual(summary.availableCount, 4);
  assert.strictEqual(summary.positiveCount, 2);
  assert.strictEqual(summary.negativeCount, 1);
});

test('summarizeFactors: no factors at all never throws and reports zero counts', () => {
  const summary = summarizeFactors([]);
  assert.strictEqual(summary.consideredCount, 0);
  assert.strictEqual(summary.positiveCount, 0);
});

console.log(`\n${passed} passed`);
if (process.exitCode) {
  console.error('Some forecastFactors tests failed.');
}
