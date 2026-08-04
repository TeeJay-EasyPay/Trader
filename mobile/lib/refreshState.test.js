// Plain Node assert-based tests for refreshState.js. No test framework is installed for
// this project (see mobile/package.json) - run directly with `node mobile/lib/refreshState.test.js`.
// Exits non-zero on any failure so it can be wired into CI later without changes.

'use strict';

const assert = require('assert');
const {
  DISPLAY_STATE,
  TONE_EMOJI,
  classifyDisplayState,
  snapshotFreshness,
  formatAgeSeconds,
  cacheBannerDetails,
  friendlyRefreshFailureReason,
  displayStateBadge,
  connectionMessage,
} = require('./refreshState');

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

// --- classifyDisplayState ---

test('classifyDisplayState: in-flight refresh always wins, regardless of prior state', () => {
  const result = classifyDisplayState({
    isRefreshing: true,
    hasAttempted: true,
    lastRefreshSucceeded: false,
    hasCachedData: true,
    backendSnapshotStale: false,
  });
  assert.strictEqual(result, DISPLAY_STATE.REFRESHING);
});

test('classifyDisplayState: before the first attempt completes is No Data Available, not Refresh Failed', () => {
  const result = classifyDisplayState({
    isRefreshing: false,
    hasAttempted: false,
    lastRefreshSucceeded: null,
    hasCachedData: false,
    backendSnapshotStale: null,
  });
  assert.strictEqual(result, DISPLAY_STATE.NO_DATA_AVAILABLE);
});

test('classifyDisplayState: successful fetch with a fresh backend snapshot is Live', () => {
  const result = classifyDisplayState({
    isRefreshing: false,
    hasAttempted: true,
    lastRefreshSucceeded: true,
    hasCachedData: true,
    backendSnapshotStale: false,
  });
  assert.strictEqual(result, DISPLAY_STATE.LIVE);
});

test('classifyDisplayState: successful fetch but the backend snapshot itself is stale', () => {
  const result = classifyDisplayState({
    isRefreshing: false,
    hasAttempted: true,
    lastRefreshSucceeded: true,
    hasCachedData: true,
    backendSnapshotStale: true,
  });
  assert.strictEqual(result, DISPLAY_STATE.BACKEND_SNAPSHOT_STALE);
});

test('classifyDisplayState: failed fetch (after retry) with a cache available is Cached, never silently Live', () => {
  const result = classifyDisplayState({
    isRefreshing: false,
    hasAttempted: true,
    lastRefreshSucceeded: false,
    hasCachedData: true,
    backendSnapshotStale: null,
  });
  assert.strictEqual(result, DISPLAY_STATE.CACHED);
});

test('classifyDisplayState: failed fetch (after retry) with no cache at all is Refresh Failed, not silently blank', () => {
  const result = classifyDisplayState({
    isRefreshing: false,
    hasAttempted: true,
    lastRefreshSucceeded: false,
    hasCachedData: false,
    backendSnapshotStale: null,
  });
  assert.strictEqual(result, DISPLAY_STATE.REFRESH_FAILED);
});

test('classifyDisplayState: a prior successful fetch never gets reported as Live while a new attempt is in flight', () => {
  const result = classifyDisplayState({
    isRefreshing: true,
    hasAttempted: true,
    lastRefreshSucceeded: true,
    hasCachedData: true,
    backendSnapshotStale: false,
  });
  assert.strictEqual(result, DISPLAY_STATE.REFRESHING);
});

// --- snapshotFreshness ---

test('snapshotFreshness: missing snapshot field (e.g. _snapshot_not_ready_payload) is reported as unknown, not stale/fresh', () => {
  const result = snapshotFreshness(undefined);
  assert.strictEqual(result.known, false);
  assert.strictEqual(result.ageSeconds, null);
  assert.strictEqual(result.stale, null);
});

test('snapshotFreshness: reads age_seconds/stale/generated_at straight from the backend payload', () => {
  const result = snapshotFreshness({ served_from: 'worker_projection', age_seconds: 512, stale: false, generated_at: '2026-08-03T01:00:00Z' });
  assert.deepStrictEqual(result, { known: true, ageSeconds: 512, stale: false, generatedAt: '2026-08-03T01:00:00Z' });
});

test('snapshotFreshness: stale flag true is preserved exactly, not inferred locally', () => {
  const result = snapshotFreshness({ age_seconds: 950, stale: true, generated_at: '2026-08-03T00:40:00Z' });
  assert.strictEqual(result.stale, true);
});

// --- formatAgeSeconds ---

test('formatAgeSeconds: under a minute', () => {
  assert.strictEqual(formatAgeSeconds(45), '45s ago');
});

test('formatAgeSeconds: minutes', () => {
  assert.strictEqual(formatAgeSeconds(125), '2m ago');
});

test('formatAgeSeconds: hours', () => {
  assert.strictEqual(formatAgeSeconds(3 * 3600 + 200), '3h ago');
});

test('formatAgeSeconds: days once past 48 hours', () => {
  assert.strictEqual(formatAgeSeconds(3 * 86400), '3d ago');
});

test('formatAgeSeconds: null/invalid input never throws or returns NaN text', () => {
  assert.strictEqual(formatAgeSeconds(null), null);
  assert.strictEqual(formatAgeSeconds(undefined), null);
  assert.strictEqual(formatAgeSeconds(-5), null);
  assert.strictEqual(formatAgeSeconds(NaN), null);
});

// --- cacheBannerDetails ---

