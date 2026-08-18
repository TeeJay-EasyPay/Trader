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

test('unavailableStatus (AT-ED-011.9): does not presume every failure is specifically a Render API timeout', () => {
  const result = unavailableStatus('unauthorized: token mismatch');
  const check = result.connection_readiness.checks[0];
  assert.notStrictEqual(check.status, 'timeout');
  assert.strictEqual(check.detail, 'unauthorized: token mismatch');
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
  const headline = founderHeadline({ brokers: [{ broker: 'alpaca', day_pnl: -5 }], trades: [1], status: { state: 'OPERATING NORMALLY' } });
  assert.ok(headline.includes('down'));
  assert.ok(headline.includes('1 broker order'));
});

test('founderHeadline (AT-ED-017 Founder request): names Alpaca (USD) and Kraken (GBP) separately, never blended under one currency symbol', () => {
  const headline = founderHeadline({
    brokers: [{ broker: 'alpaca', day_pnl: 490.15 }, { broker: 'kraken', day_pnl: -21.48 }],
    trades: [],
    status: { state: 'OPERATING NORMALLY' },
  });
  assert.ok(headline.includes('Alpaca is up $490.15'));
  assert.ok(headline.includes('Kraken is down £21.48'));
});

test('founderHeadline: no per-broker P&L evidence is honest, not fabricated', () => {
  const headline = founderHeadline({ brokers: [], trades: [], status: { state: 'OPERATING NORMALLY' } });
  assert.ok(headline.includes('awaiting comparable broker evidence'));
});

test('founderAction: not operating normally always asks to review Activity first', () => {
  assert.ok(founderAction({ status: { state: 'STATUS UNKNOWN' } }).startsWith('Open Activity'));
});

test('statusFromFounderEvidence (AT-ED-016.3): never leaks raw why-no-trade reason codes/counts into upcoming_risks', () => {
  const result = statusFromFounderEvidence({
    why_no_trade: {
      conclusion: 'AI Trader reviewed 9 asset(s), but no opportunity progressed to a candidate.',
      top_reasons: [
        { reason: 'philosophy_fit_below_auto_trade_minimum', count: 24 },
        { reason: 'Handled by the independent per-broker auto-execution jobs.', count: 4 },
      ],
    },
  });
  const upcomingRisks = result.founder_experience.market_intelligence_centre.upcoming_risks;
  assert.deepStrictEqual(upcomingRisks, []);
});

test('statusFromFounderEvidence (AT-ED-017 Founder request): portfolio_health names each broker in its own currency, never blended', () => {
  const result = statusFromFounderEvidence({
    portfolio: { portfolio_value: 95000 },
    brokers: [
      { broker: 'alpaca', portfolio_value: 65000, day_pnl: 490.15 },
      { broker: 'kraken', portfolio_value: 30000, day_pnl: -21.48 },
    ],
  });
  const health = result.founder_experience.executive_dashboard.portfolio_health;
  assert.ok(health.includes('Alpaca is up $490.15'));
  assert.ok(health.includes('Kraken is down £21.48'));
  assert.ok(!health.endsWith('..'));
});

test('statusFromFounderEvidence (AT-ED-016.3): never mislabels a research-run summary sentence as the current market regime', () => {
  const result = statusFromFounderEvidence({
    research: [{ broker: 'kraken', summary: 'Kraken research reviewed 9 asset(s) and created 6 recommendation(s).' }],
  });
  assert.strictEqual(result.founder_experience.market_intelligence_centre.current_market_regime, null);
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

test('founderLearningForMobile (2026-08-17 hosted finding): reads closed_trade_history, not the period-bound trades field, and recognises an Alpaca "filled" exit', () => {
  const result = founderLearningForMobile({
    learning: [],
    trades: [], // period-scoped (default 24h) - deliberately empty, must be ignored here
    closed_trade_history: [
      { status: 'filled', side: 'sell', realized_pnl: 639.12, closed_at: '2026-08-12T13:33:46Z', ai_decided: true },
      { status: 'filled', side: 'buy', realized_pnl: null, closed_at: '2026-07-03T13:50:55Z', ai_decided: true },
    ],
    generated_at: '2026-08-18T00:00:00Z',
  });
  assert.strictEqual(result.trade_outcomes.closed_trades, 1);
  assert.strictEqual(result.trade_outcomes.win_rate, 1);
  assert.strictEqual(result.trade_outcomes.total_profit_loss, 639.12);
});

test('founderLearningForMobile (2026-08-18 Founder request): excludes a real closed trade the AI did not decide, even with a real realized_pnl', () => {
  const result = founderLearningForMobile({
    learning: [],
    trades: [],
    closed_trade_history: [
      // Shaped exactly like the real CSL legacy exit this fix was built around: a genuine
      // realized_pnl, but never proposed or governed by the AI's own execution path.
      { symbol: 'CSL', status: 'filled', side: 'sell', realized_pnl: 639.12, closed_at: '2026-08-12T13:33:46Z', ai_decided: false },
    ],
    generated_at: '2026-08-18T00:00:00Z',
  });
  assert.strictEqual(result.trade_outcomes.closed_trades, 0);
  assert.strictEqual(result.trade_outcomes.win_rate, null);
  assert.strictEqual(result.trade_outcomes.total_profit_loss, null);
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
