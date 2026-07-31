// Plain Node assert-based tests for founderPresentation.js. No test framework is installed for
// this project (see mobile/package.json) - run directly with `node mobile/lib/founderPresentation.test.js`.
// Exits non-zero on any failure so it can be wired into CI later without changes.

'use strict';

const assert = require('assert');
const {
  operationalRollup,
  operationalLevelTone,
  brokerOverallReadiness,
  activityCategoryFor,
  groupActivity,
  recommendationLifecycle,
  positionOwnership,
  learningSummary,
} = require('./founderPresentation');

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

// --- operationalRollup / operationalLevelTone ---

test('operationalRollup: NOT OPERATING is Critical regardless of brokers', () => {
  const result = operationalRollup({
    operatingState: 'NOT OPERATING',
    plainEnglish: 'Worker heartbeat is stale.',
    liveWorker: { deployment_commit: 'abc1234', last_heartbeat_at: '2026-07-31T00:00:00Z' },
    brokerPanels: [],
    generatedAt: '2026-07-31T00:05:00Z',
  });
  assert.strictEqual(result.level, 'Critical');
  assert.strictEqual(result.deployed_commit, 'abc1234');
});

test('operationalRollup: enabled-but-blocked broker is Blocked, not Degraded, when system is healthy', () => {
  const result = operationalRollup({
    operatingState: 'OPERATING NORMALLY',
    plainEnglish: 'All good.',
    liveWorker: null,
    brokerPanels: [
      { label: 'Kraken', auto_trading_enabled: true, block_reason: 'Kraken entry reconciliation requires verification.' },
      { label: 'Alpaca', auto_trading_enabled: true, block_reason: null },
    ],
    generatedAt: null,
  });
  assert.strictEqual(result.level, 'Blocked');
  assert.match(result.reason, /Kraken/);
});

test('operationalRollup: normal state with no blocks is Normal', () => {
  const result = operationalRollup({
    operatingState: 'OPERATING NORMALLY',
    plainEnglish: 'All good.',
    liveWorker: null,
    brokerPanels: [{ label: 'Alpaca', auto_trading_enabled: true, block_reason: null }],
    generatedAt: null,
  });
  assert.strictEqual(result.level, 'Normal');
});

test('operationalLevelTone maps every level to a tone', () => {
  assert.strictEqual(operationalLevelTone('Normal'), 'good');
  assert.strictEqual(operationalLevelTone('Blocked'), 'warn');
  assert.strictEqual(operationalLevelTone('Degraded'), 'warn');
  assert.strictEqual(operationalLevelTone('Critical'), 'danger');
  assert.strictEqual(operationalLevelTone('Unknown'), 'neutral');
});

// --- brokerOverallReadiness ---

test('brokerOverallReadiness: enabled + block_reason reads Enabled but Blocked, never Disabled', () => {
  const result = brokerOverallReadiness({
    connection_status: 'Connected',
    auto_trading_enabled: true,
    block_reason: 'Kraken entry reconciliation and the AI-managed capital ledger require verification.',
  });
  assert.strictEqual(result.label, 'Enabled but Blocked');
  assert.strictEqual(result.newEntriesAllowed, false);
});

test('brokerOverallReadiness: missing auto_trading_enabled reads Unknown, never false', () => {
  const result = brokerOverallReadiness({ connection_status: 'Connected', auto_trading_enabled: null, block_reason: null });
  assert.strictEqual(result.label, 'Unknown');
  assert.strictEqual(result.newEntriesAllowed, null);
});

test('brokerOverallReadiness: disconnected broker reads Data Unavailable, not a false readiness claim', () => {
  const result = brokerOverallReadiness({ connection_status: 'Connection error', auto_trading_enabled: true, block_reason: null });
  assert.strictEqual(result.label, 'Data Unavailable');
});

// --- activityCategoryFor / groupActivity ---

