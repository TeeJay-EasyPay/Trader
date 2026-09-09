'use strict';
const DAY = 86400000;
const finite = value => typeof value === 'number' && Number.isFinite(value);

// Geometry only: interpolate the drawn line, never invent a daily observation.
// Missing rows and explicit nulls split BOTH the stroke and the shaded area.
function accountChart(rows, width, height) {
  const good = rows.filter(row => finite(row.value));
  if (!good.length) return { ticks: [], points: [], strokes: [], fills: [] };
  const low = Math.min(...good.map(r => r.value)), high = Math.max(...good.map(r => r.value));
  const range = high - low || Math.max(Math.abs(high) * .04, 1);
  const rawStep = range / 3;
  const power = 10 ** Math.floor(Math.log10(rawStep));
  const step = [1, 2, 2.5, 5, 10].map(n => n * power).find(n => n >= rawStep);
  const min = Math.floor((low - range * .05) / step) * step;
  const max = Math.ceil((high + range * .05) / step) * step;
  const first = Date.parse(rows[0].date), duration = Math.max(DAY, Date.parse(rows.at(-1).date) - first);
  const y = value => height - (value - min) / (max - min) * height;
  const points = rows.map(r => ({ ...r, x: (Date.parse(r.date) - first) / duration * width, y: finite(r.value) ? y(r.value) : null }));
  const ticks = [];
  for (let value = min; value <= max + step / 100; value += step) ticks.push({ value, y: y(value) });
  const strokes = [], fills = [];
  points.forEach((point, i) => {
    const before = points[i - 1];
    if (!before || before.y === null || point.y === null || Date.parse(point.date) - Date.parse(before.date) > DAY) return;
    const dx = point.x - before.x, dy = point.y - before.y;
    if (dx <= 0) return;
    strokes.push({ x: (before.x + point.x) / 2, y: (before.y + point.y) / 2, length: Math.hypot(dx, dy), angle: Math.atan2(dy, dx) });
    // Narrow native rectangles form the area under the same straight segment.
    // No new native dependency/build or remote chart service is required.
    const count = Math.ceil(dx / 2);
    for (let j = 0; j < count; j++) {
      const top = before.y + dy * ((j + .5) / count);
      fills.push({ x: before.x + dx * j / count, y: top, width: dx / count + .25, height: Math.max(0, height - top) });
    }
  });
  return { ticks, points, strokes, fills, min, max };
}

function dateTicks(rows, count = 3) {
  if (!rows.length) return [];
  const indices = [...new Set(Array.from({ length: Math.min(count, rows.length) }, (_, i) => Math.round(i * (rows.length - 1) / Math.max(1, Math.min(count, rows.length) - 1))))];
  return indices.map(i => rows[i].date);
}

function compactMoney(value, currency, step) {
  const prefix = currency === 'GBP' ? '£' : currency === 'USD' ? 'US$' : `${currency || ''} `;
  const abs = Math.abs(value);
  const divisor = abs >= 1e6 ? 1e6 : abs >= 1e3 ? 1e3 : 1;
  const digits = finite(step) && step > 0 ? Math.min(6, Math.max(0, Math.ceil(-Math.log10(step / divisor)) + 1)) : divisor === 1 && abs < 10 ? 2 : 1;
  return `${value < 0 ? '−' : ''}${prefix}${Number((abs / divisor).toFixed(digits))}${divisor === 1e6 ? 'M' : divisor === 1e3 ? 'K' : ''}`;
}
module.exports = { accountChart, dateTicks, compactMoney };
