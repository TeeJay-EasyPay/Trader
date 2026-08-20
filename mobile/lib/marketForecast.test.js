// Plain Node assert-based tests for marketForecast.js - run with
// `node lib/marketForecast.test.js`.
//
// Phase 7 of the CIO-level forecasting build (2026-08-20). These protect the
// honest-disclosure rule this codebase holds throughout: never fabricate a number to
// fill a shape, and never present an old view as if it were current.

'use strict';

const assert = require('assert');
const {
  NO_FORECAST_CARD,
  confidenceLabel,
  directionLabel,
  forecastCardFromRecord,
  marketForecastCards,
  stalenessNote,
} = require('./marketForecast');

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

function record(overrides = {}) {
  return {
    forecast_id: 1,
    symbol: 'BTC',
    direction: 'bullish',
    horizon_days: 14,
    confidence: 0.75,
    reasoning: 'Daily momentum is strong at 0.96 and price sits above both moving averages.',
    invalidation: 'A daily close below 46114.3.',
    created_at: new Date().toISOString(),
    evidence_json: JSON.stringify({
      supporting_evidence: ['Daily momentum 0.96'],
      contradictory_evidence: ['Weekly trend weak at 0.19'],
      key_risks: ['A broad risk-off move'],
    }),
    ...overrides,
  };
}

// --- Honest empty state -----------------------------------------------------------------

test('no forecasts yet is an honest explained empty state, never a fabricated number', () => {
  const cards = marketForecastCards({ forecasts: [] });
  assert.strictEqual(cards.length, 1);
  assert.strictEqual(cards[0].available, false);
  assert.ok(/have not produced a market forecast yet/i.test(cards[0].reason));
  // Must not invent any numeric projection to fill the shape.
  assert.strictEqual(cards[0].expectedValue, undefined);
  assert.strictEqual(cards[0].expectedChange, undefined);
});

test('a missing/undefined response is treated the same as no forecasts', () => {
  assert.strictEqual(marketForecastCards(undefined)[0].available, false);
  assert.strictEqual(marketForecastCards({})[0].available, false);
});

// --- Real forecast shaping --------------------------------------------------------------

test('a real forecast becomes a card with all four founder-facing fields populated', () => {
  const card = forecastCardFromRecord(record());
  assert.strictEqual(card.available, true);
  assert.strictEqual(card.direction, 'bullish');
  assert.ok(/Upward/.test(card.whatIExpect));
  assert.ok(/14 days/.test(card.whatIExpect));
  assert.ok(/Daily momentum is strong/.test(card.why));
  assert.ok(/would be wrong if/.test(card.whatCouldChange));
});

test('the contradictory case and key risks are surfaced, not buried', () => {
  const card = forecastCardFromRecord(record());
  assert.ok(/Weekly trend weak/.test(card.whatCouldChange), 'contradictory evidence must be shown to the Founder');
  assert.ok(/broad risk-off/.test(card.whatCouldChange), 'key risks must be shown to the Founder');
});

test('confidence maps to the same bands the backend uses, never overstated', () => {
  assert.strictEqual(confidenceLabel(0.9), 'High');
  assert.strictEqual(confidenceLabel(0.75), 'High');
  assert.strictEqual(confidenceLabel(0.6), 'Medium');
  assert.strictEqual(confidenceLabel(0.3), 'Low');
  assert.strictEqual(confidenceLabel(null), 'Unknown');
  assert.strictEqual(confidenceLabel('not-a-number'), 'Unknown');
});

test('direction labels are plain English, and an unknown direction is never guessed', () => {
  assert.strictEqual(directionLabel('bullish'), 'Upward');
  assert.strictEqual(directionLabel('bearish'), 'Downward');
  assert.strictEqual(directionLabel('neutral'), 'Sideways');
  assert.strictEqual(directionLabel('uncertain'), 'Unclear');
  assert.strictEqual(directionLabel('something-else'), 'Unclear');
});

// --- Staleness is disclosed, not hidden --------------------------------------------------

test('a fresh forecast carries no staleness warning', () => {
  assert.strictEqual(stalenessNote({ created_at: new Date().toISOString() }), null);
});

test('an old forecast is explicitly flagged as old rather than shown as current', () => {
  const threeDaysAgo = new Date(Date.now() - 3 * 24 * 3600 * 1000).toISOString();
  const note = stalenessNote({ created_at: threeDaysAgo });
  assert.ok(note && /3 days old/.test(note), `expected a staleness note, got: ${note}`);
  const card = forecastCardFromRecord(record({ created_at: threeDaysAgo }));
  assert.ok(/may no longer reflect current conditions/.test(card.whatIExpect));
});

test('an unparseable created_at does not crash and simply omits the note', () => {
  assert.strictEqual(stalenessNote({ created_at: 'not-a-date' }), null);
});

// --- Robustness -------------------------------------------------------------------------

test('a malformed evidence payload degrades gracefully instead of throwing', () => {
  const card = forecastCardFromRecord(record({ evidence_json: '{not valid json' }));
  assert.strictEqual(card.available, true);
  assert.ok(card.why.length > 0);
});

test('a forecast with no reasoning says so plainly rather than rendering blank', () => {
  const card = forecastCardFromRecord(record({ reasoning: '', invalidation: '', evidence_json: '{}' }));
  assert.ok(/No reasoning was recorded/.test(card.why));
  assert.ok(/No invalidation conditions were recorded/.test(card.whatCouldChange));
});

test('only the newest forecast per symbol is shown', () => {
  const cards = marketForecastCards({
    forecasts: [
      record({ forecast_id: 3, symbol: 'BTC', direction: 'bearish' }),
      record({ forecast_id: 2, symbol: 'BTC', direction: 'bullish' }),
      record({ forecast_id: 1, symbol: 'ETH', direction: 'bullish' }),
    ],
  });
  assert.strictEqual(cards.length, 2, 'one card per symbol');
  assert.strictEqual(cards[0].symbol, 'BTC');
  assert.strictEqual(cards[0].direction, 'bearish', 'the newest BTC view wins');
  assert.strictEqual(cards[1].symbol, 'ETH');
});

test('records without a symbol are skipped rather than rendered as blank cards', () => {
  const cards = marketForecastCards({ forecasts: [record({ symbol: null })] });
  assert.strictEqual(cards.length, 1);
  assert.strictEqual(cards[0].available, false, 'falls back to the honest empty state');
});

test('NO_FORECAST_CARD is frozen so a screen cannot mutate the shared empty state', () => {
  assert.throws(() => {
    'use strict';
    NO_FORECAST_CARD.reason = 'mutated';
  });
});

console.log(`\n${passed} test(s) passed.`);
