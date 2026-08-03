// Plain Node assert-based tests for money.js - run with `node mobile/lib/money.test.js`.

'use strict';

const assert = require('assert');
const {
  brokerKey,
  money,
  gbp,
  moneyOrText,
  gbpOrText,
  brokerMoney,
  historyMoneyOrText,
} = require('./money');

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

test('money: formats a USD amount with the dollar sign', () => {
  assert.strictEqual(money(1234.5), '$1,234.5');
});

test('money: null/undefined/empty all return null', () => {
  assert.strictEqual(money(null), null);
  assert.strictEqual(money(undefined), null);
  assert.strictEqual(money(''), null);
});

test('gbp: formats a GBP amount with the pound sign', () => {
  assert.strictEqual(gbp(50), '£50');
});

test('moneyOrText: passes through an existing "Not available" string unchanged', () => {
  assert.strictEqual(moneyOrText('Not available - reason.'), 'Not available - reason.');
});

test('moneyOrText: formats a real number', () => {
  assert.strictEqual(moneyOrText(10), '$10');
});

test('gbpOrText: passes through an existing "Not available" string unchanged', () => {
  assert.strictEqual(gbpOrText('Not available - reason.'), 'Not available - reason.');
});

test('brokerKey: normalises case, spaces, underscores and hyphens', () => {
  assert.strictEqual(brokerKey('Background Worker'), 'backgroundworker');
  assert.strictEqual(brokerKey('kraken-ui'), 'krakenui');
  assert.strictEqual(brokerKey(null), 'all');
});

test('brokerMoney: routes Kraken brokers to GBP formatting', () => {
  assert.strictEqual(brokerMoney({ broker: 'kraken' }, 100), '£100');
});

test('brokerMoney: routes non-Kraken brokers to USD formatting', () => {
  assert.strictEqual(brokerMoney({ broker: 'alpaca' }, 100), '$100');
});

test('historyMoneyOrText: routes by the selected exchange, not the row broker', () => {
  assert.strictEqual(historyMoneyOrText('Kraken', 100), '£100');
  assert.strictEqual(historyMoneyOrText('Alpaca', 100), '$100');
  assert.strictEqual(historyMoneyOrText('All', 100), '$100');
});

console.log(`\n${passed} passed`);
