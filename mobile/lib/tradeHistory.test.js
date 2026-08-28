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
  tradeTableRow,
  commissionExplanation,
  formatQuantity,
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

// --- tradeTableRow ---------------------------------------------------------------------
// 2026-08-21 Founder request: Trade History rebuilt as a real column table instead of a
// sentence per trade.

test('tradeTableRow: a closed Kraken trade reports its real symbol, side, price, and P&L in GBP', () => {
  const row = tradeTableRow({
    broker: 'kraken', symbol: 'XETHZGBP', side: 'sell', status: 'closed',
    quantity: 0.00119506, exit_price: 1741.54, profit_loss: 0.48, closed_at: '2026-08-21T07:49:34Z',
  });
  assert.strictEqual(row.symbol, 'XETHZGBP');
  assert.strictEqual(row.side, 'SELL');
  assert.strictEqual(row.priceText, '£1,741.54');
  assert.strictEqual(row.pnlText, '£0.48');
  assert.strictEqual(row.pnlSign, 'positive');
});

test('tradeTableRow: a loss reports pnlSign negative', () => {
  const row = tradeTableRow({
    broker: 'alpaca', symbol: 'AAPL', side: 'sell', status: 'closed',
    quantity: 10, exit_price: 100, profit_loss: -5, closed_at: '2026-08-21T07:49:34Z',
  });
  assert.strictEqual(row.pnlSign, 'negative');
  assert.strictEqual(row.pnlText, '-$5');
});

test('tradeTableRow: an open/unsold position shows the entry price, and P&L reads Unsold rather than blank or a fabricated zero', () => {
  const row = tradeTableRow({
    broker: 'alpaca', symbol: 'MSFT', side: 'buy', status: 'filled',
    quantity: 5, entry_price: 300, closed_at: null,
  });
  assert.strictEqual(row.priceText, '$300');
  assert.strictEqual(row.pnlText, 'Unsold');
  assert.strictEqual(row.pnlSign, 'neutral');
});

test('tradeTableRow: a bare broker_trade row with no symbol/side reports Not available for both rather than blank', () => {
  const row = tradeTableRow({ broker: 'kraken', status: 'closed', quantity: 0.00119506, price: 1741.53, closed_at: '2026-08-21T07:56:00Z' });
  assert.ok(row.symbol.startsWith('Not available'));
  assert.ok(row.side.startsWith('Not available'));
});

// 2026-08-21 Founder request: two more columns - commission % and commission amount.
// commissionPct uses the exact same per-leg formula as the backend's own measured fee rate
// (trade_scorecard.py's estimate_round_trip_fee_pct: fee / abs(quantity * price)).

test("tradeTableRow: commission % and commission amount are computed from the row's real fee, quantity, and price", () => {
  const row = tradeTableRow({
    broker: 'alpaca', symbol: 'AAPL', side: 'sell', status: 'closed',
    quantity: 10, exit_price: 100, profit_loss: 45, fee: 8, closed_at: '2026-08-21T07:49:34Z',
  });
  assert.strictEqual(row.commissionPctText, '0.80%');
  assert.strictEqual(row.commissionText, '$8');
});

test('tradeTableRow: a Kraken trade reports its commission amount in GBP, matching the price/P&L columns', () => {
  const row = tradeTableRow({
    broker: 'kraken', symbol: 'XETHZGBP', side: 'sell', status: 'closed',
    quantity: 0.00119506, exit_price: 1741.54, profit_loss: 0.48, fee: 0.02, closed_at: '2026-08-21T07:49:34Z',
  });
  assert.strictEqual(row.commissionText, '£0.02');
});

