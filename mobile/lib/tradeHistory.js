// Trade/transaction interpretation and formatting shared across the Dashboard and Portfolio
// screens (BrokerPanel's latest-trade line, the Portfolio trade history list and detail view).
// Extracted from App.js as part of AT-ED-011 Phase 2 (mobile modularisation).

'use strict';

const { brokerKey, historyMoneyOrText } = require('./money');
const { dateMs, formatPercent, formatShortDateTime } = require('./datetime');
const { notAvailable } = require('./notAvailable');
const { parseMaybeJson } = require('./json');
const { brokerCurrency } = require('./portfolioPosition');

// 2026-08-21 Founder-reported bug: one real trade was rendering as three separate rows in
// Trade History - Kraken's BROKER_TRADE_HISTORY logs a "filled" order-fill row and a separate,
// less complete "closed" position-tracking row for the same underlying event (no symbol/side,
// just quantity/price - see multi_broker.py's record_broker_trade_history, which allows this by
// design via its UNIQUE(broker, external_id, status, updated_at) constraint), and the reconciled
// performance-attribution table adds a third, fuller record of the same fill. There is no shared
// foreign key across these tables to key a dedup off directly (the same gap this codebase already
// documents for recommendation-to-trade matching), so this is a best-effort match on broker +
// quantity + price + a short time window - a heuristic, not a guaranteed link, same tradeoff
// already accepted elsewhere in this file's history.
const DEDUPABLE_EVENT_TYPES = new Set(['performance_attribution', 'broker_trade', 'broker_fill', 'broker_order']);
const DEDUP_WINDOW_MS = 30 * 60 * 1000;
const DEDUP_QUANTITY_TOLERANCE = 0.001;
const DEDUP_PRICE_TOLERANCE = 0.005;

// Reconciled performance-attribution outranks a raw broker row (it carries the authoritative
// realised P&L); between two raw broker rows, the one with a real symbol outranks the bare
// tracking row that has none.
function transactionRank(item) {
  if (item.event_type === 'performance_attribution') {
    return 3;
  }
  const normalized = normalizeTradeRow(item);
  if (!normalized.symbol) {
    return 1;
  }
  // 2026-08-28: when several rows describe one order, the one carrying the realised P&L is
  // the one worth keeping. Without this the first row seen won -- for SCCO that was a
  // partial_fill with an empty P&L column, so a -69.14 loss was collapsed away and the sale
  // looked like it had no result. Ranked above a bare symbol match but below reconciled
  // attribution, which remains the most authoritative source of realised P&L.
  return numeric(normalized.profitLoss) !== null ? 2.5 : 2;
}

function sameTrade(a, b) {
  if (!DEDUPABLE_EVENT_TYPES.has(a.event_type) || !DEDUPABLE_EVENT_TYPES.has(b.event_type)) {
    return false;
  }
  const na = normalizeTradeRow(a);
  const nb = normalizeTradeRow(b);
  if (na.broker !== nb.broker) {
    return false;
  }
  // Never merge two genuinely different symbols just because quantity/price/timing happened
  // to line up - only treat missing symbol (the bare tracking row) as compatible with anything.
  if (na.symbol && nb.symbol && na.symbol !== nb.symbol) {
    return false;
  }
  if (na.quantity === null || nb.quantity === null) {
    return false;
  }
  const quantityDenominator = Math.max(Math.abs(na.quantity), Math.abs(nb.quantity), 1e-9);
  if (Math.abs(na.quantity - nb.quantity) / quantityDenominator > DEDUP_QUANTITY_TOLERANCE) {
    return false;
  }
  const priceA = na.exitPrice ?? na.price ?? na.entryPrice;
  const priceB = nb.exitPrice ?? nb.price ?? nb.entryPrice;
  if (priceA !== null && priceB !== null) {
    const priceDenominator = Math.max(Math.abs(priceA), Math.abs(priceB), 1e-9);
    if (Math.abs(priceA - priceB) / priceDenominator > DEDUP_PRICE_TOLERANCE) {
      return false;
    }
  }
  const timeA = dateMs(na.eventTime);
  const timeB = dateMs(nb.eventTime);
  if (!timeA || !timeB || Math.abs(timeA - timeB) > DEDUP_WINDOW_MS) {
    return false;
  }
  return true;
}

