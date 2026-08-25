'use strict';

const assert = require('assert');
const { brokerStandingBlock, brokerStandingBlocks, safeNumber } = require('./brokerStanding');

let passed = 0;
function test(name, fn) {
  fn();
  console.log(`ok - ${name}`);
  passed += 1;
}

const ALPACA = {
  broker: 'alpaca', portfolio_value: 101833.56, cash_available: 96287.7,
  todays_pnl: -40.72, week_pnl: -30.44, month_pnl: 807.56,
};
const KRAKEN = {
  broker: 'kraken', portfolio_value: 4546.72, cash_available: 521.66,
  todays_pnl: -26.38, week_pnl: 637.92, month_pnl: 858.5,
};
const POSITIONS = [
  { broker: 'alpaca', symbol: 'NEE', unrealized_pl: 4.42 },
  { broker: 'alpaca', symbol: 'FSLR', unrealized_pl: -15.49 },
  { broker: 'kraken', symbol: 'BCH', unrealized_pl: 2.1 },
];

test('each broker reports only its own money', () => {
  // The bug this replaces: "Portfolio value: $101,833.56 + £4,546.72" -- two unrelated
  // accounts in two currencies added on one line.
  const [alpaca, kraken] = brokerStandingBlocks([ALPACA, KRAKEN], { openPositions: POSITIONS });
  const value = (block, label) => block.rows.find((row) => row.label === label).amount;

  assert.strictEqual(value(alpaca, 'Portfolio value'), 101833.56);
  assert.strictEqual(value(kraken, 'Portfolio value'), 4546.72);
  assert.strictEqual(value(alpaca, 'This week (total change)'), -30.44);
  assert.strictEqual(value(kraken, 'This week (total change)'), 637.92);
});

test('open positions are counted per broker, not blended', () => {
  // The old card said "Open positions: 15", hiding that 13 were the Founder's own coins.
  const [alpaca, kraken] = brokerStandingBlocks([ALPACA, KRAKEN], { openPositions: POSITIONS });

  assert.strictEqual(alpaca.openPositions, 2);
  assert.strictEqual(kraken.openPositions, 1);
});

test('best and worst performers come from that broker alone', () => {
  const [alpaca] = brokerStandingBlocks([ALPACA, KRAKEN], { openPositions: POSITIONS });

  assert.strictEqual(alpaca.winner.symbol, 'NEE');
  assert.strictEqual(alpaca.loser.symbol, 'FSLR');
});

test('each block names its own currency so no figure is ambiguous', () => {
  const [alpaca, kraken] = brokerStandingBlocks([ALPACA, KRAKEN], {});

  assert.ok(alpaca.label.includes('$'), alpaca.label);
  assert.ok(kraken.label.includes('£'), kraken.label);
});

test('realised profit is attributed to the broker that earned it', () => {
  const today = new Date().toISOString();
  const trades = [
    { broker: 'alpaca', profit_loss: 12.5, closed_at: today, status: 'closed' },
    { broker: 'kraken', profit_loss: -0.8, closed_at: today, status: 'closed' },
  ];

  const [alpaca, kraken] = brokerStandingBlocks([ALPACA, KRAKEN], { trades });
  const realised = (block) => block.rows.find((row) => row.label === 'Realised today (closed trades only)').amount;

  assert.strictEqual(realised(alpaca), 12.5);
  assert.strictEqual(realised(kraken), -0.8);
});

test('a figure the broker did not report is absent, never a fabricated zero', () => {
  // "Flat today" and "we do not know yet" are different answers and must not look alike.
  const block = brokerStandingBlock({ broker: 'alpaca', portfolio_value: 100 }, {});
  const cash = block.rows.find((row) => row.label === 'Cash available');

  assert.strictEqual(cash.amount, null);
  assert.strictEqual(safeNumber(''), null);
  assert.strictEqual(safeNumber('not available'), null);
  assert.strictEqual(safeNumber(0), 0, 'a real zero is still a real number');
});

test('placeholder brokers with no account behind them are not shown', () => {
  const blocks = brokerStandingBlocks(
    [ALPACA, KRAKEN, { broker: 'coinbase' }, { broker: 'binance' }, { broker: 'interactive_brokers' }],
    {}
  );

  assert.deepStrictEqual(blocks.map((block) => block.broker), ['alpaca', 'kraken']);
});

console.log(`\n${passed} passed`);