test('cacheBannerDetails: computes a human age from cachedAt against a fixed clock', () => {
  const result = cacheBannerDetails({
    cachedAt: '2026-08-03T01:00:00.000Z',
    lastError: 'Request timed out after 18s: /founder-evidence',
    nowMs: new Date('2026-08-03T01:05:00.000Z').getTime(),
  });
  assert.strictEqual(result.headline, 'Cached Data');
  assert.strictEqual(result.captured, '2026-08-03T01:00:00.000Z');
  assert.strictEqual(result.age, '5m ago');
  // AT-ED-013 Section 12: the raw "/founder-evidence" path is engineering detail and must
  // never reach this Founder-facing reason string.
  assert.strictEqual(result.reason, 'Live refresh failed: the backend took too long to respond.');
  assert.ok(!result.reason.includes('/founder-evidence'));
});

test('cacheBannerDetails: falls back to a generic reason when no error message was captured', () => {
  const result = cacheBannerDetails({ cachedAt: null, lastError: null, nowMs: Date.now() });
  assert.strictEqual(result.age, null);
  assert.strictEqual(result.reason, 'Live refresh failed.');
});

// --- friendlyRefreshFailureReason (AT-ED-013 Section 12) ---

test('friendlyRefreshFailureReason: no error recorded is distinguished from a real failure', () => {
  assert.strictEqual(friendlyRefreshFailureReason(null), 'Live refresh failed.');
  assert.strictEqual(friendlyRefreshFailureReason(undefined), 'Live refresh failed.');
});

test('friendlyRefreshFailureReason: a raw HTTP status/path error never leaks into the Founder-facing reason', () => {
  const result = friendlyRefreshFailureReason('Request failed: 500');
  assert.ok(!result.includes('500'));
  assert.strictEqual(result, 'Live refresh failed: AI Trader could not reach the backend.');
});

test('friendlyRefreshFailureReason: a timeout is named as slow, not as a generic failure', () => {
  const result = friendlyRefreshFailureReason('Request timed out after 18s: /founder-evidence');
  assert.strictEqual(result, 'Live refresh failed: the backend took too long to respond.');
  assert.ok(!result.includes('founder-evidence'));
});

// --- displayStateBadge ---

test('displayStateBadge: every DISPLAY_STATE value has a distinct label', () => {
  const labels = new Set(Object.values(DISPLAY_STATE).map((state) => displayStateBadge(state).label));
  assert.strictEqual(labels.size, Object.values(DISPLAY_STATE).length, 'every state must render a distinguishable label');
});

test('displayStateBadge: Live is the only "good" tone; everything else is a visible warning or failure', () => {
  assert.strictEqual(displayStateBadge(DISPLAY_STATE.LIVE).tone, 'good');
  assert.notStrictEqual(displayStateBadge(DISPLAY_STATE.CACHED).tone, 'good');
  assert.notStrictEqual(displayStateBadge(DISPLAY_STATE.BACKEND_SNAPSHOT_STALE).tone, 'good');
  assert.notStrictEqual(displayStateBadge(DISPLAY_STATE.REFRESH_FAILED).tone, 'good');
  assert.notStrictEqual(displayStateBadge(DISPLAY_STATE.NO_DATA_AVAILABLE).tone, 'good');
});

test('displayStateBadge: AT-ED-013 Section 12 visual language - Live is green, Refreshing is blue', () => {
  assert.strictEqual(displayStateBadge(DISPLAY_STATE.LIVE).emoji, TONE_EMOJI.good);
  assert.ok(displayStateBadge(DISPLAY_STATE.LIVE).label.startsWith(TONE_EMOJI.good));
  assert.strictEqual(displayStateBadge(DISPLAY_STATE.REFRESHING).emoji, TONE_EMOJI.neutral);
});

test('displayStateBadge: warn-tone states are yellow, danger-tone states are red, matching the tone exactly', () => {
  assert.strictEqual(displayStateBadge(DISPLAY_STATE.CACHED).emoji, TONE_EMOJI.warn);
  assert.strictEqual(displayStateBadge(DISPLAY_STATE.BACKEND_SNAPSHOT_STALE).emoji, TONE_EMOJI.warn);
  assert.strictEqual(displayStateBadge(DISPLAY_STATE.REFRESH_FAILED).emoji, TONE_EMOJI.danger);
  assert.strictEqual(displayStateBadge(DISPLAY_STATE.NO_DATA_AVAILABLE).emoji, TONE_EMOJI.danger);
});

// --- connectionMessage ---

test('connectionMessage: not refreshing is silent (no in-progress message when nothing is happening)', () => {
  assert.strictEqual(connectionMessage({ isRefreshing: false, isRetrying: false, hasAttempted: true }), null);
  assert.strictEqual(connectionMessage({ isRefreshing: false, isRetrying: true, hasAttempted: false }), null);
});

test('connectionMessage: first-ever attempt this session, primary in flight', () => {
  assert.strictEqual(
    connectionMessage({ isRefreshing: true, isRetrying: false, hasAttempted: false }),
    'Connecting to AI Trader...'
  );
});

test('connectionMessage: first-ever attempt this session, on the bounded retry', () => {
  assert.strictEqual(
    connectionMessage({ isRefreshing: true, isRetrying: true, hasAttempted: false }),
    'Waking backend service...'
  );
});

test('connectionMessage: a later refresh (data already loaded once), primary in flight', () => {
  assert.strictEqual(
    connectionMessage({ isRefreshing: true, isRetrying: false, hasAttempted: true }),
    'Refreshing...'
  );
});

test('connectionMessage: a later refresh, on the bounded retry', () => {
  assert.strictEqual(
    connectionMessage({ isRefreshing: true, isRetrying: true, hasAttempted: true }),
    'Backend slow to respond - retrying...'
  );
});

console.log(`\n${passed} passed`);
if (process.exitCode) {
  console.error('Some refreshState tests failed.');
}
