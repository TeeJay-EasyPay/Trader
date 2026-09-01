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
  assessment: 'Momentum is strong but the weekly view disagrees.', confidence: 0.42, created_at: '2026-08-20T07:16:18Z',
};

test('a record becomes a compact row', () => {
  const row = declineRow(record);
  assert.strictEqual(row.symbol, 'XLM');
  assert.strictEqual(row.outcome, 'Declined');
  assert.strictEqual(row.confidence, '42% confident');
  assert.strictEqual(row.assessment, 'Momentum is strong but the weekly view disagrees.');
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

test('mechanical reasons fill the card when there is no judgement call to report', () => {
  // 2026-09-01: the card read empty for days while the app was turning down hundreds of
  // ideas. Correct by its own design -- it shows the AI reviewer's judgement, and nothing
  // reached the reviewer -- but a card titled "Trades I Turned Down" showing nothing on such
  // a day reads as broken rather than as precise.
  const card = declineReasonsCard({
    declines: [],
    available: true,
    mechanical_summary: [
      { reason: 'fee_hurdle_not_cleared', count: 3, explanation: 'profit would not have covered fees', examples: ['SOL'] },
    ],
  });
  assert.strictEqual(card.mechanical, true);
  assert.strictEqual(card.rows.length, 1);
  assert.ok(card.rows[0].why.includes('fees'));
  assert.ok(card.rows[0].symbol.includes('3 ideas'));
});

test('a real judgement call still takes precedence over the mechanical summary', () => {
  const card = declineReasonsCard({
    // declineRow needs symbol AND why; anything else is dropped as unrenderable.
    declines: [{ symbol: 'SCCO', why: 'The setup was already too extended to buy safely.' }],
    mechanical_summary: [{ reason: 'fee_hurdle_not_cleared', count: 9, explanation: 'fees', examples: [] }],
  });
  assert.strictEqual(card.mechanical, false);
  assert.ok(card.rows.length >= 1);
});

test('genuinely nothing refused still reads as empty', () => {
  const card = declineReasonsCard({ declines: [], available: true, mechanical_summary: [] });
  assert.strictEqual(card.rows.length, 0);
  assert.strictEqual(card.mechanical, false);
});

console.log(`\n${passed} test(s) passed.`);