test('activityCategoryFor: backend categories map directly, job names map by pattern', () => {
  assert.strictEqual(activityCategoryFor({ category: 'Research' }), 'Research');
  assert.strictEqual(activityCategoryFor({ category: 'Execution' }), 'Trades');
  assert.strictEqual(activityCategoryFor({ category: 'Learning' }), 'Learning');
  assert.strictEqual(activityCategoryFor({ category: 'System', title: 'auto-execution-alpaca completed_no_action' }), 'Recommendations');
  assert.strictEqual(activityCategoryFor({ category: 'System', title: 'broker-poll-kraken completed' }), 'Broker Operations');
  assert.strictEqual(activityCategoryFor({ category: 'System', title: 'managed-exits completed' }), 'Portfolio');
  assert.strictEqual(activityCategoryFor({ category: 'System', title: 'evidence-snapshot timed_out' }), 'System Health');
  assert.strictEqual(activityCategoryFor({ category: 'System', title: 'push-dispatch completed' }), 'Founder Actions');
  assert.strictEqual(activityCategoryFor({ category: 'System', title: 'something-unrecognized completed' }), 'System Health');
});

test('groupActivity: collapses repeated identical titles into one event with a count', () => {
  const items = [
    { category: 'System', title: 'auto-execution-alpaca completed_no_action', timestamp: '2026-07-31T09:00:00Z', outcome: 'completed_no_action', severity: 'information' },
    { category: 'System', title: 'auto-execution-alpaca completed_no_action', timestamp: '2026-07-31T09:14:00Z', outcome: 'completed_no_action', severity: 'information' },
    { category: 'System', title: 'auto-execution-alpaca completed_no_action', timestamp: '2026-07-31T09:28:00Z', outcome: 'completed_no_action', severity: 'information' },
  ];
  const groups = groupActivity(items);
  const recommendationsGroup = groups.find((group) => group.category === 'Recommendations');
  assert.strictEqual(recommendationsGroup.events.length, 1, 'repeated identical events must collapse to one line');
  assert.strictEqual(recommendationsGroup.events[0].count, 3);
  assert.strictEqual(recommendationsGroup.events[0].latestAt, '2026-07-31T09:28:00Z');
});

test('groupActivity: filters out events before the cutoff', () => {
  const items = [
    { category: 'Research', title: 'Research completed', timestamp: '2026-07-30T00:00:00Z', outcome: 'completed', severity: 'success' },
    { category: 'Research', title: 'Research completed', timestamp: '2026-07-31T12:00:00Z', outcome: 'completed', severity: 'success' },
  ];
  const groups = groupActivity(items, { sinceIso: '2026-07-31T00:00:00Z' });
  const researchGroup = groups.find((group) => group.category === 'Research');
  assert.strictEqual(researchGroup.totalCount, 1);
});

test('groupActivity: a failed/timed-out event marks its category as requiring attention', () => {
  const items = [
    { category: 'System', title: 'evidence-snapshot timed_out', timestamp: '2026-07-31T09:00:00Z', outcome: 'timed_out', severity: 'failure' },
  ];
  const groups = groupActivity(items);
  const systemHealth = groups.find((group) => group.category === 'System Health');
  assert.strictEqual(systemHealth.requiresAttention, true);
});

test('groupActivity: always returns all 9 named categories, even when empty', () => {
  const groups = groupActivity([]);
  assert.strictEqual(groups.length, 9);
  assert.deepStrictEqual(groups.map((g) => g.category).sort(), [
    'Broker Operations', 'Decisions', 'Founder Actions', 'Learning', 'Portfolio',
    'Recommendations', 'Research', 'System Health', 'Trades',
  ].sort());
});

// --- recommendationLifecycle ---

test('recommendationLifecycle: expired recommendation reads Expired', () => {
  const result = recommendationLifecycle({ freshness_status: 'Expired', confidence: 0.9, guardrails_passed: true }, []);
  assert.strictEqual(result.stage, 'Expired');
});

test('recommendationLifecycle: failed guardrails reads Blocked with the real failure reasons', () => {
  const result = recommendationLifecycle(
    { freshness_status: 'Fresh', confidence: 0.9, guardrails_passed: false, guardrail_failures: ['max_open_positions_exceeded'] },
    []
  );
  assert.strictEqual(result.stage, 'Blocked');
  assert.match(result.reason, /max open positions exceeded/);
});

