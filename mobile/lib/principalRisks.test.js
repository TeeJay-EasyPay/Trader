// Plain Node assert-based tests for principalRisks.js - run with `node lib/principalRisks.test.js`.

'use strict';

const assert = require('assert');
const { impactTierForLossPct, positionsAtLossCard, buildRiskCards } = require('./principalRisks');

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

// --- impactTierForLossPct ---

test('impactTierForLossPct: real disclosed thresholds', () => {
  assert.strictEqual(impactTierForLossPct(0.01), 'Low');
  assert.strictEqual(impactTierForLossPct(0.03), 'Medium');
  assert.strictEqual(impactTierForLossPct(0.10), 'High');
});

// --- positionsAtLossCard ---

test('positionsAtLossCard: no positions at loss returns null, never a fabricated card', () => {
  assert.strictEqual(positionsAtLossCard({ positionsAtLoss: [], portfolioValue: 1000 }), null);
});

test('positionsAtLossCard: no portfolio value returns null - cannot compute a real percentage without it', () => {
  assert.strictEqual(positionsAtLossCard({ positionsAtLoss: [{ symbol: 'AAA', unrealizedPl: -50 }], portfolioValue: null }), null);
});

test('positionsAtLossCard: computes a real percentage-based impact tier', () => {
  const card = positionsAtLossCard({ positionsAtLoss: [{ symbol: 'AAA', unrealizedPl: -100 }], portfolioValue: 1000 });
  assert.ok(card.impact.startsWith('High'));
  assert.ok(card.potentialEffect.includes('AAA'));
});

// --- buildRiskCards ---

test('buildRiskCards: composes both the loss card and market risk cards, capped at 3 market risks', () => {
  const cards = buildRiskCards({
    upcomingRisks: ['risk 1', 'risk 2', 'risk 3', 'risk 4'],
    positionsAtLoss: [{ symbol: 'AAA', unrealizedPl: -20 }],
    portfolioValue: 1000,
  });
  assert.strictEqual(cards.length, 4); // 1 loss card + 3 (capped) market risks
});

test('buildRiskCards: no evidence at all returns an empty array, never fabricated cards', () => {
  assert.deepStrictEqual(buildRiskCards({ upcomingRisks: [], positionsAtLoss: [], portfolioValue: null }), []);
});

console.log(`\n${passed} passed`);
if (process.exitCode) {
  console.error('Some principalRisks tests failed.');
}
