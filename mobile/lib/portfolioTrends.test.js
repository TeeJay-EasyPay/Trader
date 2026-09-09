const test = require('node:test');
const assert = require('node:assert/strict');
const { seriesFor, outcomeBuckets, lineGeometry, loadTrends } = require('./portfolioTrends');
const asOf = '2026-09-09T12:00:00Z';

test('allocation changes are marked, zero values retained, window bounded', () => {
  const data = seriesFor({ values: [
    { date: '2026-09-01', value: 100, allocation: 100 },
    { date: '2026-09-08', value: 120, allocation: 125 },
    { date: '2026-09-09', value: 0, allocation: 125 },
  ] }, 7, asOf);
  assert.equal(data.values.length, 2);
  assert.equal(data.values[0].flow, 25);
  assert.equal(data.values[1].value, 0);
});
test('weekly bars sum net profits and unknowns without counting them as losses', () => {
  const bins = outcomeBuckets([{ date: '2026-09-08', wins: 1, losses: 2, unknown: 3, net_pnl: -4 }], 7, asOf, true);
  assert.equal(bins.length, 2);
  assert.equal(bins[1].date, '2026-09-07');
  assert.equal(bins[1].net_pnl, -4);
  assert.equal(bins[1].unknown, 3);
});
test('line geometry never joins missing dates, handles flat/empty/single series', () => {
  assert.deepEqual(lineGeometry([], 260, 100).points, []);
  const graph = lineGeometry([{ date: '2026-09-01', value: 100 }, { date: '2026-09-03', value: 100 }], 260, 100);
  assert.equal(graph.segments.length, 0);
  assert.ok(graph.points.every(p => Number.isFinite(p.y)));
  assert.equal(lineGeometry([{ date: '2026-09-01', value: 0 }], 260, 100).points.length, 1);
});
test('parallel requests and reopening share one bounded response', async () => {
  let calls = 0;
  const request = async () => { calls++; return { as_of: asOf, brokers: [] }; };
  await Promise.all([loadTrends(request), loadTrends(request)]);
  await loadTrends(request);
  assert.equal(calls, 1);
});