test('recommendationLifecycle: below-threshold confidence reads No Action', () => {
  const result = recommendationLifecycle({ freshness_status: 'Fresh', confidence: 0.6, guardrails_passed: true }, []);
  assert.strictEqual(result.stage, 'No Action');
});

test('recommendationLifecycle: fresh, passing, high-confidence with no matching trade reads Under Review', () => {
  const result = recommendationLifecycle({ freshness_status: 'Fresh', confidence: 0.9, guardrails_passed: true }, []);
  assert.strictEqual(result.stage, 'Under Review');
});

test('recommendationLifecycle: a same-broker/symbol fill inside the window reads Executed', () => {
  const item = {
    freshness_status: 'Fresh',
    confidence: 0.9,
    guardrails_passed: true,
    suggested_broker: 'alpaca',
    ticker: 'AAPL',
    created_at: '2026-07-31T09:00:00Z',
    expires_at: '2026-07-31T13:00:00Z',
  };
  const trades = [{ broker: 'alpaca', symbol: 'AAPL', status: 'filled', observed_at: '2026-07-31T09:05:00Z' }];
  const result = recommendationLifecycle(item, trades);
  assert.strictEqual(result.stage, 'Executed');
});

test('recommendationLifecycle: a fill for a different symbol does not count as Executed', () => {
  const item = {
    freshness_status: 'Fresh', confidence: 0.9, guardrails_passed: true,
    suggested_broker: 'alpaca', ticker: 'AAPL', created_at: '2026-07-31T09:00:00Z', expires_at: '2026-07-31T13:00:00Z',
  };
  const trades = [{ broker: 'alpaca', symbol: 'MSFT', status: 'filled', observed_at: '2026-07-31T09:05:00Z' }];
  const result = recommendationLifecycle(item, trades);
  assert.strictEqual(result.stage, 'Under Review');
});

// --- positionOwnership ---

test('positionOwnership: a position with a matching open managed-exit is AI-managed', () => {
  const result = positionOwnership({ symbol: 'BTC' }, [{ symbol: 'BTC', status: 'open', payload: { proposal_id: 'p-1' } }]);
  assert.strictEqual(result.isAiManaged, true);
  assert.strictEqual(result.managedExit.payload.proposal_id, 'p-1');
});

test('positionOwnership: a manual holding with no managed-exit row is never labelled AI-managed', () => {
  const result = positionOwnership({ symbol: 'ETH' }, [{ symbol: 'BTC', status: 'open' }]);
  assert.strictEqual(result.isAiManaged, false);
  assert.strictEqual(result.managedExit, null);
});

test('positionOwnership: a closed managed-exit does not count as a currently AI-managed position', () => {
  const result = positionOwnership({ symbol: 'BTC' }, [{ symbol: 'BTC', status: 'closed' }]);
  assert.strictEqual(result.isAiManaged, false);
});

// --- learningSummary ---

test('learningSummary: no closed trades yet gives the no-evidence empty state, not repeated Not-available rows', () => {
  const result = learningSummary({ learning: [], trades: [], recommendations: [] });
  assert.strictEqual(result.completedTradesReviewed, 0);
  assert.strictEqual(result.hasEnoughEvidence, false);
  assert.match(result.missingEvidence, /No completed, reconciled trades/);
});

test('learningSummary: closed trades but no learning run yet says so specifically', () => {
  const result = learningSummary({
    learning: [],
    trades: [{ status: 'closed', broker: 'kraken', symbol: 'BTC' }],
    recommendations: [],
  });
  assert.strictEqual(result.completedTradesReviewed, 1);
  assert.match(result.missingEvidence, /have closed, but the learning processor/);
});

test('learningSummary: counts distinct strategies from recommendations, not raw recommendation count', () => {
  const result = learningSummary({
    learning: [{ summary: 'Lesson.' }],
    trades: [{ status: 'closed' }],
    recommendations: [{ strategy_id: 'trend-following' }, { strategy_id: 'trend-following' }, { strategy_id: 'mean-reversion' }],
  });
  assert.strictEqual(result.strategiesEvaluated, 2);
  assert.strictEqual(result.latestLesson, 'Lesson.');
});

console.log(`\n${passed} test(s) passed.`);
if (process.exitCode) {
  console.error('One or more tests failed.');
}
