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

test('combineLoading: true when any one source is loading (one screen must not appear to load because another source is mid-refresh, and vice versa)', () => {
  assert.strictEqual(combineLoading([source({ loading: true }), source({ loading: false })]), true);
});

// --- latestTimestamp ---------------------------------------------------------------------

test('latestTimestamp: null when no source has ever completed a refresh', () => {
  assert.strictEqual(latestTimestamp([source(), source()]), null);
});

test('latestTimestamp: picks the later of two independently-completed sources (ExecutiveBriefing = shared + founderBrief + market)', () => {
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

test('composeScreenRefresh: a single-source screen never reports another screen as loading or erroring', () => {
  const single = source({ loading: true, lastRefreshError: 'benchmark: timeout' });
  const composed = composeScreenRefresh([single]);
  assert.strictEqual(composed.loading, true);
  assert.strictEqual(composed.lastRefreshError, 'benchmark: timeout');
});

test('composeScreenRefresh: refresh() calls every underlying source exactly once and waits for all of them (ExecutiveBriefing = shared + founderBrief + market)', async () => {
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

// APP SIMPLIFICATION (2026-08-21): Recommendations and Market were deleted as dedicated
// screens; Market's 'market' (themes) source moved onto ExecutiveBriefing instead of being
// dropped entirely, since the Briefing still genuinely needs it.
test('SCREEN_DATA_SOURCES: exactly the three navigable screens are registered', () => {
  // 2026-08-24 simplification: five screens -> three. Operations was developer tooling,
  // Activity a notification list scrolled past, and Learning duplicated the Trade Scorecard.
  assert.deepStrictEqual(
    Object.keys(SCREEN_DATA_SOURCES).sort(),
    ['Ask', 'ExecutiveBriefing', 'Portfolio']
  );
});

test('SCREEN_DATA_SOURCES: Ask has no evidence source of its own', () => {
  // It asks the backend a question on demand rather than rendering a snapshot, so
  // pull-to-refresh there has nothing to refresh.
  assert.deepStrictEqual(SCREEN_DATA_SOURCES.Ask, []);
});

test('buildScreenRefreshRegistry: ExecutiveBriefing composes shared + founderBrief + market while other shared screens stay shared-only', () => {
  const shared = source({ lastRefreshedAt: '2026-08-03T10:00:00.000Z' });
  const market = source({ lastRefreshedAt: '2026-08-03T10:02:00.000Z' });
  const founderBrief = source({ lastRefreshedAt: '2026-08-03T10:01:00.000Z' });
  const registry = buildScreenRefreshRegistry({ shared, market, founderBrief });

  ['Portfolio'].forEach((screen) => {
    assert.strictEqual(registry[screen].lastRefreshedAt, shared.lastRefreshedAt, `${screen} should mirror the shared source`);
  });
  assert.strictEqual(registry.ExecutiveBriefing.lastRefreshedAt, market.lastRefreshedAt);
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


test('Portfolio refresh does not fetch market-exclusive endpoints', async () => {
  const { registry, calls } = trackedRegistry();
  await registry.Portfolio.refresh();
  assert.strictEqual(calls.market, 0);
  assert.strictEqual(calls.shared, 1);
});


test('ExecutiveBriefing refresh fetches its shared, founderBrief, and market sources exactly once each', async () => {
  const { registry, calls } = trackedRegistry();
  await registry.ExecutiveBriefing.refresh();
  assert.strictEqual(calls.shared, 1);
  assert.strictEqual(calls.founderBrief, 1);
  assert.strictEqual(calls.market, 1);
});


test('repeated taps on the same screen do not change how many underlying sources are composed (dedup is each source\'s own responsibility, not re-implemented here)', async () => {
  const { registry, calls } = trackedRegistry();
  // Was registry.Activity, which stopped existing when the app was cut to three
  // screens -- the test crashed on undefined rather than failing an assertion, so it
  // read as a broken suite instead of a stale one. Portfolio is the shared-only screen
  // this case is actually about.
  await Promise.all([registry.Portfolio.refresh(), registry.Portfolio.refresh()]);
  // composeScreenRefresh itself calls the underlying source's refresh() once per call; the
  // underlying source (useFounderEvidence's own refreshInFlightRef, tested in
  // refreshLifecycle.test.js's shouldStartRefresh cases) is what collapses these into one
  // network request. This test only proves screenRefresh.js does not ITSELF add a second way
  // to double-fetch on top of that guard.
  assert.strictEqual(calls.shared, 2);
});

console.log(`\n${passed} passed`);
