// Pure refresh-outcome decision logic, extracted out of hooks/useFounderEvidence.js and
// hooks/useMarketData.js as part of AT-ED-011.5 (Mobile Refresh Reliability and Data-Truth
// Alignment) so the actual decisions a refresh makes - did it succeed, should it fall back to
// cache, which of several independent endpoints failed - are unit-testable the same way every
// other lib/*.js module in this project is (plain Node assert, no framework, no React import).
//
// This project's test files cannot require('react-native') or
// require('@react-native-async-storage/async-storage') directly under plain `node` (those
// packages ship untransformed JSX/Flow source that only resolves through Metro/babel-preset-
// expo - see AT-ED-011's own note on this), so the hooks themselves are verified through the
// project's established babel-transform + `expo export` bundle check, not direct execution.
// Extracting the meaningful decision logic here - rather than leaving it inline in the hooks -
// is what makes it possible to actually unit-test the fix for AT-ED-011.5's permanent-spinner
// bug (see resolveFounderEvidenceRefresh's "apply succeeded" case below) instead of only
// asserting it via code review.

'use strict';

// Mirrors the exact success/failure decision refresh() makes in useFounderEvidence.js.
// `founderEvidence` is the parsed payload if the fetch (primary attempt + one bounded retry)
// succeeded, or null if both attempts failed. `applyError` is set only if the fetch succeeded
// but applyLiveFounderEvidence(founderEvidence) itself threw (e.g. an AsyncStorage write
// failure) - this is the exact case that used to leave `loading` stuck true forever, because
// nothing downstream of that throw ever ran. A fetch that succeeds but cannot be applied is
// NOT a successful refresh: the Founder must see a truthful failure, not silently-kept-stale
// data reported as fresh.
function resolveFounderEvidenceRefresh({ founderEvidence, fetchError, applyError }) {
  const succeeded = founderEvidence !== null && founderEvidence !== undefined && !applyError;
  return {
    succeeded,
    error: succeeded ? null : applyError || fetchError || null,
    // Only fetch the secondary (notifications) batch and skip the cache fallback when the
    // primary payload was both fetched AND successfully applied/cached.
    shouldFetchSecondary: succeeded,
    shouldFallBackToCache: !succeeded,
  };
}

// Should a new refresh() call actually run, or does one already own the network request?
// Used by both useFounderEvidence and useMarketData's refreshInFlightRef guard - the fix for
// "repeated refresh taps" / the auto-refresh timer firing while a manual refresh is still in
// flight causing duplicate concurrent requests.
function shouldStartRefresh(refreshInFlight) {
  return refreshInFlight !== true;
}

// Combines the results of several independently-fetched, non-critical endpoints (Market's
// benchmark/themes/companies; could extend to others later) where one slow/failed request
// must not prevent the others from updating their own state. Each entry's `result` is either
// the parsed payload or an object with `__error` set (matching the `optional()` helper's
// catch shape in useMarketData.js). Returns which keys succeeded (and should overwrite state)
// and a combined, human-readable error string naming every endpoint that failed - truthful,
// not hidden, per the AT-ED-011.5 directive's explicit requirement.
function combineOptionalResults(entries) {
  const succeededKeys = [];
  const failures = [];
  entries.forEach(({ key, result }) => {
    if (result && result.__error) {
      failures.push(`${key}: ${result.__error}`);
    } else {
      succeededKeys.push(key);
    }
  });
  return {
    succeededKeys,
    error: failures.length ? failures.join('; ') : null,
  };
}

module.exports = {
  resolveFounderEvidenceRefresh,
  shouldStartRefresh,
  combineOptionalResults,
};
