// Plain Node assert-based tests for cio.js - run with `node mobile/lib/cio.test.js`.

'use strict';

const assert = require('assert');
const {
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
} = require('./cio');

let passed = 0;
function test(name, fn) {
  try {
    fn();
    passed += 1;
    console.log(`ok - ${name}`);
  } catch (err) {
    console.error(`FAIL - ${name}`);
    console.error(err);
    process.exitCode = 1;
  }
}

// --- greetingForHour / cioGreeting ---

test('greetingForHour: covers morning, afternoon, evening, and late night', () => {
  assert.strictEqual(greetingForHour(8), 'Good morning');
  assert.strictEqual(greetingForHour(14), 'Good afternoon');
  assert.strictEqual(greetingForHour(20), 'Good evening');
  assert.strictEqual(greetingForHour(2), 'Good evening');
});

test('greetingForHour: invalid input never throws', () => {
  assert.strictEqual(greetingForHour(null), 'Hello');
  assert.strictEqual(greetingForHour(undefined), 'Hello');
  assert.strictEqual(greetingForHour(NaN), 'Hello');
});

test('cioGreeting: includes the Founder name and a time-appropriate greeting', () => {
  const morning = new Date('2026-08-04T08:00:00');
  assert.strictEqual(cioGreeting(morning), `Good morning ${FOUNDER_NAME}.`);
});

// --- cioExecutiveSummary ---

test('cioExecutiveSummary: joins real backend sentences with a real paragraph break, not a single run-on block (AT-ED-016.2)', () => {
  const text = cioExecutiveSummary({
    headline: 'Portfolio is stable.',
    whatToDo: 'Review two new recommendations.',
    whatToWorryAbout: 'Watch Kraken reconciliation.',
  });
  assert.strictEqual(text, 'Portfolio is stable.\n\nReview two new recommendations.\n\nWatch Kraken reconciliation.');
});

test('cioExecutiveSummary: no evidence yet is honest, not fabricated', () => {
  const text = cioExecutiveSummary({ headline: null, whatToDo: null, whatToWorryAbout: null });
  assert.ok(text.includes('do not have a clear enough picture'));
});

// --- cioOvernightActivity ---

test('cioOvernightActivity: names every real count with correct singular/plural grammar', () => {
  const text = cioOvernightActivity({ researchRuns: 1, recommendationsCreated: 3, ordersSubmitted: 0 });
  assert.ok(text.includes('completed 1 research review'));
  assert.ok(text.includes('identified 3 new opportunities'));
  assert.ok(!text.includes('submitted'));
});

test('cioOvernightActivity: a genuinely quiet period is reported as quiet, not padded out', () => {
  const text = cioOvernightActivity({ researchRuns: 0, recommendationsCreated: 0, ordersSubmitted: 0 });
  assert.ok(text.includes('have not recorded any new'));
});

test('cioOvernightActivity: exactly one order uses singular grammar', () => {
  const text = cioOvernightActivity({ researchRuns: 0, recommendationsCreated: 0, ordersSubmitted: 1 });
  assert.ok(text.includes('submitted 1 order.'));
});

// --- cioTodaysMoneyBreakdown (AT-ED-017 Part 3) ---

test('cioTodaysMoneyBreakdown: names both real realised and unrealised halves', () => {
  const text = cioTodaysMoneyBreakdown({ realizedToday: 50, realizedTodayText: '£50', unrealizedTotal: 20, unrealizedTotalText: '£20', exitsToday: 2, openPositionsCount: 5 });
  assert.ok(text.includes('£50 of today\'s movement is realised profit'));
  assert.ok(text.includes('2 closed positions'));
  assert.ok(text.includes('an unrealised gain of £20'));
  assert.ok(text.includes('5 open positions'));
});

test('cioTodaysMoneyBreakdown: a negative realised figure is named as a loss, not a fabricated profit', () => {
  const text = cioTodaysMoneyBreakdown({ realizedToday: -30, realizedTodayText: '£30', unrealizedTotal: null, unrealizedTotalText: null, exitsToday: 1, openPositionsCount: 0 });
  assert.ok(text.includes('a realised loss'));
});

test('cioTodaysMoneyBreakdown: nothing closed today is stated honestly, not silently omitted', () => {
  const text = cioTodaysMoneyBreakdown({ realizedToday: null, realizedTodayText: null, unrealizedTotal: 20, unrealizedTotalText: '£20', exitsToday: 0, openPositionsCount: 3 });
  assert.ok(text.includes('No positions have closed today'));
});

test('cioTodaysMoneyBreakdown: neither figure available returns null, never fabricated', () => {
  assert.strictEqual(cioTodaysMoneyBreakdown({ realizedToday: null, realizedTodayText: null, unrealizedTotal: null, unrealizedTotalText: null, exitsToday: 0, openPositionsCount: 0 }), null);
});

// --- cioAutonomyStatement (AT-ED-017 Part 5) ---

