// Plain Node assert-based tests for todaysStrategy.js - run with `node lib/todaysStrategy.test.js`.

'use strict';

const assert = require('assert');
const { describeDailyPlan } = require('./todaysStrategy');

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

test('describeDailyPlan: no plan yet reports not_yet_generated with a plain-English fallback', () => {
  const described = describeDailyPlan(undefined);
  assert.strictEqual(described.status, 'not_yet_generated');
  assert.ok(described.plainEnglish.includes('not been generated yet'));
});

test('describeDailyPlan: honours a backend-provided plain_english message when present', () => {
  const described = describeDailyPlan({ status: 'not_yet_generated', plain_english: 'Custom message.' });
  assert.strictEqual(described.plainEnglish, 'Custom message.');
});

test('describeDailyPlan: seek_trades renders a positive-tone "seeking" label', () => {
  const described = describeDailyPlan({
    status: 'generated',
    decision: 'seek_trades',
    reasoning: 'AAPL: strong quarter.',
    outcome_plain_english: 'Still seeking -- no trade has executed yet today.',
  });
  assert.strictEqual(described.status, 'generated');
  assert.strictEqual(described.decisionLabel, 'Seeking trades today');
  assert.strictEqual(described.decisionTone, 'good');
  assert.strictEqual(described.reasoning, 'AAPL: strong quarter.');
  assert.strictEqual(described.outcomeText, 'Still seeking -- no trade has executed yet today.');
});

test('describeDailyPlan: stand_aside renders a neutral-tone "standing aside" label', () => {
  const described = describeDailyPlan({
    status: 'generated',
    decision: 'stand_aside',
    reasoning: 'No candidate cleared due diligence.',
    outcome_plain_english: 'Stood aside as planned -- no trades attempted today.',
  });
  assert.strictEqual(described.decisionLabel, 'Standing aside today');
  assert.strictEqual(described.decisionTone, 'neutral');
});

console.log(`${passed} passed`);
