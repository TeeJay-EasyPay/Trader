// Plain Node assert-based tests for tradeHistory.js - run with `node mobile/lib/tradeHistory.test.js`.

'use strict';

const assert = require('assert');
const {
  combinedTransactions,
  describeLatestTrade,
  describeTransaction,
  normalizeTradeRow,
  isOpenTrade,
  unavailableReason,
  firstValue,
  firstNumber,
  numeric,
  isBuy,
  isSell,
  terminalTradeStatus,
  isToday,
  formatDuration,
  formatHoldingDuration,
  tradeHistoryBrokers,
  titleCaseBroker,
  tradeHistorySummary,
  tradeKey,
  friendlyEvent,
  dedupeTransactions,
  sameTrade,
  transactionRank,
} = require('./tradeHistory');

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

test('firstValue: returns the first defined, non-empty value', () => {
  assert.strictEqual(firstValue(undefined, null, '', 'x', 'y'), 'x');
});

test('firstNumber: returns the first value that parses as a number', () => {
  assert.strictEqual(firstNumber('abc', null, '5.5', 10), 5.5);
});

test('numeric: strips currency symbols and commas', () => {
  assert.strictEqual(numeric('$1,234'), 1234);
  assert.strictEqual(numeric('£50'), 50);
  assert.strictEqual(numeric(''), null);
});

test('isBuy / isSell: case-insensitive side matching', () => {
  assert.strictEqual(isBuy('BUY'), true);
  assert.strictEqual(isSell('sell'), true);
  assert.strictEqual(isBuy('sell'), false);
});

test('terminalTradeStatus: closed/sold/cancelled are terminal, open is not', () => {
  assert.strictEqual(terminalTradeStatus('closed'), true);
  assert.strictEqual(terminalTradeStatus('open'), false);
});

test('isToday: matches the current calendar date, not a rolling 24h window', () => {
  assert.strictEqual(isToday(new Date().toISOString()), true);
  assert.strictEqual(isToday('2020-01-01T00:00:00Z'), false);
});

test('formatDuration: renders minutes, hours, or days depending on span', () => {
  const start = '2026-01-01T00:00:00Z';
  assert.strictEqual(formatDuration(start, '2026-01-01T00:30:00Z'), '30 min');
  assert.strictEqual(formatDuration(start, '2026-01-01T05:00:00Z'), '5.0 hours');
  assert.strictEqual(formatDuration(start, '2026-01-05T00:00:00Z'), '4.0 days');
});

test('formatDuration: an end before start returns null rather than a negative duration', () => {
  assert.strictEqual(formatDuration('2026-01-02T00:00:00Z', '2026-01-01T00:00:00Z'), null);
});

test('formatHoldingDuration: an open position measures against now, appending "so far"', () => {
  const start = new Date(Date.now() - 30 * 60000).toISOString();
  const result = formatHoldingDuration(start, null, true);
  assert.ok(result.endsWith('so far'));
});

test('titleCaseBroker: capitalises and replaces underscores; empty input reads Unknown', () => {
  assert.strictEqual(titleCaseBroker('alpaca_paper'), 'Alpaca paper');
  assert.strictEqual(titleCaseBroker(''), 'Unknown');
});

test('normalizeTradeRow: prefers top-level fields, falling back to the raw broker payload', () => {
  const row = normalizeTradeRow({
    broker: 'alpaca',
    side: 'buy',
    status: 'filled',
    price: 100,
    quantity: 5,
    symbol: 'AAPL',
  });
  assert.strictEqual(row.broker, 'Alpaca');
  assert.strictEqual(row.side, 'buy');
  assert.strictEqual(row.entryPrice, 100);
  assert.strictEqual(row.quantity, 5);
});

test('normalizeTradeRow: falls back to the parsed payload_json when no top-level fields exist', () => {
  const row = normalizeTradeRow({ payload_json: JSON.stringify({ side: 'sell', price: 42, symbol: 'MSFT' }) });
  assert.strictEqual(row.side, 'sell');
  assert.strictEqual(row.exitPrice, 42);
  assert.strictEqual(row.symbol, 'MSFT');
});

