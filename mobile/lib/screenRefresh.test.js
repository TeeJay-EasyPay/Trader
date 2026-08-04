// Plain Node assert-based tests for screenRefresh.js - run with
// `node mobile/lib/screenRefresh.test.js`. See that file's module comment for why this exists:
// AT-ED-011.5 requirement 5 ("each major screen refreshes independently"), verified here at the
// pure-function level since the hooks themselves cannot run under plain `node`.

'use strict';

const assert = require('assert');
const {
  SCREEN_DATA_SOURCES,
  combineLoading,
  latestTimestamp,
  combineErrors,
  composeScreenRefresh,
  buildScreenRefreshRegistry,
} = require('./screenRefresh');

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

function source({ loading = false, lastRefreshedAt = null, lastRefreshError = null, refresh = async () => {} } = {}) {
  return { loading, lastRefreshedAt, lastRefreshError, refresh };
}

// --- combineLoading ---------------------------------------------------------------------

test('combineLoading: false when no source is loading', () => {
  assert.strictEqual(combineLoading([source(), source()]), false);
});

test('combineLoading: true when any one source is loading (Market must not appear to load because founder-evidence is mid-refresh, and vice versa)', () => {
  assert.strictEqual(combineLoading([source({ loading: true }), source({ loading: false })]), true);
});

// --- latestTimestamp ---------------------------------------------------------------------

test('latestTimestamp: null when no source has ever completed a refresh', () => {
  assert.strictEqual(latestTimestamp([source(), source()]), null);
});

test('latestTimestamp: picks the later of two independently-completed sources (ExecutiveBriefing/Operations = shared + founderBrief)', () => {
  const earlier = '2026-08-03T10:00:00.000Z';
  const later = '2026-08-03T10:05:00.000Z';
  assert.strictEqual(
    latestTimestamp([source({ lastRefreshedAt: earlier }), source({ lastRefreshedAt: later })]),
    later
  );
});

test('latestTimestamp: ignores sources that have not completed yet', () => {
  const only = '2026-08-03T10:00:00.000Z';
  assert.strictEqual(latestTimestamp([source({ lastRefreshedAt: only }), source()]), only);
});

// --- combineErrors -----------------------------------------------------------------------

test('combineErrors: null when nothing failed', () => {
  assert.strictEqual(combineErrors([source(), source()]), null);
});

test('combineErrors: names every failing source, truthfully, not merged into one vague message', () => {
  const combined = combineErrors([
    source({ lastRefreshError: 'shared failed' }),
    source({ lastRefreshError: null }),
  ]);
  assert.strictEqual(combined, 'shared failed');
});

// --- composeScreenRefresh ------------------------------------------------------------------

test('composeScreenRefresh: a single-source screen (Market) never reports another screen as loading or erroring', () => {
  const market = source({ loading: true, lastRefreshError: 'benchmark: timeout' });
  const composed = composeScreenRefresh([market]);
  assert.strictEqual(composed.loading, true);
  assert.strictEqual(composed.lastRefreshError, 'benchmark: timeout');
});

test('composeScreenRefresh: refresh() calls every underlying source exactly once and waits for all of them (ExecutiveBriefing/Operations = shared + founderBrief)', async () => {
  const calls = [];
  const shared = source({ refresh: async () => { calls.push('shared'); } });
  const founderBrief = source({ refresh: async () => { calls.push('founderBrief'); } });
  await composeScreenRefresh([shared, founderBrief]).refresh();
  assert.deepStrictEqual(calls.sort(), ['founderBrief', 'shared']);
});

test('composeScreenRefresh: one failing source does not stop the composed refresh from calling the others (screen failures stay isolated)', async () => {
  const calls = [];
  const failing = source({ refresh: async () => { calls.push('failing'); throw new Error('boom'); } });
  const healthy = source({ refresh: async () => { calls.push('healthy'); } });
  await assert.rejects(() => composeScreenRefresh([failing, healthy]).refresh());
  assert.deepStrictEqual(calls.sort(), ['failing', 'healthy']);
});

// --- buildScreenRefreshRegistry / SCREEN_DATA_SOURCES --------------------------------------

test('SCREEN_DATA_SOURCES: exactly the seven navigable screens are registered (AT-ED-015 renamed CIO to ExecutiveBriefing)', () => {
  assert.deepStrictEqual(
    Object.keys(SCREEN_DATA_SOURCES).sort(),
    ['Activity', 'ExecutiveBriefing', 'Learning', 'Market', 'Operations', 'Portfolio', 'Recommendations']
  );
});

