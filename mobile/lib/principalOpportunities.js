// AT-ED-015 Section 7: Principal Opportunities as individual, structured cards - each gets its
// own Why / Evidence / Expected Benefit / Confidence / Time Horizon, built from real
// recommendation and theme fields the app already fetches (Recommendations.js already renders
// `reason_for_recommendation`, `expected_return_r`, `confidence`, and `expires_at` per item -
// this reuses the same fields, not a new evidence source). Kept dependency-free (no React/RN
// imports) - see principalOpportunities.test.js.

'use strict';

const { formatPercent, formatDateTime } = require('./datetime');

// AT-ED-016 Part 1 Section 8: Catalyst, added alongside Why/Evidence/Expected Benefit/Confidence/
// Time Horizon. For a recommendation, the catalyst is its `strongest_argument_for` - a real,
// distinct field Recommendations.js already renders (`item.strongest_argument_for`), separate
// from `reason_for_recommendation` ("Why") so the two fields never just repeat each other.
function recommendationOpportunityCard(item) {
  return {
    title: item.ticker || item.symbol || 'Recommendation',
    why: item.reason_for_recommendation || 'No one-sentence thesis was recorded for this recommendation.',
    evidence: item.strategy_name || item.strategy_id || 'Strategy not recorded',
    expectedBenefit: item.expected_return_r !== undefined && item.expected_return_r !== null
      ? `${Number(item.expected_return_r).toFixed(2)}R expected return`
      : 'Not estimated for this recommendation',
    confidence: item.confidence !== undefined && item.confidence !== null ? formatPercent(item.confidence) : 'Not available',
    timeHorizon: item.expires_at ? `Actionable until ${formatDateTime(item.expires_at)}` : 'Not specified',
    catalyst: item.strongest_argument_for || 'No specific catalyst recorded for this recommendation.',
  };
}

// AT-ED-015.1 root cause fix: /intelligence/themes returns `key_drivers` as a plain string in
// production (confirmed via a live emulator reproduction - see Root_Cause_Analysis.md), not the
// array this originally assumed. `.slice(0, 3).join('; ')` on a string throws
// "theme.key_drivers.slice(...).join is not a function" (String has no .join), which crashed
// PrincipalOpportunitiesSection's render with no error boundary to catch it, blanking the whole
// app. Normalized the same way lib/investmentThesis.js's alternativeThesis() already handles the
// identical shape ambiguity for theme.key_risks (Array.isArray(...) ? ... : [...]), so both
// theme-derived list fields use one consistent, safe pattern.
function keyDriversList(theme) {
  const raw = theme.key_drivers;
  if (!raw) {
    return [];
  }
  const list = Array.isArray(raw) ? raw : [raw];
  return list.filter(Boolean);
}

function keyDriversText(theme) {
  const list = keyDriversList(theme).slice(0, 3);
  return list.length ? list.join('; ') : 'No key drivers recorded';
}

// AT-ED-016 Part 1 Section 8: for a theme, the catalyst is its first documented key driver - the
// same real, already-normalized (string-or-array-safe, see keyDriversText's AT-ED-015.1 history)
// evidence keyDriversText draws from, just the single leading item rather than a joined list.
function themeOpportunityCard(theme) {
  const drivers = keyDriversList(theme);
  return {
    title: theme.theme,
    why: theme.summary || theme.current_outlook || 'No thematic summary recorded.',
    evidence: keyDriversText(theme),
    expectedBenefit: theme.current_outlook || 'Not specified',
    confidence: theme.confidence !== undefined && theme.confidence !== null ? formatPercent(theme.confidence) : 'Not available',
    timeHorizon: 'Not specified - thematic view, not a dated trade',
    catalyst: drivers.length ? drivers[0] : 'No specific catalyst recorded for this theme.',
  };
}

// recommendations: fresh (non-expired) recommendations only, sorted by confidence, take the top
// `maxRecommendations`. themes: at most one, the highest-confidence tracked theme, if any exists.
function buildOpportunityCards({ recommendations, themes, maxRecommendations = 3 }) {
  const fresh = (recommendations || [])
    .filter((item) => item.freshness_status !== 'Expired')
    .slice()
    .sort((a, b) => (Number(b.confidence) || 0) - (Number(a.confidence) || 0))
    .slice(0, maxRecommendations)
    .map(recommendationOpportunityCard);

  const topTheme = (themes || [])
    .filter((item) => item && item.theme)
    .slice()
    .sort((a, b) => (Number(b.confidence) || 0) - (Number(a.confidence) || 0))[0];

  return topTheme ? [...fresh, themeOpportunityCard(topTheme)] : fresh;
}

module.exports = {
  recommendationOpportunityCard,
  keyDriversText,
  themeOpportunityCard,
  buildOpportunityCards,
};