test('isOpenTrade: an unclosed managed exit is open', () => {
  assert.strictEqual(isOpenTrade({ managedExitId: 1, closedAt: null }), true);
});

test('isOpenTrade: a filled buy with no exit price or close date is open', () => {
  assert.strictEqual(isOpenTrade({ side: 'buy', status: 'filled', closedAt: null, exitPrice: null }), true);
});

test('isOpenTrade: a closed trade with an exit price is not open', () => {
  assert.strictEqual(isOpenTrade({ side: 'buy', status: 'closed', exitPrice: 100 }), false);
});

test('unavailableReason: a managed-exit row explains fields are not recorded yet', () => {
  assert.strictEqual(unavailableReason({ managedExitId: 1 }, 'target'), 'Not recorded yet');
});

test('unavailableReason: exitReason on an open trade reads Unsold, not a generic error', () => {
  assert.strictEqual(unavailableReason({ status: 'open' }, 'exitReason'), 'Unsold');
});

test('describeTransaction: composes a readable one-line summary from a raw broker row', () => {
  const text = describeTransaction({
    event_type: 'broker_fill',
    broker: 'alpaca',
    side: 'buy',
    symbol: 'AAPL',
    position_size: 10,
    price: 150,
    status: 'filled',
  });
  assert.ok(text.startsWith('Broker fill BUY AAPL for 10'));
});

test('describeLatestTrade: a plain string value is passed through unchanged', () => {
  assert.strictEqual(describeLatestTrade('Not available'), 'Not available');
});

test('describeLatestTrade: a fill object is described as a broker_fill transaction', () => {
  const text = describeLatestTrade({ type: 'fill', symbol: 'AAPL', side: 'buy', qty: 1, price: 100, status: 'filled' });
  assert.ok(text.includes('Broker fill'));
});

test('tradeKey: prefers a stable identifier, falling back to a composite key', () => {
  assert.strictEqual(tradeKey({ attribution_id: 'abc' }, 0), 'abc');
  assert.strictEqual(tradeKey({ created_at: '2026-01-01', symbol: 'AAPL' }, 2), '2026-01-01-AAPL-2');
});

test('friendlyEvent: known event types map to plain-English labels', () => {
  assert.strictEqual(friendlyEvent('broker_fill'), 'Broker fill');
});

test('friendlyEvent: unknown event types fall back to the Not-available convention', () => {
  assert.strictEqual(friendlyEvent('mystery_event'), 'mystery_event');
});

test('tradeHistoryBrokers: builds an "All" plus deduped, title-cased broker list', () => {
  const status = { brokers: [{ broker: 'alpaca' }, { broker: 'kraken' }, { label: 'alpaca' }] };
  assert.deepStrictEqual(tradeHistoryBrokers(status), ['All', 'Alpaca', 'Kraken']);
});

test('tradeHistorySummary: sums today\'s realised P&L only from today\'s terminal, closed trades', () => {
  const trades = [
    { broker: 'alpaca', side: 'buy', status: 'closed', closed_at: new Date().toISOString(), profit_loss: 50, exit_price: 1 },
    { broker: 'alpaca', side: 'buy', status: 'open', profit_loss: 999 },
  ];
  const summary = tradeHistorySummary({ brokers: [] }, trades, 'All');
  assert.deepStrictEqual(summary.dailyPnlByCurrency, { USD: 50 });
  assert.strictEqual(summary.completedTradesToday, 1);
});

