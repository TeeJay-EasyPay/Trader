// Plain Node assert-based tests for recommendations.js - run with `node mobile/lib/recommendations.test.js`.

'use strict';

const assert = require('assert');
const {
  withRecommendationFreshness,
  clientAutoTradeReason,
  formatGuardrailChecks,
  marketRegimeText,
  rMultiple,
  committeeSummary,
  signalSummary,
  lifecycleSummary,
  uniqueValues,
  groupRecommendations,
  filterRecommendations,
  exitPlan,
  probabilityRange,
} = require('./recommendations');

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

test('withRecommendationFreshness: backend-provided freshness/expiry is trusted as-is', () => {
  const item = { freshness_status: 'Fresh', expires_at: '2026-01-01T00:00:00Z' };
  assert.strictEqual(withRecommendationFreshness(item), item);
});

test('withRecommendationFreshness: no created_at leaves freshness fields null rather than guessing', () => {
  const result = withRecommendationFreshness({ confidence: 0.9 });
  assert.strictEqual(result.freshness_status, null);
});

test('withRecommendationFreshness: a fresh, high-confidence, passing recommendation is auto-trade eligible', () => {
  const result = withRecommendationFreshness({
    created_at: new Date().toISOString(),
    confidence: 0.9,
    guardrails_passed: true,
  });
  assert.strictEqual(result.freshness_status, 'Fresh');
  assert.strictEqual(result.auto_trade_eligible, true);
});

test('withRecommendationFreshness: an old recommendation past its lifetime reads Expired', () => {
  const result = withRecommendationFreshness({
    created_at: new Date(Date.now() - 30 * 60 * 60 * 1000).toISOString(),
    confidence: 0.9,
  });
  assert.strictEqual(result.freshness_status, 'Expired');
  assert.strictEqual(result.auto_trade_eligible, false);
});

test('clientAutoTradeReason: already-executed takes priority over everything else', () => {
  assert.strictEqual(clientAutoTradeReason({ already_executed: true }, 0.9, 'Fresh'), 'Already executed.');
});

test('clientAutoTradeReason: below-threshold confidence is explained', () => {
  assert.strictEqual(clientAutoTradeReason({}, 0.5, 'Fresh'), 'Confidence is below 85%.');
});

test('clientAutoTradeReason: eligible case', () => {
  assert.strictEqual(clientAutoTradeReason({}, 0.9, 'Fresh'), 'Eligible for paper auto-trade.');
});

test('formatGuardrailChecks: no checks returns null', () => {
  assert.strictEqual(formatGuardrailChecks(null, 'passed'), null);
});

test('formatGuardrailChecks: failed status with no matches reads None, not null', () => {
  assert.strictEqual(formatGuardrailChecks([{ status: 'passed', key: 'a' }], 'failed'), 'None');
});

test('formatGuardrailChecks: lists matching checks by label or humanised key', () => {
  const result = formatGuardrailChecks([{ status: 'failed', key: 'max_position_size' }], 'failed');
  assert.strictEqual(result, '- max position size');
});

test('marketRegimeText: null returns null', () => {
  assert.strictEqual(marketRegimeText(null), null);
});

test('marketRegimeText: joins primary/trend/risk regimes', () => {
  assert.strictEqual(
    marketRegimeText({ primary_regime: 'bull', trend_regime: 'up', risk_regime: 'low' }),
    'bull; up; low'
  );
});

test('rMultiple: formats a numeric R value', () => {
  assert.strictEqual(rMultiple(1.5), '1.50R');
});

test('rMultiple: empty input returns null', () => {
  assert.strictEqual(rMultiple(''), null);
});

test('committeeSummary: no committee returns null', () => {
  assert.strictEqual(committeeSummary(null), null);
});

test('signalSummary: empty array returns null', () => {
  assert.strictEqual(signalSummary([]), null);
});

test('lifecycleSummary: empty array returns null', () => {
  assert.strictEqual(lifecycleSummary([]), null);
});

test('uniqueValues: dedupes and drops empty-string entries (values are stringified first, so null becomes the truthy string "null")', () => {
  assert.deepStrictEqual(uniqueValues(['a', 'b', 'a', '']), ['a', 'b']);
});

test('groupRecommendations: groups by broker and sorts each group by confidence descending', () => {
  const grouped = groupRecommendations([
    { suggested_broker: 'alpaca', confidence: 0.5 },
    { suggested_broker: 'alpaca', confidence: 0.9 },
    { suggested_broker: 'kraken', confidence: 0.7 },
  ]);
  assert.deepStrictEqual(grouped.alpaca.map((item) => item.confidence), [0.9, 0.5]);
  assert.strictEqual(grouped.kraken.length, 1);
});

test('filterRecommendations: applies broker, asset type, status, and confidence filters together', () => {
  const items = [
    { suggested_broker: 'alpaca', asset_type: 'equity', freshness_status: 'Fresh', confidence: 0.9 },
    { suggested_broker: 'alpaca', asset_type: 'equity', freshness_status: 'Fresh', confidence: 0.8 },
    { suggested_broker: 'kraken', asset_type: 'crypto', freshness_status: 'Fresh', confidence: 0.95 },
  ];
  const result = filterRecommendations(items, 'alpaca', '85%+', 'equity', 'Fresh');
  assert.strictEqual(result.length, 1);
  assert.strictEqual(result[0].confidence, 0.9);
});

test('exitPlan: describes the bracket order using Not-available-safe stop/take-profit values', () => {
  const text = exitPlan({ suggested_stop_loss: 90, suggested_take_profit: 110 });
  assert.ok(text.includes('stop loss'));
  assert.ok(text.includes('take profit'));
});

test('probabilityRange: builds a +/-5% band around the value', () => {
  assert.strictEqual(probabilityRange(0.6), '55%-65%');
});

test('probabilityRange: non-numeric input explains the missing model output', () => {
  assert.strictEqual(probabilityRange('n/a'), 'Not available - probability model did not return a value.');
});

console.log(`\n${passed} passed`);
