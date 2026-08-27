// Pure presentation-logic helpers shared across mobile/App.js screens (Command, Activity,
// Recommendations, Portfolio, Learning). Kept dependency-free (no React/React Native imports)
// so these can be required directly from a plain Node test script without a bundler or test
// framework - see founderPresentation.test.js.
//
// Every function here is a *read* over fields the backend already computes and exposes via
// /founder-evidence (see src/ai_trader/production_evidence.py). None of them invent data the
// backend does not provide; where the evidence is genuinely insufficient to answer a question
// precisely (e.g. distinguishing "Approved" from "Executed"), the function says so explicitly
// rather than guessing.

'use strict';

const { formatDateTime } = require('./datetime');
const { explainMissing } = require('./notAvailable');
const { gbpOrText } = require('./money');

// ---------------------------------------------------------------------------
// Operational rollup (Command screen summary card)
// ---------------------------------------------------------------------------

// Single Normal/Degraded/Blocked/Critical rollup, grounded only in fields the backend already
// computes:
//  - operatingState comes from _operating_state() in production_evidence.py: "NOT OPERATING"
//    (worker heartbeat stale), "OPERATING WITH WARNINGS" (a recent job failed, or the served
//    snapshot itself is stale), or "OPERATING NORMALLY".
//  - "Blocked" is a distinct axis from system health: a broker can be fully healthy and still
//    have new entries intentionally gated (Kraken's reconciliation hold is the current example)
//    while auto_trading_enabled is true. That must never collapse into "Degraded"/"Critical",
//    since nothing is actually broken -- it is a deliberate governance gate.
function operationalRollup({ operatingState, plainEnglish, liveWorker, brokerPanels, generatedAt }) {
  const blockedBrokers = (brokerPanels || []).filter((broker) => broker.auto_trading_enabled === true && broker.block_reason);
  const base = {
    deployed_commit: liveWorker?.deployment_commit || null,
    last_heartbeat_at: liveWorker?.last_heartbeat_at || null,
    generated_at: generatedAt || null,
  };
  if (operatingState === 'NOT OPERATING') {
    return { ...base, level: 'Critical', reason: plainEnglish || 'The background worker has not reported a fresh heartbeat.' };
  }
  if (operatingState === 'OPERATING WITH WARNINGS') {
    return { ...base, level: 'Degraded', reason: plainEnglish || 'A recent scheduled job failed or the served evidence snapshot is stale.' };
  }
  if (blockedBrokers.length) {
    const names = blockedBrokers.map((broker) => broker.label).join(', ');
    return { ...base, level: 'Blocked', reason: `${names} auto trading is enabled but new entries are blocked: ${blockedBrokers[0].block_reason}` };
  }
  return { ...base, level: 'Normal', reason: plainEnglish || 'All systems operating normally.' };
}

function brokerOverallReadiness(broker) {
  if (!broker) {
    return { label: 'Data Unavailable', tone: 'neutral', newEntriesAllowed: null };
  }
  if (String(broker.connection_status || '').toLowerCase() !== 'connected') {
    return { label: 'Data Unavailable', tone: 'neutral', newEntriesAllowed: null };
  }
  if (broker.auto_trading_enabled === true && broker.block_reason) {
    return { label: 'Enabled but Blocked', tone: 'warn', newEntriesAllowed: false };
  }
  if (broker.auto_trading_enabled === true) {
    return { label: 'Ready', tone: 'good', newEntriesAllowed: true };
  }
  if (broker.auto_trading_enabled === false) {
    return { label: 'Disabled by Founder', tone: 'neutral', newEntriesAllowed: false };
  }
  return { label: 'Unknown', tone: 'neutral', newEntriesAllowed: null };
}

