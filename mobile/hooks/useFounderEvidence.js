// The founder-evidence data-fetching/cache/refresh state machine, extracted out of App.js's
// top-level state as part of AT-ED-011 Phase 2 (mobile modularisation) - see the "one place
// derives what the Founder should be told about data freshness" comment this hook now owns
// (previously a comment on App.js's header render). App.js is left with only navigation/UI
// state (screen, amounts, selectedExchange, targetRecommendationId, askMessages) and
// composition; everything about founder-evidence data lives here.

'use strict';

const React = require('react');
const { useCallback, useEffect, useMemo, useState } = React;
const AsyncStorage = require('@react-native-async-storage/async-storage').default;
const { Alert, Linking } = require('react-native');
const {
  unavailableStatus,
  unavailableActivity,
  statusFromFounderEvidence,
  activityFromFounderEvidence,
  productionTradeForMobile,
  founderLearningForMobile,
  sortByConfidence,
} = require('../lib/founderEvidenceMapping');
const {
  DISPLAY_STATE,
  classifyDisplayState,
  snapshotFreshness,
  cacheBannerDetails,
  displayStateBadge,
} = require('../lib/refreshState');
const {
  PRIMARY_REFRESH_TIMEOUT_MS,
  SECONDARY_REFRESH_TIMEOUT_MS,
  COMMAND_TIMEOUT_MS,
  API_BASE,
  absoluteApiUrl,
  apiRequest,
} = require('../api/client');
const { todayIso } = require('../lib/datetime');
const { notAvailable } = require('../lib/notAvailable');

const RECOMMENDATION_CACHE_KEY = 'ai-trader:last-recommendations';
const FOUNDER_EVIDENCE_CACHE_KEY = 'ai-trader:last-founder-evidence';
// AT-ED-010 requirement 3 ("continue normal scheduled refreshes" / "automatically recover
// to LIVE mode as soon as a successful refresh occurs"): there was previously no periodic
// refresh at all, only manual pull-to-refresh and the initial mount fetch, so a stale/cached
// state could persist indefinitely with nothing to trigger auto-recovery. This is a new
// mechanism, not a re-tuned existing value - 2 minutes is a conservative starting point,
// not a measured figure (that measurement work is a separate, parallel task; production
// /founder-evidence latency was independently sampled at a consistent 3-3.75s, so this
// interval is not expected to cause request overlap in practice).
const AUTO_REFRESH_INTERVAL_MS = 120000;

async function loadCachedRecommendations() {
  try {
    const raw = await AsyncStorage.getItem(RECOMMENDATION_CACHE_KEY);
    if (!raw) {
      return [];
    }
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? sortByConfidence(parsed) : [];
  } catch (error) {
    return [];
  }
}

// AT-ED-010: the cache now stores { data, fetchedAt } so the app can show the Founder how
// old the *phone's own copy* is (distinct from the backend's snapshot age - see
// lib/refreshState.js's module comment). Older installs may still have a bare founder-
// evidence payload written by a previous app version under this same key; that's handled
// as fetchedAt: null (age unknown) rather than discarding the cache outright.
async function loadCachedFounderEvidence() {
  try {
    const raw = await AsyncStorage.getItem(FOUNDER_EVIDENCE_CACHE_KEY);
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') {
      return null;
    }
    if (parsed.data && typeof parsed.data === 'object') {
      return { data: parsed.data, fetchedAt: parsed.fetchedAt || null };
    }
    // Pre-AT-ED-010 cache format: the raw founder-evidence payload itself.
    return { data: parsed, fetchedAt: null };
  } catch (error) {
    return null;
  }
}

