// Plain Node assert-based tests for forecastAccountability.js - run with
// `node lib/forecastAccountability.test.js`.

'use strict';

const assert = require('assert');
const { forecastAccountability, isResolved } = require('./forecastAccountability');

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

// --- forecastAccountability (deliberate honesty check) ---

test('forecastAccountability: no records at all is honestly "no track record yet", never a fabricated accuracy figure', () => {
  const result = forecastAccountability([]);
  assert.strictEqual(result.available, false);
  assert.strictEqual(result.accuracy, null);
  assert.ok(result.reason.includes('has not yet recorded a forecast'));
});

test('forecastAccountability: null input never throws and is treated the same as empty', () => {
  const result = forecastAccountability(null);
  assert.strictEqual(result.available, false);
});

test('forecastAccountability: computes a real accuracy figure only from records that have actually been judged', () => {
  const result = forecastAccountability([
    { forecast: 'a', actualOutcome: 'hit', correct: true, confidenceGiven: 0.8 },
    { forecast: 'b', actualOutcome: 'miss', correct: false, confidenceGiven: 0.6 },
    { forecast: 'c', actualOutcome: null }, // not yet resolved
  ]);
  assert.strictEqual(result.available, true);
  assert.strictEqual(result.accuracy, 0.5);
});

test('forecastAccountability: unresolved/unjudged records never count toward accuracy', () => {
  const result = forecastAccountability([{ forecast: 'a', actualOutcome: null }]);
  assert.strictEqual(result.accuracy, null);
});

test('isResolved: distinguishes a real outcome from one that has not happened yet', () => {
  assert.strictEqual(isResolved({ actualOutcome: 'hit' }), true);
  assert.strictEqual(isResolved({ actualOutcome: null }), false);
  assert.strictEqual(isResolved({}), false);
});

console.log(`\n${passed} passed`);
if (process.exitCode) {
  console.error('Some forecastAccountability tests failed.');
}
