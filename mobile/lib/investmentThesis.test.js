// Plain Node assert-based tests for investmentThesis.js - run with `node lib/investmentThesis.test.js`.

'use strict';

const assert = require('assert');
const {
  leadTheme,
  dominantStrategy,
  currentInvestmentThesis,
  alternativeThesis,
  evidenceStrength,
} = require('./investmentThesis');

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

// --- leadTheme ---

test('leadTheme: picks the real highest-confidence theme, not the first in the array', () => {
  const themes = [
    { theme: 'Energy Transition', confidence: 0.4 },
    { theme: 'AI Infrastructure', confidence: 0.82 },
  ];
  assert.strictEqual(leadTheme(themes).theme, 'AI Infrastructure');
});

test('leadTheme: empty/null input returns null, never a fabricated theme', () => {
  assert.strictEqual(leadTheme([]), null);
  assert.strictEqual(leadTheme(null), null);
});

// --- dominantStrategy ---

test('dominantStrategy: counts only non-expired recommendations', () => {
  const recommendations = [
    { strategy_name: 'Momentum', freshness_status: 'Fresh' },
    { strategy_name: 'Momentum', freshness_status: 'Fresh' },
    { strategy_name: 'Mean Reversion', freshness_status: 'Expired' },
  ];
  const result = dominantStrategy(recommendations);
  assert.strictEqual(result.name, 'Momentum');
  assert.strictEqual(result.count, 2);
});

test('dominantStrategy: no strategy evidence returns null', () => {
  assert.strictEqual(dominantStrategy([]), null);
});

// --- currentInvestmentThesis ---

test('currentInvestmentThesis: no theme or strategy evidence is honest, not fabricated', () => {
  const result = currentInvestmentThesis({ themes: [], recommendations: [] });
  assert.strictEqual(result.available, false);
  assert.ok(result.statement.includes('does not yet have enough'));
});

test('currentInvestmentThesis: composes a real statement from theme + strategy evidence', () => {
  const result = currentInvestmentThesis({
    themes: [{ theme: 'AI Infrastructure', confidence: 0.8, summary: 'Datacentre demand remains strong.' }],
    recommendations: [{ strategy_name: 'Momentum', freshness_status: 'Fresh' }],
  });
  assert.strictEqual(result.available, true);
  assert.ok(result.statement.includes('AI Infrastructure'));
  assert.ok(result.statement.includes('Momentum'));
  assert.strictEqual(result.evidence.length, 2);
});

// --- alternativeThesis ---

test('alternativeThesis: no documented risk evidence is honest, not fabricated', () => {
  const result = alternativeThesis({ themes: [{ theme: 'AI Infrastructure', confidence: 0.8, key_risks: [] }] });
  assert.strictEqual(result.available, false);
});

test('alternativeThesis: built from the lead theme\'s own key_risks, capped at 3', () => {
  const result = alternativeThesis({
    themes: [{ theme: 'AI Infrastructure', confidence: 0.8, key_risks: ['rate shock', 'demand slowdown', 'regulation', 'a fourth risk'] }],
  });
  assert.strictEqual(result.available, true);
  assert.ok(result.statement.includes('rate shock; demand slowdown; regulation'));
  assert.ok(!result.statement.includes('a fourth risk'));
});

// --- evidenceStrength (AT-ED-016) ---

test('evidenceStrength: no factors considered is honestly "not yet established"', () => {
  assert.ok(evidenceStrength(null).includes('Not yet established'));
  assert.ok(evidenceStrength({ consideredCount: 0 }).includes('Not yet established'));
});

test('evidenceStrength: real ratio drives the Strong/Moderate/Weak tier, with the real counts named', () => {
  assert.ok(evidenceStrength({ consideredCount: 8, availableCount: 7 }).startsWith('Strong'));
  assert.ok(evidenceStrength({ consideredCount: 8, availableCount: 4 }).startsWith('Moderate'));
  assert.ok(evidenceStrength({ consideredCount: 8, availableCount: 1 }).startsWith('Weak'));
  assert.ok(evidenceStrength({ consideredCount: 8, availableCount: 7 }).includes('7 of 8'));
});

console.log(`\n${passed} passed`);
if (process.exitCode) {
  console.error('Some investmentThesis tests failed.');
}
