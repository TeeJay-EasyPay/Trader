// Plain Node assert-based tests for principalOpportunities.js - run with
// `node lib/principalOpportunities.test.js`.
// AT-ED-016.1: field names/wording simplified to Why I Like It/Potential Upside/Main Catalyst/
// Confidence - same underlying real fields, tests updated to match.

'use strict';

const assert = require('assert');
const { recommendationOpportunityCard, keyDriversText, themeOpportunityCard, buildOpportunityCards } = require('./principalOpportunities');

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

test('recommendationOpportunityCard: uses real fields, with honest fallbacks for missing ones', () => {
  const card = recommendationOpportunityCard({
    ticker: 'AAPL',
    reason_for_recommendation: 'Strong momentum.',
    strategy_name: 'Momentum',
    expected_return_r: 1.5,
    confidence: 0.9,
    expires_at: '2026-08-05T12:00:00Z',
  });
  assert.strictEqual(card.title, 'AAPL');
  assert.strictEqual(card.whyILikeIt, 'Strong momentum.');
  assert.ok(card.potentialUpside.includes('1.50R'));
});

test('recommendationOpportunityCard: missing expected_return_r is honest, not fabricated', () => {
  const card = recommendationOpportunityCard({ ticker: 'AAPL' });
  assert.strictEqual(card.potentialUpside, 'Not yet estimated');
});

test('themeOpportunityCard: uses real theme fields', () => {
  const card = themeOpportunityCard({ theme: 'AI Infrastructure', summary: 'Strong demand.', confidence: 0.8, key_drivers: ['a', 'b', 'c', 'd'] });
  assert.strictEqual(card.title, 'AI Infrastructure');
  assert.strictEqual(card.whyILikeIt, 'Strong demand.');
});

test('recommendationOpportunityCard: catalyst uses the real, distinct strongest_argument_for field (AT-ED-016)', () => {
  const card = recommendationOpportunityCard({ ticker: 'AAPL', reason_for_recommendation: 'Strong momentum.', strongest_argument_for: 'Institutional accumulation observed.' });
  assert.strictEqual(card.catalyst, 'Institutional accumulation observed.');
  assert.notStrictEqual(card.catalyst, card.whyILikeIt);
});

test('themeOpportunityCard: catalyst uses the first key driver, honest fallback when none exist (AT-ED-016)', () => {
  const withDrivers = themeOpportunityCard({ theme: 'AI Infrastructure', key_drivers: ['Datacentre demand', 'Cloud capex'] });
  const withoutDrivers = themeOpportunityCard({ theme: 'AI Infrastructure' });
  assert.strictEqual(withDrivers.catalyst, 'Datacentre demand');
  assert.ok(withoutDrivers.catalyst.includes('No specific catalyst'));
});

test('themeOpportunityCard: production-representative key_drivers (a plain string) never throws', () => {
  const card = themeOpportunityCard({ theme: 'AI Infrastructure', summary: 'Strong demand.', confidence: 0.8, key_drivers: 'Strong capex growth, cloud demand' });
  assert.strictEqual(card.catalyst, 'Strong capex growth, cloud demand');
});

test('themeOpportunityCard: missing or empty key_drivers is honest, never throws', () => {
  assert.ok(themeOpportunityCard({ theme: 'X' }).catalyst.includes('No specific catalyst'));
  assert.ok(themeOpportunityCard({ theme: 'X', key_drivers: '' }).catalyst.includes('No specific catalyst'));
});

test('keyDriversText: array input still joins the first three entries, unchanged behaviour', () => {
  assert.strictEqual(keyDriversText({ key_drivers: ['a', 'b', 'c', 'd'] }), 'a; b; c');
});

test('buildOpportunityCards: a string-shaped key_drivers on the top theme never crashes (the exact AT-ED-015.1 white-screen trigger)', () => {
  const themes = [{ theme: 'AI Infrastructure', confidence: 0.8, key_drivers: 'Strong capex growth' }];
  assert.doesNotThrow(() => buildOpportunityCards({ recommendations: [], themes }));
});

test('buildOpportunityCards: caps fresh recommendations and appends at most one top theme', () => {
  const recommendations = Array.from({ length: 5 }, (_, i) => ({ ticker: `T${i}`, confidence: 0.5 + i / 10, freshness_status: 'Fresh' }));
  const themes = [{ theme: 'AI Infrastructure', confidence: 0.8 }, { theme: 'Energy', confidence: 0.4 }];
  const cards = buildOpportunityCards({ recommendations, themes, maxRecommendations: 3 });
  assert.strictEqual(cards.length, 4); // 3 recommendations + 1 theme
  assert.strictEqual(cards[cards.length - 1].title, 'AI Infrastructure');
});

test('buildOpportunityCards: excludes expired recommendations', () => {
  const recommendations = [{ ticker: 'A', confidence: 0.9, freshness_status: 'Expired' }, { ticker: 'B', confidence: 0.6, freshness_status: 'Fresh' }];
  const cards = buildOpportunityCards({ recommendations, themes: [] });
  assert.strictEqual(cards.length, 1);
  assert.strictEqual(cards[0].title, 'B');
});

test('buildOpportunityCards: no evidence at all returns an empty array, never fabricated', () => {
  assert.deepStrictEqual(buildOpportunityCards({ recommendations: [], themes: [] }), []);
});

console.log(`\n${passed} passed`);
if (process.exitCode) {
  console.error('Some principalOpportunities tests failed.');
}
