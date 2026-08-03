// Pure recommendation-domain logic used by the Recommendations screen: freshness/expiry
// derivation, auto-trade eligibility text, filtering/grouping, and the per-recommendation
// evidence formatters (committee, signals, lifecycle, exit plan).
// Extracted from App.js as part of AT-ED-011 Phase 2 (mobile modularisation).

'use strict';

const { formatPercent, formatDateTime } = require('./datetime');
const { notAvailable } = require('./notAvailable');
const { formatGuardrailFailures } = require('./founderPresentation');

function withRecommendationFreshness(item) {
  if (item.freshness_status && item.expires_at) {
    return item;
  }
  const generatedAt = item.created_at ? new Date(item.created_at) : null;
  if (!generatedAt || Number.isNaN(generatedAt.getTime())) {
    return {
      ...item,
      freshness_status: item.freshness_status || null,
      freshness_note: item.freshness_note || null,
      auto_trade_eligible: item.auto_trade_eligible,
    };
  }
  const confidence = Number(item.confidence || 0);
  const lifetimeHours = confidence >= 0.85 ? 4 : confidence >= 0.75 ? 12 : 24;
  const expiresAt = new Date(generatedAt.getTime() + lifetimeHours * 60 * 60 * 1000);
  const now = new Date();
  const halfLife = new Date(generatedAt.getTime() + (lifetimeHours / 2) * 60 * 60 * 1000);
  const freshness = now > expiresAt ? 'Expired' : now > halfLife ? 'Stale' : 'Fresh';
  return {
    ...item,
    expires_at: item.expires_at || expiresAt.toISOString(),
    freshness_status: item.freshness_status || freshness,
    freshness_note: item.freshness_note || `${freshness}. This trade idea expires after ${lifetimeHours} hours.`,
    auto_trade_eligible:
      item.auto_trade_eligible ?? (
        freshness !== 'Expired'
        && confidence >= 0.85
        && item.guardrails_passed !== false
        && item.already_executed !== true
      ),
    auto_trade_reason: item.auto_trade_reason || clientAutoTradeReason(item, confidence, freshness),
    guardrail_summary: item.guardrail_summary || formatGuardrailFailures(item.guardrail_failures),
  };
}

function clientAutoTradeReason(item, confidence, freshness) {
  if (item.already_executed) {
    return 'Already executed.';
  }
  if (freshness === 'Expired') {
    return 'Expired. Run new analysis before execution.';
  }
  if (confidence < 0.85) {
    return 'Confidence is below 85%.';
  }
  if (item.guardrails_passed === false) {
    const guardrails = formatGuardrailFailures(item.guardrail_failures);
    if (guardrails) {
      return `Execution guardrails failed: ${guardrails}.`;
    }
    return 'Execution guardrails did not pass, so auto-trade is blocked.';
  }
  return 'Eligible for paper auto-trade.';
}

function formatGuardrailChecks(checks, status) {
  if (!checks || !checks.length) {
    return null;
  }
  const matching = checks.filter((item) => item.status === status);
  if (!matching.length) {
    return status === 'failed' ? 'None' : null;
  }
  return matching.map((item) => `- ${item.label || String(item.key).replaceAll('_', ' ')}`).join('\n');
}

function marketRegimeText(regime) {
  if (!regime) {
    return null;
  }
  const primary = regime.primary_regime || 'unknown';
  const trend = regime.trend_regime || 'unknown trend';
  const risk = regime.risk_regime || 'neutral';
  return `${primary}; ${trend}; ${risk}`;
}

function rMultiple(value) {
  if (value === null || value === undefined || value === '') {
    return null;
  }
  const number = Number(value);
  if (Number.isNaN(number)) {
    return String(value);
  }
  return `${number.toFixed(2)}R`;
}

function committeeSummary(committee) {
  if (!committee) {
    return null;
  }
  const result = committee.committee_result ? `Result: ${committee.committee_result}` : null;
  const votes = Array.isArray(committee.member_votes) ? committee.member_votes : [];
  const voteText = votes
    .slice(0, 6)
    .map((vote) => `${vote.member}: ${vote.vote} (${formatPercent(vote.score)})`)
    .join('\n');
  return [result, voteText].filter(Boolean).join('\n');
}

function signalSummary(signals) {
  if (!Array.isArray(signals) || !signals.length) {
    return null;
  }
  return signals
    .slice(0, 6)
    .map((signal) => `${signal.signal_name}: ${formatPercent(signal.score)} weight ${formatPercent(signal.weight)}`)
    .join('\n');
}

function lifecycleSummary(stages) {
  if (!Array.isArray(stages) || !stages.length) {
    return null;
  }
  return stages
    .slice(-5)
    .map((stage) => `${formatDateTime(stage.created_at)} - ${stage.stage}: ${stage.stage_reason}`)
    .join('\n');
}

function uniqueValues(items) {
  return [...new Set(items.map((item) => String(item)).filter(Boolean))];
}

function groupRecommendations(items) {
  return items.reduce((groups, item) => {
    const broker = item.suggested_broker || item.exchange || 'Unassigned';
    if (!groups[broker]) {
      groups[broker] = [];
    }
    groups[broker].push(item);
    groups[broker].sort((a, b) => (Number(b.confidence || 0) - Number(a.confidence || 0)));
    return groups;
  }, {});
}

function filterRecommendations(items, brokerFilter, confidenceFilter, assetTypeFilter, statusFilter) {
  return items.filter((item) => {
    const broker = item.suggested_broker || item.exchange || 'Unassigned';
    if (brokerFilter !== 'All' && broker !== brokerFilter) {
      return false;
    }
    if (assetTypeFilter !== 'All' && item.asset_type !== assetTypeFilter) {
      return false;
    }
    if (statusFilter !== 'All' && item.freshness_status !== statusFilter) {
      return false;
    }
    const confidence = Number(item.confidence || 0);
    if (confidenceFilter === '85%+' && confidence < 0.85) {
      return false;
    }
    if (confidenceFilter === '90%+' && confidence < 0.9) {
      return false;
    }
    return true;
  });
}

function exitPlan(item) {
  const stop = notAvailable(item.suggested_stop_loss);
  const take = notAvailable(item.suggested_take_profit);
  return `If executed, the broker order is submitted as a bracket order with stop loss ${stop} and take profit ${take}.`;
}

function probabilityRange(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return 'Not available - probability model did not return a value.';
  const lower = Math.max(0, number - 0.05);
  const upper = Math.min(1, number + 0.05);
  return `${Math.round(lower * 100)}%-${Math.round(upper * 100)}%`;
}

module.exports = {
  withRecommendationFreshness,
  clientAutoTradeReason,
  formatGuardrailChecks,
  marketRegimeText,
  rMultiple,
  committeeSummary,
  signalSummary,
  lifecycleSummary,
  uniqueValues,
  groupRecommendations,
  filterRecommendations,
  exitPlan,
  probabilityRange,
};
