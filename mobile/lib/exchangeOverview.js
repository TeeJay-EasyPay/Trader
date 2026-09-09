'use strict';
const key = value => String(value || '').trim().toLowerCase();
function exchangeName(broker) {
  return broker?.label || ({ kraken: 'Kraken', alpaca: 'Alpaca' })[key(broker?.broker)] || broker?.broker || 'Unknown exchange';
}
function currencyFor(broker) {
  return broker?.currency || ({ kraken: 'GBP', alpaca: 'USD' })[key(broker?.broker)] || null;
}
function exchangeMoney(value, currency) {
  if (value === null || value === undefined || value === '' || !Number.isFinite(Number(value))) return 'Unavailable';
  if (!currency) return `${Number(value).toLocaleString()} (currency unknown)`;
  try { return new Intl.NumberFormat('en-GB', { style: 'currency', currency }).format(Number(value)); }
  catch (_) { return `${currency} ${Number(value).toFixed(2)}`; }
}
function activityByExchange(activity, broker) {
  const id = key(broker.broker);
  const research = (activity?.research || []).filter(r => key(r.broker) === id);
  const trades = (activity?.trades || []).filter(r => key(r.broker) === id);
  const observed = new Set(), filled = new Set();
  let unidentified = 0;
  for (const row of trades) {
    const orderId = row.broker_order_id || row.external_id;
    if (!orderId) { unidentified += 1; continue; }
    observed.add(`${id}:${orderId}`);
    if (['fill', 'filled', 'partial_fill', 'partially_filled'].includes(key(row.status))) filled.add(`${id}:${orderId}`);
  }
  return {
    available: Array.isArray(activity?.research) && Array.isArray(activity?.trades),
    checks: research.reduce((n, r) => n + (Number(r.assets_analysed) || 0), 0),
    candidates: research.reduce((n, r) => n + (Number(r.recommendations_created) || 0), 0),
    orders: observed.size, fills: filled.size, unidentified,
  };
}
function periodLabel(period) {
  return ({ '24h': 'Last 24 hours', '7d': 'Last 7 days', '30d': 'Last 30 days', today: 'Today', day: 'Last 24 hours', week: 'Last 7 days', month: 'Last 30 days' })[period] || `Selected period${period ? `: ${period}` : ' (not supplied)'}`;
}
module.exports = { exchangeName, currencyFor, exchangeMoney, activityByExchange, periodLabel };
