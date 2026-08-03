// The founder-evidence data-fetching/cache/refresh state machine, extracted out of App.js's
// top-level state as part of AT-ED-011 Phase 2 (mobile modularisation) - see the "one place
// derives what the Founder should be told about data freshness" comment this hook now owns
// (previously a comment on App.js's header render). App.js is left with only navigation/UI
// state (screen, amounts, selectedExchange, targetRecommendationId, askMessages) and
// composition; everything about founder-evidence data lives here.
//
// AT-ED-011.5: this hook owns the ONE `/founder-evidence` payload that Dashboard, Activity,
// Portfolio, Recommendations, and Learning all genuinely share (status/portfolio/activity/
// recommendations/performanceAttribution/dailyLearning are all fields of that single response)
// - per the directive's own rule that shared data should use a shared hook only where multiple
// screens genuinely consume the same authoritative payload. Data that has its OWN endpoint and
// is only consumed by ONE screen (Market's themes/companies/benchmark, Dashboard's founder
// brief) has been split into mobile/hooks/useMarketData.js and mobile/hooks/useFounderBrief.js
// so those screens can refresh independently of this shared core and of each other.

'use strict';

const React = require('react');
const { useCallback, useEffect, useMemo, useRef, useState } = React;
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
const { resolveFounderEvidenceRefresh, shouldStartRefresh } = require('../lib/refreshLifecycle');
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
  // "loading" keeps its pre-existing meaning: true while ANY refresh (initial, auto, manual
  // pull, or post-command) of the shared founder-evidence payload is in flight. AT-ED-011.5
  // adds `hasAttempted` to the public return value so callers can distinguish "no refresh has
  // ever completed yet" (bootstrap - worth a full-screen indicator) from "a later refresh is
  // in flight" (should only show a small screen-level indicator, per the AT-ED-011.5
  // directive's requirement that the top-level global spinner is reserved for initial
  // bootstrap only).
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState(null);
  const [portfolio, setPortfolio] = useState(null);
  const [recommendations, setRecommendations] = useState([]);
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

  // AT-ED-011.5 requirement ("Prevent concurrent duplicate refreshes for the same screen" /
  // "any stale closure or unmounted-component issue"): isMountedRef guards every setState
  // that runs after an await against firing post-unmount; refreshInFlightRef coalesces
  // overlapping refresh() calls (repeated pull-to-refresh taps, the auto-refresh timer firing
  // while a manual refresh is still running, a command's post-action refresh racing the timer)
  // into the single already-running attempt instead of issuing duplicate network requests.
  const isMountedRef = useRef(true);
  const refreshInFlightRef = useRef(false);
  useEffect(
    () => () => {
      isMountedRef.current = false;
    },
    []
  );

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
    if (!isMountedRef.current) {
      return;
    }
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
      if (!isMountedRef.current) {
        return;
      }
      setRecommendations(cached.length ? cached : []);
    }
    const fetchedAt = new Date().toISOString();
    await AsyncStorage.setItem(FOUNDER_EVIDENCE_CACHE_KEY, JSON.stringify({ data: founderEvidence, fetchedAt }));
    if (!isMountedRef.current) {
      return;
    }
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

  // AT-ED-011.5 root-cause fix for the permanent "Refreshing" spinner: the previous version
  // called setLoading(false) from two separate points inside the function body instead of one
  // guaranteed path. If ANYTHING between those two calls threw - most plausibly
  // applyLiveFounderEvidence's AsyncStorage.setItem writes, which persist the full multi-
  // megabyte founder-evidence payload and can fail on storage-constrained devices - the
  // exception propagated out of refresh() with nothing to catch it (refresh() is called from
  // a useEffect and from RefreshControl's onRefresh with no .catch()), so setLoading(false)
  // never ran and the header's "Refreshing" badge/spinner stuck forever, even though the
  // screen already had data because the setState calls in applyLiveFounderEvidence run BEFORE
  // its AsyncStorage writes. Wrapping the whole body in try/finally guarantees setLoading(false)
  // always runs, on every path, whatever throws - matching this phase's explicit requirement
  // that loading state must clear via a finally block or an equivalent guaranteed path, and
  // that failures must remain visible rather than being hidden merely to stop the spinner.
  const refresh = useCallback(async () => {
    if (!shouldStartRefresh(refreshInFlightRef.current)) {
      return;
    }
    refreshInFlightRef.current = true;
    setLoading(true);
    try {
      let founderEvidence = null;
      let fetchError = null;
      let applyError = null;
      try {
        founderEvidence = await fetchFounderEvidenceOnce();
      } catch (firstError) {
        // AT-ED-010 requirement 3: one bounded retry before falling back to cache - a
        // transient hiccup should recover to LIVE on its own, not immediately read as
        // "the backend is down".
        try {
          founderEvidence = await fetchFounderEvidenceOnce();
        } catch (secondError) {
          fetchError = String(secondError.message || secondError);
        }
      }

      if (!isMountedRef.current) {
        return;
      }

      if (founderEvidence !== null) {
        try {
          await applyLiveFounderEvidence(founderEvidence);
        } catch (error) {
          // The fetch succeeded but applying/caching it failed (e.g. AsyncStorage rejected
          // the write). This is a real, truthful failure - it must not be reported as a
          // successful live refresh, and must not be swallowed just to let the spinner stop.
          applyError = String(error.message || error);
        }
      }

      if (!isMountedRef.current) {
        return;
      }

      // See lib/refreshLifecycle.js's resolveFounderEvidenceRefresh - this is the same
      // decision logic AT-ED-011.5's tests exercise directly, applied here to the real fetch.
      const outcome = resolveFounderEvidenceRefresh({ founderEvidence, fetchError, applyError });
      setHasAttempted(true);
      setLastRefreshSucceeded(outcome.succeeded);
      setLastRefreshError(outcome.error);

      if (outcome.succeeded) {
        // Fire-and-forget: /notifications is fetched here (unchanged data ownership) and
        // rendered by Activity's NotificationsCard (see Data_Freshness_Findings.md, notifications
        // decision - AT-ED-011.5). The .catch() below already resolves to a fallback on its own
        // failure, so this can never reject and does not need a second one; the mount guard
        // stops it writing state after unmount instead.
        apiRequest('/notifications', { timeoutMs: SECONDARY_REFRESH_TIMEOUT_MS })
          .catch(() => ({ notifications: [] }))
          .then((nextNotifications) => {
            if (isMountedRef.current) {
              setNotifications(nextNotifications.notifications || []);
            }
          });
        return;
      }

      // Either the fetch failed (both attempts) or the fetch succeeded but could not be
      // applied/cached. AT-ED-010 requirement 3: never silently keep showing whatever was on
      // screen without recording the failure - fall back to cache if one exists, clearly
      // marked (see the DISPLAY_STATE derivation in the render below), and otherwise show an
      // explicit unavailable state.
      const cached = await loadCachedFounderEvidence();
      if (!isMountedRef.current) {
        return;
      }
      if (cached && cached.data) {
        applyCachedFounderEvidence(cached);
      } else {
        setActivity(unavailableActivity(`Production evidence could not be loaded: ${outcome.error}`));
        setStatus(unavailableStatus(String(outcome.error)));
        setSnapshotMeta(null);
        setCachedAt(null);
      }
    } finally {
      refreshInFlightRef.current = false;
      if (isMountedRef.current) {
        setLoading(false);
      }
    }
  }, [fetchFounderEvidenceOnce, applyLiveFounderEvidence, applyCachedFounderEvidence]);

  useEffect(() => {
    loadCachedFounderEvidence().then((cached) => {
      if (isMountedRef.current && cached && cached.data) {
        applyCachedFounderEvidence(cached);
      }
    });
    loadCachedRecommendations().then((cached) => {
      if (isMountedRef.current && cached.length) {
        setRecommendations(cached);
      }
    });
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refresh]);

  // AT-ED-010 requirement 3 ("continue normal scheduled refreshes" / "automatically
  // recover to LIVE mode as soon as a successful refresh occurs"): previously the only
  // triggers were the initial mount and manual/pull-to-refresh, so a Cached or Refresh
  // Failed state had no path back to Live without the Founder opening the app and pulling
  // to refresh themselves. refresh() itself now no-ops via refreshInFlightRef if a refresh
  // is already running, so this no longer needs its own `loading` check to avoid overlap.
  useEffect(() => {
    const interval = setInterval(() => {
      refresh();
    }, AUTO_REFRESH_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [refresh]);

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
      if (!isMountedRef.current) {
        return;
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
      if (isMountedRef.current) {
        setLoading(false);
      }
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
      if (!isMountedRef.current) {
        return;
      }
      setLatestReport(result);
      if (result.report_url) {
        await Linking.openURL(absoluteApiUrl(result.report_url));
      }
      Alert.alert('Report ready', commandMessage('/trading-report', result));
      await refresh();
    } catch (error) {
      Alert.alert('Report failed', String(error.message || error));
    } finally {
      if (isMountedRef.current) {
        setLoading(false);
      }
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
    recommendations,
    notifications,
    performanceAttribution,
    dailyLearning,
    latestReport,
    activity,
    activityPeriod,
    setActivityPeriod,
    loading,
    // AT-ED-011.5: true only before the first refresh attempt of this app session has
    // completed - the signal App.js uses to decide whether the full-screen bootstrap
    // spinner should show, as distinct from `loading` (true for every refresh, which now
    // only drives small screen-level indicators after bootstrap).
    bootstrapping: !hasAttempted,
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
