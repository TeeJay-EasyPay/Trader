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

const { TERMINAL_STATUSES } = require('./forecastEngine');
const { dateMs, todayIso } = require('./datetime');

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

// AT-ED-017 Part 3: "how much has Alpaca made, how much has Kraken made, and is it realised or
// unrealised?" - real evidence for both halves already exists, just never grouped by broker
// before. Unrealised comes from portfolio.open_positions[].unrealized_pl, which
// _portfolio_payload() in production_evidence.py already tags with a real `broker` field
// (`positions.append({**position, "broker": row.get("broker")})`).
function unrealizedPnlByBroker(openPositions) {
  const totals = {};
  (openPositions || []).forEach((position) => {
    const broker = position?.broker;
    const raw = position?.unrealized_pl;
    if (!broker || raw === null || raw === undefined) {
      return;
    }
    const value = Number(raw);
    if (!Number.isFinite(value)) {
      return;
    }
    totals[broker] = (totals[broker] || 0) + value;
  });
  return totals;
}

function totalUnrealizedPnl(openPositions) {
  const byBroker = unrealizedPnlByBroker(openPositions);
  const values = Object.values(byBroker);
  return values.length ? values.reduce((sum, value) => sum + value, 0) : null;
}

// Realised P&L is the closed-trade side of the same story - each performanceAttribution/
// productionTradeForMobile item is one broker's PRODUCTION_TRADE_EVIDENCE row (real broker,
// real status, real realized_pnl/profit_loss). Reuses forecastEngine's own TERMINAL_STATUSES so
// "closed" never means something different in two places in the same screen. "Today" uses UTC
// calendar-day boundaries via lib/datetime's todayIso(), matching every other "today" figure in
// this codebase (portfolio.todays_pnl is computed the same way on the backend).
function closedTradesToday(trades) {
  const today = todayIso();
  return (trades || []).filter((trade) => {
    if (!TERMINAL_STATUSES.includes(String(trade?.status || '').toLowerCase())) {
      return false;
    }
    const closedAt = trade?.closed_at || trade?.created_at;
    if (!closedAt) {
      return false;
    }
    const ms = dateMs(closedAt);
    return ms && new Date(ms).toISOString().slice(0, 10) === today;
  });
}

// `Number(null)`/`Number(undefined)` is 0/NaN respectively - a trade with a genuinely missing
// profit_loss must never be silently counted as a real zero, so null/undefined are filtered out
// before conversion (the same gotcha sumBrokerField() above guards against).
function withRealProfitLoss(trades) {
  return (trades || []).filter((trade) => trade?.profit_loss !== null && trade?.profit_loss !== undefined && Number.isFinite(Number(trade.profit_loss)));
}

function realizedPnlToday(trades) {
  const closedToday = withRealProfitLoss(closedTradesToday(trades));
  return closedToday.length ? closedToday.reduce((sum, trade) => sum + Number(trade.profit_loss), 0) : null;
}

function realizedPnlByBrokerToday(trades) {
  const totals = {};
  withRealProfitLoss(closedTradesToday(trades)).forEach((trade) => {
    const broker = trade?.broker;
    if (!broker) {
      return;
    }
    totals[broker] = (totals[broker] || 0) + Number(trade.profit_loss);
  });
  return totals;
}

function exitsTodayCount(trades) {
  return closedTradesToday(trades).length;
}

module.exports = {
  weekToDatePnl,
  monthToDatePnl,
  largestPosition,
  unrealizedPnlByBroker,
  totalUnrealizedPnl,
  closedTradesToday,
  realizedPnlToday,
  realizedPnlByBrokerToday,
  exitsTodayCount,
};
