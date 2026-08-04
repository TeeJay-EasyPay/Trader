// Plain Node assert-based tests for founderActions.js - run with `node lib/founderActions.test.js`.
// AT-ED-016.1: collapsed to a single spoken recommendation + a plain consequence sentence -
// same real fields, tests updated to match.

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

test('recommendationAction: composes a real recommendation sentence naming the symbol and the real reason', () => {
  const action = recommendationAction({
    ticker: 'AAPL',
    reason_for_recommendation: 'Strong momentum.',
    expires_at: '2026-08-05T12:00:00Z',
  });
  assert.ok(action.recommendation.includes('AAPL'));
  assert.ok(action.recommendation.includes('Strong momentum.'));
  assert.ok(action.ifNothing.length > 0);
});

test('recommendationAction: missing reason is still a valid sentence, never fabricated', () => {
  const action = recommendationAction({ ticker: 'AAPL' });
  assert.ok(action.recommendation.startsWith('I recommend reviewing AAPL'));
});

test('incidentAction: real count is named, with correct singular/plural grammar', () => {
  assert.ok(incidentAction(1).recommendation.includes('1 open item'));
  assert.ok(incidentAction(3).recommendation.includes('3 open items'));
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