test('tradeTableRow: a missing fee shows a compact dash in both commission columns, never a fabricated zero', () => {
  // 2026-08-23 Founder-reported: these previously carried notAvailable()'s full sentence,
  // which React Native shrank to unreadable text inside a column a few characters wide
  // ("very small text instead of any values"). The dash keeps the cell legible; the full
  // explanation is still one tap away in TradeDetail. What must NOT happen is a 0 that
  // reads as "this trade was free".
  //
  // 2026-08-27: this case used to use Alpaca purely as a stand-in for "some broker with no
  // fee on the row". Alpaca no longer fits, because its fee is now known rather than missing --
  // checked against the live API, it charges no per-trade commission on US equities, so a
  // genuine 0.00 is the honest answer there. The rule this test exists for is unchanged and
  // still enforced, using a broker whose fee really is unrecorded.
  const row = tradeTableRow({
    broker: 'coinbase', symbol: 'BTC', side: 'sell', status: 'closed',
    quantity: 10, exit_price: 100, profit_loss: 45, closed_at: '2026-08-21T07:49:34Z',
  });
  assert.strictEqual(row.commissionPctText, '-');
  assert.strictEqual(row.commissionText, '-');
  assert.ok(!row.commissionText.includes('0'), 'a missing fee must never render as a zero amount');
  assert.ok(row.commissionPctText.length < 4, 'must stay short enough to render in a narrow column');
});

test('tradeTableRow: reports the amount actually committed to the trade', () => {
  // 2026-08-23 Founder request: "this table should also show the amount put forward to
  // trade for each". Price alone hid the difference between a GBP 2 and a GBP 25 position
  // -- the exact sizing problem that took three separate fixes to find this weekend.
  const row = tradeTableRow({
    broker: 'kraken', symbol: 'LINK', side: 'buy', status: 'holding',
    quantity: 2.96912, entry_price: 8.42, opened_at: '2026-08-23T17:51:00Z',
  });
  assert.strictEqual(row.amountText, '£25', "qty x price, in the broker currency");
});

test('tradeTableRow: an unknown amount is a dash, never a fabricated zero', () => {
  const row = tradeTableRow({ broker: 'kraken', symbol: 'BCH', side: 'buy', status: 'holding' });
  assert.strictEqual(row.amountText, '-');
});

test('tradeTableRow: a real fee with no usable quantity/price still reports the fee amount but not a fabricated percentage', () => {
  const row = tradeTableRow({ broker: 'kraken', status: 'closed', fee: 0.02, closed_at: '2026-08-21T07:56:00Z' });
  // The dash replaced the long sentence here too (2026-08-23) -- the point of the test is
  // unchanged: a real fee is still shown, and the percentage is NOT invented from nothing.
  assert.strictEqual(row.commissionPctText, '-');
  assert.strictEqual(row.commissionText, '£0.02');
});

console.log(`\n${passed} passed`);

// 2026-08-27 Founder-reported: the Portfolio card said "Completed today 19" while the Briefing
// said 13 and the day's real answer was 6. A broker records one row per order EVENT, so the
// same completed trade arrives several times and counting rows counted paperwork. Mirrors
// src/ai_trader/trade_counting.py, which applies the same rule server-side.
test('completedTradesToday counts distinct orders, not the several event rows each one produces', () => {
  const today = new Date().toISOString();
  const closedRow = (orderId, symbol) => ({
    broker: 'alpaca', broker_order_id: orderId, symbol, side: 'sell',
    status: 'closed', closed_at: today, exit_price: 90, price: 90, quantity: 2, profit_loss: 4,
  });
  const trades = [
    closedRow('nee-exit', 'NEE'),
    closedRow('nee-exit', 'NEE'),
    closedRow('nee-exit', 'NEE'),
    closedRow('mlm-exit', 'MLM'),
    closedRow('mlm-exit', 'MLM'),
  ];
  const summary = tradeHistorySummary({ brokers: [] }, trades, 'all');
  assert.strictEqual(summary.completedTradesToday, 2, 'five event rows describe two real orders');
});

