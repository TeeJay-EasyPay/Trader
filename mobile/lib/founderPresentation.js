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

function operationalLevelTone(level) {
  if (level === 'Normal') return 'good';
  if (level === 'Blocked' || level === 'Degraded') return 'warn';
  if (level === 'Critical') return 'danger';
  return 'neutral';
}

// One derived readiness label per broker, used by Command, Broker Panels, Portfolio, and
// Activity so the same broker never reads "Enabled" on one screen and "Disabled" on another.
// Never says "Disabled" when the DB control is actually enabled, and never says "Healthy"/
// "Ready" merely because a connection exists.
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

// ---------------------------------------------------------------------------
// Activity screen: grouping, collapsing, and Founder-facing framing
// ---------------------------------------------------------------------------

const ACTIVITY_CATEGORY_ORDER = [
  'Research',
  'Recommendations',
  'Decisions',
  'Trades',
  'Portfolio',
  'Broker Operations',
  'Learning',
  'System Health',
  'Founder Actions',
];

// Backend timeline items (_timeline() in production_evidence.py) only carry four raw
// categories: Research, Execution, Learning, System (everything else, keyed by job_name in the
// title). Job names are pattern-matched here to place worker-job events into the finer
// Founder-facing taxonomy without requiring a backend schema change.
const JOB_NAME_CATEGORY_PATTERNS = [
  [/auto-execution/, 'Recommendations'],
  [/broker-poll/, 'Broker Operations'],
  [/reconcil/, 'Broker Operations'],
  [/managed-exits/, 'Portfolio'],
  [/evidence-snapshot/, 'System Health'],
  [/push-dispatch/, 'Founder Actions'],
  [/strategy-lab/, 'Learning'],
  [/report/, 'Founder Actions'],
];

function activityCategoryFor(item) {
  const backendCategory = item?.category;
  if (backendCategory === 'Research') return 'Research';
  if (backendCategory === 'Execution') return 'Trades';
  if (backendCategory === 'Learning') return 'Learning';
  const title = String(item?.title || '').toLowerCase();
  const match = JOB_NAME_CATEGORY_PATTERNS.find(([pattern]) => pattern.test(title));
  return match ? match[1] : 'System Health';
}

function activitySeverityRequiresAttention(item) {
  const outcome = String(item?.outcome || '').toLowerCase();
  return item?.severity === 'failure' || outcome.includes('timed_out') || outcome.includes('failed');
}

// One line answering what/why/outcome/action-required for a (possibly collapsed) event.
function describeActivityEvent(item, category) {
  const actionRequired = activitySeverityRequiresAttention(item);
  const why = {
    Research: 'Research evidence is what feeds new recommendations; a gap here means fewer or no fresh ideas.',
    Recommendations: 'Auto-execution is the only path a recommendation can become a trade through.',
    Decisions: 'Governance decisions are the final gate before any capital is committed.',
    Trades: 'This is a confirmed broker order or fill event.',
    Portfolio: 'Managed-exit checks are what close AI-managed positions on stop-loss/take-profit.',
    'Broker Operations': 'Broker polling and reconciliation are what keep position and order truth current.',
    Learning: 'Learning only runs after a trade is terminal and reconciled.',
    'System Health': 'This is worker/job infrastructure evidence, not a trading outcome by itself.',
    'Founder Actions': 'This is evidence sent toward the Founder (e.g. a push notification), not a Founder-initiated command.',
  }[category] || 'Operational evidence.';
  return {
    what: item?.title || 'Unnamed event',
    why,
    outcome: item?.outcome || item?.summary || 'No outcome recorded.',
    actionRequired,
  };
}

// Groups raw timeline items into the 9 Founder-facing categories, filters to the given cutoff,
// and collapses repeated identical titles (e.g. "auto-execution-alpaca completed_no_action"
// appearing on every worker cycle) into one line with a count and the latest occurrence -
// matching the "Auto execution completed with no eligible action x18" example in the spec.
function groupActivity(items, { sinceIso } = {}) {
  const cutoffMs = sinceIso ? new Date(sinceIso).getTime() : null;
  const filtered = (items || []).filter((item) => {
    if (cutoffMs === null) return true;
    const timeMs = item?.timestamp ? new Date(item.timestamp).getTime() : NaN;
    return Number.isNaN(timeMs) ? true : timeMs >= cutoffMs;
  });

  const buckets = {};
  for (const item of filtered) {
    const category = activityCategoryFor(item);
    const key = String(item.title || 'Unknown event');
    buckets[category] = buckets[category] || {};
    const existing = buckets[category][key];
    if (!existing) {
      buckets[category][key] = { item, count: 1, latestAt: item.timestamp };
    } else {
      existing.count += 1;
      if (!existing.latestAt || (item.timestamp && new Date(item.timestamp) > new Date(existing.latestAt))) {
        existing.latestAt = item.timestamp;
        existing.item = item;
      }
    }
  }

  return ACTIVITY_CATEGORY_ORDER.map((category) => {
    const grouped = Object.values(buckets[category] || {}).sort(
      (a, b) => new Date(b.latestAt || 0).getTime() - new Date(a.latestAt || 0).getTime()
    );
    const events = grouped.map((entry) => ({
      ...describeActivityEvent(entry.item, category),
      count: entry.count,
      latestAt: entry.latestAt,
      broker: entry.item.broker || null,
      symbol: entry.item.symbol || null,
      raw: entry.item,
    }));
    return {
      category,
      totalCount: events.reduce((sum, event) => sum + event.count, 0),
      requiresAttention: events.some((event) => event.actionRequired),
      events,
    };
  });
}

