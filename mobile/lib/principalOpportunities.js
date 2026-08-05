// AT-ED-015 Section 7: Principal Opportunities as individual, structured cards - each gets its
// own Why / Evidence / Expected Benefit / Confidence / Time Horizon, built from real
// recommendation and theme fields the app already fetches (Recommendations.js already renders
// `reason_for_recommendation`, `expected_return_r`, `confidence`, and `expires_at` per item -
// this reuses the same fields, not a new evidence source). Kept dependency-free (no React/RN
// imports) - see principalOpportunities.test.js.

'use strict';

const { formatPercent } = require('./datetime');

// AT-ED-016.1 Communication Refinement: collapsed from six fields (Why/Evidence/Expected
// Benefit/Confidence/Time Horizon/Catalyst) to exactly the four a CIO would actually say - Why I
// Like It / Potential Upside / Main Catalyst / Confidence. The catalyst is `strongest_argument_for`
// - a real, distinct field Recommendations.js already renders, separate from
// `reason_for_recommendation` ("Why I Like It") so the two never just repeat each other.
function recommendationOpportunityCard(item) {
  return {
    title: item.ticker || item.symbol || 'Recommendation',
    whyILikeIt: item.reason_for_recommendation || 'I do not have a documented thesis for this one yet.',
    // AT-ED-017 (live-review fix): "0.15R if this plays out as expected" - "R" is a trading-desk
    // risk-multiple unit (gain as a multiple of the amount risked) a non-technical Founder has no
    // reason to know. Same real number, explained in plain English instead of jargon.
    potentialUpside: item.expected_return_r !== undefined && item.expected_return_r !== null
      ? `If this plays out as expected, the gain is about ${Number(item.expected_return_r).toFixed(2)} times the amount being risked on this trade.`
      : 'Not yet estimated',
    catalyst: item.strongest_argument_for || 'No specific catalyst identified yet.',
    confidence: item.confidence !== undefined && item.confidence !== null ? formatPercent(item.confidence) : 'Not available',
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
// AT-ED-017 (live-review fix): production key_drivers is consistently a single semicolon-joined
// string (see intelligence_data.py - every theme's key_drivers is "Item A; Item B; Item C."), not
// an array of individual items. Wrapping the whole string as one array element meant every
// consumer of "the first driver" (themeOpportunityCard's catalyst, below) showed the ENTIRE
// semicolon-joined list instead of one real catalyst - confirmed live on the emulator ("Main
// catalyst: Passenger demand; premium travel; cargo; capacity discipline; tourism flows." where
// only "Passenger demand" was intended). Splitting a string input on semicolons gives real
// individual items; a genuine array input (or a string with no semicolon) behaves as before.
function keyDriversList(theme) {
  const raw = theme.key_drivers;
  if (!raw) {
    return [];
  }
  const list = Array.isArray(raw) ? raw : String(raw).split(';').map((item) => item.trim());
  return list.filter(Boolean);
}

function keyDriversText(theme) {
  const list = keyDriversList(theme).slice(0, 3);
  return list.length ? list.join('; ') : 'No key drivers recorded';
}

// AT-ED-016.1: the catalyst is the theme's first documented key driver - the same real,
// already-normalized (string-or-array-safe, see keyDriversText's AT-ED-015.1 history) evidence
// keyDriversText draws from, just the single leading item rather than a joined list.
function themeOpportunityCard(theme) {
  const drivers = keyDriversList(theme);
  return {
    title: theme.theme,
    whyILikeIt: theme.summary || theme.current_outlook || 'I do not have a documented view on this yet.',
    // AT-ED-016.3: theme.current_outlook is a sentiment word (e.g. "Cautious", "Positive"), not
    // a magnitude of expected upside - it was previously reused here directly, so a cautious
    // outlook showed up as the literal "potential upside" of the opportunity, which reads as a
    // mismatched/nonsensical label. Themes carry no numeric return estimate (unlike
    // recommendations' expected_return_r above), so this is honestly disclosed as unavailable
    // rather than repurposing a field that means something different.
    potentialUpside: 'Not yet estimated - AI Trader does not track a numeric return estimate for themes.',
    catalyst: drivers.length ? drivers[0] : 'No specific catalyst identified yet.',
    confidence: theme.confidence !== undefined && theme.confidence !== null ? formatPercent(theme.confidence) : 'Not available',
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