// 2026-08-21 Founder-reported bug: filtered to Kraken, "Daily P&L" read "$0.48" for a real GBP
// trade - a plain dollar sign wearing a pound figure, the same currency-blending bug class
// AT-ED-017 already fixed elsewhere on Current Position.
test('tradeHistorySummary: a Kraken-only realised gain reports under GBP, never USD', () => {
  const trades = [
    { broker: 'kraken', side: 'sell', status: 'closed', closed_at: new Date().toISOString(), profit_loss: 0.48, exit_price: 1741.54 },
  ];
  const summary = tradeHistorySummary({ brokers: [] }, trades, 'Kraken');
  assert.deepStrictEqual(summary.dailyPnlByCurrency, { GBP: 0.48 });
});

test('tradeHistorySummary: "All" keeps Alpaca and Kraken realised gains as two honest per-currency totals, never blended', () => {
  const trades = [
    { broker: 'alpaca', side: 'sell', status: 'closed', closed_at: new Date().toISOString(), profit_loss: 10, exit_price: 1 },
    { broker: 'kraken', side: 'sell', status: 'closed', closed_at: new Date().toISOString(), profit_loss: 0.48, exit_price: 1741.54 },
  ];
  const summary = tradeHistorySummary({ brokers: [] }, trades, 'All');
  assert.deepStrictEqual(summary.dailyPnlByCurrency, { USD: 10, GBP: 0.48 });
});

test('tradeHistorySummary: falls back to each currency\'s own broker-reported day P&L independently when that currency has no realised evidence today', () => {
  const trades = [
    { broker: 'alpaca', side: 'sell', status: 'closed', closed_at: new Date().toISOString(), profit_loss: 10, exit_price: 1 },
  ];
  const brokers = [{ broker: 'alpaca', todays_pnl: 10 }, { broker: 'kraken', todays_pnl: 3.17 }];
  const summary = tradeHistorySummary({ brokers }, trades, 'All');
  // Alpaca has real realised evidence today (10) so that wins over its own broker snapshot;
  // Kraken has none today, so it falls back to its own broker-reported day P&L - never to
  // Alpaca's evidence, and never left out entirely.
  assert.deepStrictEqual(summary.dailyPnlByCurrency, { USD: 10, GBP: 3.17 });
});

// --- dedupeTransactions / sameTrade / transactionRank -------------------------------------
// 2026-08-21 Founder-reported bug: one real Kraken ETH sell rendered as THREE separate Trade
// History rows - a bare BROKER_TRADE_HISTORY "closed" tracking row with no symbol, a fuller
// "filled" BROKER_TRADE_HISTORY row, and the reconciled performance-attribution row for the
// same fill. This also silently double-counted "Completed Trades Today" (both "closed"-status
// rows passed the terminal-status filter).

function ethClosedAttributionRow() {
  return {
    event_type: 'performance_attribution',
    broker: 'Kraken',
    symbol: 'XETHZGBP',
    side: 'sell',
    status: 'closed',
    quantity: 0.00119506,
    exit_price: 1741.54,
    profit_loss: 0.48,
    created_at: '2026-08-21T07:49:34Z',
  };
}

function ethFilledBrokerTradeRow() {
  return {
    event_type: 'broker_trade',
    broker: 'Kraken',
    symbol: 'XETHZGBP',
    side: 'sell',
    status: 'filled',
    quantity: 0.00119506,
    price: 1741.54,
    profit_loss: 0.48,
    created_at: '2026-08-21T07:49:34Z',
  };
}

function ethBareClosedBrokerTradeRow() {
  // The bare tracking row genuinely has no symbol/side in production - only quantity/price/time.
  return {
    event_type: 'broker_trade',
    broker: 'Kraken',
    status: 'closed',
    quantity: 0.00119506,
    price: 1741.53,
    created_at: '2026-08-21T07:56:00Z',
  };
}

test('transactionRank: reconciled performance_attribution outranks a raw broker row, which outranks a bare symbol-less row', () => {
  assert.ok(transactionRank(ethClosedAttributionRow()) > transactionRank(ethFilledBrokerTradeRow()));
  assert.ok(transactionRank(ethFilledBrokerTradeRow()) > transactionRank(ethBareClosedBrokerTradeRow()));
});

