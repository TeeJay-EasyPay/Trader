// Full recommendation dossiers are deliberately screen-owned and loaded on demand.
// The shared two-minute Founder refresh carries compact summaries only; fetching nested
// committee/strategy/signal evidence continuously was the dominant Supabase egress source.

'use strict';

const React = require('react');
const { useCallback, useEffect, useRef, useState } = React;
const AsyncStorage = require('@react-native-async-storage/async-storage').default;
const { PRIMARY_REFRESH_TIMEOUT_MS, apiRequest } = require('../api/client');
const { sortByConfidence } = require('../lib/founderEvidenceMapping');
const { shouldStartRefresh } = require('../lib/refreshLifecycle');
const { MAX_CACHED_RECOMMENDATION_LIST_ITEMS } = require('../lib/founderEvidenceCache');

const RECOMMENDATION_DOSSIER_CACHE_KEY = 'ai-trader:recommendation-dossiers';

function useRecommendationDossiers(enabled) {
  const [recommendations, setRecommendations] = useState([]);
  const [loading, setLoading] = useState(false);
  const [lastRefreshError, setLastRefreshError] = useState(null);
  const [lastRefreshedAt, setLastRefreshedAt] = useState(null);
  const isMountedRef = useRef(true);
  const refreshInFlightRef = useRef(false);
  const fetchedOnceRef = useRef(false);

  useEffect(
    () => () => {
      isMountedRef.current = false;
    },
    []
  );

  useEffect(() => {
    AsyncStorage.getItem(RECOMMENDATION_DOSSIER_CACHE_KEY)
      .then((raw) => {
        if (!isMountedRef.current || !raw) return;
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed)) setRecommendations(sortByConfidence(parsed));
      })
      .catch(() => {});
  }, []);

  const refresh = useCallback(async () => {
    if (!shouldStartRefresh(refreshInFlightRef.current)) return;
    refreshInFlightRef.current = true;
    setLoading(true);
    try {
      const payload = await apiRequest(
        `/recommendations?limit=${MAX_CACHED_RECOMMENDATION_LIST_ITEMS}`,
        { timeoutMs: PRIMARY_REFRESH_TIMEOUT_MS }
      );
      const next = sortByConfidence(payload.recommendations || []);
      if (!isMountedRef.current) return;
      setRecommendations(next);
      setLastRefreshError(null);
      const refreshedAt = new Date().toISOString();
      setLastRefreshedAt(refreshedAt);
      AsyncStorage.setItem(RECOMMENDATION_DOSSIER_CACHE_KEY, JSON.stringify(next)).catch(() => {});
    } catch (error) {
      if (isMountedRef.current) setLastRefreshError(String(error.message || error));
    } finally {
      refreshInFlightRef.current = false;
      if (isMountedRef.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (enabled && !fetchedOnceRef.current) {
      fetchedOnceRef.current = true;
      refresh();
    }
  }, [enabled, refresh]);

  return { recommendations, loading, lastRefreshError, lastRefreshedAt, refresh };
}

module.exports = { RECOMMENDATION_DOSSIER_CACHE_KEY, useRecommendationDossiers };
