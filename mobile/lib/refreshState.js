// Pure state-machine logic for AT-ED-010 (UI Data Freshness and Evidence Alignment).
// Kept dependency-free (no React/RN imports) so it can be required directly from a plain
// Node test script without a bundler or test framework - see refreshState.test.js, and
// matching the convention founderPresentation.js already established in this file.
//
// This module answers two DIFFERENT questions that AT-ED-010 requires the app to keep
// visually and textually distinct:
//   1. classifyDisplayState - is what's on screen right now Live / Refreshing / Cached /
//      Backend-Snapshot-Stale / Refresh-Failed / No-Data-Available? This is about the
//      MOBILE APP's own fetch/cache behaviour.
//   2. snapshotFreshness - is the BACKEND's own persisted evidence snapshot (the thing
//      /founder-evidence read even on a successful, live, fast fetch) fresh or stale?
//      This is a property of the data itself, independent of whether the phone's request
//      succeeded quickly.
// A successful live fetch of a stale backend snapshot is BACKEND_SNAPSHOT_STALE, not LIVE -
// the Founder needs to know the evidence itself is old even though the phone's connection
// to the API is working fine.

'use strict';

const DISPLAY_STATE = Object.freeze({
  LIVE: 'live',
  REFRESHING: 'refreshing',
  CACHED: 'cached',
  BACKEND_SNAPSHOT_STALE: 'backend_snapshot_stale',
  REFRESH_FAILED: 'refresh_failed',
  NO_DATA_AVAILABLE: 'no_data_available',
});

// hasAttempted: has the app ever completed a refresh attempt (success or failure) this
//   session - false only for the brief window before the very first refresh() resolves.
// lastRefreshSucceeded: did the most recently COMPLETED attempt (primary fetch, or its one
//   bounded retry) succeed - null before the first attempt completes.
// hasCachedData: is there AsyncStorage-cached founder-evidence data available to fall back
//   to right now (independent of whether it's currently being displayed).
// backendSnapshotStale: founderEvidence.snapshot.stale from the most recent successful
//   fetch - only meaningful when lastRefreshSucceeded is true.
function classifyDisplayState({ isRefreshing, hasAttempted, lastRefreshSucceeded, hasCachedData, backendSnapshotStale }) {
  if (isRefreshing) {
    return DISPLAY_STATE.REFRESHING;
  }
  if (!hasAttempted) {
    return DISPLAY_STATE.NO_DATA_AVAILABLE;
  }
  if (lastRefreshSucceeded) {
    return backendSnapshotStale ? DISPLAY_STATE.BACKEND_SNAPSHOT_STALE : DISPLAY_STATE.LIVE;
  }
  return hasCachedData ? DISPLAY_STATE.CACHED : DISPLAY_STATE.REFRESH_FAILED;
}

// Normalizes the backend's snapshot metadata (production_evidence.py's
// load_founder_evidence_snapshot() attaches this under payload["snapshot"]) into a shape
// safe to render even when the field is missing entirely (e.g. _snapshot_not_ready_payload,
// returned while the worker hasn't written its first snapshot yet, has no "snapshot" key).
function snapshotFreshness(snapshot) {
  if (!snapshot || typeof snapshot !== 'object') {
    return { known: false, ageSeconds: null, stale: null, generatedAt: null };
  }
  return {
    known: true,
    ageSeconds: typeof snapshot.age_seconds === 'number' ? snapshot.age_seconds : null,
    stale: typeof snapshot.stale === 'boolean' ? snapshot.stale : null,
    generatedAt: snapshot.generated_at || null,
  };
}

function formatAgeSeconds(seconds) {
  if (typeof seconds !== 'number' || Number.isNaN(seconds) || seconds < 0) {
    return null;
  }
  if (seconds < 60) {
    return `${Math.round(seconds)}s ago`;
  }
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) {
    return `${minutes}m ago`;
  }
  const hours = Math.round(minutes / 60);
  if (hours < 48) {
    return `${hours}h ago`;
  }
  return `${Math.round(hours / 24)}d ago`;
}

// The banner content for Requirement 1's "Cached Data / Captured: / Age: / Live refresh
// failed." card. cachedAt is the ISO timestamp the currently-displayed cache was originally
// fetched LIVE (stored alongside the cached payload - see App.js's AsyncStorage envelope),
// which is a different concept from the backend snapshot's own age (snapshotFreshness above)
// - a five-minute-old phone cache of a five-minute-old backend snapshot is ten minutes of
// combined staleness, and the Founder should be able to tell the two apart.
function cacheBannerDetails({ cachedAt, lastError, nowMs = Date.now() }) {
  const ageSeconds = cachedAt ? (nowMs - new Date(cachedAt).getTime()) / 1000 : null;
  return {
    headline: 'Cached Data',
    captured: cachedAt || null,
    age: formatAgeSeconds(ageSeconds),
    reason: lastError ? `Live refresh failed: ${lastError}` : 'Live refresh failed.',
  };
}

// Short label + tone for the StatusPill shown in the app header, one call site so every
// screen renders the identical wording/colour for a given state.
function displayStateBadge(state) {
  switch (state) {
    case DISPLAY_STATE.LIVE:
      return { label: 'Live', tone: 'good' };
    case DISPLAY_STATE.REFRESHING:
      return { label: 'Refreshing', tone: 'neutral' };
    case DISPLAY_STATE.CACHED:
      return { label: 'Cached', tone: 'warn' };
    case DISPLAY_STATE.BACKEND_SNAPSHOT_STALE:
      return { label: 'Backend Snapshot Stale', tone: 'warn' };
    case DISPLAY_STATE.REFRESH_FAILED:
      return { label: 'Refresh Failed', tone: 'danger' };
    case DISPLAY_STATE.NO_DATA_AVAILABLE:
    default:
      return { label: 'No Data Available', tone: 'danger' };
  }
}

module.exports = {
  DISPLAY_STATE,
  classifyDisplayState,
  snapshotFreshness,
  formatAgeSeconds,
  cacheBannerDetails,
  displayStateBadge,
};
