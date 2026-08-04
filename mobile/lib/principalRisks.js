// AT-ED-015 Section 6: Principal Risks as individual, structured cards - each risk gets its own
// Impact / Likelihood / Potential Effect / Mitigation, rather than one joined paragraph
// (AT-ED-013/014's `cioPrincipalRisks()`, kept as-is for the Morning Brief's one-line summary).
// Kept dependency-free (no React/RN imports) - see principalRisks.test.js.
//
// Two real evidence sources are used, and impact/likelihood are only ever scored when this
// backend actually provides a basis for scoring:
//  - `upcomingRisks` (market_intelligence_centre.upcoming_risks / a theme's key_risks) are plain
//    strings with no attached severity or frequency data - this backend has no risk-scoring
//    model, so both fields are honestly reported as not-yet-scored rather than guessed.
//  - Positions currently at a loss DO have real, computable evidence (the actual £ amount at
//    risk as a percentage of total portfolio value), so that one risk card gets a real Impact
//    tier from a disclosed threshold, not a placeholder.

'use strict';

const NOT_SCORED = 'Not currently scored - AI Trader does not yet model risk severity or likelihood.';

function marketRiskCard(riskText) {
  return {
    title: riskText,
    impact: NOT_SCORED,
    likelihood: NOT_SCORED,
    potentialEffect: riskText,
    mitigation: 'Monitored; no portfolio action is currently triggered by this risk alone.',
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
  return {
    title: `${list.length} Position${list.length === 1 ? '' : 's'} Currently at a Loss`,
    impact: `${impact} (${Math.round(pct * 100)}% of portfolio value)`,
    likelihood: 'Currently occurring, not a future probability.',
    potentialEffect: `${list.map((item) => item.symbol).filter(Boolean).join(', ')} currently show unrealised losses totalling approximately ${totalAtRisk.toFixed(2)}.`,
    mitigation: impact === 'High'
      ? 'Reviewed as part of standard stop-loss/take-profit management; no incremental Founder action required beyond existing governance.'
      : 'No action required; within normal trading variance.',
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
  NOT_SCORED,
  impactTierForLossPct,
  positionsAtLossCard,
  buildRiskCards,
};
