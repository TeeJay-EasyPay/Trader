// Plain Node assert-based tests for json.js - run with `node mobile/lib/json.test.js`.

'use strict';

const assert = require('assert');
const { parseMaybeJson, formatJsonText } = require('./json');

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

test('parseMaybeJson: falsy input returns null', () => {
  assert.strictEqual(parseMaybeJson(null), null);
  assert.strictEqual(parseMaybeJson(''), null);
});

test('parseMaybeJson: an already-parsed object is returned unchanged', () => {
  const obj = { a: 1 };
  assert.strictEqual(parseMaybeJson(obj), obj);
});

test('parseMaybeJson: a JSON string is parsed', () => {
  assert.deepStrictEqual(parseMaybeJson('{"a":1}'), { a: 1 });
});

test('parseMaybeJson: an unparseable string returns null, not a thrown error', () => {
  assert.strictEqual(parseMaybeJson('not json'), null);
});

test('formatJsonText: a JSON string is pretty-printed', () => {
  assert.strictEqual(formatJsonText('{"a":1}'), JSON.stringify({ a: 1 }, null, 2));
});

test('formatJsonText: an unparseable string is returned as-is', () => {
  assert.strictEqual(formatJsonText('plain text'), 'plain text');
});

test('formatJsonText: a non-string, unparseable value returns null', () => {
  assert.strictEqual(formatJsonText(undefined), null);
});

console.log(`\n${passed} passed`);