test('buildScreenRefreshRegistry: Activity, Portfolio, Recommendations, and Learning all compose to the SAME shared source, not their own copies', () => {
  const shared = source({ lastRefreshedAt: '2026-08-03T10:00:00.000Z' });
  const market = source({ lastRefreshedAt: '2026-08-03T09:00:00.000Z' });
  const founderBrief = source({ lastRefreshedAt: '2026-08-03T10:01:00.000Z' });
  const registry = buildScreenRefreshRegistry({ shared, market, founderBrief });

  ['Activity', 'Portfolio', 'Recommendations', 'Learning'].forEach((screen) => {
    assert.strictEqual(registry[screen].lastRefreshedAt, shared.lastRefreshedAt, `${screen} should mirror the shared source`);
  });
});

test('buildScreenRefreshRegistry: Market never fetches Founder Evidence and Learning never fetches Founder Brief', async () => {
  const sharedCalls = [];
  const marketCalls = [];
  const founderBriefCalls = [];
  const registry = buildScreenRefreshRegistry({
    shared: source({ refresh: async () => { sharedCalls.push(1); } }),
    market: source({ refresh: async () => { marketCalls.push(1); } }),
    founderBrief: source({ refresh: async () => { founderBriefCalls.push(1); } }),
  });

  await registry.Market.refresh();
  assert.strictEqual(marketCalls.length, 1);
  assert.strictEqual(sharedCalls.length, 0);
  assert.strictEqual(founderBriefCalls.length, 0);

  await registry.Learning.refresh();
  assert.strictEqual(sharedCalls.length, 1);
  assert.strictEqual(founderBriefCalls.length, 0);
});

test('buildScreenRefreshRegistry: ExecutiveBriefing and Operations both compose shared + founderBrief only, never market', async () => {
  const marketCalls = [];
  const registry = buildScreenRefreshRegistry({
    shared: source(),
    market: source({ refresh: async () => { marketCalls.push(1); } }),
    founderBrief: source(),
  });
  await registry.ExecutiveBriefing.refresh();
  await registry.Operations.refresh();
  assert.strictEqual(marketCalls.length, 0);
});

// --- AT-ED-011.5 required-test checklist: one explicit test per named requirement -----------
// (largely re-proving what the tests above already establish structurally, but named to match
// the directive's own checklist 1:1 so each requirement has a directly-traceable test.)

function trackedRegistry() {
  const calls = { shared: 0, market: 0, founderBrief: 0 };
  const registry = buildScreenRefreshRegistry({
    shared: source({ refresh: async () => { calls.shared += 1; } }),
    market: source({ refresh: async () => { calls.market += 1; } }),
    founderBrief: source({ refresh: async () => { calls.founderBrief += 1; } }),
  });
  return { registry, calls };
}

test('Activity refresh does not fetch Market-exclusive endpoints', async () => {
  const { registry, calls } = trackedRegistry();
  await registry.Activity.refresh();
  assert.strictEqual(calls.market, 0);
  assert.strictEqual(calls.shared, 1);
});

test('Portfolio refresh does not fetch Market-exclusive endpoints', async () => {
  const { registry, calls } = trackedRegistry();
  await registry.Portfolio.refresh();
  assert.strictEqual(calls.market, 0);
  assert.strictEqual(calls.shared, 1);
});

test('Learning refresh does not fetch Founder Brief', async () => {
  const { registry, calls } = trackedRegistry();
  await registry.Learning.refresh();
  assert.strictEqual(calls.founderBrief, 0);
  assert.strictEqual(calls.shared, 1);
});

test('Market refresh does not refresh Founder Evidence', async () => {
  const { registry, calls } = trackedRegistry();
  await registry.Market.refresh();
  assert.strictEqual(calls.shared, 0);
  assert.strictEqual(calls.founderBrief, 0);
  assert.strictEqual(calls.market, 1);
});

test('ExecutiveBriefing refresh fetches only its required shared and exclusive (founderBrief) sources', async () => {
  const { registry, calls } = trackedRegistry();
  await registry.ExecutiveBriefing.refresh();
  assert.strictEqual(calls.shared, 1);
  assert.strictEqual(calls.founderBrief, 1);
  assert.strictEqual(calls.market, 0);
});

test('Operations refresh fetches only its required shared and exclusive (founderBrief) sources', async () => {
  const { registry, calls } = trackedRegistry();
  await registry.Operations.refresh();
  assert.strictEqual(calls.shared, 1);
  assert.strictEqual(calls.founderBrief, 1);
  assert.strictEqual(calls.market, 0);
});

test('repeated taps on the same screen do not change how many underlying sources are composed (dedup is each source\'s own responsibility, not re-implemented here)', async () => {
  const { registry, calls } = trackedRegistry();
  await Promise.all([registry.Activity.refresh(), registry.Activity.refresh()]);
  // composeScreenRefresh itself calls the underlying source's refresh() once per call; the
  // underlying source (useFounderEvidence's own refreshInFlightRef, tested in
  // refreshLifecycle.test.js's shouldStartRefresh cases) is what collapses these into one
  // network request. This test only proves screenRefresh.js does not ITSELF add a second way
  // to double-fetch on top of that guard.
  assert.strictEqual(calls.shared, 2);
});

console.log(`\n${passed} passed`);