// AT-ED-012: one plain-English sentence summarising a broker's connection/trading state,
// read from the same fields brokerOverallReadiness() already classifies - shown above the
// metric grid in BrokerPanel so the Founder gets the story before the numbers.
function brokerReadinessSentence(broker) {
  const label = broker?.label || broker?.broker || 'This broker';
  const isKraken = String(broker?.broker || '').toLowerCase() === 'kraken';
  const mode = isKraken ? 'live trading' : 'paper trading';
  const connected = String(broker?.connection_status || '').toLowerCase() === 'connected';
  if (!connected) {
    return `${label} is not currently connected, so AI Trader cannot see live balances or place trades here.`;
  }
  if (broker.auto_trading_enabled === true && broker.block_reason) {
    return `${label} is connected and set up for ${mode}, but new trades are paused right now: ${broker.block_reason}`;
  }
  if (broker.auto_trading_enabled === true) {
    return `${label} is connected and ready - AI Trader can open new ${mode} positions here.`;
  }
  if (broker.auto_trading_enabled === false) {
    return `${label} is connected, but automatic trading here is turned off by the Founder.`;
  }
  return `${label} is connected. Whether it's allowed to trade has not been recorded yet.`;
}

// AT-ED-012 Phase 4 financial-terminology audit: for Kraken specifically, "Portfolio"/"Cash"
// (balance_summary.total_estimated_gbp/gbp_cash - see broker_service.py's _exchange_portfolio)
// describe the Founder's WHOLE personal Kraken account, not just what AI Trader manages -
// unlike Alpaca, which is a dedicated paper account with no such split. Read only, never
// computed here: explains an existing distinction, invents nothing.
function krakenWholeAccountNote(broker) {
  if (String(broker?.broker || '').toLowerCase() !== 'kraken') {
    return null;
  }
  return 'Kraken is your own personal account. The figures below cover everything in it - your existing holdings plus the amount AI Trader is allowed to manage - not just the AI\'s own activity.';
}

// ---------------------------------------------------------------------------
// Activity screen: grouping, collapsing, and Founder-facing framing
// ---------------------------------------------------------------------------

function positionOwnership(position, managedExits) {
  const symbol = String(position?.symbol || '').toUpperCase();
  const match = (managedExits || []).find((exit) => String(exit.symbol || '').toUpperCase() === symbol && exit.status === 'open');
  if (!match) {
    return { isAiManaged: false, managedExit: null };
  }
  return { isAiManaged: true, managedExit: match };
}

// AT-ED-012: one short, honest sentence for the top of the Portfolio screen, replacing a
// static question ("Where is capital, where is risk...") with an actual answer. Takes an
// already-formatted, currency-correct P&L string rather than formatting money itself, so
// currency handling stays in lib/money.js/the screen - this only composes sentence structure
// from numbers the screen already computed.
function portfolioHeadline({ openPositionsCount, pnlText, pnlIsPositive, atLossCount }) {
  if (openPositionsCount === null || openPositionsCount === undefined) {
    return 'Portfolio detail is not available yet - check back after the next successful refresh.';
  }
  const positionsSentence = openPositionsCount === 0
    ? 'AI Trader currently holds no open positions.'
    : `You have ${openPositionsCount} open position${openPositionsCount === 1 ? '' : 's'}${pnlText ? `, ${pnlIsPositive ? 'up' : 'down'} ${pnlText} today` : ''}.`;
  const attentionSentence = atLossCount
    ? ` ${atLossCount} position${atLossCount === 1 ? ' is' : 's are'} currently at a loss and worth a look.`
    : ' Nothing here currently needs your attention.';
  return `${positionsSentence}${attentionSentence}`;
}

// ---------------------------------------------------------------------------
// Learning screen: concise summary + single empty-state
// ---------------------------------------------------------------------------

const CLOSED_TRADE_STATUSES = new Set(['closed', 'target_exit', 'stop_exit', 'manual_exit']);

