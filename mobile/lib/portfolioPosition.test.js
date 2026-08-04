// Plain Node assert-based tests for portfolioPosition.js - run with `node lib/portfolioPosition.test.js`.

'use strict';

const assert = require('assert');
const { weekToDatePnl, monthToDatePnl, largestPosition } = require('./portfolioPosition');

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

test('weekToDatePnl: sums real per-broker week_pnl values', () => {
  assert.strictEqual(weekToDatePnl([{ week_pnl: 10 }, { week_pnl: -3 }]), 7);
});

test('weekToDatePnl: no brokers with real week_pnl evidence returns null, never a fabricated zero', () => {
  assert.strictEqual(weekToDatePnl([]), null);
  assert.strictEqual(weekToDatePnl([{ week_pnl: null }]), null);
});

test('monthToDatePnl: sums real per-broker month_pnl values', () => {
  assert.strictEqual(monthToDatePnl([{ month_pnl: 100 }, { month_pnl: 50 }]), 150);
});

test('largestPosition: picks the real largest winning position by unrealized_pl', () => {
  const positions = [{ symbol: 'AAA', unrealized_pl: 10 }, { symbol: 'BBB', unrealized_pl: 40 }, { symbol: 'CCC', unrealized_pl: -50 }];
  const result = largestPosition(positions, 'winning');
  assert.strictEqual(result.symbol, 'BBB');
});

test('largestPosition: picks the real largest losing position by unrealized_pl', () => {
  const positions = [{ symbol: 'AAA', unrealized_pl: 10 }, { symbol: 'BBB', unrealized_pl: -5 }, { symbol: 'CCC', unrealized_pl: -50 }];
  const result = largestPosition(positions, 'losing');
  assert.strictEqual(result.symbol, 'CCC');
});

test('largestPosition: no qualifying position returns null, never fabricated', () => {
  assert.strictEqual(largestPosition([{ symbol: 'AAA', unrealized_pl: 10 }], 'losing'), null);
  assert.strictEqual(largestPosition([], 'winning'), null);
});

console.log(`\n${passed} passed`);
if (process.exitCode) {
  console.error('Some portfolioPosition tests failed.');
}
