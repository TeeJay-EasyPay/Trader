// Market screen's own data: benchmark traders, theme definitions, and monitored companies.
// AT-ED-011.5 (Mobile Refresh Reliability and Data-Truth Alignment): split out of
// useFounderEvidence.js because these three endpoints are genuinely Market-screen-exclusive
// (no other screen consumes them - verified by grepping every screen/component for `benchmark`,
// `themes`, `companies` before this split) and have no relationship to the shared
// `/founder-evidence` payload, so they can and should refresh independently of it: pulling to
// refresh on Market must not re-fetch the founder-evidence payload or show the shared header's
// "Refreshing" state, and refreshing founder-evidence (from Dashboard/Activity/Portfolio/
// Recommendations/Learning, or the 2-minute auto-refresh) must not re-fetch these.
//
// Owned by App.js (constructed once, alongside useFounderEvidence()) rather than mounted
// inside the Market screen component itself, so its data survives switching away from and
// back to the Market tab instead of being re-fetched on every visit - screen-owned in the
// sense of "no other screen reads or writes this state", not "only exists while that screen
// is mounted".

'use strict';

const React = require('react');
const { useCallback, useEffect, useRef, useState } = React;
const { SECONDARY_REFRESH_TIMEOUT_MS, apiRequest } = require('../api/client');
const { todayIso } = require('../lib/datetime');
const { combineOptionalResults, shouldStartRefresh } = require('../lib/refreshLifecycle');

function useMarketData() {
  const [benchmark, setBenchmark] = useState(null);
  const [themes, setThemes] = useState([]);
  const [companies, setCompanies] = useState([]);
  const [loading, setLoading] = useState(false);
  const [hasAttempted, setHasAttempted] = useState(false);
  const [lastRefreshError, setLastRefreshError] = useState(null);
  const [lastRefreshedAt, setLastRefreshedAt] = useState(null);

  const isMountedRef = useRef(true);
  const refreshInFlightRef = useRef(false);
  useEffect(
    () => () => {
      isMountedRef.current = false;
    },
    []
  );

  const refresh = useCallback(async () => {
    if (!shouldStartRefresh(refreshInFlightRef.current)) {
      return;
    }
    refreshInFlightRef.current = true;
    setLoading(true);
    try {
      const optional = (path, fallback) =>
        apiRequest(path, { timeoutMs: SECONDARY_REFRESH_TIMEOUT_MS }).catch((error) => ({
          __error: String(error.message || error),
          ...fallback,
        }));
      const [nextBenchmark, nextThemes, nextCompanies] = await Promise.all([
        optional(`/benchmark-daily-brief?date=${todayIso()}`, {}),
        optional('/intelligence/themes', { themes: [] }),
        optional('/intelligence/companies', { companies: [] }),
      ]);
      if (!isMountedRef.current) {
        return;
      }
      // See lib/refreshLifecycle.js's combineOptionalResults - a failed endpoint keeps
      // whatever this screen was already showing (each of the three is applied independently)
      // rather than overwriting good data with an empty error placeholder, isolating one
      // slow/failed request from clobbering the other two.
      const combined = combineOptionalResults([
        { key: 'benchmark', result: nextBenchmark },
        { key: 'themes', result: nextThemes },
        { key: 'companies', result: nextCompanies },
      ]);
      if (combined.succeededKeys.includes('benchmark')) {
        setBenchmark(nextBenchmark);
      }
      if (combined.succeededKeys.includes('themes')) {
        setThemes(nextThemes.themes || []);
      }
      if (combined.succeededKeys.includes('companies')) {
        setCompanies(nextCompanies.companies || []);
      }
      setHasAttempted(true);
      // Partial failure is truthful, not hidden: any endpoint that failed is named, while the
      // endpoints that succeeded still update their own state above (isolating one slow/failed
      // request from blocking the others, per the AT-ED-011.5 directive).
      setLastRefreshError(combined.error);
      setLastRefreshedAt(new Date().toISOString());
    } finally {
      refreshInFlightRef.current = false;
      if (isMountedRef.current) {
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return {
    benchmark,
    themes,
    companies,
    loading,
    bootstrapping: !hasAttempted,
    lastRefreshError,
    lastRefreshedAt,
    refresh,
  };
}

module.exports = { useMarketData };
