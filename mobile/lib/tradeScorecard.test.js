// Plain Node assert-based tests for tradeScorecard.js - run with
// `node lib/tradeScorecard.test.js`.
//
// Founder-requested 2026-08-20: a small Executive Briefing card showing how many trades
// each day, week and month were successful and how many were not, plus a short lessons
// line. These protect the same honest-disclosure rule the rest of this codebase holds:
// never let "not known yet" render as a confident zero.

const assert = require('assert');

const {
  NO_SCORECARD_MESSAGE,
  countText,
  lessonsText,
  netText,
  pendingText,
  scorecardRows,
  tradeScorecardCard,
  winRateText,
} = require('./tradeScorecard');

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

function bucket(overrides = {}) {
  return {
    successful: 3,
    unsuccessful: 1,
    breakeven: 0,
    unknown: 2,
    settled: 4,
    total: 6,
    win_rate: 0.75,
    net_pnl: 12.345,
    ...overrides,
  };
}

test('counts read as plain English rather than raw field names', () => {
  assert.strictEqual(countText(bucket()), "3 worked / 1 didn't");
});

test('a period with no completed trades says so instead of showing 0 / 0', () => {
  assert.strictEqual(countText({ successful: 0, unsuccessful: 0 }), 'No completed trades');
});

test('not-yet-loaded stays distinct from genuinely zero', () => {
  // Number(null) === 0 is finite -- the exact trap that previously rendered a missing
  // confidence as "Low" in marketForecast.js. Missing must be null, never 0.
  assert.strictEqual(countText(null), null);
  assert.strictEqual(countText({ successful: null, unsuccessful: null }), null);
  assert.strictEqual(countText({}), null);
});

test('win rate is omitted when undefined rather than shown as 0%', () => {
  assert.strictEqual(winRateText(bucket()), '75% win rate');
  assert.strictEqual(winRateText({ win_rate: null }), null);
  assert.strictEqual(winRateText({}), null);
});

test('unreconciled trades are surfaced separately, never counted as wins', () => {
  assert.strictEqual(pendingText(bucket()), '2 awaiting reconciliation');
  assert.strictEqual(pendingText({ unknown: 0 }), null);
  assert.strictEqual(pendingText({}), null);
});

test('net shows a sign and two decimals, and is hidden when flat', () => {
  assert.strictEqual(netText(bucket()), '+£12.35');
  assert.strictEqual(netText({ net_pnl: -4.5 }), '-£4.50');
  assert.strictEqual(netText({ net_pnl: 0 }), null);
  assert.strictEqual(netText({}), null);
});

test('rows cover exactly the three periods the Founder asked for', () => {
  const rows = scorecardRows({ day: bucket(), week: bucket(), month: bucket() });
  // 2026-08-25: these are ROLLING windows, and calling the first one "Today" put it in
  // direct contradiction with the Portfolio card's calendar-day "Completed Trades Today".
  // Both numbers were right; only the labels were lying.
  assert.deepStrictEqual(rows.map((row) => row.label), ['Last 24 hours', 'Last 7 days', 'Last 30 days']);
});

test('a null scorecard yields no rows and an honest message', () => {
  assert.deepStrictEqual(scorecardRows(null), []);
  assert.strictEqual(lessonsText(null), NO_SCORECARD_MESSAGE);
  assert.strictEqual(tradeScorecardCard(null).loaded, false);
});

test('the lessons line passes through, and blank text never renders empty', () => {
  assert.strictEqual(
    lessonsText({ lessons: 'Losses clustered in low-liquidity hours.' }),
    'Losses clustered in low-liquidity hours.',
  );
  assert.strictEqual(lessonsText({ lessons: '   ' }), 'No lessons recorded yet.');
  assert.strictEqual(lessonsText({}), 'No lessons recorded yet.');
});

test('a loaded card reports loaded true with real rows', () => {
  const card = tradeScorecardCard({
    day: bucket(),
    week: bucket(),
    month: bucket(),
    lessons: 'Held winners too briefly.',
  });
  assert.strictEqual(card.loaded, true);
  assert.strictEqual(card.rows.length, 3);
  assert.strictEqual(card.lessons, 'Held winners too briefly.');
});

test('a missing period renders as no completed trades, not a crash', () => {
  const rows = scorecardRows({ lessons: 'x' });
  assert.strictEqual(rows.length, 3);
  rows.forEach((row) => assert.strictEqual(row.counts, 'No completed trades'));
});

console.log(`\n${passed} test(s) passed.`);