// Collapses rows judged the same underlying trade into one, keeping the highest-ranked
// (most complete/authoritative) version. Order-preserving on the first-seen slot so callers
// that pre-sort newest-first keep that order for the surviving row.
function dedupeTransactions(transactions) {
  const kept = [];
  const byOrderId = new Map();
  (transactions || []).forEach((item) => {
    // 2026-08-28 Founder-reported: "a number of sales today... but no figures on what the
    // profit or losses for some of the sales." Today's two real sells rendered as TEN rows,
    // and only two carried a P&L.
    //
    // A broker files one row per order EVENT, and the realised P&L lands on the terminal one:
    // SCCO arrived as partial_fill (x3), fill, filled and canceled, with -69.14 on the
    // 'filled' row alone. The five siblings were shown as separate sales with an empty P&L
    // column, which reads as missing data rather than as the same sale reported six times.
    //
    // The existing heuristic could not merge them: it matches on quantity, and the partials
    // were 1, 1, 10 and 13 of the same order. The broker's own order id says exactly what
    // belongs together, so it is used first and the heuristic stays as the fallback for rows
    // that carry no id.
    const orderId = normalizeTradeRow(item).orderId;
    if (orderId) {
      const key = String(orderId);
      const seenIndex = byOrderId.get(key);
      if (seenIndex === undefined) {
        byOrderId.set(key, kept.length);
        kept.push(item);
      } else if (transactionRank(item) > transactionRank(kept[seenIndex])) {
        kept[seenIndex] = item;
      }
      return;
    }
    const matchIndex = kept.findIndex((existing) => sameTrade(existing, item));
    if (matchIndex === -1) {
      kept.push(item);
      return;
    }
    if (transactionRank(item) > transactionRank(kept[matchIndex])) {
      kept[matchIndex] = item;
    }
  });
  return kept;
}

// 2026-08-31, Founder-reported after seeing "ISRG BUY $368.74 / ISRG SELL - / ISRG SELL -"
// on his own Trade History and asking whether it was the same duplication bug as the crypto
// universe. It was not: nothing is duplicated, and the order-id dedup above is already
// collapsing the partial fills correctly. Checked against production, NKE's 64 shares filled
// as 7 + 3 + 45 + 9 under ONE order id and collapse to one row as intended.
//
// What remains is three genuinely DIFFERENT orders per position: the buy, plus the two
// resting bracket exits (take-profit and stop-loss) that every buy places. Those are real
// orders, correctly recorded, and they have not executed -- which is why price and amount
// render as blank dashes. Shown in a list headed "Trade History" they read as phantom sales.
//
// A resting stop-loss is a protective order, not a trade. This is the line between them:
// a row belongs in trade history when something actually EXECUTED.
const EXECUTED_STATUSES = new Set([
  'filled', 'fill', 'partially_filled', 'partial_fill', 'closed', 'done', 'settled', 'executed',
]);

// Sources that only ever contain things that already happened. A broker's trade_history and
// a reconciled attribution row are settled records, not order states, and they carry no
// status field to check -- so the source itself is the evidence. Without this the filter was
// too strict and dropped genuine completed trades, caught by an existing test rather than in
// production, which is the right order for that to happen in.
const SETTLED_SOURCES = new Set(['performance_attribution', 'broker_trade', 'managed_exit']);

function isExecutedTrade(item) {
  const normalized = normalizeTradeRow(item);
  if (SETTLED_SOURCES.has(String(item?.event_type || ''))) return true;
  const status = String(normalized.status || '').toLowerCase().replace(/[\s-]/g, '_');
  if (EXECUTED_STATUSES.has(status)) return true;
  // No status is not the same as not executed: some sources carry only a price and quantity.
  // A row with a real fill price is evidence that something happened, whatever it is called.
  if (!status && numeric(normalized.price) !== null) return true;
  return false;
}