test('a completed row carrying no order id is still counted once rather than dropped', () => {
  // Under-reporting the Founder's real activity would be worse than counting one row twice.
  const today = new Date().toISOString();
  const bare = (symbol) => ({
    broker: 'alpaca', symbol, side: 'sell', status: 'closed',
    closed_at: today, exit_price: 5, price: 5, quantity: 1, profit_loss: 1,
  });
  const summary = tradeHistorySummary({ brokers: [] }, [bare('AAA'), bare('BBB')], 'all');
  assert.strictEqual(summary.completedTradesToday, 2);
});

// 2026-08-27 Founder-reported: "blank spaces in the trade history card where the commission
// for maker and taker should sit." Every Alpaca row showed a dash.
//
// Verified against the live Alpaca API rather than assumed: a FILL activity carries no
// commission field at all, because Alpaca charges no per-trade commission on US equities. A
// dash means "we do not know", which was the wrong answer to a question that has a real one --
// and it hid a genuine advantage Alpaca has over Kraken's 0.80% per side.
test('a commission-free broker shows a real zero, not a dash that means unknown', () => {
  const row = tradeTableRow({
    broker: 'alpaca', symbol: 'NEE', side: 'sell', status: 'closed',
    price: 82.87, position_size: 21, exit_price: 82.87, profit_loss: -18.69,
    closed_at: '2026-08-27T14:37:00Z',
  });
  assert.strictEqual(row.commissionPctText, '0.00%');
  assert.notStrictEqual(row.commissionText, '-');
  assert.ok(/0/.test(row.commissionText), `expected a zero amount, got ${row.commissionText}`);
});

test('Kraken keeps its real fee and is never zeroed', () => {
  // Kraken charges a genuine 0.40%/0.80% maker/taker fee. Showing zero there would be a lie
  // about money, which is why the commission-free list is an explicit allow-list.
  const row = tradeTableRow({
    broker: 'kraken', symbol: 'XRPGBP', side: 'buy', status: 'filled',
    price: 0.75, position_size: 2.65, fee: 0.02, opened_at: '2026-08-27T00:05:00Z',
  });
  assert.ok(row.commissionText.includes('0.02'), row.commissionText);
  assert.notStrictEqual(row.commissionPctText, '0.00%');
});

test('an unknown broker with no fee still shows a dash rather than inventing a zero', () => {
  const row = tradeTableRow({
    broker: 'coinbase', symbol: 'BTC', side: 'buy', status: 'filled',
    price: 100, position_size: 1, opened_at: '2026-08-27T00:05:00Z',
  });
  assert.strictEqual(row.commissionText, '-');
  assert.strictEqual(row.commissionPctText, '-');
});

test('the detail view explains a zero commission instead of leaving it bare', () => {
  const text = commissionExplanation(normalizeTradeRow({ broker: 'alpaca', symbol: 'NEE', side: 'sell' }));
  assert.ok(/no per-trade commission/i.test(text), text);
  assert.ok(/regulatory/i.test(text), 'must still disclose the fees Alpaca does charge');
});

test('the detail view reports a real fee plainly, with no explanation needed', () => {
  const text = commissionExplanation(normalizeTradeRow({ broker: 'kraken', symbol: 'XRPGBP', side: 'buy', fee: 0.02 }));
  assert.ok(text.includes('0.02'), text);
  assert.ok(!/no per-trade commission/i.test(text));
});

// 2026-08-28 Founder-reported: "a number of sales today... but no figures on what the profit or
// losses for some of the sales." Today's TWO real sells rendered as TEN rows, and only two
// carried a P&L. A broker files one row per order EVENT and the realised P&L lands on the
// terminal one: SCCO arrived as partial_fill (x3), fill, filled and canceled, with -69.14 on
// the 'filled' row alone. The five siblings showed as separate sales with an empty P&L column,
// which reads as missing data rather than as one sale reported six times.
function sccoEventRows() {
  const mk = (status, quantity, price, realized_pnl) => ({
    broker: 'alpaca', broker_order_id: 'scco-sell-1', symbol: 'SCCO', side: 'sell',
    status, quantity, price, realized_pnl, exit_price: price,
    closed_at: '2026-08-28T14:07:00Z', created_at: '2026-08-28T14:07:00Z', event_type: 'broker_trade',
  });
  return [
    mk('partial_fill', 1, 211.32, null),
    mk('partial_fill', 1, 211.32, null),
    mk('partial_fill', 10, 211.32, null),
    mk('fill', 1, 211.21, null),
    mk('filled', 13, 211.31, -69.14),
    mk('canceled', 13, null, null),
  ];
}