test('cioAutonomyStatement: fully ready and no incidents states autonomy plainly', () => {
  const text = cioAutonomyStatement({ tradeReady: true, unresolvedIncidentCount: 0 });
  assert.ok(text.includes('operating fully autonomously'));
});

test('cioAutonomyStatement: unresolved incidents mean it is honestly not fully autonomous', () => {
  const text = cioAutonomyStatement({ tradeReady: true, unresolvedIncidentCount: 2 });
  assert.ok(text.includes('not fully autonomous'));
  assert.ok(text.includes('2 operational items'));
});

test('cioAutonomyStatement: not trade-ready without an incident count still flags caution', () => {
  const text = cioAutonomyStatement({ tradeReady: false, unresolvedIncidentCount: 0 });
  assert.ok(text.includes('some caution'));
});

// --- cioActivityFunnel (AT-ED-017 Part 5) ---

test('cioActivityFunnel: reports real structured counts, never the raw internal reason codes', () => {
  const text = cioActivityFunnel({ eligible_for_paper_execution: 1, rejected: 3, orders_submitted: 1 });
  assert.ok(text.includes('1 opportunity cleared every gate'));
  assert.ok(text.includes('3 were rejected by governance'));
  assert.ok(text.includes('1 order was actually submitted'));
});

test('cioActivityFunnel: all-zero counts return null rather than a hollow zero-filled sentence', () => {
  assert.strictEqual(cioActivityFunnel({ eligible_for_paper_execution: 0, rejected: 0, orders_submitted: 0 }), null);
  assert.strictEqual(cioActivityFunnel(null), null);
});

// --- cioMarketOutlook ---

test('cioMarketOutlook: composes only fields that actually have content', () => {
  const text = cioMarketOutlook({ marketHealth: 'Markets are calm.', currentRegime: null, cryptoHealth: null, upcomingRisks: [] });
  assert.strictEqual(text, 'Markets are calm.');
});

test('cioMarketOutlook: no market evidence at all is honest, not fabricated', () => {
  const text = cioMarketOutlook({ marketHealth: null, currentRegime: null, cryptoHealth: null, upcomingRisks: [] });
  assert.ok(text.includes('do not yet have a clear read'));
});

test('cioMarketOutlook: names up to 3 upcoming risks when present', () => {
  const text = cioMarketOutlook({ marketHealth: 'Stable.', currentRegime: null, cryptoHealth: null, upcomingRisks: ['inflation data', 'rate decision', 'earnings season', 'a fourth risk'] });
  assert.ok(text.includes('inflation data, rate decision, earnings season'));
  assert.ok(!text.includes('a fourth risk'));
});

test('cioMarketOutlook (AT-ED-016.3): frames the raw crypto research status fragment as a real sentence, never as an orphan lowercase fragment', () => {
  const text = cioMarketOutlook({ marketHealth: null, currentRegime: null, cryptoHealth: 'completed - 9 asset(s), Aug 04, 2026, 11:29 PM', upcomingRisks: [] });
  assert.strictEqual(text, 'On the crypto side, Kraken research is completed - 9 asset(s), Aug 04, 2026, 11:29 PM.');
});

// --- cioAverageConfidence ---

test('cioAverageConfidence: computes a real mean across non-expired recommendations only', () => {
  const result = cioAverageConfidence([
    { confidence: 0.9, freshness_status: 'Fresh' },
    { confidence: 0.7, freshness_status: 'Fresh' },
    { confidence: 0.99, freshness_status: 'Expired' },
  ]);
  assert.strictEqual(result, 80);
});

test('cioAverageConfidence: no recommendations at all returns null, never a fabricated number', () => {
  assert.strictEqual(cioAverageConfidence([]), null);
  assert.strictEqual(cioAverageConfidence(null), null);
});

// --- portfolioProjection (AT-ED-013 Section 8 deliberate honesty check) ---

test('portfolioProjection: never returns a fabricated number - no forecasting model exists in this backend', () => {
  const result = portfolioProjection();
  assert.strictEqual(result.available, false);
  assert.ok(result.reason.length > 0);
});

// --- cioLearningNarrative ---

test('cioLearningNarrative: not enough evidence yet is stated plainly', () => {
  const text = cioLearningNarrative({ completedTradesReviewed: 0, latestLesson: null, hasEnoughEvidence: false, missingEvidence: 'No closed trades yet.' });
  assert.ok(text.includes('do not yet have enough closed'));
  assert.ok(text.includes('No closed trades yet.'));
});

test('cioLearningNarrative: reports real trade count and latest lesson when evidence exists', () => {
  const text = cioLearningNarrative({ completedTradesReviewed: 5, latestLesson: 'Momentum trades performed well.', hasEnoughEvidence: true, missingEvidence: null });
  assert.ok(text.includes('reviewed 5 closed trades'));
  assert.ok(text.includes('Momentum trades performed well.'));
});

// --- cioPrincipalRisks (AT-ED-014) ---