// The resting exits, counted so they can be acknowledged rather than silently dropped. The
// Founder should be able to see that his positions are protected without those orders
// masquerading as sales.
function restingProtectiveOrders(transactions) {
  return (transactions || []).filter((item) => {
    if (isExecutedTrade(item)) return false;
    const normalized = normalizeTradeRow(item);
    const status = String(normalized.status || '').toLowerCase();
    return isSell(normalized.side) && (status === 'new' || status === 'held' || status === 'accepted');
  });
}

function allTransactions(status, portfolio, selectedExchange = 'All', performanceAttribution = [], limit = 20) {
  const selected = brokerKey(selectedExchange);
  const attribution = (performanceAttribution || [])
    .filter((item) => selected === 'all' || brokerKey(item.broker) === selected)
    .map((item) => ({
      ...item,
      event_type: 'performance_attribution',
      status: 'closed',
      created_at: item.closed_at || item.created_at,
      raw: parseMaybeJson(item.primary_factors_json),
    }));
  const brokerTrades = (status?.brokers || [])
    .filter((panel) => selected === 'all' || brokerKey(panel.broker || panel.label) === selected)
    .flatMap((panel) => (panel.trade_history || []).map((item) => ({
      ...item,
      broker: item.broker || panel.broker,
      event_type: 'broker_trade',
      created_at: item.closed_at || item.opened_at || item.updated_at,
      raw: parseMaybeJson(item.payload_json) || item,
    })));
  const managedExits = (status?.brokers || [])
    .filter((panel) => selected === 'all' || brokerKey(panel.broker || panel.label) === selected)
    .flatMap((panel) => (panel.managed_exits || []).map((item) => ({
      ...item,
      broker: item.broker || panel.broker,
      event_type: 'managed_open_trade',
      status: item.status || 'open',
      created_at: item.created_at || item.updated_at,
      raw: parseMaybeJson(item.payload_json) || item,
    })));
  const auditRows = (status?.recent_transactions || []).filter((item) => (
    item.event_type === 'execution_approved' || item.event_type === 'execution_rejected'
  ) && (selected === 'all' || brokerKey(item.broker) === selected));
  const fills = (portfolio?.recent_activities || []).map((item) => ({
    event_type: 'broker_fill',
    broker: 'alpaca',
    symbol: item.symbol,
    side: item.side,
    position_size: item.qty,
    price: item.price,
    created_at: item.transaction_time || item.date || item.updated_at,
    raw: item,
  }));
  const orders = (portfolio?.recent_orders || []).map((item) => ({
    event_type: 'broker_order',
    broker: 'alpaca',
    symbol: item.symbol,
    side: item.side,
    position_size: item.qty,
    status: item.status,
    created_at: item.submitted_at || item.updated_at || item.created_at,
    raw: item,
  }));
  const alpacaRows = selected === 'all' || selected === 'alpaca' ? [...fills, ...orders] : [];
  const merged = [...managedExits, ...attribution, ...brokerTrades, ...auditRows, ...alpacaRows]
    .filter((item) => item.created_at || item.symbol || item.event_type)
    .sort((a, b) => dateMs(normalizeTradeRow(b).eventTime) - dateMs(normalizeTradeRow(a).eventTime));
  // Dedup runs on the FULL merged/sorted list, before the limit is applied - otherwise
  // duplicate rows for recent trades could push a genuinely distinct older trade out of the
  // returned window.
  return dedupeTransactions(merged).slice(0, limit);
}

// Executions only -- what belongs under the heading "Trade History".
//
// See isExecutedTrade: resting bracket exits are real orders but not trades, and showing
// them here is what made one ISRG purchase render as a buy and two sells. Callers that need
// the resting orders too (to count them) use allTransactions above.
function combinedTransactions(status, portfolio, selectedExchange = 'All', performanceAttribution = [], limit = 20) {
  return allTransactions(status, portfolio, selectedExchange, performanceAttribution, limit)
    .filter(isExecutedTrade);
}

