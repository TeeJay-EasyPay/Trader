// AT-ED-015 Section 6 / AT-ED-016.1 Communication Refinement: Principal Risks as individual,
// structured cards. AT-ED-016.1 collapsed the original six-field structure (Impact/Likelihood/
// Potential Effect/Mitigation/Monitoring Owner/Estimated Portfolio Effect) down to exactly the
// four fields a CIO would actually say out loud: Risk / Why It Matters / Probability / What I Am
// Doing About It - the same real evidence and the same real percentage math, spoken in fewer,
// plainer sentences instead of a six-row label grid. Kept dependency-free (no React/RN imports)
// - see principalRisks.test.js.
//
// Two real evidence sources are used, and probability is only ever a real read when this backend
// actually provides a basis for one:
//  - `upcomingRisks` (market_intelligence_centre.upcoming_risks / a theme's key_risks) are plain
//    strings with no attached severity or frequency data - this backend has no risk-scoring
//    model, so probability is honestly described as unscored rather than guessed.
//  - Positions currently at a loss DO have real, computable evidence (the actual amount at risk
//    as a percentage of total portfolio value), so that one risk card's "why it matters" carries
//    a real, disclosed-threshold severity read.

'use strict';

function marketRiskCard(riskText) {
  return {
    title: riskText,
    whyItMatters: riskText,
    probability: 'Not something I can put a precise number on yet - I am watching it closely.',
    whatImDoing: 'Monitoring it. Nothing here currently changes how I am running the portfolio.',
  };
}

function impactTierForLossPct(pct) {
  if (pct < 0.02) return 'Low';
  if (pct < 0.05) return 'Medium';
  return 'High';
}

// positionsAtLoss: array of { symbol, unrealizedPl } (unrealizedPl negative). Returns null (no
// card) when there is nothing at a loss or portfolio value is unknown - never a fabricated card.
function positionsAtLossCard({ positionsAtLoss, portfolioValue }) {
  const list = (positionsAtLoss || []).filter((item) => Number(item.unrealizedPl) < 0);
  if (!list.length || !portfolioValue) {
    return null;
  }
  const totalAtRisk = list.reduce((sum, item) => sum + Math.abs(Number(item.unrealizedPl) || 0), 0);
  const pct = totalAtRisk / portfolioValue;
  const impact = impactTierForLossPct(pct);
  const names = list.map((item) => item.symbol).filter(Boolean).join(', ');
  return {
    title: `${list.length} Position${list.length === 1 ? '' : 's'} Currently at a Loss`,
    whyItMatters: `${names || 'These positions'} ${list.length === 1 ? 'is' : 'are'} down about ${totalAtRisk.toFixed(2)} in total - roughly ${Math.round(pct * 100)}% of the portfolio.`,
    probability: 'This is already happening, not a future possibility.',
    whatImDoing: impact === 'High'
      ? 'Watching this closely through our normal stop-loss and take-profit process. No action is needed from you.'
      : 'Nothing needed here - this is within normal day-to-day movement.',
  };
}

function buildRiskCards({ upcomingRisks, positionsAtLoss, portfolioValue }) {
  const cards = [];
  const lossCard = positionsAtLossCard({ positionsAtLoss, portfolioValue });
  if (lossCard) {
    cards.push(lossCard);
  }
  (upcomingRisks || []).slice(0, 3).forEach((riskText) => {
    if (riskText) {
      cards.push(marketRiskCard(riskText));
    }
  });
  return cards;
}

module.exports = {
  impactTierForLossPct,
  positionsAtLossCard,
  buildRiskCards,
};
