// Plain Node assert-based tests for founderPresentation.js. No test framework is installed for
// this project (see mobile/package.json) - run directly with `node mobile/lib/founderPresentation.test.js`.
// Exits non-zero on any failure so it can be wired into CI later without changes.

'use strict';

const assert = require('assert');
const {
  operationalRollup,
  brokerOverallReadiness,
  brokerReadinessSentence,
  krakenWholeAccountNote,
  portfolioHeadline,
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

test('brokerReadinessSentence (AT-ED-012): disconnected broker explains why in plain English', () => {
  const sentence = brokerReadinessSentence({ broker: 'kraken', label: 'Kraken', connection_status: 'not connected' });
  assert.ok(sentence.includes('not currently connected'));
});

test('brokerReadinessSentence (AT-ED-012): enabled-but-blocked broker names the block reason, not just "Blocked"', () => {
  const sentence = brokerReadinessSentence({
    broker: 'kraken',
    label: 'Kraken',
    connection_status: 'Connected',
    auto_trading_enabled: true,
    block_reason: 'Reconciliation hold active',
  });
  assert.ok(sentence.includes('Reconciliation hold active'));
});

test('brokerReadinessSentence (AT-ED-012): ready broker names the correct trading mode per broker', () => {
  const kraken = brokerReadinessSentence({ broker: 'kraken', label: 'Kraken', connection_status: 'Connected', auto_trading_enabled: true });
  const alpaca = brokerReadinessSentence({ broker: 'alpaca', label: 'Alpaca', connection_status: 'Connected', auto_trading_enabled: true });
  assert.ok(kraken.includes('live trading'));
  assert.ok(alpaca.includes('paper trading'));
});

test('krakenWholeAccountNote (AT-ED-012 Phase 4): only returned for Kraken, explains the whole-account-vs-AI-sleeve distinction', () => {
  assert.strictEqual(krakenWholeAccountNote({ broker: 'alpaca' }), null);
  const note = krakenWholeAccountNote({ broker: 'kraken' });
  assert.ok(note.includes('personal account'));
});

test('portfolioHeadline (AT-ED-012): no data yet is honest, not a fabricated summary', () => {
  const text = portfolioHeadline({ openPositionsCount: null, pnlText: null, pnlIsPositive: null, atLossCount: null });
  assert.ok(text.includes('not available yet'));
});

test('portfolioHeadline (AT-ED-012): zero open positions reads as a plain fact', () => {
  const text = portfolioHeadline({ openPositionsCount: 0, pnlText: null, pnlIsPositive: null, atLossCount: 0 });
  assert.ok(text.includes('holds no open positions'));
  assert.ok(text.includes('Nothing here currently needs'));
});

test('portfolioHeadline (AT-ED-012): open positions with a loss names the count needing attention', () => {
  const text = portfolioHeadline({ openPositionsCount: 3, pnlText: '$45.00', pnlIsPositive: true, atLossCount: 1 });
  assert.ok(text.includes('3 open positions'));
  assert.ok(text.includes('up $45.00 today'));
  assert.ok(text.includes('1 position is currently at a loss'));
});

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
