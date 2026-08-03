// Pure presentation logic for the Market screen: orchestrator-decision text, markets-open
// status, learning summaries, and matching companies/recommendations to themes.
// Extracted from App.js as part of AT-ED-011 Phase 2 (mobile modularisation).

'use strict';

const { notAvailable } = require('./notAvailable');

function describeDecision(decision) {
  if (!decision) {
    return null;
  }
  return `${notAvailable(decision.symbol)} ${notAvailable(decision.decision)}${decision.rejection_reason ? `: ${decision.rejection_reason}` : ''}`;
}

function marketsOpenText(status) {
  const decision = status?.last_orchestrator_decision;
  if (!decision) {
    return 'Not available';
  }
  return decision.market_open ? `${decision.exchange || 'Market'} open` : `${decision.exchange || 'Market'} closed`;
}

function latestLearningText(status, benchmark) {
  const observed = benchmark?.items?.[0]?.ai_interpretation;
  const decision = status?.last_orchestrator_decision;
  if (observed && decision) {
    return `${observed}\nLast orchestrator decision: ${describeDecision(decision)}`;
  }
  return observed || describeDecision(decision);
}

function companiesForThemeList(theme, companies) {
  if (!companies || !companies.length) {
    return [];
  }
  const themeText = `${theme.theme || ''} ${theme.summary || ''} ${theme.key_drivers || ''}`.toLowerCase();
  const matches = companies.filter((company) => {
    const sector = String(company.sector || '').toLowerCase();
    const name = String(company.company_name || '').toLowerCase();
    return themeText.includes(sector) || sector.includes(String(theme.theme || '').toLowerCase()) || themeText.includes(name);
  });
  return matches.slice(0, 8);
}

function findRecommendationForCompany(company, recommendations) {
  const ticker = String(company?.ticker || '').toUpperCase();
  if (!ticker || !recommendations?.length) {
    return null;
  }
  return recommendations.find((item) => String(item.ticker || '').toUpperCase() === ticker) || null;
}


module.exports = {
  describeDecision,
  marketsOpenText,
  latestLearningText,
  companiesForThemeList,
  findRecommendationForCompany,
};
