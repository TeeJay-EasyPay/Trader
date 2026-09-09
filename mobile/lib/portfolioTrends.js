'use strict';

const DAY = 86400000;
const numeric = value => typeof value === 'number' && Number.isFinite(value);

function seriesFor(broker, days, asOf) {
  const end = Date.parse(String(asOf).slice(0, 10) + 'T00:00:00Z');
  const cutoff = end - (days - 1) * DAY;
  const inWindow = row => Date.parse(row.date + 'T00:00:00Z') >= cutoff && Date.parse(row.date + 'T00:00:00Z') <= end;
  const all = [...(broker.values || [])].sort((a, b) => a.date.localeCompare(b.date));
  const values = all.map((row, index) => ({ ...row,
    flow: index && numeric(row.allocation) && numeric(all[index - 1].allocation)
      ? row.allocation - all[index - 1].allocation : null,
  })).filter(inWindow);
  return { values, outcomes: (broker.outcomes || []).filter(inWindow) };
}

function outcomeBuckets(rows, days, asOf, weekly) {
  const end = Date.parse(String(asOf).slice(0, 10) + 'T00:00:00Z');
  const bins = new Map();
  const keyFor = time => {
    const day = new Date(time).getUTCDay();
    return new Date(weekly ? time - ((day + 6) % 7) * DAY : time).toISOString().slice(0, 10);
  };
  for (let i = days - 1; i >= 0; i--) {
    const key = keyFor(end - i * DAY);
    if (!bins.has(key)) bins.set(key, { date: key, wins: 0, losses: 0, breakeven: 0, unknown: 0, net_pnl: 0 });
  }
  for (const row of rows) {
    const bin = bins.get(keyFor(Date.parse(row.date + 'T00:00:00Z')));
    if (bin) for (const field of ['wins', 'losses', 'breakeven', 'unknown', 'net_pnl']) bin[field] += numeric(row[field]) ? row[field] : 0;
  }
  return [...bins.values()];
}

function lineGeometry(rows, width, height) {
  const good = rows.filter(row => numeric(row.value));
  if (!good.length) return { points: [], segments: [] };
  const min = Math.min(...good.map(row => row.value));
  const max = Math.max(...good.map(row => row.value));
  const span = max - min || Math.max(Math.abs(max) * .02, 1);
  const start = Date.parse(rows[0].date);
  const duration = Math.max(DAY, Date.parse(rows[rows.length - 1].date) - start);
  const points = rows.map(row => ({ ...row, x: (Date.parse(row.date) - start) / duration * width,
    y: numeric(row.value) ? (max === min ? height / 2 : height - 8 - (row.value - min + span * .1) / (span * 1.2) * (height - 16)) : null }));
  const segments = [];
  points.forEach((p, i) => {
    const before = points[i - 1];
    if (before && before.y !== null && p.y !== null && Date.parse(p.date) - Date.parse(before.date) <= DAY) {
      const dx = p.x - before.x, dy = p.y - before.y;
      segments.push({ x: (p.x + before.x) / 2, y: (p.y + before.y) / 2,
        length: Math.hypot(dx, dy), angle: Math.atan2(dy, dx) });
    }
  });
  return { points, segments, min, max };
}

let cached = null;
let pending = null;
function loadTrends(request) {
  if (cached && Date.now() - cached.time < 600000) return Promise.resolve(cached.value);
  if (pending) return pending;
  pending = request('/portfolio-trends?scope=whole_account').then(value => {
    if (!Array.isArray(value?.brokers) || !Number.isFinite(Date.parse(value.as_of))) throw new Error('Historical summary unavailable');
    cached = { time: Date.now(), value };
    return value;
  }).finally(() => { pending = null; });
  return pending;
}

module.exports = { seriesFor, outcomeBuckets, lineGeometry, loadTrends };
