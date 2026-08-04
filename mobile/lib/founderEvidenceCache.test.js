// Plain Node assert-based tests for founderEvidenceCache.js.
// Run with `node mobile/lib/founderEvidenceCache.test.js`.

'use strict';

const assert = require('assert');
const {
  FOUNDER_EVIDENCE_CACHE_VERSION,
  MAX_CACHED_RECOMMENDATION_STUBS,
  MAX_CACHED_TRADES,
  MAX_CACHED_JOBS,
  MAX_CACHED_TIMELINE_ITEMS,
  MAX_CACHED_RESEARCH_ROWS,
  MAX_CACHED_LEARNING_ROWS,
  buildFounderEvidenceCacheSnapshot,
  parseCachedFounderEvidenceEnvelope,
} = require('./founderEvidenceCache');

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

// A representative large recommendation, matching the field shapes and rough sizes measured
// against production /founder-evidence on 2026-08-04 (see founderEvidenceCache.js's module
// comment): the heavy fields (intelligence/committee/strategy/signals/probability) are the
// ~94.9%-of-payload contributor this fix targets.
function heavyRecommendation(index) {
  return {
    proposal_id: `proposal-${index}`,
    recommendation_id: `rec-${index}`,
    symbol: `SYM${index}`,
    broker: index % 2 === 0 ? 'alpaca' : 'kraken',
    suggested_broker: index % 2 === 0 ? 'alpaca' : 'kraken',
    freshness_status: index % 3 === 0 ? 'Expired' : 'Fresh',
    confidence: 0.5 + (index % 50) / 100,
    created_at: '2026-08-04T00:00:00Z',
    // Heavy fields below are never read by statusFromFounderEvidence beyond the scalars
    // above - they must not survive into the cache.
    intelligence: { longText: 'x'.repeat(20000) },
    committee: { members: Array.from({ length: 5 }, () => ({ vote: 'buy', reasoning: 'y'.repeat(500) })) },
    strategy: { name: 'trend', notes: 'z'.repeat(4000) },
    signals: Array.from({ length: 10 }, () => ({ indicator: 'rsi', value: 50, note: 'w'.repeat(300) })),
    probability: { distribution: Array.from({ length: 20 }, () => 0.05) },
    plain_english_reasoning: 'a'.repeat(80),
  };
}

function heavyBroker(broker) {
  const payload = { balance_summary: { converted_assets: Array.from({ length: 30 }, (_, i) => ({ asset: `A${i}`, value_gbp: 1.23 })) } };
  return {
    broker,
    connection_status: 'Connected',
    portfolio_value: 1000,
    cash: 100,
    // Duplicate encodings that must be dropped:
    payload,
    payload_json: JSON.stringify(payload),
    positions: [{ symbol: 'BTC', qty: 1 }],
    positions_json: JSON.stringify([{ symbol: 'BTC', qty: 1 }]),
  };
}

function representativeLargeFounderEvidence() {
  return {
    generated_at: '2026-08-04T00:00:00Z',
    period: '24h',
    status: { state: 'OPERATING NORMALLY', plain_english: 'ok', database_status: 'postgres' },
    portfolio: {
      portfolio_value: 5000,
      cash_available: 100,
      deployed_capital: 4900,
      todays_pnl: 12.5,
      open_positions: Array.from({ length: 13 }, (_, i) => ({ symbol: `P${i}` })),
      // Duplicate of the top-level `brokers` array - must be dropped.
      brokers: [heavyBroker('alpaca'), heavyBroker('kraken')],
    },
    brokers: [heavyBroker('alpaca'), heavyBroker('kraken')],
    summary: { research: { runs: 5, assets_analysed: 40 } },
    why_no_trade: { state: 'unknown', conclusion: 'none' },
    snapshot: { served_from: 'worker_projection', stale: false },
    truthfulness: { source: 'test', mock_data_used: false },
    recommendations: Array.from({ length: 100 }, (_, i) => heavyRecommendation(i)),
    trades: Array.from({ length: 100 }, (_, i) => ({ proposal_id: `p${i}`, observed_at: '2026-08-04T00:00:00Z' })),
    research: Array.from({ length: 32 }, (_, i) => ({ broker: 'alpaca', completed_at: '2026-08-04T00:00:00Z', assets_analysed: i })),
    learning: [],
    jobs: Array.from({ length: 100 }, (_, i) => ({ job_name: `job-${i}`, status: 'completed', completed_at: '2026-08-04T00:00:00Z' })),
    timeline: { items: Array.from({ length: 120 }, (_, i) => ({ title: `event-${i}`, timestamp: '2026-08-04T00:00:00Z' })), total: 120 },
  };
}

