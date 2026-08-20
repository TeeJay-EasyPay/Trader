// Plain Node assert-based tests - run with `node lib/declineReasons.test.js`.
const assert = require('assert');
const {
  NO_DECLINES_MESSAGE,
  NOT_LOADED_MESSAGE,
  confidenceNote,
  declineReasonsCard,
  declineRow,
  declineRows,
} = require('./declineReasons');

let passed = 0;
function test(name, fn) {
  try { fn(); passed += 1; console.log(`ok - ${name}`); }
  catch (err) { console.error(`FAIL - ${name}`); console.error(err); process.exitCode = 1; }
}

const record = {
  symbol: 'XLM', outcome: 'Declined', why: 'Price sits near the top of its range.',
  main_concern: 'Little room to resistance.', confidence: 0.42, created_at: '2026-08-20T07:16:18Z',
};

test('a record becomes a compact row', () => {
  const row = declineRow(record);
  assert.strictEqual(row.symbol, 'XLM');
  assert.strictEqual(row.outcome, 'Declined');
  assert.strictEqual(row.confidence, '42% confident');
  assert.strictEqual(row.concern, 'Little room to resistance.');
});

test('records without a symbol or reason are dropped, not rendered blank', () => {
  assert.strictEqual(declineRow({ why: 'x' }), null);
  assert.strictEqual(declineRow({ symbol: 'BTC' }), null);
  assert.strictEqual(declineRow(null), null);
});

test('a missing confidence is omitted rather than shown as 0%', () => {
  // Number(null) === 0 is finite - the trap that once rendered missing data as "Low".
  assert.strictEqual(confidenceNote(null), null);
  assert.strictEqual(confidenceNote(undefined), null);
  assert.strictEqual(confidenceNote(''), null);
  assert.strictEqual(confidenceNote('abc'), null);
  assert.strictEqual(confidenceNote(0.9), '90% confident');
});

test('not loaded is distinct from loaded-but-empty', () => {
  assert.strictEqual(declineReasonsCard(null).loaded, false);
  assert.strictEqual(declineReasonsCard(null).emptyMessage, NOT_LOADED_MESSAGE);
  const empty = declineReasonsCard({ declines: [] });
  assert.strictEqual(empty.loaded, true);
  assert.strictEqual(empty.emptyMessage, NO_DECLINES_MESSAGE);
  assert.deepStrictEqual(empty.rows, []);
});

test('rows survive a malformed payload', () => {
  assert.deepStrictEqual(declineRows({ declines: 'nope' }), []);
  assert.deepStrictEqual(declineRows({}), []);
  assert.deepStrictEqual(declineRows(null), []);
});

test('a real payload yields real rows', () => {
  const card = declineReasonsCard({ declines: [record, { symbol: 'SOL', why: 'Too extended.' }] });
  assert.strictEqual(card.rows.length, 2);
  assert.strictEqual(card.rows[1].outcome, 'Declined');
  assert.strictEqual(card.rows[1].confidence, null);
});

console.log(`\n${passed} test(s) passed.`);
