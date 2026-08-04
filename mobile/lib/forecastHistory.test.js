// Plain Node assert-based tests for forecastHistory.js - run with `node lib/forecastHistory.test.js`.

'use strict';

const assert = require('assert');
const {
  shouldRecordNewForecast,
  buildForecastRecord,
  buildNewRecordsForHorizons,
  isDueForResolution,
  judgeDirection,
  resolveRecord,
  resolveDueRecords,
} = require('./forecastHistory');
const { forecastAccountability } = require('./forecastAccountability');

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

const availableHorizon = {
  horizonKey: 'sevenDay',
  horizon: '7 Days',
  available: true,
  expectedValue: 1070,
  bullCase: { expectedValue: 1140 },
  bearCase: { expectedValue: 1000 },
  probability: 0.6,
};

// --- buildForecastRecord ---

test('buildForecastRecord: an unavailable horizon is never stored as a promise', () => {
  assert.strictEqual(buildForecastRecord({ horizon: { available: false }, horizonDays: 7, portfolioValueAtCreation: 1000 }), null);
});

test('buildForecastRecord: a real available horizon produces a record matching lib/forecastAccountability.js\'s expected shape', () => {
  const record = buildForecastRecord({ horizon: availableHorizon, horizonDays: 7, portfolioValueAtCreation: 1000, createdAt: '2026-08-06T00:00:00.000Z' });
  assert.strictEqual(record.expectedOutcome, 1070);
  assert.strictEqual(record.confidenceGiven, 0.6);
  assert.strictEqual(record.targetDate, '2026-08-13T00:00:00.000Z');
  assert.strictEqual(record.actualOutcome, null);
  assert.strictEqual(record.correct, null);
});

// --- isDueForResolution ---

test('isDueForResolution: a future target date is not yet due', () => {
  const record = buildForecastRecord({ horizon: availableHorizon, horizonDays: 7, portfolioValueAtCreation: 1000, createdAt: '2026-08-06T00:00:00.000Z' });
  assert.strictEqual(isDueForResolution(record, new Date('2026-08-07T00:00:00.000Z')), false);
});

test('isDueForResolution: a passed target date is due', () => {
  const record = buildForecastRecord({ horizon: availableHorizon, horizonDays: 7, portfolioValueAtCreation: 1000, createdAt: '2026-08-06T00:00:00.000Z' });
  assert.strictEqual(isDueForResolution(record, new Date('2026-08-14T00:00:00.000Z')), true);
});

test('isDueForResolution: an already-resolved record is never due again', () => {
  const record = { targetDate: '2020-01-01T00:00:00.000Z', resolvedAt: '2020-01-02T00:00:00.000Z' };
  assert.strictEqual(isDueForResolution(record, new Date('2026-01-01T00:00:00.000Z')), false);
});

// --- judgeDirection ---

test('judgeDirection: real up/down calls, and null (not a fabricated verdict) for no change or missing values', () => {
  assert.strictEqual(judgeDirection(1000, 1100), 'up');
  assert.strictEqual(judgeDirection(1000, 900), 'down');
  assert.strictEqual(judgeDirection(1000, 1000), null);
  assert.strictEqual(judgeDirection(null, 1000), null);
});

// --- resolveRecord ---

test('resolveRecord: a correct directional call is marked correct', () => {
  const record = buildForecastRecord({ horizon: availableHorizon, horizonDays: 7, portfolioValueAtCreation: 1000, createdAt: '2026-08-06T00:00:00.000Z' });
  const resolved = resolveRecord(record, 1050, new Date('2026-08-13T00:00:01.000Z'));
  assert.strictEqual(resolved.correct, true);
  assert.strictEqual(resolved.forecastError, 1050 - 1070);
  assert.ok(resolved.resolvedAt);
});

test('resolveRecord: an incorrect directional call is marked incorrect, honestly', () => {
  const record = buildForecastRecord({ horizon: availableHorizon, horizonDays: 7, portfolioValueAtCreation: 1000, createdAt: '2026-08-06T00:00:00.000Z' });
  const resolved = resolveRecord(record, 950, new Date('2026-08-13T00:00:01.000Z'));
  assert.strictEqual(resolved.correct, false);
});

// --- resolveDueRecords ---

test('resolveDueRecords: only due, unresolved records are resolved - others pass through unchanged', () => {
  const due = buildForecastRecord({ horizon: availableHorizon, horizonDays: 7, portfolioValueAtCreation: 1000, createdAt: '2026-08-06T00:00:00.000Z' });
  const notDue = buildForecastRecord({ horizon: availableHorizon, horizonDays: 365, portfolioValueAtCreation: 1000, createdAt: '2026-08-06T00:00:00.000Z' });
  const results = resolveDueRecords([due, notDue], 1100, new Date('2026-08-14T00:00:00.000Z'));
  assert.strictEqual(results[0].resolvedAt !== null, true);
  assert.strictEqual(results[1].resolvedAt, null);
});

// --- shouldRecordNewForecast / buildNewRecordsForHorizons (dedup, roughly once/day) ---

test('shouldRecordNewForecast: no existing record for this horizon means yes, record it', () => {
  assert.strictEqual(shouldRecordNewForecast([], 'sevenDay'), true);
});

test('shouldRecordNewForecast: a recent record for the same horizon means no, do not spam a duplicate', () => {
  const records = [{ horizonKey: 'sevenDay', createdAt: new Date().toISOString() }];
  assert.strictEqual(shouldRecordNewForecast(records, 'sevenDay'), false);
});

test('shouldRecordNewForecast: an old record for the same horizon means yes, record a fresh one', () => {
  const oldDate = new Date(Date.now() - 30 * 60 * 60 * 1000).toISOString(); // 30 hours ago
  const records = [{ horizonKey: 'sevenDay', createdAt: oldDate }];
  assert.strictEqual(shouldRecordNewForecast(records, 'sevenDay'), true);
});

test('buildNewRecordsForHorizons: skips unavailable horizons and dedupes against existing records', () => {
  const horizons = [
    availableHorizon,
    { ...availableHorizon, horizonKey: 'thirtyDay', horizon: '30 Days' },
    { available: false, horizonKey: 'quarter', reason: 'not enough evidence' },
  ];
  const existingRecords = [{ horizonKey: 'thirtyDay', createdAt: new Date().toISOString() }];
  const result = buildNewRecordsForHorizons({ horizons, portfolioValueAtCreation: 1000, existingRecords, createdAt: '2026-08-06T00:00:00.000Z' });
  assert.strictEqual(result.length, 1);
  assert.strictEqual(result[0].horizonKey, 'sevenDay');
});

// --- integration with lib/forecastAccountability.js (AT-ED-014's scaffold, now fed real records) ---

test('integration: resolved records flow directly into forecastAccountability() and produce a real accuracy figure', () => {
  const record = buildForecastRecord({ horizon: availableHorizon, horizonDays: 7, portfolioValueAtCreation: 1000, createdAt: '2026-08-06T00:00:00.000Z' });
  const resolved = resolveRecord(record, 1050, new Date('2026-08-13T00:00:01.000Z'));
  const summary = forecastAccountability([resolved]);
  assert.strictEqual(summary.available, true);
  assert.strictEqual(summary.accuracy, 1);
});

console.log(`\n${passed} passed`);
if (process.exitCode) {
  console.error('Some forecastHistory tests failed.');
}