test('sameTrade: the same broker/quantity/price within the time window matches even when one row has no symbol', () => {
  assert.strictEqual(sameTrade(ethFilledBrokerTradeRow(), ethBareClosedBrokerTradeRow()), true);
  assert.strictEqual(sameTrade(ethClosedAttributionRow(), ethFilledBrokerTradeRow()), true);
});

test('sameTrade: two rows with the same quantity/price but different real symbols never match', () => {
  const a = { ...ethFilledBrokerTradeRow(), symbol: 'XETHZGBP' };
  const b = { ...ethFilledBrokerTradeRow(), symbol: 'XXBTZGBP' };
  assert.strictEqual(sameTrade(a, b), false);
});

test('sameTrade: rows more than 30 minutes apart never match, even with identical quantity/price', () => {
  const a = ethFilledBrokerTradeRow();
  const b = { ...ethBareClosedBrokerTradeRow(), created_at: '2026-08-21T09:00:00Z' };
  assert.strictEqual(sameTrade(a, b), false);
});

test('sameTrade: event types outside the dedupable set (e.g. managed_open_trade) are never matched', () => {
  const managed = { ...ethFilledBrokerTradeRow(), event_type: 'managed_open_trade' };
  assert.strictEqual(sameTrade(managed, ethFilledBrokerTradeRow()), false);
});

test('dedupeTransactions: collapses the real three-row ETH case into one, keeping the reconciled attribution row', () => {
  const result = dedupeTransactions([ethBareClosedBrokerTradeRow(), ethClosedAttributionRow(), ethFilledBrokerTradeRow()]);
  assert.strictEqual(result.length, 1);
  assert.strictEqual(result[0].event_type, 'performance_attribution');
});

test('dedupeTransactions: two genuinely different trades are both kept', () => {
  const btc = { ...ethFilledBrokerTradeRow(), symbol: 'XXBTZGBP', quantity: 0.00005, price: 52258.3 };
  const result = dedupeTransactions([ethFilledBrokerTradeRow(), btc]);
  assert.strictEqual(result.length, 2);
});

test('combinedTransactions: the same trade reaching combinedTransactions via both broker_trade rows and performance_attribution renders as one row, not three', () => {
  const status = {
    brokers: [{
      broker: 'kraken',
      trade_history: [
        { symbol: 'XETHZGBP', side: 'sell', status: 'filled', quantity: 0.00119506, price: 1741.54, profit_loss: 0.48, closed_at: '2026-08-21T07:49:34Z' },
        { status: 'closed', quantity: 0.00119506, price: 1741.53, closed_at: '2026-08-21T07:56:00Z' },
      ],
    }],
  };
  const attribution = [{ broker: 'kraken', symbol: 'XETHZGBP', side: 'sell', quantity: 0.00119506, exit_price: 1741.54, profit_loss: 0.48, closed_at: '2026-08-21T07:49:34Z' }];
  const result = combinedTransactions(status, null, 'Kraken', attribution, 20);
  assert.strictEqual(result.length, 1);
  assert.strictEqual(result[0].event_type, 'performance_attribution');
});

test('combinedTransactions: filters by the selected exchange and sorts newest-first', () => {
  const status = {
    brokers: [
      { broker: 'alpaca', trade_history: [{ symbol: 'AAPL', closed_at: '2026-01-02T00:00:00Z' }] },
      { broker: 'kraken', trade_history: [{ symbol: 'BTC', closed_at: '2026-01-03T00:00:00Z' }] },
    ],
  };
  const all = combinedTransactions(status, null, 'All', [], 20);
  assert.strictEqual(all.length, 2);
  assert.strictEqual(all[0].symbol, 'BTC');

  const alpacaOnly = combinedTransactions(status, null, 'Alpaca', [], 20);
  assert.strictEqual(alpacaOnly.length, 1);
  assert.strictEqual(alpacaOnly[0].symbol, 'AAPL');
});

console.log(`\n${passed} passed`);
