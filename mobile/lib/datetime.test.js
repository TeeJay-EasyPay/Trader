// Plain Node assert-based tests for datetime.js - run with `node mobile/lib/datetime.test.js`.

'use strict';

const assert = require('assert');
const { dateMs, formatDateTime, formatPercent } = require('./datetime');

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

test('dateMs: parses an ISO string', () => {
  assert.strictEqual(dateMs('2026-01-01T00:00:00Z'), Date.parse('2026-01-01T00:00:00Z'));
});

test('dateMs: treats a large numeric-looking string as epoch milliseconds', () => {
  assert.strictEqual(dateMs('1700000000000'), 1700000000000);
});

test('dateMs: treats a numeric-looking string in seconds range as epoch seconds, scaled to ms', () => {
  assert.strictEqual(dateMs('1700000000'), 1700000000000);
});

test('dateMs: invalid input returns 0', () => {
  assert.strictEqual(dateMs('not a date'), 0);
  assert.strictEqual(dateMs(''), 0);
});

test('formatDateTime: null/falsy returns null', () => {
  assert.strictEqual(formatDateTime(null), null);
  assert.strictEqual(formatDateTime(''), null);
});

test('formatDateTime: formats a valid date into a readable string', () => {
  const result = formatDateTime('2026-03-15T10:30:00Z');
  assert.ok(typeof result === 'string' && result.length > 0);
  assert.ok(result.includes('2026'));
});

test('formatDateTime: unparseable value is returned unchanged', () => {
  assert.strictEqual(formatDateTime('not a date'), 'not a date');
});

test('formatPercent: null/undefined/empty returns null', () => {
  assert.strictEqual(formatPercent(null), null);
  assert.strictEqual(formatPercent(undefined), null);
  assert.strictEqual(formatPercent(''), null);
});

test('formatPercent: fraction <= 1 is scaled to a percentage', () => {
  assert.strictEqual(formatPercent(0.42), '42%');
});

test('formatPercent: value already > 1 is used as-is', () => {
  assert.strictEqual(formatPercent(42), '42%');
});

test('formatPercent: non-numeric value is returned unchanged', () => {
  assert.strictEqual(formatPercent('n/a'), 'n/a');
});

console.log(`\n${passed} passed`);