function describeLatestTrade(value) {
  if (!value || typeof value === 'string') {
    return value;
  }
  return describeTransaction({
    event_type: value.type === 'fill' ? 'broker_fill' : 'broker_order',
    symbol: value.symbol,
    side: value.side,
    position_size: value.qty,
    price: value.price,
    status: value.status,
  });
}

function tradeHistoryBrokers(status) {
  const names = (status?.brokers || [])
    .map((broker) => broker.label || broker.broker)
    .filter(Boolean);
  return ['All', ...Array.from(new Set(names.map((item) => titleCaseBroker(item))))];
}

function titleCaseBroker(value) {
  const text = String(value || '').replaceAll('_', ' ');
  if (!text) {
    return 'Unknown';
  }
  return text.charAt(0).toUpperCase() + text.slice(1);
}

// AT-ED-017 (Founder-reported bug, 2026-08-21): "Daily P&L" was rendered with a plain $ sign
// even while filtered to Kraken (GBP) - the same "one blended figure wearing the wrong symbol"
// class of bug already fixed elsewhere on Current Position (lib/portfolioPosition.js's
// *ByCurrency helpers). Grouped by real currency here too, per-broker via brokerCurrency, so a
// Kraken-only view reads £ and an Alpaca-only view reads $, and an "All" view honestly shows
// both real totals instead of summing GBP into a $ figure.
function tradeHistorySummary(status, trades, selectedExchange) {
  const selected = brokerKey(selectedExchange);
  const brokerPanels = (status?.brokers || []).filter((broker) => (
    selected === 'all' || brokerKey(broker.broker || broker.label) === selected
  ));
  const normalized = (trades || []).map(normalizeTradeRow);
  const todaysClosed = normalized.filter((item) => isToday(item.closedAt || item.eventTime) && terminalTradeStatus(item.status) && !isOpenTrade(item));

  const currenciesWithRealisedEvidence = new Set();
  const realisedPnlByCurrency = {};
  todaysClosed.forEach((item) => {
    const value = numeric(item.profitLoss);
    if (value === null) {
      return;
    }
    const currency = brokerCurrency(item.broker);
    currenciesWithRealisedEvidence.add(currency);
    realisedPnlByCurrency[currency] = (realisedPnlByCurrency[currency] || 0) + value;
  });
  const brokerDayPnlByCurrency = {};
  brokerPanels.forEach((broker) => {
    const value = numeric(broker.todays_pnl);
    if (value === null) {
      return;
    }
    const currency = brokerCurrency(broker.broker || broker.label);
    brokerDayPnlByCurrency[currency] = (brokerDayPnlByCurrency[currency] || 0) + value;
  });
  // Same per-currency fallback rule the original global boolean used, just applied
  // independently per currency instead of gating the whole figure on one shared flag: a
  // currency with real realised evidence today uses that sum, otherwise falls back to that
  // currency's broker-reported day P&L.
  const dailyPnlByCurrency = {};
  new Set([...Object.keys(realisedPnlByCurrency), ...Object.keys(brokerDayPnlByCurrency)]).forEach((currency) => {
    dailyPnlByCurrency[currency] = currenciesWithRealisedEvidence.has(currency)
      ? realisedPnlByCurrency[currency]
      : brokerDayPnlByCurrency[currency];
  });

  const openPositions = brokerPanels
    .map((broker) => Number(broker.open_positions || 0))
    .filter(Number.isFinite)
    .reduce((sum, value) => sum + value, 0);
  // Distinct ORDERS, not event rows. See normalizeTradeRow's orderId comment: the same
  // completed trade arrives as several rows, so `todaysClosed.length` reported 19 on a day
  // with 6. A row with no usable order id still counts once on its own -- under-reporting the
  // Founder's real activity would be a worse failure than counting one row twice.
  const completedOrderIds = new Set();
  let unidentifiedCompleted = 0;
  todaysClosed.forEach((item, index) => {
    if (item.orderId) {
      completedOrderIds.add(String(item.orderId));
    } else {
      unidentifiedCompleted += 1;
    }
  });
  return {
    dailyPnlByCurrency,
    completedTradesToday: completedOrderIds.size + unidentifiedCompleted,
    openPositions,
  };
}

