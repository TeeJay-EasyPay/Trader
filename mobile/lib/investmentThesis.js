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

// AT-ED-017 (live-review fix): a real emulator check showed "My conviction in Airlines currently
// sits at NaN%." - /intelligence/themes' seed/production data stores confidence as a string label
// ("Low"/"Medium"/"High", see intelligence_data.py), not always the 0-1 fraction this line
// assumed. Math.round(Number("Medium") * 100) is NaN, and NaN was rendered straight to the
// Founder. Handles both real shapes honestly instead of assuming one.
function formatThemeConviction(theme) {
  const confidence = theme.confidence;
  if (confidence === undefined || confidence === null || confidence === '') {
    return `My conviction in ${theme.theme} is a level I have not yet rated.`;
  }
  const numeric = Number(confidence);
  if (Number.isFinite(numeric)) {
    return `My conviction in ${theme.theme} currently sits at ${Math.round(numeric * 100)}%.`;
  }
  return `My conviction in ${theme.theme} is currently rated ${confidence}.`;
}

// AT-ED-017 (live-review fix): theme.summary/current_outlook and each theme.key_risks entry
// already end with their own period in production data - appending another "." unconditionally
// produced visible double periods ("...route disruption..") on the emulator. Only adds one if
// the text doesn't already end with sentence punctuation.
function withPeriod(text) {
  const trimmed = String(text || '').trim();
  if (!trimmed) {
    return trimmed;
  }
  return /[.!?]$/.test(trimmed) ? trimmed : `${trimmed}.`;
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
    sentences.push(`Our current thesis centres on ${theme.theme}: ${withPeriod(theme.summary || theme.current_outlook || 'evidence-backed outlook not yet summarised')}`);
    evidence.push(formatThemeConviction(theme));
  }
  if (strategy) {
    // AT-ED-017 (live-review fix): "1 of our current recommendation lean on..." - the noun was
    // already pluralised for count, but the verb wasn't, so a sample of exactly 1 read as a
    // subject-verb agreement error.
    const verb = strategy.count === 1 ? 'leans' : 'lean';
    const followVerb = strategy.count === 1 ? 'follows' : 'follow';
    sentences.push(`${strategy.count} of our current recommendation${strategy.count === 1 ? '' : 's'} ${verb} on the ${strategy.name} approach.`);
    evidence.push(`${strategy.count} of our current idea${strategy.count === 1 ? '' : 's'} ${followVerb} the ${strategy.name} approach.`);
  }
  // AT-ED-016.2: real paragraph break, not a space - the theme view and the strategy note are
  // two distinct ideas and were previously running together in one dense paragraph.
  return { available: true, statement: sentences.join('\n\n'), evidence };
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
  const topRisks = risks.slice(0, 3);
  // AT-ED-017 (live-review fix): each key_risks entry already ends with its own period in
  // production data - joining them and appending a final "." produced a visible double period
  // ("...regulation..") on the emulator. Strip each entry's own trailing period before joining,
  // so there is exactly one at the end of the sentence.
  const cleanedRisks = topRisks.map((risk) => String(risk || '').trim().replace(/[.]+$/, ''));
  return {
    available: true,
    statement: `We would be wrong if: ${cleanedRisks.join('; ')}.`,
    evidence: topRisks,
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
  formatThemeConviction,
  withPeriod,
  currentInvestmentThesis,
  alternativeThesis,
  evidenceStrength,
};
