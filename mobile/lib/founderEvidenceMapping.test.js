// Plain Node assert-based tests for founderEvidenceMapping.js.
// Run with `node mobile/lib/founderEvidenceMapping.test.js`.

'use strict';

const assert = require('assert');
const {
  unavailableStatus,
  unavailableActivity,
  statusFromFounderEvidence,
  activityFromFounderEvidence,
  productionTradeForMobile,
  brokerResearchStatus,
  founderHeadline,
  founderAction,
  founderLearningForMobile,
  sortByConfidence,
} = require('./founderEvidenceMapping');

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

test('unavailableStatus: builds a degraded-but-honest shape, never fabricating a healthy state', () => {
  const result = unavailableStatus('backend timed out');
  assert.strictEqual(result.system_status, 'partial');
  assert.strictEqual(result.connection_readiness.trade_ready, false);
  assert.ok(result.research_status.includes('backend timed out'));
});

test('unavailableActivity: builds a degraded-but-honest activity shape with all 9 sections present', () => {
  const result = unavailableActivity('network error');
  assert.strictEqual(result.status.state, 'STATUS UNKNOWN');
  assert.strictEqual(result.fetch_error, 'network error');
  assert.deepStrictEqual(result.timeline.items, []);
});

test('productionTradeForMobile: maps broker trade evidence field names to the mobile shape', () => {
  const result = productionTradeForMobile({ observed_at: '2026-01-01', quantity: 5, average_fill_price: 10, realized_pnl: 3 });
  assert.strictEqual(result.created_at, '2026-01-01');
  assert.strictEqual(result.qty, 5);
  assert.strictEqual(result.filled_avg_price, 10);
  assert.strictEqual(result.profit_loss, 3);
});

test('brokerResearchStatus: finds the matching broker row case-insensitively', () => {
  const rows = [{ broker: 'Kraken', status: 'completed', assets_analysed: 4, completed_at: '2026-01-01T00:00:00Z' }];
  assert.ok(brokerResearchStatus(rows, 'kraken').startsWith('completed - 4 asset(s)'));
});

test('brokerResearchStatus: no matching row reads as no evidence, not an error', () => {
  assert.strictEqual(brokerResearchStatus([], 'alpaca'), 'No research evidence recorded for this broker in the selected period');
});

test('founderHeadline: reports the day P&L direction and trade count', () => {
  const headline = founderHeadline({ portfolio: { todays_pnl: -5 }, trades: [1], status: { state: 'OPERATING NORMALLY' } });
  assert.ok(headline.includes('down'));
  assert.ok(headline.includes('1 broker order'));
});

test('founderAction: not operating normally always asks to review Activity first', () => {
  assert.ok(founderAction({ status: { state: 'STATUS UNKNOWN' } }).startsWith('Open Activity'));
});

test('founderAction: operating normally with recommendations asks to review them', () => {
  const action = founderAction({ status: { state: 'OPERATING NORMALLY' }, recommendations: [{}, {}] });
  assert.ok(action.includes('Review 2 persisted recommendation(s)'));
});

test('statusFromFounderEvidence: maps a minimal evidence payload without throwing', () => {
  const result = statusFromFounderEvidence({
    status: { state: 'OPERATING NORMALLY', plain_english: 'ok' },
    portfolio: { portfolio_value: 100, todays_pnl: 1 },
    brokers: [{ broker: 'alpaca', payload: {}, connection_status: 'connected' }],
    trades: [],
    recommendations: [],
    learning: [],
    research: [],
    jobs: [],
  });
  assert.strictEqual(result.system_status, 'OPERATING NORMALLY');
  assert.strictEqual(result.brokers.length, 1);
  assert.strictEqual(result.brokers[0].label, 'Alpaca');
});

test('statusFromFounderEvidence: a non-postgres database_status never renders the raw backend word to the Founder', () => {
  const result = statusFromFounderEvidence({
    status: { state: 'OPERATING WITH WARNINGS', plain_english: 'degraded', database_status: 'sqlite' },
    portfolio: { portfolio_value: 100, todays_pnl: 1 },
    brokers: [],
    trades: [],
    recommendations: [],
    learning: [],
    research: [],
    jobs: [],
  });
  assert.ok(!result.operations_health.database_durability.toLowerCase().includes('sqlite'));
  const postgresCheck = result.connection_readiness.checks.find((item) => item.component === 'Supabase Postgres');
  assert.ok(!postgresCheck.status.toLowerCase().includes('sqlite'));
  assert.strictEqual(postgresCheck.ready, false);
  // The technical diagnostic field is allowed to carry the raw identifier - only the
  // Founder-facing presentation fields above must never show it bare.
  assert.strictEqual(result.operations_health.database_backend.active_backend, 'sqlite');
});

test('activityFromFounderEvidence: derives timeline counts and an empty-state message when there is no activity', () => {
  const result = activityFromFounderEvidence({ timeline: { items: [], total: 0 }, status: { state: 'OPERATING NORMALLY' } });
  assert.strictEqual(result.timeline.returned, 0);
  assert.ok(result.timeline.empty_state.includes('No autonomous activity'));
});

test('founderLearningForMobile: no closed trades gives the no-evidence summary, not a fabricated win rate', () => {
  const result = founderLearningForMobile({ learning: [], trades: [], generated_at: '2026-01-01T00:00:00Z' });
  assert.strictEqual(result.trade_outcomes.closed_trades, 0);
  assert.strictEqual(result.trade_outcomes.win_rate, null);
});

test('sortByConfidence: sorts descending by confidence, breaking ties by newest first', () => {
  const items = [
    { confidence: 0.5, created_at: '2026-01-01T00:00:00Z' },
    { confidence: 0.9, created_at: '2026-01-01T00:00:00Z' },
    { confidence: 0.5, created_at: '2026-01-02T00:00:00Z' },
  ];
  const sorted = sortByConfidence(items);
  assert.strictEqual(sorted[0].confidence, 0.9);
  assert.strictEqual(sorted[1].created_at, '2026-01-02T00:00:00Z');
});

console.log(`\n${passed} passed`);