function normalizeTradeRow(item) {
  const raw = item?.raw || item?.payload || parseMaybeJson(item?.payload_json) || {};
  const descr = raw.descr || {};
  const side = firstValue(item?.side, raw.side, raw.order_side, raw.type, descr.type);
  const status = firstValue(item?.status, raw.status, raw.order_status);
  const price = firstNumber(
    item?.price,
    raw.price,
    raw.price2,
    raw.execution_price,
    raw.average_price,
    raw.filled_avg_price,
    raw.avg_price
  );
  const entryPrice = firstNumber(item?.entry_price, item?.entry, raw.entry_price, raw.entryPrice, isBuy(side) ? price : null);
  const exitPrice = firstNumber(item?.exit_price, item?.exit, raw.exit_price, raw.exitPrice, isSell(side) ? price : null);
  const openedAt = firstValue(item?.opened_at, item?.entry_time, raw.opened_at, raw.opentm, raw.entry_time, raw.submitted_at, raw.time);
  const closedAt = firstValue(item?.closed_at, item?.exit_time, raw.closed_at, raw.closetm, raw.exit_time);
  const eventTime = firstValue(item?.created_at, item?.updated_at, item?.closed_at, item?.opened_at, raw.transaction_time, raw.time, raw.date, raw.created_at, raw.updated_at);
  return {
    // 2026-08-27 Founder-reported: the Portfolio card said "Completed today 19" while the
    // Briefing said 13 and the day's real answer was 6. A broker records one row per order
    // EVENT -- a bracketed buy produces new/held/partial_fill/fill/filled -- so counting rows
    // counts paperwork. Carrying the broker's own order id up from the payload lets the
    // summary count orders instead. Mirrors src/ai_trader/trade_counting.py::broker_order_key,
    // which is the same rule on the backend.
    orderId: firstValue(
      item?.broker_order_id, item?.order_id, item?.external_id,
      raw.order_id, raw.orderId, raw.id, raw.txid, raw.ordertxid,
      item?.client_order_id, raw.client_order_id
    ),
    managedExitId: firstNumber(item?.managed_exit_id, raw.managed_exit_id),
    broker: titleCaseBroker(firstValue(item?.broker, raw.broker)),
    symbol: firstValue(item?.symbol, raw.symbol, raw.pair, raw.asset_pair, raw.instrument, descr.pair),
    side,
    status,
    quantity: firstNumber(item?.position_size, item?.quantity, item?.qty, raw.quantity, raw.qty, raw.vol_exec, raw.vol, raw.volume),
    price,
    entryPrice,
    exitPrice,
    targetPrice: firstNumber(item?.take_profit, item?.target_price, raw.take_profit, raw.target_price),
    stopLoss: firstNumber(item?.stop_loss, raw.stop_loss),
    currentPrice: firstNumber(item?.current_price, raw.current_price, raw.last_price),
    profitLoss: firstNumber(item?.profit_loss, item?.pnl, item?.realized_pnl, raw.profit_loss, raw.pnl, raw.realized_pnl),
    fee: firstNumber(item?.fee, raw.fee, raw.commission),
    openedAt,
    closedAt,
    eventTime,
    entryReason: firstValue(item?.entry_reason, item?.ai_reasoning, raw.entry_reason, raw.reasoning),
    exitReason: firstValue(item?.exit_reason, item?.lessons_learned, raw.exit_reason, raw.reason),
  };
}

function isOpenTrade(item) {
  const status = String(item?.status || '').toLowerCase();
  if (status === 'open') {
    return true;
  }
  if (item?.managedExitId && !item?.closedAt) {
    return true;
  }
  if (isBuy(item?.side) && status === 'filled' && !item?.closedAt && !item?.exitPrice) {
    return true;
  }
  if (isBuy(item?.side) && status === 'closed' && !item?.exitPrice) {
    return true;
  }
  return false;
}

