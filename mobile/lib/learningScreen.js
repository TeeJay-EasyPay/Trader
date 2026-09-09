'use strict';
const cache = new Map(), pending = new Map();
function learningRequest(request, path) {
  const hit = cache.get(path);
  if (hit && Date.now() - hit.time < 600000) return Promise.resolve(hit.value);
  if (pending.has(path)) return pending.get(path);
  const promise = request(path).then(value => {
    if (!value || value.error) throw Error(value?.error || 'Learning evidence unavailable');
    cache.set(path, { time: Date.now(), value });
    while (cache.size > 24) cache.delete(cache.keys().next().value);
    return value;
  }).finally(() => pending.delete(path));
  pending.set(path, promise);
  return promise;
}
function shiftedDate(anchor, period, direction) {
  const d = new Date(anchor + 'T12:00:00Z');
  if (period === 'monthly') { d.setUTCDate(1); d.setUTCMonth(d.getUTCMonth() + direction); }
  else d.setUTCDate(d.getUTCDate() + direction * (period === 'weekly' ? 7 : 1));
  return d.toISOString().slice(0, 10);
}
function resultText(value, broker) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 'Unknown';
  return `${value < 0 ? '−' : value > 0 ? '+' : ''}${broker === 'kraken' ? '£' : 'US$'}${Math.abs(value).toFixed(2)}`;
}
function humanStatus(value) {
  return ({ ai_review_declined: 'Declined after AI review', pending: 'Still tracking', unsettleable: 'Outcome uncertain', stop_hit: 'Modelled stop reached',
    target_hit: 'Modelled target reached', expired: 'Tracking window ended' })[value] || String(value || 'Unknown').replace(/_/g, ' ');
}
function priceText(value) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 'Unknown';
  return Number(value.toPrecision(6)).toString();
}
function matchesLearningView(data, detail) {
  return !!data && (detail ? data.kind === detail && Array.isArray(data.rows) : Array.isArray(data.outcomes) && !!data.assessment);
}
module.exports = { learningRequest, shiftedDate, resultText, humanStatus, priceText, matchesLearningView };
