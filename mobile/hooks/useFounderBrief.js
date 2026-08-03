// Dashboard screen's own data: the `/founder-brief` markdown report. AT-ED-011.5 split out
// of useFounderEvidence.js for the same reason as useMarketData.js - this endpoint is
// Dashboard-exclusive and unrelated to the shared `/founder-evidence` payload, so it refreshes
// independently. See Data_Freshness_Findings.md for how this was found: the report was already
// being fetched on every refresh but the resulting text was never rendered by any screen -
// wired into Dashboard.js alongside this split, not left orphaned a second time.

'use strict';

const React = require('react');
const { useCallback, useEffect, useRef, useState } = React;
const { SECONDARY_REFRESH_TIMEOUT_MS, apiRequest } = require('../api/client');
const { shouldStartRefresh } = require('../lib/refreshLifecycle');

function useFounderBrief() {
  const [brief, setBrief] = useState(null);
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
      let nextBrief = null;
      let error = null;
      try {
        nextBrief = await apiRequest('/founder-brief', { timeoutMs: SECONDARY_REFRESH_TIMEOUT_MS });
      } catch (fetchError) {
        error = String(fetchError.message || fetchError);
      }
      if (!isMountedRef.current) {
        return;
      }
      if (nextBrief !== null) {
        setBrief(nextBrief);
      }
      setHasAttempted(true);
      setLastRefreshError(error);
      if (nextBrief !== null) {
        setLastRefreshedAt(new Date().toISOString());
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
    brief,
    loading,
    bootstrapping: !hasAttempted,
    lastRefreshError,
    lastRefreshedAt,
    refresh,
  };
}

module.exports = { useFounderBrief };