test('cioPrincipalRisks: composes real at-loss count and real upcoming risks', () => {
  const text = cioPrincipalRisks({ upcomingRisks: ['inflation data', 'rate decision'], positionsAtLossCount: 2 });
  assert.ok(text.includes('2 open positions are currently at a loss'));
  assert.ok(text.includes('inflation data; rate decision'));
});

test('cioPrincipalRisks: no risk evidence at all is honest, not fabricated', () => {
  assert.strictEqual(
    cioPrincipalRisks({ upcomingRisks: [], positionsAtLossCount: 0 }),
    'No principal risks are currently flagged in the evidence.'
  );
});

// --- cioPrincipalOpportunities (AT-ED-014) ---

test('cioPrincipalOpportunities: names a real fresh-recommendation count', () => {
  const text = cioPrincipalOpportunities({ freshRecommendationsCount: 3, topThemeSummary: null });
  assert.ok(text.includes('3 fresh recommendations currently meet'));
});

test('cioPrincipalOpportunities: no opportunity evidence at all is honest, not fabricated', () => {
  assert.strictEqual(
    cioPrincipalOpportunities({ freshRecommendationsCount: 0, topThemeSummary: null }),
    'No new opportunities currently clear our evidence bar.'
  );
});

// --- cioFounderActionRequired (AT-ED-014 Section 3, question 10) ---

test('cioFounderActionRequired: genuinely nothing outstanding says so plainly, matching the directive\'s own example', () => {
  assert.strictEqual(
    cioFounderActionRequired({ outstandingRecommendationsCount: 0, unresolvedIncidentCount: 0 }),
    'No Founder action is required today.'
  );
});

test('cioFounderActionRequired: real outstanding counts are named, not summarised away', () => {
  const text = cioFounderActionRequired({ outstandingRecommendationsCount: 2, unresolvedIncidentCount: 1 });
  assert.ok(text.includes('2 recommendations awaiting your review'));
  assert.ok(text.includes('1 unresolved incident needing attention'));
});

// --- cioNoActionReason (AT-ED-016 Part 1 Section 9: never bare "no action required") ---

test('cioNoActionReason: something outstanding means there is no "no action" reason to give', () => {
  assert.strictEqual(cioNoActionReason({ tradeReady: true, outstandingRecommendationsCount: 1, unresolvedIncidentCount: 0 }), null);
});

test('cioNoActionReason: genuinely nothing outstanding explains why, naming real readiness state', () => {
  const text = cioNoActionReason({ tradeReady: true, outstandingRecommendationsCount: 0, unresolvedIncidentCount: 0 });
  assert.ok(text.startsWith('I recommend no intervention today, because'));
  assert.ok(text.includes('comfortable with our current positioning'));
});

test('cioNoActionReason: readiness not fully clear is named honestly, not hidden behind a generic reason', () => {
  const text = cioNoActionReason({ tradeReady: false, outstandingRecommendationsCount: 0, unresolvedIncidentCount: 0, readinessNote: 'Kraken connection degraded.' });
  assert.ok(text.includes('Kraken connection degraded.'));
});

// --- cioClosingRecommendation (AT-ED-015 Section 2) ---

test('cioClosingRecommendation: no thesis evidence is honest, not a fabricated recommendation', () => {
  const text = cioClosingRecommendation({ convictionLevel: 'Not Established', thesisAvailable: false, actionRequired: false });
  assert.ok(text.includes('do not yet have enough conviction'));
});

test('cioClosingRecommendation: high conviction and no action required recommends staying the course', () => {
  const text = cioClosingRecommendation({ convictionLevel: 'High', thesisAvailable: true, actionRequired: false });
  assert.ok(text.includes('strong conviction'));
  assert.ok(text.includes('stay the course'));
});

test('cioClosingRecommendation: low conviction is named as a real caveat, not hidden', () => {
  const text = cioClosingRecommendation({ convictionLevel: 'Low', thesisAvailable: true, actionRequired: true });
  assert.ok(text.includes('currently low'));
  assert.ok(text.includes('review the items above'));
});

// --- cioExecutiveBriefingSummary (AT-ED-016 Part 1 Section 1) ---

test('cioExecutiveBriefingSummary: joins only the real, non-empty fragments provided, each on its own line (AT-ED-016.2)', () => {
  const text = cioExecutiveBriefingSummary({ greeting: 'Good morning Tarik.', headlineSummary: 'Markets are stable.', overnightSummary: null, marketSummary: 'Tech continues to lead.', comfortSentence: null });
  assert.strictEqual(text, 'Good morning Tarik.\n\nMarkets are stable.\n\nTech continues to lead.');
});

test('cioExecutiveBriefingSummary: no fragments at all is honest, not fabricated', () => {
  const text = cioExecutiveBriefingSummary({});
  assert.ok(text.includes('do not have a clear enough picture'));
});

console.log(`\n${passed} passed`);
if (process.exitCode) {
  console.error('Some cio tests failed.');
}
