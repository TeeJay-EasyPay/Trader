// Plain Node assert-based tests for lists.js - run with `node mobile/lib/lists.test.js`.

'use strict';

const assert = require('assert');
const { formatList, formatListInline } = require('./lists');

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

test('formatList: empty/null/undefined returns null', () => {
  assert.strictEqual(formatList(null), null);
  assert.strictEqual(formatList(undefined), null);
  assert.strictEqual(formatList([]), null);
});

test('formatList: a plain string is returned unchanged', () => {
  assert.strictEqual(formatList('already text'), 'already text');
});

test('formatList: an array is rendered as a bulleted block', () => {
  assert.strictEqual(formatList(['a', 'b']), '- a\n- b');
});

test('formatListInline: empty/null/undefined returns null', () => {
  assert.strictEqual(formatListInline(null), null);
  assert.strictEqual(formatListInline([]), null);
});

test('formatListInline: an array is joined with commas on one line', () => {
  assert.strictEqual(formatListInline(['a', 'b', 'c']), 'a, b, c');
});

console.log(`\n${passed} passed`);
