// AT-ED-015 Section 10: Founder Actions become genuinely actionable - each item answers What do
// I need to do? Why? Expected benefit? Risk? Deadline? What happens if I do nothing? Kept
// dependency-free (no React/RN imports) - see founderActions.test.js.
//
// Built from the same real recommendation and operational fields every other module in this app
// already reads (`reason_for_recommendation`, `expected_return_r`, `key_risks`, `expires_at` on
// recommendations; `incidents` on operations_health) - not a new evidence source. When there is
// genuinely nothing outstanding, `buildFounderActions()` returns an empty array and the caller
// shows the honest, literal "No Founder action is required today" state (lib/cio.js's
// `cioFounderActionRequired()`), matching the directive's own example verbatim.

'use strict';

const { formatDateTime } = require('./datetime');

function recommendationAction(item) {
  return {
    what: `Review and decide on the ${item.ticker || item.symbol || 'recommendation'} recommendation.`,
    why: item.reason_for_recommendation || 'No one-sentence thesis was recorded for this recommendation.',
    expectedBenefit: item.expected_return_r !== undefined && item.expected_return_r !== null
      ? `${Number(item.expected_return_r).toFixed(2)}R expected return`
      : 'Not estimated for this recommendation',
    risk: item.key_risks || 'Not documented for this recommendation',
    deadline: item.expires_at ? formatDateTime(item.expires_at) : 'No expiry recorded',
    ifNothing: 'This opportunity will expire unreviewed and no trade will be placed on it.',
  };
}

function incidentAction(count) {
  return {
    what: `Review ${count} unresolved operational incident${count === 1 ? '' : 's'}.`,
    why: 'An unresolved incident may be limiting research, execution, or reporting until addressed.',
    expectedBenefit: 'Restores full operational capability.',
    risk: 'Low direct capital risk; primarily an operational and evidence-quality risk.',
    deadline: 'No fixed deadline - review at your convenience.',
    ifNothing: 'The incident remains open and AI Trader continues operating with reduced evidence or capability in that area.',
  };
}

// recommendations: all current recommendations (freshness_status already computed elsewhere);
// unresolvedIncidentCount: real count from operations_health.incidents. Returns [] when nothing
// is genuinely outstanding - never pads the list to make the organisation look busier.
function buildFounderActions({ recommendations, unresolvedIncidentCount = 0, maxRecommendations = 3 }) {
  const actions = (recommendations || [])
    .filter((item) => item.freshness_status !== 'Expired')
    .slice()
    .sort((a, b) => (Number(b.confidence) || 0) - (Number(a.confidence) || 0))
    .slice(0, maxRecommendations)
    .map(recommendationAction);
  if (unresolvedIncidentCount) {
    actions.push(incidentAction(unresolvedIncidentCount));
  }
  return actions;
}

module.exports = {
  recommendationAction,
  incidentAction,
  buildFounderActions,
};
