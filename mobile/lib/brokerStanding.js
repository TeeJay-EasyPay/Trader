// 2026-08-25, Founder-directed: "I don't like explanations combining Alpaca and Kraken
// together. I want to know what happened today with Alpaca, and then separately what happened
// today with Kraken."
//
// Every figure on the "Where We Stand" card used to be summed across both brokers and rendered
// through money.js's formatByCurrency, which joins currencies with a plus sign. The card read:
//
//   Portfolio value:            $101,833.56 + £4,546.72
//   This week (total change):   -$30.44 + £637.92
//   Cash available:             $96,287.70 + £521.66
//   Open positions:             15
//
// Two unrelated accounts, in two currencies, added together on one line. There is no decision
// anyone can make from "$101,833.56 + £4,546.72", and the blended position count hides the fact
// that 13 of those 15 are the Founder's own coins rather than anything this system opened. It
// made him open the app and then ask what it meant, which is the behaviour the screen exists to
// prevent.
//
// This builds one self-contained block per broker, every figure in that broker's own currency.
// Nothing is summed across brokers.

'use strict';

const { largestPosition, realizedPnlToday, realizedPnlThisMonth } = require('./portfolioPosition');

const BROKER_LABELS = {
  alpaca: 'Alpaca - US shares ($)',
  kraken: 'Kraken - crypto (£)',
};

// Only brokers the Founder actually trades. Others in the evidence (coinbase, binance,
// interactive_brokers) are placeholders with no account behind them, and an empty block for
// each is noise on the screen this change exists to quieten.
const SHOWN_BROKERS = ['alpaca', 'kraken'];

function brokerKey(broker) {
  return String(broker?.broker || broker || '').toLowerCase();
}

// A figure is shown only when it is a real number. A broker that reported nothing gets no line,
// never a fabricated zero -- matching portfolioPosition.js's existing convention, and the
// difference between "flat today" and "we don't know yet" matters to the Founder.
function safeNumber(raw) {
  if (raw === null || raw === undefined || raw === '') {
    return null;
  }
  const number = Number(raw);
  return Number.isFinite(number) ? number : null;
}

function brokerStandingBlock(broker, { openPositions = [], trades = [] } = {}) {
  const key = brokerKey(broker);
  const positions = openPositions.filter((position) => brokerKey(position) === key);
  const ownTrades = trades.filter((trade) => brokerKey(trade) === key);
  const winner = largestPosition(positions, 'winning');
  const loser = largestPosition(positions, 'losing');
  return {
    broker: key,
    label: BROKER_LABELS[key] || key,
    rows: [
      ['Portfolio value', safeNumber(broker?.portfolio_value)],
      ['Cash available', safeNumber(broker?.cash_available)],
      ['Today (total change)', safeNumber(broker?.todays_pnl)],
      ['This week (total change)', safeNumber(broker?.week_pnl)],
      ['This month (total change)', safeNumber(broker?.month_pnl)],
      ['Realised today (closed trades only)', safeNumber(realizedPnlToday(ownTrades))],
      ['Realised this month (closed trades only)', safeNumber(realizedPnlThisMonth(ownTrades))],
    ].map(([label, amount]) => ({ label, amount })),
    openPositions: positions.length,
    winner,
    loser,
  };
}

function brokerStandingBlocks(brokers, context) {
  return (brokers || [])
    .filter((broker) => SHOWN_BROKERS.includes(brokerKey(broker)))
    .map((broker) => brokerStandingBlock(broker, context));
}

module.exports = { brokerStandingBlock, brokerStandingBlocks, safeNumber, BROKER_LABELS };
