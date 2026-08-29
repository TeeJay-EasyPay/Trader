// Plain Node assert-based tests for cycleProgress.js - run with
// `node mobile/lib/cycleProgress.test.js`.
//
// 2026-08-29, from the Founder's report: "when I go to the executive briefing and come back
// it stops. i then don't know if it actually stopped or it is still running in the
// background." The header line these tests cover is the part that answers that question from
// whichever screen he happens to be on.

'use strict';

const assert = require('assert');
const { cycleProgressLabel, currentStepOf, isTerminal } = require('./cycleProgress');

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

const steps = [
  { seq: 1, label: 'Refresh the list of coins we are allowed to trade', status: 'completed' },
  { seq: 2, label: 'Get fresh prices, liquidity and news for each coin', status: 'completed' },
  { seq: 3, label: 'Research and score every coin', status: 'running' },
  { seq: 4, label: 'Check each idea against the two rules', status: 'pending' },
  { seq: 5, label: 'Place any crypto orders', status: 'pending' },
];

test('names the step in flight, so the line is specific rather than a bare spinner', () => {
  const label = cycleProgressLabel({
    running: true,
    starting: false,
    steps,
    currentStep: currentStepOf(steps),
  });
  assert.strictEqual(
    label,
    'Cycle running - step 3 of 5: Research and score every coin'
  );
});

test('says nothing once the cycle has finished', () => {
  // Deliberate: a header that keeps advertising a run which ended ten minutes ago trains the
  // Founder to ignore the line, and it then fails exactly when it matters.
  assert.strictEqual(
    cycleProgressLabel({ running: false, starting: false, steps, currentStep: null }),
    null
  );
});

test('reports the starting state before any step exists', () => {
  assert.strictEqual(
    cycleProgressLabel({ running: false, starting: true, steps: [], currentStep: null }),
    'Starting a cycle...'
  );
});

test('degrades to a plain message rather than printing undefined', () => {
  // Between one step closing and the next opening there is a moment with no running step.
  assert.strictEqual(
    cycleProgressLabel({ running: true, starting: false, steps, currentStep: null }),
    'Cycle running...'
  );
});

test('survives a malformed or empty state without throwing', () => {
  assert.strictEqual(cycleProgressLabel(null), null);
  assert.strictEqual(cycleProgressLabel({}), null);
  assert.strictEqual(cycleProgressLabel({ running: true, steps: null, currentStep: null }), 'Cycle running...');
});

test('currentStepOf finds only the running step', () => {
  assert.strictEqual(currentStepOf(steps).seq, 3);
  assert.strictEqual(currentStepOf([]), null);
  assert.strictEqual(currentStepOf(null), null);
  assert.strictEqual(currentStepOf(steps.map((s) => ({ ...s, status: 'completed' }))), null);
});

test('polling continues for a running cycle and stops for a finished one', () => {
  // This is what keeps the run observable after switching tabs: the hook keeps its timer
  // alive while isTerminal is false, wherever in the app the Founder happens to be.
  assert.strictEqual(isTerminal('running'), false);
  assert.strictEqual(isTerminal('completed'), true);
  assert.strictEqual(isTerminal('failed'), true);
  assert.strictEqual(isTerminal('none'), true);
});

console.log(`\n${passed} passed`);