function unavailableReason(item, field) {
  if (item?.managedExitId) {
    return 'Not recorded yet';
  }
  if (field === 'target' || field === 'stop') {
    return 'Only available for AI-managed trades';
  }
  if (field === 'current') {
    return 'Live price not returned by broker yet';
  }
  if (field === 'entryReason') {
    return 'Raw broker row - AI reason is stored only on linked AI-managed trades';
  }
  if (field === 'exitReason') {
    return isOpenTrade(item) ? 'Unsold' : 'No exit reason recorded by broker';
  }
  return 'Not recorded';
}

// The commission line for TradeDetail. The table cell has room for a number only; this is
// where the Founder gets the reason behind it, which matters because "0.00" and "we do not
// know" look identical in a 40px column and mean opposite things.
function commissionExplanation(normalized) {
  const fee = normalized?.fee;
  if (fee !== null && fee !== undefined) {
    return historyMoneyOrText(normalized.broker, fee);
  }
  if (isCommissionFreePerTrade(normalized?.broker)) {
    return `${historyMoneyOrText(normalized.broker, 0)} - this broker charges no per-trade `
      + 'commission on US shares. Regulatory fees (SEC, TAF, CAT) are billed daily against the '
      + 'account for that day of trading as a whole, so they cannot be attributed to one trade here.';
  }
  return 'Not recorded by the broker for this row';
}

// 2026-08-27 Founder-reported: a Kraken position rendered as "5e-8". JavaScript switches to
// exponent notation below 1e-6, and crypto quantities routinely go that small -- 0.00000005 of
// a coin is a real holding, but "5e-8" is not a number a person reads. Rendered in full
// instead, with trailing zeros trimmed so ordinary quantities are unaffected.
function formatQuantity(value) {
  const number = numeric(value);
  if (number === null) {
    return value ?? null;
  }
  if (number === 0) {
    return '0';
  }
  if (Math.abs(number) >= 0.001) {
    // Ordinary sizes keep their natural form: 13, 2.5, 0.673.
    return String(Number(number.toFixed(8)));
  }
  // Small enough that JS would use exponent notation. toFixed(12) is beyond any real
  // broker's precision, so nothing meaningful is lost by trimming the trailing zeros.
  return number.toFixed(12).replace(/0+$/, '').replace(/\.$/, '');
}

function firstValue(...values) {
  return values.find((value) => value !== null && value !== undefined && value !== '');
}

function firstNumber(...values) {
  for (const value of values) {
    const parsed = numeric(value);
    if (parsed !== null) {
      return parsed;
    }
  }
  return null;
}

function numeric(value) {
  if (value === null || value === undefined || value === '') {
    return null;
  }
  const number = Number(String(value).replace(/[,$£]/g, ''));
  return Number.isFinite(number) ? number : null;
}

function isBuy(side) {
  return String(side || '').toLowerCase() === 'buy';
}

function isSell(side) {
  return String(side || '').toLowerCase() === 'sell';
}

function terminalTradeStatus(status) {
  const text = String(status || '').toLowerCase();
  return ['closed', 'sold', 'cancelled', 'canceled'].includes(text);
}

function isToday(value) {
  const date = new Date(value || '');
  if (Number.isNaN(date.getTime())) {
    return false;
  }
  const today = new Date();
  return date.getFullYear() === today.getFullYear()
    && date.getMonth() === today.getMonth()
    && date.getDate() === today.getDate();
}

function formatDuration(start, end) {
  const startMs = dateMs(start);
  const endMs = dateMs(end);
  if (!startMs || !endMs || endMs < startMs) {
    return null;
  }
  const minutes = Math.round((endMs - startMs) / 60000);
  if (minutes < 60) {
    return `${minutes} min`;
  }
  const hours = minutes / 60;
  if (hours < 48) {
    return `${hours.toFixed(1)} hours`;
  }
  return `${(hours / 24).toFixed(1)} days`;
}

function formatHoldingDuration(start, end, isOpen) {
  if (isOpen) {
    const startMs = dateMs(start);
    if (!startMs) {
      return null;
    }
    return `${formatDuration(start, new Date().toISOString()) || '0 min'} so far`;
  }
  return formatDuration(start, end);
}

