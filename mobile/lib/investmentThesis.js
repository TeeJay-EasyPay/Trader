// AT-ED-014 Section 8: the CIO's Current Investment Thesis and Alternative Thesis. Kept
// dependency-free (no React/RN imports), matching every other lib/*.js convention, so it is
// directly testable under plain Node - see investmentThesis.test.js.
//
// There is no "investment thesis" object anywhere in this backend - what exists is `themes`
// (from /intelligence/themes, each already carrying its own outlook/confidence/key_drivers/
// key_risks - the same evidence Market's Theme Definitions section already renders) and
// `recommendations` (each carrying its own strategy_name). This module derives an honest thesis
// statement from that real evidence rather than inventing a separately-tracked thesis - when
// there isn't enough evidence to derive one, it says so instead of guessing.

'use strict';

// The thesis is anchored on the highest-confidence theme currently tracked, since that is the
// one piece of evidence this backend actually scores for conviction. Ties broken by array order
// (first listed), not invented.
function leadTheme(themes) {
  const list = (themes || []).filter((item) => item && item.theme);
  if (!list.length) {
    return null;
  }
  return list.reduce((best, item) => {
    const bestConfidence = Number(best.confidence) || 0;
    const itemConfidence = Number(item.confidence) || 0;
    return itemConfidence > bestConfidence ? item : best;
  }, list[0]);
}

// Names the strategy that appears most often among current, non-expired recommendations - the
// closest real evidence this backend has to "what approach is AI Trader currently leaning on",
// without inventing a strategy that isn't actually being recommended.
function dominantStrategy(recommendations) {
  const counts = {};
  (recommendations || [])
    .filter((item) => item.freshness_status !== 'Expired' && (item.strategy_name || item.strategy_id))
    .forEach((item) => {
      const name = item.strategy_name || item.strategy_id;
      counts[name] = (counts[name] || 0) + 1;
    });
  const entries = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  return entries.length ? { name: entries[0][0], count: entries[0][1] } : null;
}

function currentInvestmentThesis({ themes, recommendations }) {
  const theme = leadTheme(themes);
  const strategy = dominantStrategy(recommendations);
  if (!theme && !strategy) {
    return {
      available: false,
      statement: 'AI Trader does not yet have enough theme or strategy evidence to state a current investment thesis.',
      evidence: [],
    };
  }
  const sentences = [];
  const evidence = [];
  if (theme) {
    sentences.push(`Our current thesis centres on ${theme.theme}: ${theme.summary || theme.current_outlook || 'evidence-backed outlook not yet summarised'}.`);
    evidence.push(`My conviction in ${theme.theme} currently sits at ${theme.confidence !== undefined && theme.confidence !== null ? `${Math.round(Number(theme.confidence) * 100)}%` : 'a level I have not yet rated'}.`);
  }
  if (strategy) {
    sentences.push(`${strategy.count} of our current recommendation${strategy.count === 1 ? '' : 's'} lean on the ${strategy.name} approach.`);
    evidence.push(`${strategy.count} of our current idea${strategy.count === 1 ? '' : 's'} follow the ${strategy.name} approach.`);
  }
  return { available: true, statement: sentences.join(' '), evidence };
}

// The alternative thesis is deliberately built from the SAME lead theme's own key_risks field,
// not a separate bearish model - "what would make us wrong" is the evidence the backend already
// flagged as risk to that theme, not a new pessimistic forecast.
function alternativeThesis({ themes }) {
  const theme = leadTheme(themes);
  if (!theme || !(theme.key_risks && theme.key_risks.length)) {
    return {
      available: false,
      statement: 'AI Trader does not yet have documented risk evidence to state an alternative thesis.',
      evidence: [],
    };
  }
  const risks = Array.isArray(theme.key_risks) ? theme.key_risks : [theme.key_risks];
  return {
    available: true,
    statement: `We would be wrong if: ${risks.slice(0, 3).join('; ')}.`,
    evidence: risks.slice(0, 3),
  };
}

// AT-ED-016 Part 1 Section 5: "Evidence Strength" for the Investment Thesis section - a real,
// disclosed ratio (how many of the tracked forecast factors from lib/forecastFactors.js
// currently have real evidence, out of how many are tracked at all), not a fabricated confidence
// score. Thresholds are the same disclosed-arbitrary-but-stated style already used elsewhere in
// this codebase (e.g. lib/principalRisks.js's 2% concentration threshold).
function evidenceStrength(factorSummary) {
  if (!factorSummary || !factorSummary.consideredCount) {
    return 'Not yet established - insufficient evidence.';
  }
  const ratio = factorSummary.availableCount / factorSummary.consideredCount;
  if (ratio >= 0.75) {
    return `Strong - ${factorSummary.availableCount} of ${factorSummary.consideredCount} tracked factors currently have real evidence.`;
  }
  if (ratio >= 0.4) {
    return `Moderate - ${factorSummary.availableCount} of ${factorSummary.consideredCount} tracked factors currently have real evidence.`;
  }
  return `Weak - only ${factorSummary.availableCount} of ${factorSummary.consideredCount} tracked factors currently have real evidence.`;
}

module.exports = {
  leadTheme,
  dominantStrategy,
  currentInvestmentThesis,
  alternativeThesis,
  evidenceStrength,
};
