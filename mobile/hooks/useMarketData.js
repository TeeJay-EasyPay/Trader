// Theme definitions, fetched independently of the shared `/founder-evidence` payload.
// AT-ED-011.5 (Mobile Refresh Reliability and Data-Truth Alignment): split out of
// useFounderEvidence.js because this endpoint is genuinely exclusive of the shared payload, so
// it can and should refresh independently of it.
//
// APP SIMPLIFICATION (2026-08-21): this hook used to also fetch `/benchmark-daily-brief` and
// `/intelligence/companies` for the now-deleted dedicated Market screen. Themes are the only
// field anything still reads (the Executive Briefing's Investment Thesis/Opportunities
// content, via lib/investmentThesis.js and lib/principalOpportunities.js) - the other two
// endpoints had no remaining reader, so fetching them was pure egress with nothing displaying
// the result. Trimmed to just themes rather than kept "just in case".
//
// Owned by App.js (constructed once, alongside useFounderEvidence()) rather than mounted
// inside a screen component, so its data survives switching tabs instead of being re-fetched
// on every visit to the Executive Briefing.

'use strict';

const React = require('react');
const { useCallback, useEffect, useRef, useState } = React;
const { SECONDARY_REFRESH_TIMEOUT_MS, apiRequest } = require('../api/client');
const { shouldStartRefresh } = require('../lib/refreshLifecycle');

function useMarketData() {
  const [themes, setThemes] = useState([]);
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
      const nextThemes = await apiRequest('/intelligence/themes', { timeoutMs: SECONDARY_REFRESH_TIMEOUT_MS });
      if (!isMountedRef.current) {
        return;
      }
      setThemes(nextThemes.themes || []);
      setHasAttempted(true);
      setLastRefreshError(null);
      setLastRefreshedAt(new Date().toISOString());
    } catch (error) {
      if (isMountedRef.current) {
        setHasAttempted(true);
        setLastRefreshError(String(error.message || error));
      }
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
    themes,
    loading,
    bootstrapping: !hasAttempted,
    lastRefreshError,
    lastRefreshedAt,
    refresh,
  };
}

module.exports = { useMarketData };
