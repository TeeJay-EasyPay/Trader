// The founder-evidence data-fetching/cache/refresh state machine, extracted out of App.js's
// top-level state as part of AT-ED-011 Phase 2 (mobile modularisation) - see the "one place
// derives what the Founder should be told about data freshness" comment this hook now owns
// (previously a comment on App.js's header render). App.js is left with only navigation/UI
// state (screen, amounts, selectedExchange, targetRecommendationId, askMessages) and
// composition; everything about founder-evidence data lives here.
//
// AT-ED-011.5: this hook owns the ONE `/founder-evidence` payload that Dashboard, Activity,
// Portfolio, Recommendations, and Learning all genuinely share (status/portfolio/activity/
// recommendation summaries/performanceAttribution/dailyLearning are fields of that response).
// Full recommendation dossiers are screen-owned by useRecommendationDossiers so the periodic
// shared refresh remains small.
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
  connectionMessage,
} = require('../lib/refreshState');
const { resolveFounderEvidenceRefresh, shouldStartRefresh } = require('../lib/refreshLifecycle');
const {
  FOUNDER_EVIDENCE_CACHE_VERSION,
  MAX_CACHED_RECOMMENDATION_LIST_ITEMS,
  buildFounderEvidenceCacheSnapshot,
  parseCachedFounderEvidenceEnvelope,
} = require('../lib/founderEvidenceCache');
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