// ---------------------------------------------------------------------------
// Recommendations screen: lifecycle stage
// ---------------------------------------------------------------------------

function formatGuardrailFailures(failures) {
  if (!failures || !failures.length) return null;
  return failures.map((entry) => String(entry).replaceAll('_', ' ')).join(', ');
}

// Best-effort match: a recommendation record has no stable foreign key to a specific broker
// fill in the current evidence model, so a trade is only treated as the outcome of this
// recommendation when broker, symbol, and timing (fill observed within the recommendation's
// created_at..expires_at window, plus a 24h grace period for delayed reconciliation) all line
// up. This is a heuristic, not a guaranteed link - the returned reason says so.
function findMatchingTrade(item, trades) {
  const broker = String(item.suggested_broker || item.broker || '').toLowerCase();
  const symbol = String(item.ticker || item.symbol || '').toUpperCase();
  const createdMs = item.created_at ? new Date(item.created_at).getTime() : NaN;
  if (!broker || !symbol || Number.isNaN(createdMs)) return null;
  const expiresMs = item.expires_at ? new Date(item.expires_at).getTime() : createdMs + 24 * 60 * 60 * 1000;
  const graceMs = 24 * 60 * 60 * 1000;
  return (trades || []).find((trade) => {
    if (String(trade.broker || '').toLowerCase() !== broker) return false;
    if (String(trade.symbol || '').toUpperCase() !== symbol) return false;
    const observedMs = trade.observed_at ? new Date(trade.observed_at).getTime() : NaN;
    if (Number.isNaN(observedMs)) return false;
    return observedMs >= createdMs && observedMs <= expiresMs + graceMs;
  }) || null;
}

// Returns one of: Executed, Expired, Blocked, No Action, Under Review.
// "Generated" (created_at is always present), "Approved", and "Rejected" are not separately
// distinguishable from these five with the evidence currently exposed by /founder-evidence -
// there is no persisted per-recommendation orchestrator decision record to read. Callers should
// show created_at as a plain fact alongside the stage, not claim a 6th/7th/8th distinct stage.
function recommendationLifecycle(item, trades) {
  const confidence = Number(item.confidence_score ?? item.confidence ?? 0);
  const guardrailsPassed = item.guardrails_passed !== false;
  const guardrailText = formatGuardrailFailures(item.guardrail_failures);
  const isExpired = item.freshness_status
    ? item.freshness_status === 'Expired'
    : Boolean(item.expires_at) && new Date(item.expires_at).getTime() < Date.now();

  const matchingTrade = findMatchingTrade(item, trades);
  if (matchingTrade) {
    return {
      stage: 'Executed',
      reason: `Matched to a ${matchingTrade.broker || 'broker'} ${matchingTrade.status || 'fill'} event by broker, symbol, and timing (not a direct database link).`,
      tone: 'good',
    };
  }
  if (isExpired) {
    return { stage: 'Expired', reason: 'This recommendation window has closed. Run new analysis for a fresh idea.', tone: 'neutral' };
  }
  if (!guardrailsPassed) {
    return {
      stage: 'Blocked',
      reason: guardrailText ? `Execution guardrails failed: ${guardrailText}.` : 'Execution guardrails did not pass at generation time.',
      tone: 'warn',
    };
  }
  if (confidence < 0.85) {
    return { stage: 'No Action', reason: 'Confidence is below the 85% auto-trade threshold.', tone: 'neutral' };
  }
  return { stage: 'Under Review', reason: 'Eligible for auto-trade; awaiting the next execution cycle or expiry.', tone: 'good' };
}

// ---------------------------------------------------------------------------
// Portfolio screen: AI-managed vs manual holdings
// ---------------------------------------------------------------------------

// A raw broker position is only ever labelled AI-managed when it has an explicit, open
// MANAGED_TRADE_EXITS row for the same symbol - the AI's own tracked entry/exit record. There
// is no heuristic fallback: if there is no managed-exit row, the position is presented as a
// plain holding, never guessed to be AI-managed.
function positionOwnership(position, managedExits) {
  const symbol = String(position?.symbol || '').toUpperCase();
  const match = (managedExits || []).find((exit) => String(exit.symbol || '').toUpperCase() === symbol && exit.status === 'open');
  if (!match) {
    return { isAiManaged: false, managedExit: null };
  }
  return { isAiManaged: true, managedExit: match };
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

module.exports = {
  operationalRollup,
  operationalLevelTone,
  brokerOverallReadiness,
  ACTIVITY_CATEGORY_ORDER,
  activityCategoryFor,
  describeActivityEvent,
  groupActivity,
  recommendationLifecycle,
  positionOwnership,
  learningSummary,
};
