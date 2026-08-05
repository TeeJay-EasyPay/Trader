// Plain Node assert-based tests for portfolioPosition.js - run with `node lib/portfolioPosition.test.js`.

'use strict';

const assert = require('assert');
const {
  weekToDatePnl,
  monthToDatePnl,
  largestPosition,
  brokerCurrency,
  sumBrokerFieldByCurrency,
  unrealizedPnlByBroker,
  unrealizedPnlByCurrency,
  totalUnrealizedPnl,
  closedTradesToday,
  realizedPnlToday,
  realizedPnlByBrokerToday,
  realizedPnlByCurrencyToday,
  exitsTodayCount,
  exitsTodayCountByCurrency,
  openPositionsCountByCurrency,
} = require('./portfolioPosition');

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

test('largestPosition (AT-ED-017 Founder request): carries the real broker through so callers can format it in its own currency', () => {
  const positions = [{ symbol: 'XBT', unrealized_pl: 40, broker: 'kraken' }];
  const result = largestPosition(positions, 'winning');
  assert.strictEqual(result.broker, 'kraken');
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

// --- AT-ED-017 (Founder request, 2026-08-05): currency-grouped totals, never blended without conversion ---

test('brokerCurrency: Kraken is GBP, everything else is USD', () => {
  assert.strictEqual(brokerCurrency('kraken'), 'GBP');
  assert.strictEqual(brokerCurrency('Kraken'), 'GBP');
  assert.strictEqual(brokerCurrency('alpaca'), 'USD');
  assert.strictEqual(brokerCurrency(null), 'USD');
});

test('sumBrokerFieldByCurrency: groups by real currency instead of blending Alpaca (USD) and Kraken (GBP) into one number', () => {
  const brokers = [
    { broker: 'alpaca', portfolio_value: 65000 },
    { broker: 'kraken', portfolio_value: 30000 },
  ];
  assert.deepStrictEqual(sumBrokerFieldByCurrency(brokers, 'portfolio_value'), { USD: 65000, GBP: 30000 });
});

test('sumBrokerFieldByCurrency: multiple brokers of the same currency are summed together within that currency', () => {
  const brokers = [
    { broker: 'alpaca', todays_pnl: 100 },
    { broker: 'alpaca-secondary', todays_pnl: 50 },
    { broker: 'kraken', todays_pnl: -20 },
  ];
  assert.deepStrictEqual(sumBrokerFieldByCurrency(brokers, 'todays_pnl'), { USD: 150, GBP: -20 });
});

test('sumBrokerFieldByCurrency: a broker with no real evidence for the field is excluded, never a fabricated zero', () => {
  assert.deepStrictEqual(sumBrokerFieldByCurrency([{ broker: 'kraken', portfolio_value: null }], 'portfolio_value'), {});
});

test('unrealizedPnlByCurrency: the same real per-broker unrealised P&L, grouped by currency', () => {
  const positions = [
    { symbol: 'AAPL', broker: 'alpaca', unrealized_pl: 40 },
    { symbol: 'XBT', broker: 'kraken', unrealized_pl: -10 },
  ];
  assert.deepStrictEqual(unrealizedPnlByCurrency(positions), { USD: 40, GBP: -10 });
});

test('realizedPnlByCurrencyToday: the same real per-broker realised P&L today, grouped by currency', () => {
  const today = new Date().toISOString();
  const trades = [
    { status: 'closed', closed_at: today, profit_loss: 12, broker: 'alpaca' },
    { status: 'closed', closed_at: today, profit_loss: -6, broker: 'kraken' },
  ];
  assert.deepStrictEqual(realizedPnlByCurrencyToday(trades), { USD: 12, GBP: -6 });
});

// --- AT-ED-017 Part 3: realised vs unrealised, by broker ---

test('unrealizedPnlByBroker: sums real unrealized_pl grouped by the broker tag production_evidence.py attaches', () => {
  const positions = [
    { symbol: 'AAA', broker: 'alpaca', unrealized_pl: 10 },
    { symbol: 'BBB', broker: 'alpaca', unrealized_pl: 5 },
    { symbol: 'XBT', broker: 'kraken', unrealized_pl: -3 },
  ];
  assert.deepStrictEqual(unrealizedPnlByBroker(positions), { alpaca: 15, kraken: -3 });
});

test('unrealizedPnlByBroker: positions missing a broker or a finite unrealized_pl are excluded, never counted as zero', () => {
  const positions = [{ symbol: 'AAA', unrealized_pl: 10 }, { symbol: 'BBB', broker: 'alpaca', unrealized_pl: null }];
  assert.deepStrictEqual(unrealizedPnlByBroker(positions), {});
});

test('totalUnrealizedPnl: sums across all brokers; no evidence returns null, never a fabricated zero', () => {
  assert.strictEqual(totalUnrealizedPnl([{ broker: 'alpaca', unrealized_pl: 10 }, { broker: 'kraken', unrealized_pl: -4 }]), 6);
  assert.strictEqual(totalUnrealizedPnl([]), null);
});

const TODAY_ISO = new Date().toISOString();
const NOT_TODAY_ISO = '2020-01-01T00:00:00Z';

test('closedTradesToday: only counts terminal-status trades with a closed_at/created_at falling on today (UTC)', () => {
  const trades = [
    { status: 'closed', closed_at: TODAY_ISO, profit_loss: 12, broker: 'alpaca' },
    { status: 'stop_exit', closed_at: NOT_TODAY_ISO, profit_loss: 5, broker: 'alpaca' },
    { status: 'open', closed_at: TODAY_ISO, profit_loss: 1, broker: 'alpaca' },
  ];
  const result = closedTradesToday(trades);
  assert.strictEqual(result.length, 1);
  assert.strictEqual(result[0].profit_loss, 12);
});

test('realizedPnlToday: sums real profit_loss from trades that closed today only', () => {
  const trades = [
    { status: 'closed', closed_at: TODAY_ISO, profit_loss: 12, broker: 'alpaca' },
    { status: 'target_exit', closed_at: TODAY_ISO, profit_loss: -4, broker: 'kraken' },
    { status: 'closed', closed_at: NOT_TODAY_ISO, profit_loss: 999, broker: 'alpaca' },
  ];
  assert.strictEqual(realizedPnlToday(trades), 8);
});

test('realizedPnlToday: nothing closed today returns null, never a fabricated zero', () => {
  assert.strictEqual(realizedPnlToday([{ status: 'closed', closed_at: NOT_TODAY_ISO, profit_loss: 12, broker: 'alpaca' }]), null);
  assert.strictEqual(realizedPnlToday([]), null);
});

test('realizedPnlToday: a closed trade with a genuinely missing profit_loss is never counted as a real zero', () => {
  assert.strictEqual(realizedPnlToday([{ status: 'closed', closed_at: TODAY_ISO, profit_loss: null, broker: 'alpaca' }]), null);
});

test('realizedPnlByBrokerToday: groups today\'s realised profit by broker', () => {
  const trades = [
    { status: 'closed', closed_at: TODAY_ISO, profit_loss: 12, broker: 'alpaca' },
    { status: 'closed', closed_at: TODAY_ISO, profit_loss: 3, broker: 'alpaca' },
    { status: 'manual_exit', closed_at: TODAY_ISO, profit_loss: -6, broker: 'kraken' },
  ];
  assert.deepStrictEqual(realizedPnlByBrokerToday(trades), { alpaca: 15, kraken: -6 });
});

test('exitsTodayCount: counts real closed positions today, zero when genuinely none', () => {
  assert.strictEqual(exitsTodayCount([{ status: 'closed', closed_at: TODAY_ISO, profit_loss: 1, broker: 'alpaca' }]), 1);
  assert.strictEqual(exitsTodayCount([]), 0);
});

test('exitsTodayCountByCurrency (AT-ED-017 Founder request): counts closed positions today, grouped by currency', () => {
  const trades = [
    { status: 'closed', closed_at: TODAY_ISO, profit_loss: 1, broker: 'alpaca' },
    { status: 'closed', closed_at: TODAY_ISO, profit_loss: 2, broker: 'alpaca' },
    { status: 'closed', closed_at: TODAY_ISO, profit_loss: -1, broker: 'kraken' },
  ];
  assert.deepStrictEqual(exitsTodayCountByCurrency(trades), { USD: 2, GBP: 1 });
});

test('openPositionsCountByCurrency: counts open positions grouped by currency', () => {
  const positions = [
    { symbol: 'AAPL', broker: 'alpaca' },
    { symbol: 'MSFT', broker: 'alpaca' },
    { symbol: 'XBT', broker: 'kraken' },
  ];
  assert.deepStrictEqual(openPositionsCountByCurrency(positions), { USD: 2, GBP: 1 });
});

console.log(`\n${passed} passed`);
if (process.exitCode) {
  console.error('Some portfolioPosition tests failed.');
}
