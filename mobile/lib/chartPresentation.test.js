const test = require('node:test');
const assert = require('node:assert/strict');
const { accountChart, dateTicks, compactMoney } = require('./chartPresentation');
const row = (date, value) => ({ date: `2026-09-${date}`, value });

test('stroke and fill both stop at missing days and explicit nulls', () => {
  const rows = [row('01', 10), row('02', 12), row('04', 15), row('05', null), row('06', 8)];
  const chart = accountChart(rows, 300, 116);
  assert.equal(chart.strokes.length, 1);
  assert.ok(chart.fills.length > 0);
  assert.ok(chart.fills.every(fill => fill.x < chart.points[1].x));
  assert.equal(chart.points[3].y, null);
  assert.deepEqual(rows.map(r => r.value), [10, 12, 15, null, 8]);
});
test('empty, flat, zero and negative histories have finite geometry', () => {
  assert.equal(accountChart([], 230, 116).ticks.length, 0);
  for (const value of [0, 500, -100]) {
    const chart = accountChart([row('01', value), row('02', value)], 230, 116);
    assert.ok(chart.ticks.length >= 3 && chart.ticks.length <= 7);
    assert.ok(chart.min < value && chart.max > value);
    assert.equal(chart.points[0].y, chart.points[1].y);
    assert.ok(chart.points.every(p => Number.isFinite(p.y) && p.y >= 0 && p.y <= 116));
    assert.ok(chart.fills.every(f => f.height >= 0 && f.height <= 116));
  }
});
test('axis domain and stroke share the same coordinate transform', () => {
  const chart = accountChart([row('01', 100), row('02', 130)], 230, 116);
  assert.ok(chart.ticks.every(t => Math.abs(t.y - (116 - (t.value - chart.min) / (chart.max - chart.min) * 116)) < .0001));
  assert.ok(chart.fills.length <= 116);
});
test('date labels are bounded and currencies remain separate', () => {
  assert.deepEqual(dateTicks([]), []);
  assert.deepEqual(dateTicks([row('01', 0)]), ['2026-09-01']);
  assert.equal(dateTicks(Array.from({ length: 30 }, (_, i) => row(String(i + 1).padStart(2, '0'), i))).length, 3);
  assert.equal(compactMoney(5200, 'GBP'), '£5.2K');
  assert.equal(compactMoney(101000, 'USD'), 'US$101K');
  assert.equal(compactMoney(-12, 'GBP'), '−£12');
  assert.notEqual(compactMoney(100001, 'USD', 1), compactMoney(100002, 'USD', 1));
});
