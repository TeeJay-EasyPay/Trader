// AT-ED-016 Part 1 Section 2: Current Position facts not already computed elsewhere -
// week-to-date/month-to-date P&L and the largest winning/losing open position. Kept
// dependency-free (no React/RN imports) - see portfolioPosition.test.js.
//
// WTD/MTD are summed from status.brokers[].week_pnl/.month_pnl - real per-broker fields
// lib/founderEvidenceMapping.js already maps from the backend (`row.week_pnl`/`row.month_pnl`),
// the same fields BrokerPanel already has access to but no screen had summed to a portfolio-wide
// figure before this pass. Largest winner/loser use only `symbol` and `unrealized_pl` on
// portfolio.open_positions[] items - the only two fields any call site in this codebase has ever
// proven safe to read from that array (see the AT-ED-016 design review's concentration caveat -
// no market-value or quantity field is assumed to exist).

'use strict';

function sumBrokerField(brokers, field) {
  // `Number(null)` is 0, not NaN - filter out null/undefined explicitly before conversion, or a
  // broker with genuinely no evidence for this field would be silently counted as a real zero.
  const values = (brokers || [])
    .filter((broker) => broker[field] !== null && broker[field] !== undefined)
    .map((broker) => Number(broker[field]))
    .filter(Number.isFinite);
  if (!values.length) {
    return null;
  }
  return values.reduce((sum, value) => sum + value, 0);
}

function weekToDatePnl(brokers) {
  return sumBrokerField(brokers, 'week_pnl');
}

function monthToDatePnl(brokers) {
  return sumBrokerField(brokers, 'month_pnl');
}

// direction: 'winning' picks the largest positive unrealized_pl, 'losing' picks the largest
// (most negative) unrealized_pl. Returns null when no position qualifies - never a fabricated
// "largest" pick from an empty or all-flat set.
function largestPosition(openPositions, direction) {
  const candidates = (openPositions || [])
    .map((position) => ({ symbol: position.symbol, unrealizedPl: Number(position.unrealized_pl) }))
    .filter((position) => Number.isFinite(position.unrealizedPl) && (direction === 'winning' ? position.unrealizedPl > 0 : position.unrealizedPl < 0));
  if (!candidates.length) {
    return null;
  }
  return candidates.reduce((best, position) => (
    direction === 'winning'
      ? (position.unrealizedPl > best.unrealizedPl ? position : best)
      : (position.unrealizedPl < best.unrealizedPl ? position : best)
  ), candidates[0]);
}

module.exports = {
  weekToDatePnl,
  monthToDatePnl,
  largestPosition,
};
