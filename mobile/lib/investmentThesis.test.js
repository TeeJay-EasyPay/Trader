// Plain Node assert-based tests for investmentThesis.js - run with `node lib/investmentThesis.test.js`.

'use strict';

const assert = require('assert');
const {
  leadTheme,
  dominantStrategy,
  formatThemeConviction,
  withPeriod,
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

// --- formatThemeConviction / withPeriod (AT-ED-017 live-review fix) ---

test('formatThemeConviction: a real numeric confidence formats as a percentage', () => {
  assert.strictEqual(formatThemeConviction({ theme: 'Airlines', confidence: 0.65 }), 'My conviction in Airlines currently sits at 65%.');
});

test('formatThemeConviction: a string confidence label (production evidence shape) is named, never a fabricated NaN%', () => {
  const text = formatThemeConviction({ theme: 'Airlines', confidence: 'Medium' });
  assert.ok(!text.includes('NaN'));
  assert.ok(text.includes('rated Medium'));
});

test('formatThemeConviction: missing confidence is honest, not fabricated', () => {
  assert.ok(formatThemeConviction({ theme: 'Airlines', confidence: null }).includes('have not yet rated'));
});

test('withPeriod: adds a period only when the text does not already end with sentence punctuation', () => {
  assert.strictEqual(withPeriod('no punctuation'), 'no punctuation.');
  assert.strictEqual(withPeriod('already punctuated.'), 'already punctuated.');
  assert.strictEqual(withPeriod('a question?'), 'a question?');
});

test('currentInvestmentThesis: a string theme confidence never produces NaN in the statement or evidence', () => {
  const result = currentInvestmentThesis({
    themes: [{ theme: 'Airlines', confidence: 'Medium', summary: 'Passenger demand remains important.' }],
    recommendations: [],
  });
  assert.ok(!result.statement.includes('NaN'));
  assert.ok(!result.evidence.join(' ').includes('NaN'));
});

test('currentInvestmentThesis: a theme summary that already ends with a period never produces a double period', () => {
  const result = currentInvestmentThesis({
    themes: [{ theme: 'Airlines', confidence: 0.5, summary: 'Passenger demand remains important.' }],
    recommendations: [],
  });
  assert.ok(!result.statement.includes('..'));
});

test('currentInvestmentThesis: exactly one recommendation uses singular subject-verb agreement, not "recommendation lean"', () => {
  const result = currentInvestmentThesis({
    themes: [],
    recommendations: [{ strategy_name: 'Momentum', freshness_status: 'Fresh' }],
  });
  assert.ok(result.statement.includes('1 of our current recommendation leans on the Momentum approach.'));
  assert.ok(result.evidence[0].includes('1 of our current idea follows the Momentum approach.'));
});

test('currentInvestmentThesis: more than one recommendation keeps plural subject-verb agreement', () => {
  const result = currentInvestmentThesis({
    themes: [],
    recommendations: [
      { strategy_name: 'Momentum', freshness_status: 'Fresh' },
      { strategy_name: 'Momentum', freshness_status: 'Fresh' },
    ],
  });
  assert.ok(result.statement.includes('2 of our current recommendations lean on the Momentum approach.'));
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

test('alternativeThesis (AT-ED-017 live-review fix): risks that already end with a period never produce a double period', () => {
  const result = alternativeThesis({
    themes: [{ theme: 'Airlines', confidence: 0.5, key_risks: ['Fuel prices.', 'Airspace disruption.', 'Regulation.'] }],
  });
  assert.ok(!result.statement.includes('..'));
  assert.ok(result.statement.endsWith('Fuel prices; Airspace disruption; Regulation.'));
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