function describeTransaction(item) {
  const normalized = normalizeTradeRow(item);
  const symbol = normalized.symbol ? ` ${normalized.symbol}` : '';
  const side = normalized.side ? ` ${String(normalized.side).toUpperCase()}` : '';
  const sizeValue = normalized.quantity;
  const size = sizeValue ? ` for ${sizeValue}` : '';
  const status = normalized.status ? ` (${normalized.status})` : '';
  const displayStatus = isOpenTrade(normalized) ? ' (holding/unsold)' : status;
  const priceValue = normalized.exitPrice || normalized.price || normalized.entryPrice;
  const price = priceValue ? ` at ${historyMoneyOrText(normalized.broker, priceValue)}` : '';
  const pnl = normalized.profitLoss !== undefined && normalized.profitLoss !== null ? ` P&L ${historyMoneyOrText(normalized.broker, normalized.profitLoss)}` : '';
  const confidence = item.ai_confidence ? ` at ${formatPercent(item.ai_confidence)} confidence` : '';
  return `${friendlyEvent(item.event_type)}${side}${symbol}${size}${price}${pnl}${confidence}${displayStatus}.`;
}

// 2026-08-21 Founder request: Trade History rebuilt as a real column table (Date/Symbol/Side/
// Price/Commission %/Commission/P&L) instead of one dense sentence per trade - the sentence
// form (describeTransaction above) stays as-is for BrokerPanel's single-line "latest confirmed
// trade", where prose still reads naturally; a column table is what a list of many trades
// actually needs. An open/still-held position shows its entry price and reads "Unsold" for P&L
// rather than a blank or a fabricated zero, matching TradeDetail's existing convention for the
// same case.
//
// Commission % uses the exact same per-leg formula the backend's own measured fee rate uses
// (trade_scorecard.py's estimate_round_trip_fee_pct: fee / abs(quantity * price)) - one row here
// is one leg (one fill), not a round trip, so this is that same ratio applied per-row rather
// than aggregated. Never computed from a fabricated/assumed rate - only when this row's own
// real fee, quantity and price are all present.
// 2026-08-23 Founder-reported: the numeric columns rendered notAvailable()'s full sentence
// ("Not available - source data has not been recorded yet.") inside cells a few characters
// wide, and adjustsFontSizeToFit shrank it until it was unreadable -- the Founder saw
// "very small text instead of any values". A compact dash is used in the TABLE only; the
// full honest explanation is still one tap away in TradeDetail (see unavailableReason),
// so nothing is hidden, it is just not crushed into a 40px column. Text columns
// (symbol/side) keep the sentence, since they are wide enough to read it.
const MISSING_NUMERIC_CELL = '-';

// Brokers that charge no per-trade commission, verified against their live API rather than
// assumed. Alpaca US equities: a FILL activity carries no commission field at all, and its
// regulatory fees are billed daily at account level rather than against any one trade.
// Kraken deliberately absent -- it charges a real 0.40%/0.80% maker/taker fee per trade, and
// showing a zero there would be a lie about money.
const COMMISSION_FREE_PER_TRADE = new Set(['alpaca']);

function isCommissionFreePerTrade(broker) {
  return COMMISSION_FREE_PER_TRADE.has(String(broker || '').trim().toLowerCase());
}