// --- buildFounderEvidenceCacheSnapshot ---

test('buildFounderEvidenceCacheSnapshot: null/non-object input returns null, never throws', () => {
  assert.strictEqual(buildFounderEvidenceCacheSnapshot(null), null);
  assert.strictEqual(buildFounderEvidenceCacheSnapshot(undefined), null);
  assert.strictEqual(buildFounderEvidenceCacheSnapshot('not an object'), null);
});

test('buildFounderEvidenceCacheSnapshot: every bounded array respects its documented maximum', () => {
  const snapshot = buildFounderEvidenceCacheSnapshot(representativeLargeFounderEvidence());
  assert.strictEqual(snapshot.recommendations.length, MAX_CACHED_RECOMMENDATION_STUBS);
  assert.strictEqual(snapshot.trades.length, MAX_CACHED_TRADES);
  assert.strictEqual(snapshot.jobs.length, MAX_CACHED_JOBS);
  assert.strictEqual(snapshot.timeline.items.length, MAX_CACHED_TIMELINE_ITEMS);
  assert.strictEqual(snapshot.research.length, MAX_CACHED_RESEARCH_ROWS);
  assert.strictEqual(snapshot.learning.length, 0);
  // total is preserved even though items are truncated, so the UI can still say "120 total".
  assert.strictEqual(snapshot.timeline.total, 120);
});

test('buildFounderEvidenceCacheSnapshot: recommendation stubs drop every heavy dossier field', () => {
  const snapshot = buildFounderEvidenceCacheSnapshot(representativeLargeFounderEvidence());
  snapshot.recommendations.forEach((stub) => {
    assert.strictEqual(stub.intelligence, undefined);
    assert.strictEqual(stub.committee, undefined);
    assert.strictEqual(stub.strategy, undefined);
    assert.strictEqual(stub.signals, undefined);
    assert.strictEqual(stub.probability, undefined);
    assert.strictEqual(stub.plain_english_reasoning, undefined);
  });
  // But the scalars statusFromFounderEvidence actually reads all survive.
  assert.strictEqual(snapshot.recommendations[0].symbol, 'SYM0');
  assert.strictEqual(snapshot.recommendations[0].freshness_status, 'Expired');
  assert.strictEqual(snapshot.recommendations[1].freshness_status, 'Fresh');
});

test('buildFounderEvidenceCacheSnapshot: drops portfolio.brokers (duplicate of top-level brokers)', () => {
  const snapshot = buildFounderEvidenceCacheSnapshot(representativeLargeFounderEvidence());
  assert.strictEqual(snapshot.portfolio.brokers, undefined);
  // The fields statusFromFounderEvidence actually reads off portfolio survive.
  assert.strictEqual(snapshot.portfolio.portfolio_value, 5000);
  assert.strictEqual(snapshot.portfolio.open_positions.length, 13);
});

test('buildFounderEvidenceCacheSnapshot: drops payload_json/positions_json (duplicates of payload/positions)', () => {
  const snapshot = buildFounderEvidenceCacheSnapshot(representativeLargeFounderEvidence());
  snapshot.brokers.forEach((broker) => {
    assert.strictEqual(broker.payload_json, undefined);
    assert.strictEqual(broker.positions_json, undefined);
    // The parsed forms statusFromFounderEvidence actually reads survive.
    assert.ok(broker.payload);
    assert.ok(broker.positions);
  });
});

