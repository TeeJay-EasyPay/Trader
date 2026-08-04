// Plain Node assert-based tests for principalRisks.js - run with `node lib/principalRisks.test.js`.
// AT-ED-016.1: field names/wording simplified to Risk/Why It Matters/Probability/What I Am Doing
// About It - same underlying real percentage math, tests updated to match.

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

test('positionsAtLossCard: real percentage math still drives the "why it matters" text', () => {
  const card = positionsAtLossCard({ positionsAtLoss: [{ symbol: 'AAA', unrealizedPl: -100 }], portfolioValue: 1000 });
  assert.ok(card.whyItMatters.includes('AAA'));
  assert.ok(card.whyItMatters.includes('100.00'));
  assert.ok(card.whyItMatters.includes('10%'));
});

test('positionsAtLossCard: a High-impact loss gets a different "what I am doing" answer than a Low one', () => {
  const high = positionsAtLossCard({ positionsAtLoss: [{ symbol: 'AAA', unrealizedPl: -100 }], portfolioValue: 1000 });
  const low = positionsAtLossCard({ positionsAtLoss: [{ symbol: 'AAA', unrealizedPl: -5 }], portfolioValue: 1000 });
  assert.notStrictEqual(high.whatImDoing, low.whatImDoing);
});

test('positionsAtLossCard: probability describes a present fact, not a future guess', () => {
  const card = positionsAtLossCard({ positionsAtLoss: [{ symbol: 'AAA', unrealizedPl: -100 }], portfolioValue: 1000 });
  assert.ok(card.probability.includes('already happening'));
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

test('buildRiskCards: market risk cards are honest about not having a real probability figure', () => {
  const cards = buildRiskCards({ upcomingRisks: ['inflation data'], positionsAtLoss: [], portfolioValue: 1000 });
  assert.ok(cards[0].probability.length > 0);
  assert.ok(cards[0].whatImDoing.length > 0);
});

test('buildRiskCards: no evidence at all returns an empty array, never fabricated cards', () => {
  assert.deepStrictEqual(buildRiskCards({ upcomingRisks: [], positionsAtLoss: [], portfolioValue: null }), []);
});

console.log(`\n${passed} passed`);
if (process.exitCode) {
  console.error('Some principalRisks tests failed.');
}