function commandMessage(path, result) {
  if (path === '/run-analysis') {
    const proposalCount = result.proposals?.length || 0;
    const symbolCount = result.symbols?.length || 0;
    const skippedCount = result.skipped_symbols?.length || 0;
    const skippedText = skippedCount ? ` ${skippedCount} symbol(s) were skipped because the broker/data provider rejected them.` : '';
    if (proposalCount === 0) {
      return `Analysis completed across ${symbolCount} companies. No safe trade recommendations were generated.${skippedText}`;
    }
    return `Analysis completed across ${symbolCount} companies. ${proposalCount} recommendation(s) generated.${skippedText}`;
  }
  if (path === '/run-crypto-analysis') {
    const proposalCount = result.proposals?.length || 0;
    const symbolCount = result.symbols?.length || 0;
    const autoMessage = result.auto_execution?.message ? `\n\nAuto execution: ${result.auto_execution.message}` : '';
    if (proposalCount === 0) {
      return `Kraken analysis completed across ${symbolCount} approved crypto asset(s). No trade recommendations were generated.${autoMessage}`;
    }
    return `Kraken analysis completed across ${symbolCount} approved crypto asset(s). ${proposalCount} recommendation(s) generated.${autoMessage}`;
  }
  if (path === '/auto-execute-recommendations') {
    const eligibleCount = result.eligible_count || 0;
    if (eligibleCount > 0) {
      return `Submitted ${eligibleCount} paper trade(s).`;
    }
    const skipped = result.skipped || [];
    if (skipped.length) {
      return [
        result.message || 'No recommendations were eligible.',
        ...skipped.slice(0, 5).map((item) => `${notAvailable(item.symbol)}: ${item.message || item.reason}`),
      ].join('\n');
    }
    return result.message || 'No recommendations were eligible.';
  }
  if (path === '/approve-and-execute') {
    const decision = result.result?.decision || result.status;
    const reason = result.result?.rejection_reason || result.message || result.result?.notes;
    if (decision === 'approved' || result.status === 'submitted') {
      return result.message || 'Trade submitted.';
    }
    return reason ? `${decision}\n${reason}` : decision || 'Manual approval finished.';
  }
  if (path === '/broker-auto-trading') {
    const sync = result.render_sync;
    const syncMessage = sync?.message ? `\n\nRender sync: ${sync.message}` : '';
    return `${notAvailable(result.broker)} auto trading ${result.auto_trading_enabled ? 'enabled' : 'disabled'}.${syncMessage}`;
  }
  if (path === '/generate-report' || path === '/trading-report') {
    return `${notAvailable(result.report_type)} report generated for ${notAvailable(result.broker)} on ${notAvailable(result.date)}.\n\n${notAvailable(result.summary)}`;
  }
  return result.message || result.status || 'Done';
}