// Everything here is read from evidence.learning (PRODUCTION_LEARNING_EVIDENCE) and
// evidence.trades/evidence.recommendations. Strategy-change-proposal approval status is not
// currently exposed by /founder-evidence (no strategy-promotion record is included in the
// projection), so missingEvidence says so explicitly instead of the screen fabricating a
// proposal or an approval state.
function learningSummary(evidence) {
  const learning = evidence?.learning || [];
  const trades = evidence?.trades || [];
  const recommendations = evidence?.recommendations || [];
  const closedTrades = trades.filter((trade) => CLOSED_TRADE_STATUSES.has(String(trade.status || '').toLowerCase()));
  const strategiesEvaluated = new Set(
    recommendations.map((item) => item.strategy_id || item.strategy_name).filter(Boolean)
  ).size;
  const latestLesson = learning.length ? learning[0].summary || null : null;
  const hasEnoughEvidence = closedTrades.length > 0 && learning.length > 0;

  let missingEvidence;
  if (closedTrades.length === 0) {
    missingEvidence = 'No completed, reconciled trades exist yet in this period. Learning only runs after a trade is terminal.';
  } else if (learning.length === 0) {
    missingEvidence = `${closedTrades.length} trade(s) have closed, but the learning processor has not completed a review yet.`;
  } else {
    missingEvidence = 'Strategy-change-proposal approval status is not yet exposed in this evidence projection.';
  }

  return {
    completedTradesReviewed: closedTrades.length,
    strategiesEvaluated,
    latestLesson,
    latestProposal: null,
    proposalApproved: null,
    hasEnoughEvidence,
    missingEvidence,
  };
}

// ---------------------------------------------------------------------------
// Cross-screen tone/status text (AT-ED-011 Phase 2: shared by 2+ screens, so kept here
// rather than colocated in a single screen file - see architecture/ARCHITECTURE_DELTA.md)
// ---------------------------------------------------------------------------

function yesNo(value) {
  if (value === null || value === undefined) {
    return null;
  }
  return value ? 'Yes' : 'No';
}

function enabledDisabled(value) {
  if (value === null || value === undefined) {
    return null;
  }
  return value ? 'Enabled' : 'Disabled';
}

function connectedFounderBrokers(brokers) {
  return (brokers || []).filter((item) => ['alpaca', 'kraken'].includes(String(item.broker || '').toLowerCase()));
}

function formatReconciliation(items) {
  if (!items || !items.length) {
    return 'Awaiting broker reconciliation - no reconciliation run has been recorded yet.';
  }
  return items.slice(0, 5).map((item) => `${item.broker}: ${item.status}. ${item.summary}`).join('\n');
}

function riskTone(value) {
  const text = String(value || '').toLowerCase();
  if (text.includes('high') || text.includes('poor') || text.includes('weak') || text.includes('attention') || text.includes('risk')) {
    return 'danger';
  }
  if (text.includes('medium') || text.includes('mixed') || text.includes('developing') || text.includes('caution')) {
    return 'warn';
  }
  if (text.includes('healthy') || text.includes('good') || text.includes('ready') || text.includes('low')) {
    return 'good';
  }
  return 'neutral';
}

function formatKrakenAssets(items, converted) {
  if (!items || !items.length) {
    return converted ? 'No priced crypto assets converted.' : 'No excluded assets reported.';
  }
  return items.map((item) => {
    if (converted) {
      return `- ${item.normalized_asset || item.asset}: ${item.quantity} via ${item.pair}, value ${gbpOrText(item.value_gbp)}`;
    }
    return `- ${item.normalized_asset || item.asset}: ${item.quantity}, reason ${item.reason || 'not valued'}`;
  }).join('\n');
}

function formatRawKrakenBalances(items) {
  if (!items || !items.length) {
    return 'No non-zero Kraken balances were returned by the API.';
  }
  return items.map((item) => `- ${item.normalized_asset || item.asset}: ${item.quantity} (${item.asset})`).join('\n');
}

module.exports = {
  operationalRollup,
  brokerOverallReadiness,
  brokerReadinessSentence,
  krakenWholeAccountNote,
  positionOwnership,
  portfolioHeadline,
  learningSummary,
  yesNo,
  enabledDisabled,
  connectedFounderBrokers,
  formatReconciliation,
  riskTone,
  formatKrakenAssets,
  formatRawKrakenBalances,
};
