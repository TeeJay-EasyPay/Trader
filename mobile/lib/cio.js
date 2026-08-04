// AT-ED-013: the "Chief Investment Officer" is a presentation-layer narrator, not a new AI
// system, model, or chat - the directive is explicit about this ("The CIO is NOT another
// chatbot. The CIO is NOT another AI model."). Every function here composes plain-English,
// CIO-voiced prose entirely out of fields the backend already computes and this app already
// had access to (mostly the same status.founder_experience/world_class_evidence/
// operations_health fields founderPresentation.js and the AT-ED-012 screen summaries already
// read) - nothing here calls a network endpoint, invents a claim, or fabricates a number.
// Where the evidence genuinely doesn't support a statement (e.g. no forecasting model exists
// anywhere in this backend), the function says so honestly instead of inventing one - see
// portfolioProjection() below, which deliberately never returns a fabricated number.
//
// Kept dependency-free (no React/React Native import) so it's directly testable under plain
// Node, matching every other lib/*.js module's convention in this project.

'use strict';

const FOUNDER_NAME = 'Tarik';

function greetingForHour(hour) {
  if (hour === null || hour === undefined || Number.isNaN(hour)) {
    return 'Hello';
  }
  if (hour < 5) return 'Good evening';
  if (hour < 12) return 'Good morning';
  if (hour < 18) return 'Good afternoon';
  return 'Good evening';
}

// `now` is injectable for tests; defaults to the device clock.
function cioGreeting(now = new Date()) {
  return `${greetingForHour(now.getHours())} ${FOUNDER_NAME}.`;
}

// AT-ED-013 Section 1: composes the backend's own headline/recommendation/risk sentences
// (already present as executive.headline/what_to_do/what_to_worry_about - see
// founderEvidenceMapping.js's statusFromFounderEvidence) into one CIO-voiced paragraph. This
// is the "Executive Investment Summary" - every sentence already existed as backend evidence;
// this only removes field labels and joins them into prose instead of a label/value grid.
function cioExecutiveSummary({ headline, whatToDo, whatToWorryAbout }) {
  const sentences = [headline, whatToDo, whatToWorryAbout].filter(Boolean);
  if (!sentences.length) {
    return 'I do not have enough evidence to brief you yet - check back after the next successful refresh.';
  }
  return sentences.join(' ');
}

// AT-ED-013 Section 2/6: "What happened overnight" - a real count-based sentence built from
// activity.summary (the same fields AutonomousActivitySummaryCard already displayed as
// separate metrics in AT-ED-011/012). No event is invented; a quiet period is reported as
// quiet, not padded out with invented activity.
function cioOvernightActivity({ researchRuns, recommendationsCreated, ordersSubmitted }) {
  const parts = [];
  if (researchRuns) {
    parts.push(`completed ${researchRuns} research review${researchRuns === 1 ? '' : 's'}`);
  }
  if (recommendationsCreated) {
    parts.push(`identified ${recommendationsCreated} new opportunit${recommendationsCreated === 1 ? 'y' : 'ies'}`);
  }
  if (ordersSubmitted) {
    parts.push(`submitted ${ordersSubmitted} order${ordersSubmitted === 1 ? '' : 's'}`);
  }
  if (!parts.length) {
    return 'Since your last visit, I have not recorded any new research, recommendations, or orders.';
  }
  const last = parts.pop();
  const joined = parts.length ? `${parts.join(', ')}, and ${last}` : last;
  return `Since your last visit, I ${joined}.`;
}

// AT-ED-013 Section 7: turns the Market Intelligence Centre's already-computed fields into one
// paragraph. Deliberately does not invent sector-level claims the backend hasn't made - where
// a field is genuinely a placeholder ("no sector-rotation provider is configured yet" and
// similar - see production_evidence.py/founderEvidenceMapping.js), this composer passes it
// through unchanged rather than dressing it up as a confident market call.
function cioMarketOutlook({ marketHealth, currentRegime, cryptoHealth, upcomingRisks }) {
  const sentences = [];
  if (marketHealth) {
    sentences.push(marketHealth);
  }
  if (currentRegime) {
    sentences.push(`The current market regime reads as ${currentRegime}.`);
  }
  if (cryptoHealth) {
    sentences.push(cryptoHealth);
  }
  if (!sentences.length) {
    return 'Market intelligence has not produced a fresh regime summary yet.';
  }
  if (upcomingRisks && upcomingRisks.length) {
    sentences.push(`Watching: ${upcomingRisks.slice(0, 3).join('; ')}.`);
  }
  return sentences.join(' ');
}

// AT-ED-013 Section 1: "Confidence must be earned through evidence" - there is no backend
// model that forecasts overall portfolio or market confidence, so this never invents one.
// Instead it computes an honest, real statistic: the mean confidence across recommendations
// that are not expired. Labelled by the caller as exactly what it is (an average of current
// recommendation confidence), never presented as a market-wide or portfolio-wide forecast.
function cioAverageConfidence(recommendations) {
  const active = (recommendations || []).filter((item) => item.freshness_status !== 'Expired');
  const values = active
    .map((item) => Number(item.confidence_score ?? item.confidence))
    .filter((value) => Number.isFinite(value));
  if (!values.length) {
    return null;
  }
  const mean = values.reduce((sum, value) => sum + value, 0) / values.length;
  return Math.round(mean * 100);
}

// AT-ED-013 Section 8 explicitly asks for 7/30/90-day portfolio projections "only where
// evidence supports reasonable forecasting". This backend has no portfolio-value forecasting
// model anywhere (confirmed by reviewing production_evidence.py and every application/*.py
// service during this pass) - only per-trade R-multiple estimates on individual
// recommendations, which are not the same thing as a portfolio-value trajectory. Rather than
// fabricate a number to satisfy the section's example output, this always returns the honest
// "not available" state. See Founder_Briefing.md for why this was a deliberate choice, not an
// oversight.
function portfolioProjection() {
  return {
    available: false,
    reason: 'AI Trader does not yet have a portfolio-value forecasting model - only individual trade-level expected-return estimates exist today. Showing a projected value without one would be a fabricated number, not a forecast.',
  };
}

// AT-ED-013 Section 9: "quarterly performance review" framing for the Learning screen, built
// from the same fields learningSummary()/dailyLearning already compute - not a new evidence
// source.
function cioLearningNarrative({ completedTradesReviewed, latestLesson, hasEnoughEvidence, missingEvidence }) {
  if (!hasEnoughEvidence) {
    return `I do not yet have enough closed, reconciled trades to report meaningful learning progress. ${missingEvidence || ''}`.trim();
  }
  const tradeText = `I have reviewed ${completedTradesReviewed} closed trade${completedTradesReviewed === 1 ? '' : 's'} so far.`;
  const lessonText = latestLesson ? ` The most recent lesson: ${latestLesson}` : '';
  return `${tradeText}${lessonText}`;
}

module.exports = {
  FOUNDER_NAME,
  greetingForHour,
  cioGreeting,
  cioExecutiveSummary,
  cioOvernightActivity,
  cioMarketOutlook,
  cioAverageConfidence,
  portfolioProjection,
  cioLearningNarrative,
};
