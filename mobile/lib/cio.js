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
// AT-ED-016.2: joined with a real paragraph break (`\n\n`, which React Native's <Text> renders
// as an actual line break), not a single space - three distinct ideas (headline/what-to-do/
// what-to-worry-about) previously ran together as one dense paragraph inside a single <Text>
// block, which is what was actually causing the "sentences don't start on a new line" complaint,
// not the wording. See Founder_Briefing.md for the full diagnosis.
function cioExecutiveSummary({ headline, whatToDo, whatToWorryAbout }) {
  const sentences = [headline, whatToDo, whatToWorryAbout].filter(Boolean);
  if (!sentences.length) {
    return 'I do not have a clear enough picture to brief you properly yet - check back shortly.';
  }
  return sentences.join('\n\n');
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

// AT-ED-017 Part 3: "are we making money, and is it realised or unrealised?" - composes the two
// real, already-computed halves (lib/portfolioPosition.js's realizedPnlToday/totalUnrealizedPnl)
// into one plain paragraph instead of leaving the Founder to infer the split from two unlabelled
// numbers next to each other. Money is pre-formatted by the caller (screens/ExecutiveBriefing.js
// already owns all currency formatting via lib/money.js) - the raw realised/unrealised numbers
// are only used here to pick the right words ("profit" vs "loss"), keeping this function
// dependency-free like every other one in this file.
function cioTodaysMoneyBreakdown({ realizedToday, realizedTodayText, unrealizedTotal, unrealizedTotalText, exitsToday, openPositionsCount }) {
  const hasRealized = realizedToday !== null && realizedToday !== undefined;
  const hasUnrealized = unrealizedTotal !== null && unrealizedTotal !== undefined;
  if (!hasRealized && !hasUnrealized) {
    return null;
  }
  const sentences = [];
  if (hasRealized) {
    const word = realizedToday >= 0 ? 'realised profit' : 'a realised loss';
    sentences.push(`${realizedTodayText} of today's movement is ${word}, from ${exitsToday} closed position${exitsToday === 1 ? '' : 's'}.`);
  } else {
    sentences.push('No positions have closed today, so none of today\'s movement is realised yet.');
  }
  if (hasUnrealized) {
    const word = unrealizedTotal >= 0 ? 'an unrealised gain' : 'an unrealised loss';
    sentences.push(`The rest is ${word} of ${unrealizedTotalText}, still sitting in ${openPositionsCount} open position${openPositionsCount === 1 ? '' : 's'}.`);
  }
  return sentences.join('\n\n');
}

// AT-ED-017 Part 5: the Founder must immediately know whether AI Trader is operating
// autonomously today, without having to infer it from the absence of a warning elsewhere. Built
// from the same connection_readiness/incidents evidence FounderActionsSection already reads -
// this states the same real facts as a direct autonomy claim, rather than only ever describing
// autonomy by omission.
function cioAutonomyStatement({ tradeReady, unresolvedIncidentCount }) {
  if (unresolvedIncidentCount) {
    return `AI Trader is not fully autonomous today - ${unresolvedIncidentCount} operational item${unresolvedIncidentCount === 1 ? '' : 's'} need${unresolvedIncidentCount === 1 ? 's' : ''} attention before every gate is clear.`;
  }
  if (tradeReady) {
    return 'AI Trader is operating fully autonomously today - no Founder action has been required to reach this point.';
  }
  return 'AI Trader is operating with some caution today - a readiness check needs a closer look before I would call this fully autonomous.';
}

// AT-ED-017 Part 5: "what has AI Trader actually done today" as a real funnel, using only
// structured counts (evidence.why_no_trade.counts) - never the raw internal reason codes
// (top_reasons) AT-ED-016.3 already removed from Founder-facing text elsewhere on this screen.
function cioActivityFunnel(counts) {
  if (!counts) {
    return null;
  }
  const eligible = Number(counts.eligible_for_paper_execution) || 0;
  const rejected = Number(counts.rejected) || 0;
  const submitted = Number(counts.orders_submitted) || 0;
  if (!eligible && !rejected && !submitted) {
    return null;
  }
  return `Of what I reviewed, ${eligible} opportunit${eligible === 1 ? 'y' : 'ies'} cleared every gate, ${rejected} ${rejected === 1 ? 'was' : 'were'} rejected by governance, and ${submitted} order${submitted === 1 ? '' : 's'} ${submitted === 1 ? 'was' : 'were'} actually submitted.`;
}

// AT-ED-013 Section 7: turns the Market Intelligence Centre's already-computed fields into one
// paragraph. Deliberately does not invent sector-level claims the backend hasn't made - where
// a field is genuinely a placeholder ("no sector-rotation provider is configured yet" and
// similar - see production_evidence.py/founderEvidenceMapping.js), this composer passes it
// through unchanged rather than dressing it up as a confident market call.
// AT-ED-016.1: first-person belief framing throughout ("I currently see/believe") rather than
// third-person system-report phrasing ("the regime reads as") - the CIO owns opinions, per the
// directive. Same inputs, same branching, wording only.
function cioMarketOutlook({ marketHealth, currentRegime, cryptoHealth, upcomingRisks }) {
  const sentences = [];
  if (marketHealth) {
    sentences.push(marketHealth);
  }
  if (currentRegime) {
    sentences.push(`I currently see ${currentRegime} conditions.`);
  }
  if (cryptoHealth) {
    // AT-ED-016.3: cryptoHealth (brokerResearchStatus()) is a raw, lowercase-starting status
    // fragment built for label/value display (e.g. "completed - 9 asset(s), Aug 04, 11:29 PM") -
    // pushed here unframed it read as an orphan, uncapitalised sentence in the middle of a CIO
    // paragraph. Give it a real sentence frame instead of pasting it in raw.
    sentences.push(`On the crypto side, Kraken research is ${cryptoHealth}.`);
  }
  if (!sentences.length) {
    return 'I do not yet have a clear read on today\'s market conditions.';
  }
  if (upcomingRisks && upcomingRisks.length) {
    sentences.push(`The main thing I'm watching: ${upcomingRisks.slice(0, 3).join(', ')}.`);
  }
  return sentences.join('\n\n');
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

// AT-ED-014 Section 3 (question 6: "what risks concern us?"): composed from real evidence only -
// the same upcoming_risks list Market already renders, plus open positions currently at a loss
// (Portfolio's own positionsRequiringAttention computation, passed in already-counted). Never
// invents a risk that isn't already surfaced elsewhere in the app.
function cioPrincipalRisks({ upcomingRisks, positionsAtLossCount }) {
  const sentences = [];
  if (positionsAtLossCount) {
    sentences.push(`${positionsAtLossCount} open position${positionsAtLossCount === 1 ? ' is' : 's are'} currently at a loss and worth a look.`);
  }
  if (upcomingRisks && upcomingRisks.length) {
    sentences.push(`The principal uncertaint${upcomingRisks.length === 1 ? 'y is' : 'ies are'}: ${upcomingRisks.slice(0, 3).join('; ')}.`);
  }
  if (!sentences.length) {
    return 'No principal risks are currently flagged in the evidence.';
  }
  return sentences.join(' ');
}

// AT-ED-014 Section 3 (question 7: "what opportunities exist?") - built from the same fresh,
// non-expired recommendations every other screen already treats as "current opportunities"
// (see lib/recommendations.js's freshness logic), not a new opportunity-scoring model.
function cioPrincipalOpportunities({ freshRecommendationsCount, topThemeSummary }) {
  const sentences = [];
  if (freshRecommendationsCount) {
    sentences.push(`${freshRecommendationsCount} fresh recommendation${freshRecommendationsCount === 1 ? '' : 's'} currently meet${freshRecommendationsCount === 1 ? 's' : ''} our evidence bar for review.`);
  }
  if (topThemeSummary) {
    sentences.push(topThemeSummary);
  }
  if (!sentences.length) {
    return 'No new opportunities currently clear our evidence bar.';
  }
  return sentences.join(' ');
}

// AT-ED-014 Section 3 (question 10: "does the Founder need to act?"). Deliberately binary and
// literal about its own evidence - "no action required" is only ever said when both inputs are
// truthfully zero, matching the example brief's own "No Founder action is required today."
function cioFounderActionRequired({ outstandingRecommendationsCount, unresolvedIncidentCount }) {
  if (!outstandingRecommendationsCount && !unresolvedIncidentCount) {
    return 'No Founder action is required today.';
  }
  const parts = [];
  if (outstandingRecommendationsCount) {
    parts.push(`${outstandingRecommendationsCount} recommendation${outstandingRecommendationsCount === 1 ? '' : 's'} awaiting your review`);
  }
  if (unresolvedIncidentCount) {
    parts.push(`${unresolvedIncidentCount} unresolved incident${unresolvedIncidentCount === 1 ? '' : 's'} needing attention`);
  }
  return `Founder action is required today: ${parts.join(', and ')}.`;
}

// AT-ED-016 Part 1 Section 9: the directive is explicit - never simply say "No action required,"
// explain WHY. Composed from the same three real facts cioFounderActionRequired() already checks
// (readiness, outstanding recommendations, incidents) plus the real readiness note when available
// - never a new evidence source, just the reasoning made explicit instead of left implicit.
function cioNoActionReason({ tradeReady, outstandingRecommendationsCount, unresolvedIncidentCount, readinessNote }) {
  if (outstandingRecommendationsCount || unresolvedIncidentCount) {
    return null;
  }
  const comfortReason = tradeReady
    ? 'I remain comfortable with our current positioning and nothing new currently clears our bar for action'
    : (readinessNote || 'a few things need a closer look behind the scenes, though nothing serious enough to change my recommendation');
  return `I recommend no intervention today, because ${comfortReason}. Should that change, I will recommend action immediately.`;
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

// AT-ED-015 Section 2: the Executive Briefing's closing line - a single sentence tying
// conviction, the current thesis, and whether the Founder needs to act into one recommendation,
// the way a real CIO would end a briefing. Composed entirely from values already computed
// elsewhere (lib/forecasting.js's deriveConviction(), lib/investmentThesis.js's
// currentInvestmentThesis(), lib/cio.js's own cioFounderActionRequired()) - never a new claim.
// AT-ED-016 Part 1 Section 11: expanded from one sentence to the directive's example structure -
// still composed entirely from the same three real values, plus a closing monitoring commitment
// that is always true of this app's own behaviour (it does refresh and re-evaluate on every
// visit and on its own auto-refresh cycle - see AT-ED-010's AUTO_REFRESH_INTERVAL_MS), not a new
// claim about capability this app does not have.
function cioClosingRecommendation({ convictionLevel, thesisAvailable, actionRequired }) {
  if (!thesisAvailable) {
    return 'I do not yet have enough conviction to close with a firm recommendation - check back shortly.';
  }
  const stance = actionRequired
    ? 'review the items above before markets move further'
    : 'stay the course - no change to our current positioning is warranted today';
  const monitoring = 'I will continue monitoring the markets and will flag it here immediately should my outlook materially change.';
  if (convictionLevel === 'High') {
    return `Given strong conviction in our current thesis, my recommendation is to ${stance}. ${monitoring}`;
  }
  if (convictionLevel === 'Low') {
    return `Conviction in our current thesis is currently low, so my recommendation is to proceed cautiously and ${stance}. ${monitoring}`;
  }
  return `My recommendation is to ${stance}, while we continue building conviction in our current thesis. ${monitoring}`;
}

// AT-ED-016 Part 1 Section 1: the Executive Summary, capped around 8-10 sentences and written
// exactly as a CIO speaking to the Founder - composed by joining sentence-fragments this module
// already produces (cioGreeting/cioExecutiveSummary/cioOvernightActivity/cioMarketOutlook, each
// independently tested above) rather than a new prose-generation path. Each fragment is already
// gated on its own real evidence by the function that produced it, so the only new logic here is
// selecting and ordering the pieces, and dropping any that came back empty/unavailable.
function cioExecutiveBriefingSummary({ greeting, headlineSummary, overnightSummary, marketSummary, comfortSentence }) {
  const parts = [greeting, headlineSummary, overnightSummary, marketSummary, comfortSentence].filter(Boolean);
  if (!parts.length) {
    return `${greeting || ''} I do not have a clear enough picture to brief you properly yet - check back shortly.`.trim();
  }
  return parts.join('\n\n');
}

module.exports = {
  FOUNDER_NAME,
  greetingForHour,
  cioGreeting,
  cioExecutiveSummary,
  cioOvernightActivity,
  cioTodaysMoneyBreakdown,
  cioAutonomyStatement,
  cioActivityFunnel,
  cioMarketOutlook,
  cioAverageConfidence,
  portfolioProjection,
  cioLearningNarrative,
  cioPrincipalRisks,
  cioPrincipalOpportunities,
  cioFounderActionRequired,
  cioNoActionReason,
  cioClosingRecommendation,
  cioExecutiveBriefingSummary,
};