test('buildFounderEvidenceCacheSnapshot: serialized size stays comfortably below the AsyncStorage ceiling that caused AT-ED-011.8', () => {
  const fullPayload = representativeLargeFounderEvidence();
  const fullSize = Buffer.byteLength(JSON.stringify(fullPayload), 'utf8');
  const snapshot = buildFounderEvidenceCacheSnapshot(fullPayload);
  const snapshotSize = Buffer.byteLength(JSON.stringify(snapshot), 'utf8');
  // The representative fixture is deliberately sized close to the real 2026-08-04 production
  // measurement (100 recommendations with heavy per-item fields dominate).
  assert.ok(fullSize > 3_000_000, `fixture should be multi-megabyte to be representative, was ${fullSize}`);
  // AsyncStorage's documented Android SQLite ceiling is commonly cited around 6MB shared
  // across every key the app has ever written - budgeting for well under 10% of that leaves
  // wide margin for every other cache key (recommendations, etc.) plus normal growth.
  assert.ok(snapshotSize < 500_000, `cache snapshot should stay well under 500KB, was ${snapshotSize}`);
});

test('buildFounderEvidenceCacheSnapshot: a small/typical payload passes through with every top-level key present', () => {
  const evidence = {
    generated_at: '2026-08-04T00:00:00Z',
    status: { state: 'OPERATING NORMALLY' },
    portfolio: { portfolio_value: 100 },
    brokers: [],
    summary: {},
    why_no_trade: {},
    recommendations: [],
    trades: [],
    research: [],
    learning: [],
    jobs: [],
    timeline: { items: [], total: 0 },
  };
  const snapshot = buildFounderEvidenceCacheSnapshot(evidence);
  ['generated_at', 'status', 'portfolio', 'brokers', 'summary', 'why_no_trade', 'recommendations', 'trades', 'research', 'learning', 'jobs', 'timeline'].forEach((key) => {
    assert.ok(key in snapshot, `expected ${key} to be present in the snapshot`);
  });
});

// --- parseCachedFounderEvidenceEnvelope ---

test('parseCachedFounderEvidenceEnvelope: current-version envelope is compatible', () => {
  const result = parseCachedFounderEvidenceEnvelope({ v: FOUNDER_EVIDENCE_CACHE_VERSION, data: { status: {} }, fetchedAt: '2026-08-04T00:00:00Z' });
  assert.strictEqual(result.compatible, true);
  assert.deepStrictEqual(result.data, { status: {} });
  assert.strictEqual(result.fetchedAt, '2026-08-04T00:00:00Z');
});

test('parseCachedFounderEvidenceEnvelope: AT-ED-011.8-era legacy cache (no v field, full raw payload under data) is incompatible', () => {
  const legacyCache = { data: representativeLargeFounderEvidence(), fetchedAt: '2026-08-03T00:00:00Z' };
  const result = parseCachedFounderEvidenceEnvelope(legacyCache);
  assert.strictEqual(result.compatible, false);
  assert.strictEqual(result.data, null);
});

test('parseCachedFounderEvidenceEnvelope: pre-AT-ED-010 bare-payload cache (no envelope at all) is incompatible', () => {
  const result = parseCachedFounderEvidenceEnvelope({ status: {}, portfolio: {} });
  assert.strictEqual(result.compatible, false);
});

test('parseCachedFounderEvidenceEnvelope: a future/unknown version is incompatible, not guessed at', () => {
  const result = parseCachedFounderEvidenceEnvelope({ v: 999, data: { status: {} } });
  assert.strictEqual(result.compatible, false);
});

test('parseCachedFounderEvidenceEnvelope: null, non-object, and malformed input never throw', () => {
  assert.strictEqual(parseCachedFounderEvidenceEnvelope(null).compatible, false);
  assert.strictEqual(parseCachedFounderEvidenceEnvelope(undefined).compatible, false);
  assert.strictEqual(parseCachedFounderEvidenceEnvelope('a string').compatible, false);
  assert.strictEqual(parseCachedFounderEvidenceEnvelope({ v: 2, data: 'not an object' }).compatible, false);
});

console.log(`\n${passed} passed`);
if (process.exitCode) {
  console.error('Some founderEvidenceCache tests failed.');
}