test('one order reported over many events collapses to a single row', () => {
  const status = { brokers: [{ broker: 'alpaca', trade_history: sccoEventRows() }] };
  const out = combinedTransactions(status, {}, 'all', [], 50);
  assert.strictEqual(out.length, 1, `six event rows describe one sale, got ${out.length}`);
});

test('the surviving row keeps the realised P&L rather than an empty partial fill', () => {
  const status = { brokers: [{ broker: 'alpaca', trade_history: sccoEventRows() }] };
  const row = tradeTableRow(combinedTransactions(status, {}, 'all', [], 50)[0]);
  assert.ok(row.pnlText.includes('69.14'), `expected the -69.14 loss, got ${row.pnlText}`);
  assert.strictEqual(row.pnlSign, 'negative');
});

test('quantity differences within one order no longer prevent the merge', () => {
  // The old heuristic matched on quantity, and these partials were 1, 1, 10 and 13 of the
  // same order, so it could never collapse them. The broker order id says what belongs together.
  const rows = sccoEventRows();
  const quantities = new Set(rows.map((r) => r.quantity));
  assert.ok(quantities.size > 1, 'this case is only meaningful with differing quantities');
  const status = { brokers: [{ broker: 'alpaca', trade_history: rows }] };
  assert.strictEqual(combinedTransactions(status, {}, 'all', [], 50).length, 1);
});

test('two genuinely different orders stay as two rows', () => {
  const rows = [
    ...sccoEventRows(),
    { broker: 'alpaca', broker_order_id: 'nee-sell-1', symbol: 'NEE', side: 'sell', status: 'filled',
      quantity: 6, price: 82.04, realized_pnl: -10.3, exit_price: 82.04,
      closed_at: '2026-08-28T13:33:00Z', created_at: '2026-08-28T13:33:00Z', event_type: 'broker_trade' },
  ];
  const status = { brokers: [{ broker: 'alpaca', trade_history: rows }] };
  const out = combinedTransactions(status, {}, 'all', [], 50);
  assert.strictEqual(out.length, 2);
});

test('rows carrying no order id still fall back to the old heuristic', () => {
  const bare = (symbol) => ({
    broker: 'kraken', symbol, side: 'buy', status: 'filled', quantity: 1, price: 100,
    created_at: '2026-08-28T10:00:00Z', event_type: 'broker_trade',
  });
  const status = { brokers: [{ broker: 'kraken', trade_history: [bare('AAA'), bare('BBB')] }] };
  assert.strictEqual(combinedTransactions(status, {}, 'all', [], 50).length, 2);
});

// 2026-08-27 Founder-reported: a Kraken position rendered as "5e-8". JavaScript switches to
// exponent notation below 1e-6, and crypto quantities routinely go that small -- 0.00000005 of
// a coin is a real holding, but "5e-8" is not a number a person reads.
test('a tiny crypto quantity renders in full rather than as exponent notation', () => {
  assert.strictEqual(formatQuantity(5e-8), '0.00000005');
  assert.ok(!String(formatQuantity(5e-8)).includes('e'));
});

test('ordinary quantities are left exactly as they read today', () => {
  assert.strictEqual(formatQuantity(13), '13');
  assert.strictEqual(formatQuantity(2.5), '2.5');
  assert.strictEqual(formatQuantity(0.673242), '0.673242');
});

test('zero and unusable quantities do not become misleading numbers', () => {
  assert.strictEqual(formatQuantity(0), '0');
  assert.strictEqual(formatQuantity(null), null);
  assert.strictEqual(formatQuantity('not a number'), 'not a number');
});