function useFounderEvidence() {
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState(null);
  const [portfolio, setPortfolio] = useState(null);
  const [brief, setBrief] = useState(null);
  const [recommendations, setRecommendations] = useState([]);
  const [benchmark, setBenchmark] = useState(null);
  const [themes, setThemes] = useState([]);
  const [companies, setCompanies] = useState([]);
  const [lastRefreshedAt, setLastRefreshedAt] = useState(null);
  // AT-ED-010 data-freshness state (mobile/lib/refreshState.js owns the derived
  // classification - these four are the raw signals it's computed from).
  const [hasAttempted, setHasAttempted] = useState(false);
  const [lastRefreshSucceeded, setLastRefreshSucceeded] = useState(null);
  const [lastRefreshError, setLastRefreshError] = useState(null);
  const [cachedAt, setCachedAt] = useState(null);
  const [snapshotMeta, setSnapshotMeta] = useState(null);
  const [notifications, setNotifications] = useState([]);
  const [performanceAttribution, setPerformanceAttribution] = useState([]);
  const [dailyLearning, setDailyLearning] = useState(null);
  const [latestReport, setLatestReport] = useState(null);
  const [activity, setActivity] = useState(null);
  const [activityPeriod, setActivityPeriod] = useState('24h');

  // AT-ED-010 requirement 3: fetch /founder-evidence once, with one bounded retry on
  // failure, before the caller decides whether to fall back to cache. No silent partial
  // states - the caller always learns definitively whether this attempt succeeded.
  const fetchFounderEvidenceOnce = useCallback(
    () => apiRequest(`/founder-evidence?period=${activityPeriod}&trade_limit=100`, { timeoutMs: PRIMARY_REFRESH_TIMEOUT_MS }),
    [activityPeriod]
  );

  const applyLiveFounderEvidence = useCallback(async (founderEvidence) => {
    const nextStatus = statusFromFounderEvidence(founderEvidence);
    const nextPortfolio = founderEvidence.portfolio || {
      portfolio_value: null,
      cash_available: null,
      deployed_capital: null,
      todays_pnl: null,
      open_positions: [],
    };
    const nextRecommendationItems = sortByConfidence(founderEvidence.recommendations || []);
    setStatus(nextStatus);
    setPortfolio(nextPortfolio);
    setActivity(activityFromFounderEvidence(founderEvidence));
    setPerformanceAttribution((founderEvidence.trades || []).map(productionTradeForMobile));
    setDailyLearning(founderLearningForMobile(founderEvidence));
    if (nextRecommendationItems.length) {
      setRecommendations(nextRecommendationItems);
      await AsyncStorage.setItem(RECOMMENDATION_CACHE_KEY, JSON.stringify(nextRecommendationItems));
    } else {
      const cached = await loadCachedRecommendations();
      setRecommendations(cached.length ? cached : []);
    }
    const fetchedAt = new Date().toISOString();
    await AsyncStorage.setItem(FOUNDER_EVIDENCE_CACHE_KEY, JSON.stringify({ data: founderEvidence, fetchedAt }));
    setSnapshotMeta(founderEvidence.snapshot || null);
    setCachedAt(fetchedAt);
    setLastRefreshedAt(fetchedAt);
  }, []);

  const applyCachedFounderEvidence = useCallback((cached) => {
    setStatus(statusFromFounderEvidence(cached.data));
    setPortfolio(cached.data.portfolio || null);
    setActivity(activityFromFounderEvidence(cached.data));
    setPerformanceAttribution((cached.data.trades || []).map(productionTradeForMobile));
    setDailyLearning(founderLearningForMobile(cached.data));
    setSnapshotMeta(cached.data.snapshot || null);
    setCachedAt(cached.fetchedAt || null);
  }, []);

  const refresh = useCallback(async () => {
    setLoading(true);
    let founderEvidence = null;
    let errorMessage = null;
    try {
      founderEvidence = await fetchFounderEvidenceOnce();
    } catch (firstError) {
      // AT-ED-010 requirement 3: one bounded retry before falling back to cache - a
      // transient hiccup should recover to LIVE on its own, not immediately read as
      // "the backend is down".
      try {
        founderEvidence = await fetchFounderEvidenceOnce();
      } catch (secondError) {
        errorMessage = String(secondError.message || secondError);
      }
    }

    setHasAttempted(true);
    setLastRefreshSucceeded(founderEvidence !== null);
    setLastRefreshError(founderEvidence !== null ? null : errorMessage);

    if (founderEvidence !== null) {
      await applyLiveFounderEvidence(founderEvidence);
      setLoading(false);

      const optional = (path, fallback, timeoutMs = SECONDARY_REFRESH_TIMEOUT_MS) =>
        apiRequest(path, { timeoutMs }).catch(() => fallback);
      Promise.all([
        optional('/founder-brief', { report_markdown: 'Not available - founder brief endpoint did not respond.' }),
        optional(`/benchmark-daily-brief?date=${todayIso()}`, null),
        optional('/intelligence/themes', { themes: [] }),
        optional('/intelligence/companies', { companies: [] }),
        optional('/notifications', { notifications: [] }),
      ]).then(([nextBrief, nextBenchmark, nextThemes, nextCompanies, nextNotifications]) => {
        setBrief(nextBrief);
        setBenchmark(nextBenchmark);
        setThemes(nextThemes.themes || []);
        setCompanies(nextCompanies.companies || []);
        setNotifications(nextNotifications.notifications || []);
      });
      return;
    }

    // Both the primary attempt and the one bounded retry failed. AT-ED-010 requirement 3:
    // never silently keep showing whatever was on screen without recording the failure -
    // fall back to cache if one exists, clearly marked (see the DISPLAY_STATE derivation
    // in the render below), and otherwise show an explicit unavailable state.
    const cached = await loadCachedFounderEvidence();
    if (cached && cached.data) {
      applyCachedFounderEvidence(cached);
    } else {
      setActivity(unavailableActivity(`Production evidence could not be loaded: ${errorMessage}`));
      setStatus(unavailableStatus(String(errorMessage)));
      setSnapshotMeta(null);
      setCachedAt(null);
    }
    setLoading(false);
  }, [fetchFounderEvidenceOnce, applyLiveFounderEvidence, applyCachedFounderEvidence]);

  useEffect(() => {
    loadCachedFounderEvidence().then((cached) => {
      if (cached && cached.data) {
        applyCachedFounderEvidence(cached);
      }
    });
    loadCachedRecommendations().then((cached) => {
      if (cached.length) {
        setRecommendations(cached);
      }
    });
    refresh();
  }, [refresh]);

  // AT-ED-010 requirement 3 ("continue normal scheduled refreshes" / "automatically
  // recover to LIVE mode as soon as a successful refresh occurs"): previously the only
  // triggers were the initial mount and manual/pull-to-refresh, so a Cached or Refresh
  // Failed state had no path back to Live without the Founder opening the app and pulling
  // to refresh themselves. This does not fire while a manual refresh is already in flight
  // (`loading`), and is cleared on unmount.
  useEffect(() => {
    const interval = setInterval(() => {
      if (!loading) {
        refresh();
      }
    }, AUTO_REFRESH_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [loading, refresh]);

  const command = async (path, body = {}, fallbackPath = null) => {
    setLoading(true);
    try {
      let result;
      try {
        result = await apiRequest(path, { method: 'POST', body: JSON.stringify(body), timeoutMs: COMMAND_TIMEOUT_MS });
      } catch (error) {
        if (fallbackPath && String(error.message || error) === 'not_found') {
          result = await apiRequest(fallbackPath, { method: 'POST', body: JSON.stringify(body), timeoutMs: COMMAND_TIMEOUT_MS });
        } else {
          throw error;
        }
      }
      if (path === '/generate-report') {
        setLatestReport(result);
      }
      Alert.alert('Command sent', commandMessage(path, result));
      await refresh();
    } catch (error) {
      const message = String(error.message || error);
      Alert.alert(
        'Command failed',
        message === 'not_found'
          ? `The phone app has newer buttons than the backend currently running.\n\nAPI: ${API_BASE}`
          : message === 'Network request failed'
            ? `The phone could not keep a connection to the hosted API while the command was running. Render may be waking up, redeploying, or the analysis took too long.\n\nTry Refresh first, then run the smaller broker-specific analysis again.\n\nAPI: ${API_BASE}`
          : message
      );
    } finally {
      setLoading(false);
    }
  };

  const reportCommand = async (body = {}) => {
    setLoading(true);
    try {
      const query = new URLSearchParams({
        type: body.type || 'daily',
        date: body.date || todayIso(),
        broker: body.broker || 'all',
      }).toString();
      const result = await apiRequest(`/trading-report?${query}`);
      setLatestReport(result);
      if (result.report_url) {
        await Linking.openURL(absoluteApiUrl(result.report_url));
      }
      Alert.alert('Report ready', commandMessage('/trading-report', result));
      await refresh();
    } catch (error) {
      Alert.alert('Report failed', String(error.message || error));
    } finally {
      setLoading(false);
    }
  };

  // AT-ED-010: one place derives what the Founder should be told about data freshness, so
  // every screen (via the header, which is always visible) shows the identical state - see
  // mobile/lib/refreshState.js for why Live/Refreshing/Cached/Backend-Snapshot-Stale/
  // Refresh-Failed/No-Data-Available must never be merged into one ambiguous indicator.
  const snapshotInfo = useMemo(() => snapshotFreshness(snapshotMeta), [snapshotMeta]);
  const dataSourceState = useMemo(
    () =>
      classifyDisplayState({
        isRefreshing: loading,
        hasAttempted,
        lastRefreshSucceeded,
        hasCachedData: Boolean(cachedAt),
        backendSnapshotStale: snapshotInfo.stale,
      }),
    [loading, hasAttempted, lastRefreshSucceeded, cachedAt, snapshotInfo.stale]
  );
  const dataSourceBadge = useMemo(() => displayStateBadge(dataSourceState), [dataSourceState]);
  const cacheBanner = useMemo(
    () =>
      dataSourceState === DISPLAY_STATE.CACHED
        ? cacheBannerDetails({ cachedAt, lastError: lastRefreshError })
        : null,
    [dataSourceState, cachedAt, lastRefreshError]
  );

  return {
    status,
    portfolio,
    brief,
    recommendations,
    benchmark,
    themes,
    companies,
    notifications,
    performanceAttribution,
    dailyLearning,
    latestReport,
    activity,
    activityPeriod,
    setActivityPeriod,
    loading,
    lastRefreshedAt,
    lastRefreshError,
    snapshotInfo,
    dataSourceState,
    dataSourceBadge,
    cacheBanner,
    refresh,
    command,
    reportCommand,
  };
}

module.exports = { useFounderEvidence };