function tradeTableRow(item) {
  const normalized = normalizeTradeRow(item);
  const isOpen = isOpenTrade(normalized);
  const priceValue = isOpen ? normalized.entryPrice : (normalized.exitPrice ?? normalized.price ?? normalized.entryPrice);
  const pnlValue = normalized.profitLoss;
  const hasPnl = !isOpen && pnlValue !== null && pnlValue !== undefined;
  // 2026-08-27 Founder-reported: "blank spaces in the trade history card where the commission
  // for maker and taker should sit." Every Alpaca row showed a dash.
  //
  // Checked against the live Alpaca API rather than guessed: a FILL activity carries no
  // commission or fee field at all (keys are activity_type, cum_qty, id, leaves_qty, order_id,
  // order_status, price, qty, side, symbol, transaction_time, type). That is not missing data
  // -- Alpaca charges no per-trade commission on US equities. A dash means "we do not know",
  // which was the wrong answer to a question that has a real one, and it hid a genuine
  // advantage Alpaca has over Kraken's 0.80%.
  //
  // Regulatory fees (SEC/TAF/CAT) do exist on the account, but Alpaca charges them daily at
  // account level for the day's trades collectively, not per fill, so they cannot honestly be
  // attributed to a row here. TradeDetail says so in full; see unavailableReason.
  const commissionFree = isCommissionFreePerTrade(normalized.broker);
  const feeValue = normalized.fee !== null && normalized.fee !== undefined
    ? normalized.fee
    : (commissionFree ? 0 : null);
  const hasFee = feeValue !== null;
  const hasCommissionBasis = hasFee && normalized.quantity && priceValue;
  const commissionPct = hasCommissionBasis ? (feeValue / Math.abs(normalized.quantity * priceValue)) * 100 : null;
  // 2026-08-23 Founder request: "this table should also show the amount put forward to
  // trade for each". Price alone never showed how much money was actually committed --
  // the difference between a GBP 2 and a GBP 25 position was invisible here, which is
  // exactly the sizing problem that took three separate fixes to find this weekend.
  const hasAmount = normalized.quantity !== null && normalized.quantity !== undefined
    && priceValue !== null && priceValue !== undefined;
  const amountValue = hasAmount ? Math.abs(normalized.quantity * priceValue) : null;
  return {
    dateText: formatShortDateTime(normalized.eventTime) || notAvailable(null),
    symbol: normalized.symbol || notAvailable(null),
    side: normalized.side ? String(normalized.side).toUpperCase() : notAvailable(null),
    priceText: priceValue !== null && priceValue !== undefined ? historyMoneyOrText(normalized.broker, priceValue) : MISSING_NUMERIC_CELL,
    amountText: amountValue !== null ? historyMoneyOrText(normalized.broker, amountValue) : MISSING_NUMERIC_CELL,
    commissionPctText: commissionPct !== null ? `${commissionPct.toFixed(2)}%` : MISSING_NUMERIC_CELL,
    commissionText: hasFee ? historyMoneyOrText(normalized.broker, feeValue) : MISSING_NUMERIC_CELL,
    pnlText: isOpen ? 'Unsold' : (hasPnl ? historyMoneyOrText(normalized.broker, pnlValue) : MISSING_NUMERIC_CELL),
    pnlSign: hasPnl ? (pnlValue > 0 ? 'positive' : pnlValue < 0 ? 'negative' : 'neutral') : 'neutral',
  };
}

function tradeKey(item, index) {
  return String(item.attribution_id || item.trade_history_id || item.external_id || item.proposal_id || `${item.created_at}-${item.symbol}-${index}`);
}

function friendlyEvent(eventType) {
  const labels = {
    agent_proposal: 'AI suggested a trade',
    execution_approved: 'Trade placed',
    execution_rejected: 'Trade rejected',
    agent_no_trade: 'No trade suggested',
    analysis_completed: 'Analysis completed',
    engine_control: 'Trading control changed',
    broker_fill: 'Broker fill',
    broker_order: 'Broker order',
    broker_trade: 'Broker trade',
    managed_open_trade: 'AI-managed open trade',
    performance_attribution: 'Closed trade',
  };
  return labels[eventType] || notAvailable(eventType);
}


module.exports = {
  allTransactions,
  isExecutedTrade,
  restingProtectiveOrders,
  combinedTransactions,
  describeLatestTrade,
  describeTransaction,
  normalizeTradeRow,
  isOpenTrade,
  unavailableReason,
  commissionExplanation,
  formatQuantity,
  firstValue,
  firstNumber,
  numeric,
  isBuy,
  isSell,
  terminalTradeStatus,
  isToday,
  formatDuration,
  formatHoldingDuration,
  tradeHistoryBrokers,
  titleCaseBroker,
  tradeHistorySummary,
  tradeKey,
  friendlyEvent,
  dedupeTransactions,
  sameTrade,
  transactionRank,
  tradeTableRow,
};
