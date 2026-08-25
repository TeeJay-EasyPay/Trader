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
  assert.strictEqual(described.decisionLabel, 'Seeking share trades today');
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
  assert.strictEqual(described.decisionLabel, 'Standing aside on shares today');
  assert.strictEqual(described.decisionTone, 'neutral');
});


test('an Alpaca plan says which market it covers so it cannot read as "did nothing"', () => {
  // 2026-08-21: the flat label read as inactivity while crypto was actively trading.
  const described = describeDailyPlan({ status: 'generated', decision: 'stand_aside', broker: 'alpaca' });
  assert.ok(described.scope, 'An Alpaca plan must disclose that it covers shares only.');
  assert.ok(/crypto/i.test(described.scope));
});

test('a non-Alpaca plan adds no shares-only caveat', () => {
  assert.strictEqual(
    describeDailyPlan({ status: 'generated', decision: 'stand_aside', broker: 'kraken' }).scope,
    null,
  );
});

console.log(`${passed} passed`);

test('the headline says what happened, not what was planned', () => {
  // 2026-08-25: on a day the AI bought FSLR and NEE, the card read "Standing aside on
  // shares today" with "Planned to stand aside, but 2 trade(s) were recorded today --
  // worth reviewing" directly underneath. A headline contradicted by its own next line.
  //
  // The cause is ordinary, not a fault: the plan is written pre-market, when every
  // candidate is correctly rejected for market_closed, and then the market opens. Right
  // when written, stale by lunchtime.
  const card = describeDailyPlan({ status: 'generated', decision: 'stand_aside', trades_today: 2 });
  assert.strictEqual(card.decisionLabel, '2 share trades placed today');
  assert.strictEqual(card.decisionTone, 'good');
});

test('one trade reads as one trade', () => {
  const card = describeDailyPlan({ status: 'generated', decision: 'stand_aside', trades_today: 1 });
  assert.strictEqual(card.decisionLabel, '1 share trade placed today');
});

test('a genuinely quiet day still says so', () => {
  // Standing aside is a real decision and must keep reading as one.
  const card = describeDailyPlan({ status: 'generated', decision: 'stand_aside', trades_today: 0 });
  assert.strictEqual(card.decisionLabel, 'Standing aside on shares today');
  assert.strictEqual(card.decisionTone, 'neutral');
});

test('the morning reasoning is kept as context, not as the claim', () => {
  const card = describeDailyPlan({
    status: 'generated', decision: 'stand_aside', trades_today: 2,
    reasoning: 'No candidate cleared due diligence before the open.',
  });
  assert.strictEqual(card.reasoning, 'No candidate cleared due diligence before the open.');
});
