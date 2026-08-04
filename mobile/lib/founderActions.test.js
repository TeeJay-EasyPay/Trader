// Plain Node assert-based tests for founderActions.js - run with `node lib/founderActions.test.js`.

'use strict';

const assert = require('assert');
const { recommendationAction, incidentAction, buildFounderActions } = require('./founderActions');

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

test('recommendationAction: answers every required field from real data', () => {
  const action = recommendationAction({
    ticker: 'AAPL',
    reason_for_recommendation: 'Strong momentum.',
    expected_return_r: 1.2,
    key_risks: 'Earnings miss.',
    expires_at: '2026-08-05T12:00:00Z',
  });
  assert.ok(action.what.includes('AAPL'));
  assert.strictEqual(action.why, 'Strong momentum.');
  assert.ok(action.expectedBenefit.includes('1.20R'));
  assert.strictEqual(action.risk, 'Earnings miss.');
  assert.ok(action.ifNothing.length > 0);
});

test('recommendationAction: missing fields are honest, not fabricated', () => {
  const action = recommendationAction({ ticker: 'AAPL' });
  assert.strictEqual(action.expectedBenefit, 'Not estimated for this recommendation');
  assert.strictEqual(action.deadline, 'No expiry recorded');
});

test('incidentAction: real count is named, with correct singular/plural grammar', () => {
  assert.ok(incidentAction(1).what.includes('1 unresolved operational incident.'));
  assert.ok(incidentAction(3).what.includes('3 unresolved operational incidents.'));
});

test('buildFounderActions: genuinely nothing outstanding returns an empty array', () => {
  assert.deepStrictEqual(buildFounderActions({ recommendations: [], unresolvedIncidentCount: 0 }), []);
});

test('buildFounderActions: caps recommendations and appends the incident action when present', () => {
  const recommendations = Array.from({ length: 5 }, (_, i) => ({ ticker: `T${i}`, confidence: 0.5 + i / 10, freshness_status: 'Fresh' }));
  const actions = buildFounderActions({ recommendations, unresolvedIncidentCount: 2, maxRecommendations: 3 });
  assert.strictEqual(actions.length, 4); // 3 recommendations + 1 incident action
});

test('buildFounderActions: excludes expired recommendations', () => {
  const recommendations = [{ ticker: 'A', confidence: 0.9, freshness_status: 'Expired' }];
  assert.deepStrictEqual(buildFounderActions({ recommendations, unresolvedIncidentCount: 0 }), []);
});

console.log(`\n${passed} passed`);
if (process.exitCode) {
  console.error('Some founderActions tests failed.');
}
