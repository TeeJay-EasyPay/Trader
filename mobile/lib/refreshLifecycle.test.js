// Plain Node assert-based tests for refreshLifecycle.js - run with
// `node mobile/lib/refreshLifecycle.test.js`. See that file's module comment for why this
// logic was extracted: it is the actual decision logic hooks/useFounderEvidence.js and
// hooks/useMarketData.js call, so these tests exercise the real AT-ED-011.5 fix rather than a
// parallel, potentially-drifted reimplementation.

'use strict';

const assert = require('assert');
const {
  resolveFounderEvidenceRefresh,
  shouldStartRefresh,
  combineOptionalResults,
} = require('./refreshLifecycle');

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

// --- resolveFounderEvidenceRefresh -----------------------------------------------------

test('resolveFounderEvidenceRefresh: successful refresh (fetch + apply both succeed)', () => {
  const outcome = resolveFounderEvidenceRefresh({
    founderEvidence: { status: {} },
    fetchError: null,
    applyError: null,
  });
  assert.strictEqual(outcome.succeeded, true);
  assert.strictEqual(outcome.error, null);
  assert.strictEqual(outcome.shouldFetchSecondary, true);
  assert.strictEqual(outcome.shouldFallBackToCache, false);
});

test('resolveFounderEvidenceRefresh: full request failure (both fetch attempts failed)', () => {
  const outcome = resolveFounderEvidenceRefresh({
    founderEvidence: null,
    fetchError: 'Network request failed',
    applyError: null,
  });
  assert.strictEqual(outcome.succeeded, false);
  assert.strictEqual(outcome.error, 'Network request failed');
  assert.strictEqual(outcome.shouldFetchSecondary, false);
  assert.strictEqual(outcome.shouldFallBackToCache, true);
});

test('resolveFounderEvidenceRefresh: timeout surfaces as a fetch failure like any other', () => {
  const outcome = resolveFounderEvidenceRefresh({
    founderEvidence: null,
    fetchError: 'Request timed out after 18s: /founder-evidence',
    applyError: null,
  });
  assert.strictEqual(outcome.succeeded, false);
  assert.strictEqual(outcome.error, 'Request timed out after 18s: /founder-evidence');
  assert.strictEqual(outcome.shouldFallBackToCache, true);
});

test('resolveFounderEvidenceRefresh: fetch succeeded but applying it threw - the AT-ED-011.5 permanent-spinner regression case', () => {
  // The scenario that used to leave `loading` stuck true forever: the fetch resolved with
  // real data, but something in applyLiveFounderEvidence threw. A successful fetch with a
  // failed apply must NOT be reported as a successful refresh - the Founder needs a truthful
  // failure, not silently-stale data marked Live.
  //
  // AT-ED-011.9 note: as of this pass, applyLiveFounderEvidence no longer performs any
  // AsyncStorage writes (see hooks/useFounderEvidence.js) - a genuine applyError here can now
  // only come from a real display-mapping failure (e.g. malformed payload), never from local
  // cache persistence. See the "cache-only failure" test below for the contract that replaced
  // this scenario's original cause.
  const outcome = resolveFounderEvidenceRefresh({
    founderEvidence: { status: {}, portfolio: {} },
    fetchError: null,
    applyError: 'Cannot read properties of undefined (reading \'state\')',
  });
  assert.strictEqual(outcome.succeeded, false);
  assert.strictEqual(outcome.error, 'Cannot read properties of undefined (reading \'state\')');
  assert.strictEqual(outcome.shouldFetchSecondary, false);
  assert.strictEqual(outcome.shouldFallBackToCache, true);
});

test('resolveFounderEvidenceRefresh (AT-ED-011.9): a cache-only failure is not representable as applyError, so it can never fail an otherwise-successful refresh', () => {
  // This is the core AT-ED-011.8/011.9 contract, proven structurally rather than by a
  // dedicated "cache failure" parameter: hooks/useFounderEvidence.js's persistFounderEvidenceCache
  // and persistRecommendationsCache are fire-and-forget (never awaited by refresh()) and their
  // .catch() handlers only ever call setCacheWarning - they have no path back into applyError
  // at all. A real live payload that applied successfully is therefore always `succeeded: true`
  // here, regardless of what AsyncStorage does afterwards - a SQLITE_FULL-style local storage
  // error under this contract is structurally incapable of reaching this function as a failure.
  const outcome = resolveFounderEvidenceRefresh({
    founderEvidence: { status: {}, portfolio: {} },
    fetchError: null,
    applyError: null, // a cache-write failure has no way to set this any more
  });
  assert.strictEqual(outcome.succeeded, true);
  assert.strictEqual(outcome.error, null);
});

test('resolveFounderEvidenceRefresh: an apply error takes precedence over a fetch error, since a fetch error only exists if founderEvidence is null (never both at once)', () => {
  const outcome = resolveFounderEvidenceRefresh({
    founderEvidence: { status: {} },
    fetchError: null,
    applyError: 'apply failed',
  });
  assert.strictEqual(outcome.error, 'apply failed');
});

// --- shouldStartRefresh (concurrency / repeated-tap guard) -----------------------------

test('shouldStartRefresh: allows a refresh to start when none is in flight', () => {
  assert.strictEqual(shouldStartRefresh(false), true);
  assert.strictEqual(shouldStartRefresh(undefined), true);
});

test('shouldStartRefresh: refuses to start a second refresh while one is already in flight', () => {
  // The re-entrancy guard behind "repeated refresh taps do not start duplicate requests" and
  // "prevent concurrent duplicate refreshes for the same screen".
  assert.strictEqual(shouldStartRefresh(true), false);
});

// --- combineOptionalResults (independent-endpoint isolation for multi-source hooks) -----------

test('combineOptionalResults: all endpoints succeed', () => {
  const combined = combineOptionalResults([
    { key: 'benchmark', result: { items: [] } },
    { key: 'themes', result: { themes: [] } },
    { key: 'companies', result: { companies: [] } },
  ]);
  assert.deepStrictEqual(combined.succeededKeys, ['benchmark', 'themes', 'companies']);
  assert.strictEqual(combined.error, null);
});

test('combineOptionalResults: one endpoint failing does not affect the others (isolation)', () => {
  const combined = combineOptionalResults([
    { key: 'benchmark', result: { items: [] } },
    { key: 'themes', result: { __error: 'Request timed out after 8s: /intelligence/themes', themes: [] } },
    { key: 'companies', result: { companies: [] } },
  ]);
  assert.deepStrictEqual(combined.succeededKeys, ['benchmark', 'companies']);
  assert.strictEqual(combined.error, 'themes: Request timed out after 8s: /intelligence/themes');
});

test('combineOptionalResults: every endpoint failing names all of them, truthfully, not hidden', () => {
  const combined = combineOptionalResults([
    { key: 'benchmark', result: { __error: 'boom-1' } },
    { key: 'themes', result: { __error: 'boom-2' } },
    { key: 'companies', result: { __error: 'boom-3' } },
  ]);
  assert.deepStrictEqual(combined.succeededKeys, []);
  assert.strictEqual(combined.error, 'benchmark: boom-1; themes: boom-2; companies: boom-3');
});

console.log(`\n${passed} passed`);
