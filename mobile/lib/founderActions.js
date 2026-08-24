// AT-ED-015 Section 10 / AT-ED-016.1 Communication Refinement: Founder Actions as advice, not
// status. AT-ED-016.1 collapsed the original six-field grid (What/Why/Expected Benefit/Risk/
// Deadline/If You Do Nothing) into a single spoken recommendation plus a plain consequence
// sentence - the same real underlying fields (`reason_for_recommendation`, `expires_at`,
// `incidents`), just said the way a CIO would say them rather than laid out as a form. Kept
// dependency-free (no React/RN imports) - see founderActions.test.js.
//
// When there is genuinely nothing outstanding, `buildFounderActions()` returns an empty array
// and the caller uses `lib/cio.js`'s `cioNoActionReason()` - never pads the list to make the
// organisation look busier.

'use strict';

const { formatDateTime } = require('./datetime');
const { wasRejectedByCommittee } = require('./principalOpportunities');

// 2026-08-24 Founder-reported: this card rendered reason_for_recommendation in FULL. For KSM
// that was a multi-paragraph essay on position-sizing theory, complete with literal
// "**markdown**" asterisks and hard line breaks mid-sentence -- pages of general trading
// theory in the one card that is supposed to say "here is what needs you, in a line".
// Exactly the wall-of-text problem just removed from The View Ahead, reappearing here.
//
// Keeps the first couple of real sentences and drops the rest: enough to know WHY without
// the essay. The full text is still on the recommendation itself for anyone who wants it.
function summariseReason(text, maxChars = 220) {
  const flat = String(text || '')
    .replace(/\*\*/g, '')       // literal markdown bold that never renders
    .replace(/[#`>]/g, '')
    .replace(/\s+/g, ' ')        // hard line breaks mid-sentence
    .trim();
  if (!flat) {
    return '';
  }
  if (flat.length <= maxChars) {
    return flat;
  }
  const cut = flat.slice(0, maxChars);
  const lastStop = Math.max(cut.lastIndexOf('. '), cut.lastIndexOf('? '), cut.lastIndexOf('! '));
  // Prefer ending on a real sentence, but never return a uselessly short fragment.
  return lastStop > maxChars * 0.4 ? cut.slice(0, lastStop + 1) : `${cut.trimEnd()}...`;
}

function recommendationAction(item) {
  const name = item.ticker || item.symbol || 'this recommendation';
  const summarised = summariseReason(item.reason_for_recommendation);
  const reason = summarised ? ` ${summarised}` : '';
  const byWhen = item.expires_at ? ` before ${formatDateTime(item.expires_at)}` : '';
  return {
    title: name,
    recommendation: `I recommend reviewing ${name}${byWhen}.${reason}`,
    ifNothing: 'If you take no action, this simply expires unreviewed - no trade will be placed.',
  };
}

function incidentAction(count) {
  return {
    title: `${count} operational item${count === 1 ? '' : 's'} behind the scenes`,
    recommendation: `I recommend taking a look at ${count} open item${count === 1 ? '' : 's'} behind the scenes when convenient. Nothing here needs urgent attention.`,
    ifNothing: 'These stay open and may quietly limit some of the evidence I can bring you until addressed.',
  };
}

// AT-ED-017 (Founder request, 2026-08-05): a recommendation AI Trader's own investment committee
// already rejected (see wasRejectedByCommittee() in lib/principalOpportunities.js) is not a real
// decision awaiting the Founder - governance already made the call. Asking the Founder to
// "review" it implies a choice that isn't actually open, which is exactly the confusion a live
// Founder report flagged ("why am I being asked to review FRES if the app is autotrading?").
//
// recommendations: all current recommendations (freshness_status already computed elsewhere);
// unresolvedIncidentCount: real count from operations_health.incidents. Returns [] when nothing
// is genuinely outstanding - never pads the list to make the organisation look busier.
function buildFounderActions({ recommendations, unresolvedIncidentCount = 0, maxRecommendations = 3 }) {
  const actions = (recommendations || [])
    .filter((item) => item.freshness_status !== 'Expired' && !wasRejectedByCommittee(item))
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
  summariseReason,
  recommendationAction,
  incidentAction,
  buildFounderActions,
};
