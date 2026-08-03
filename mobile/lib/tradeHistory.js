// Trade/transaction interpretation and formatting shared across the Dashboard and Portfolio
// screens (BrokerPanel's latest-trade line, the Portfolio trade history list and detail view).
// Extracted from App.js as part of AT-ED-011 Phase 2 (mobile modularisation).

'use strict';

const { brokerKey, historyMoneyOrText } = require('./money');
const { dateMs, formatPercent } = require('./datetime');
const { notAvailable } = require('./notAvailable');
const { parseMaybeJson } = require('./json');

function combinedTransactions(status, portfolio, selectedExchange = 'All', performanceAttribution = [], limit = 20) {
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
  return [...managedExits, ...attribution, ...brokerTrades, ...auditRows, ...alpacaRows]
    .filter((item) => item.created_at || item.symbol || item.event_type)
    .sort((a, b) => dateMs(normalizeTradeRow(b).eventTime) - dateMs(normalizeTradeRow(a).eventTime))
    .slice(0, limit);
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

function tradeHistorySummary(status, trades, selectedExchange) {
  const selected = brokerKey(selectedExchange);
  const brokerPanels = (status?.brokers || []).filter((broker) => (
    selected === 'all' || brokerKey(broker.broker || broker.label) === selected
  ));
  const normalized = (trades || []).map(normalizeTradeRow);
  const todaysClosed = normalized.filter((item) => isToday(item.closedAt || item.eventTime) && terminalTradeStatus(item.status) && !isOpenTrade(item));
  const realisedPnl = todaysClosed
    .map((item) => numeric(item.profitLoss))
    .filter((value) => value !== null)
    .reduce((sum, value) => sum + value, 0);
  const brokerDayPnl = brokerPanels
    .map((broker) => numeric(broker.todays_pnl))
    .filter((value) => value !== null)
    .reduce((sum, value) => sum + value, 0);
  const openPositions = brokerPanels
    .map((broker) => Number(broker.open_positions || 0))
    .filter(Number.isFinite)
    .reduce((sum, value) => sum + value, 0);
  return {
    dailyPnl: todaysClosed.some((item) => numeric(item.profitLoss) !== null) ? realisedPnl : brokerDayPnl,
    completedTradesToday: todaysClosed.length,
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
  combinedTransactions,
  describeLatestTrade,
  describeTransaction,
  normalizeTradeRow,
  isOpenTrade,
  unavailableReason,
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
};
