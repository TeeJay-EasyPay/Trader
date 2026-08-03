// Plain Node assert-based tests for notAvailable.js - run with `node mobile/lib/notAvailable.test.js`.

'use strict';

const assert = require('assert');
const { notAvailable, explainMissing } = require('./notAvailable');

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

test('notAvailable: null/undefined/empty produce the standard missing-data message', () => {
  assert.strictEqual(notAvailable(null), 'Not available - source data has not been recorded yet.');
  assert.strictEqual(notAvailable(undefined), 'Not available - source data has not been recorded yet.');
  assert.strictEqual(notAvailable(''), 'Not available - source data has not been recorded yet.');
});

test('notAvailable: a present value is stringified and returned', () => {
  assert.strictEqual(notAvailable(42), '42');
  assert.strictEqual(notAvailable('hello'), 'hello');
});

test('explainMissing: builds a field-specific missing-data explanation', () => {
  assert.strictEqual(
    explainMissing('portfolio value', 'the broker has not reported it yet'),
    'Not available - portfolio value is unavailable because the broker has not reported it yet.',
  );
});

console.log(`\n${passed} passed`);