// AT-ED-011.9: the cache now stores a small, versioned, deliberately trimmed projection (see
// lib/founderEvidenceCache.js) instead of the full /founder-evidence payload - AT-ED-011.8
// traced a production "database or disk is full (SQLite code 13 SQLITE_FULL)" Founder-visible
// error to AsyncStorage's Android backing store choking on that full multi-megabyte write.
// Any cache written before this fix (no `v` field, full raw payload under `data`) - or any
// unrecognised future version - is treated as incompatible and discarded rather than guessed
// at: the old shape doesn't match what statusFromFounderEvidence's callers now expect to be
// small, and re-using it would silently reintroduce the exact failure mode this fixes.
async function loadCachedFounderEvidence() {
  try {
    const raw = await AsyncStorage.getItem(FOUNDER_EVIDENCE_CACHE_KEY);
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw);
    const envelope = parseCachedFounderEvidenceEnvelope(parsed);
    if (envelope.compatible) {
      return { data: envelope.data, fetchedAt: envelope.fetchedAt };
    }
    // Safe, simple migration: discard rather than attempt to re-shape an old/incompatible
    // cache. The next successful refresh repopulates it in the new, small format; a failed
    // removal here is not fatal (the incompatible envelope is simply re-detected and
    // re-discarded next launch, never used).
    AsyncStorage.removeItem(FOUNDER_EVIDENCE_CACHE_KEY).catch(() => {});
    return null;
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
  // AT-ED-011.6: true only while the bounded retry (below) is in flight, so the UI can tell
  // the Founder a slow/cold backend is genuinely still being retried instead of showing an
  // undifferentiated spinner - see lib/refreshState.js's connectionMessage.
  const [isRetrying, setIsRetrying] = useState(false);
  const [cachedAt, setCachedAt] = useState(null);
  // AT-ED-011.9: set only when a background local-cache write fails after a successful live
  // refresh (e.g. AsyncStorage rejecting the write). Deliberately never merged into
  // lastRefreshError and never rendered as a Founder-facing banner - the live refresh already
  // succeeded and the screen already shows real data; this is diagnostic-only (see
  // Cache_Design.md). Kept in state (rather than only console.warn) so it's directly testable
  // and available to development/diagnostic tooling.
  const [cacheWarning, setCacheWarning] = useState(null);
  const [snapshotMeta, setSnapshotMeta] = useState(null);
  const [notifications, setNotifications] = useState([]);
  // Phase 7 (2026-08-20): the real market forecast, from /market-forecast. Separate from
  // founder-evidence because it has its own worker-side refresh cadence (every 6h).
  const [marketForecast, setMarketForecast] = useState([]);
  const [tradeScorecard, setTradeScorecard] = useState(null);
  const [declineReasons, setDeclineReasons] = useState(null);
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
  // AT-ED-011.9: guards against overlapping AsyncStorage writes to the same key (e.g. the
  // 2-minute auto-refresh firing again while the previous refresh's background cache write is
  // still in flight) - a second write is simply skipped rather than interleaved, matching
  // shouldStartRefresh's existing coalescing pattern for refresh() itself.
  const founderEvidenceCacheWriteInFlightRef = useRef(false);
  const recommendationsCacheWriteInFlightRef = useRef(false);
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
    (timeoutMs = PRIMARY_REFRESH_TIMEOUT_MS) =>
      apiRequest(`/founder-evidence?period=${activityPeriod}&trade_limit=100`, { timeoutMs }),
    [activityPeriod]
  );

  // AT-ED-011.9: applies the live payload to every piece of display state and nothing else -
  // no AsyncStorage writes happen here. This is the "live-data application" result state the
  // directive asks be kept distinct from "local cache persistence": a payload that parses and
  // applies successfully is a successful refresh regardless of whether the (separate,
  // background) cache write that follows it succeeds. See persistFounderEvidenceCache /
  // persistRecommendationsCache below for the write path, and refresh()'s call site for how
  // the two are sequenced without one blocking or being able to fail the other.
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
    // 2026-08-17 hosted finding: `founderEvidence.trades` is bounded by the Founder-evidence
    // `period` window (default 24h) -- correct for the "N event(s) visible in this period"
    // operational sentence it also feeds, but a real ~$639 CSL profit stayed invisible on
    // Current Position/Forecast Centre because the exit itself was 6 days old and could
    // never appear in a rolling 24h window. closed_trade_history is the same terminal-trade
    // data with no period bound (see production_evidence.py's _load_closed_trade_history).
    setPerformanceAttribution((founderEvidence.closed_trade_history || []).map(productionTradeForMobile));
    setDailyLearning(founderLearningForMobile(founderEvidence));
    if (nextRecommendationItems.length) {
      setRecommendations(nextRecommendationItems);
    } else {
      // A read, not a write - safe to keep inline and awaited; loadCachedRecommendations
      // already catches its own errors and resolves to [].
      const cached = await loadCachedRecommendations();
      if (!isMountedRef.current) {
        return;
      }
      setRecommendations(cached.length ? cached : []);
    }
    const fetchedAt = new Date().toISOString();
    setSnapshotMeta(founderEvidence.snapshot || null);
    setLastRefreshedAt(fetchedAt);
    return { nextRecommendationItems, fetchedAt };
  }, []);

  // AT-ED-011.9: local cache persistence, fully decoupled from refresh success. Deliberately
  // not awaited by refresh() (fire-and-forget with its own .then/.catch/.finally, never an
  // unhandled rejection) so a large local write can never delay the loading spinner clearing
  // or the UI reflecting the live data that already applied successfully above. Guarded
  // against overlapping writes to the same key; safe to resolve after unmount (isMountedRef
  // checked before every setState).
  const persistFounderEvidenceCache = useCallback((founderEvidence, fetchedAt) => {
    if (founderEvidenceCacheWriteInFlightRef.current) {
      return;
    }
    founderEvidenceCacheWriteInFlightRef.current = true;
    const snapshot = buildFounderEvidenceCacheSnapshot(founderEvidence);
    AsyncStorage.setItem(
      FOUNDER_EVIDENCE_CACHE_KEY,
      JSON.stringify({ v: FOUNDER_EVIDENCE_CACHE_VERSION, data: snapshot, fetchedAt })
    )
      .then(() => {
        if (isMountedRef.current) {
          setCachedAt(fetchedAt);
          setCacheWarning(null);
        }
      })
      .catch((error) => {
        // Never Founder-facing (no banner reads cacheWarning) and never merged into
        // lastRefreshError - the live refresh already succeeded. Kept for diagnostics only;
        // see Cache_Design.md for why the raw message is safe to keep internally (it never
        // reaches any rendered text).
        if (isMountedRef.current) {
          setCacheWarning(String(error.message || error));
        }
      })
      .finally(() => {
        founderEvidenceCacheWriteInFlightRef.current = false;
      });
  }, []);

  const persistRecommendationsCache = useCallback((recommendationItems) => {
    if (recommendationsCacheWriteInFlightRef.current) {
      return;
    }
    recommendationsCacheWriteInFlightRef.current = true;
    AsyncStorage.setItem(
      RECOMMENDATION_CACHE_KEY,
      JSON.stringify(recommendationItems.slice(0, MAX_CACHED_RECOMMENDATION_LIST_ITEMS))
    )
      .catch(() => {
        // Same reasoning as persistFounderEvidenceCache: never Founder-facing, never affects
        // refresh success. Shared recommendation summaries remain live in memory this session;
        // only their lightweight offline fallback would be affected.
      })
      .finally(() => {
        recommendationsCacheWriteInFlightRef.current = false;
      });
  }, []);

  const applyCachedFounderEvidence = useCallback((cached) => {
    setStatus(statusFromFounderEvidence(cached.data));
    setPortfolio(cached.data.portfolio || null);
    setActivity(activityFromFounderEvidence(cached.data));
    setPerformanceAttribution((cached.data.closed_trade_history || []).map(productionTradeForMobile));
    setDailyLearning(founderLearningForMobile(cached.data));
    setSnapshotMeta(cached.data.snapshot || null);
    setCachedAt(cached.fetchedAt || null);
  }, []);

  // AT-ED-011.5 root-cause fix for the permanent "Refreshing" spinner: the previous version
  // called setLoading(false) from two separate points inside the function body instead of one
  // guaranteed path, so anything thrown between them left it stuck true forever. Wrapping the
  // whole body in try/finally guarantees setLoading(false) always runs, on every path.
  //
  // AT-ED-011.9: applyLiveFounderEvidence no longer performs any AsyncStorage writes (see its
  // own comment) - a large local cache write can therefore never again be the thing that
  // throws here and gets reported as a failed refresh. applyError below is now genuinely only
  // "the live payload was fetched but could not be applied" (e.g. a mapping crash on
  // malformed data), matching the directive's requirement that an optional persistence
  // failure must never invalidate a successful network refresh.
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
        //
        // AT-ED-011.6: the retry uses SECONDARY_REFRESH_TIMEOUT_MS (8s), not another full
        // primary timeout. Measured evidence: a Render free-tier cold start is what the
        // primary attempt's timeout budget exists to absorb - by the time this retry runs,
        // that same cold start has already had the whole primary-timeout duration to finish
        // booting in the background, so the container should now be warm (measured warm
        // response: 2.9-3.8s). Reusing the full primary timeout here would only extend how
        // long the Founder waits before learning about a genuinely broken backend, with no
        // evidence it ever helps a cold start specifically.
        if (isMountedRef.current) {
          setIsRetrying(true);
        }
        try {
          founderEvidence = await fetchFounderEvidenceOnce(SECONDARY_REFRESH_TIMEOUT_MS);
        } catch (secondError) {
          fetchError = String(secondError.message || secondError);
        } finally {
          if (isMountedRef.current) {
            setIsRetrying(false);
          }
        }
      }

      if (!isMountedRef.current) {
        return;
      }

      let appliedRecommendations = null;
      let appliedFetchedAt = null;
      if (founderEvidence !== null) {
        try {
          const applied = await applyLiveFounderEvidence(founderEvidence);
          appliedRecommendations = applied?.nextRecommendationItems || null;
          appliedFetchedAt = applied?.fetchedAt || null;
        } catch (error) {
          // A genuine failure to apply the live payload (e.g. a mapping crash on malformed
          // data) - this is a real, truthful failure and must not be swallowed just to let
          // the spinner stop. Local cache persistence is a separate, later step (below) and
          // cannot reach this catch block at all any more - see applyLiveFounderEvidence's
          // comment.
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
        // AT-ED-011.9: local cache persistence happens here - after success is already
        // determined and the UI already reflects the live data - and is never awaited, so it
        // cannot delay this function returning or setLoading(false) in the finally block
        // below. Skipped only if founderEvidence/appliedFetchedAt are unexpectedly absent
        // (outcome.succeeded already guarantees founderEvidence !== null in practice).
        if (founderEvidence !== null && appliedFetchedAt) {
          persistFounderEvidenceCache(founderEvidence, appliedFetchedAt);
        }
        if (appliedRecommendations && appliedRecommendations.length) {
          persistRecommendationsCache(appliedRecommendations);
        }
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
        // Phase 7 of the CIO-level forecasting build (2026-08-20): the real market
        // forecast has its own endpoint and its own worker-side refresh cadence (every
        // 6h), so it is fetched alongside /notifications rather than bloating the
        // founder-evidence snapshot. Same fire-and-forget shape: its own .catch resolves
        // to an empty result, so a forecast outage can never fail or delay the main
        // refresh -- marketForecastCards then renders the honest "no forecast yet" state.
        apiRequest('/market-forecast', { timeoutMs: SECONDARY_REFRESH_TIMEOUT_MS })
          .catch(() => ({ forecasts: [] }))
          .then((nextForecasts) => {
            if (isMountedRef.current) {
              setMarketForecast(nextForecasts.forecasts || []);
            }
          });
        // Founder-requested 2026-08-20: the trade scorecard (day/week/month wins and
        // losses plus a short lessons line). Same fire-and-forget shape for the same
        // reason -- a reporting query must never be able to fail or delay the refresh
        // that the rest of the briefing depends on. null means "not loaded yet", which
        // the card renders as its own honest empty state rather than as zero trades.
        apiRequest('/trade-scorecard', { timeoutMs: SECONDARY_REFRESH_TIMEOUT_MS })
          .catch(() => null)
          .then((nextScorecard) => {
            if (isMountedRef.current && nextScorecard) {
              setTradeScorecard(nextScorecard);
            }
          });
        // Founder-requested 2026-08-20: why the AI turned trades down, in short plain
        // English. Same fire-and-forget shape -- an explanation query must never be able
        // to fail or delay the refresh the rest of the briefing depends on.
        apiRequest('/decline-reasons', { timeoutMs: SECONDARY_REFRESH_TIMEOUT_MS })
          .catch(() => null)
          .then((nextDeclines) => {
            if (isMountedRef.current && nextDeclines) {
              setDeclineReasons(nextDeclines);
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
  }, [
    fetchFounderEvidenceOnce,
    applyLiveFounderEvidence,
    applyCachedFounderEvidence,
    persistFounderEvidenceCache,
    persistRecommendationsCache,
  ]);

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
  const inProgressMessage = useMemo(
    () => connectionMessage({ isRefreshing: loading, isRetrying, hasAttempted }),
    [loading, isRetrying, hasAttempted]
  );
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
    marketForecast,
    tradeScorecard,
    declineReasons,
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
    // AT-ED-011.9: diagnostic-only - never rendered as a Founder-facing banner (a cache-write
    // failure after a successful live refresh must stay invisible to the Founder; see
    // Cache_Design.md). Exposed for development/diagnostic tooling and direct testing.
    cacheWarning,
    snapshotInfo,
    dataSourceState,
    dataSourceBadge,
    cacheBanner,
    isRetrying,
    inProgressMessage,
    refresh,
    command,
    reportCommand,
  };
}

module.exports = { useFounderEvidence };
