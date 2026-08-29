import React, { useMemo, useState } from 'react';
import {
  ActivityIndicator,
  RefreshControl,
  SafeAreaView,
  ScrollView,
  StatusBar,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import { styles } from './styles';
import { StatusPill } from './components/shared';
import { ErrorBoundary } from './components/ErrorBoundary';
import { ExecutiveBriefing } from './screens/ExecutiveBriefing';
import { PortfolioCommandCentre } from './screens/Portfolio';
import { AskAiTrader } from './screens/Ask';
import { RunCycleScreen } from './screens/RunCycle';
import { useFounderEvidence } from './hooks/useFounderEvidence';
import { useMarketData } from './hooks/useMarketData';
import { useFounderBrief } from './hooks/useFounderBrief';
const {
  DISPLAY_STATE,
  displayStateBadge,
  formatAgeSeconds,
  friendlyRefreshFailureReason,
} = require('./lib/refreshState');
const { buildScreenRefreshRegistry } = require('./lib/screenRefresh');
const { formatDateTime } = require('./lib/datetime');
const { shortApiBase, apiRequest } = require('./api/client');

// AT-ED-014 Section 1 / AT-ED-015 Section 11: the Executive Briefing (formerly "CIO") is the
// primary experience - the app launches directly into it, not Operations (the renamed former
// Dashboard, now operational-health only). SCREEN_LABELS maps the internal routing key to the
// Founder-facing tab text, since 'ExecutiveBriefing' as one word would read poorly as a label.
// APP SIMPLIFICATION (Founder-agreed 2026-08-21): Recommendations and Market were both deleted
// as dedicated screens - trading is autonomous now, so "why did it trade" is answered by the
// Briefing + decline card, and Market's read-once reference lists (themes/companies/benchmark
// traders) were not worth a whole tab. Market's "Today's Learning, In Brief" content moved into
// Learning; its themes data still feeds the Executive Briefing's Investment Thesis/Opportunities
// content directly (see the 'market' screen-data-source now owned by ExecutiveBriefing below).
// APP SIMPLIFICATION (2026-08-24, Founder-directed): five screens -> three.
// Operations was developer tooling (Run Analysis, Emergency Stop) -- its actions moved onto
// the Briefing, the rest was diagnostics the Founder does not act on. Activity was a
// notification list scrolled past. Learning's numbers duplicated the Trade Scorecard, so its
// one unique line (the latest lesson) moved there and Ask became its own screen.
// What is left answers the only three questions the Founder actually has: how am I doing,
// what do I hold, and let me ask something.
// 2026-08-26, Founder-directed: "I think we can now remove the Ask Trader screen." Three
// screens -> two. Ask is not gone, it moved: the same component now sits on the Executive
// Briefing directly under the summary, sharing one conversation, which is where the questions
// get asked anyway ("that way I don't need to go to a separate screen"). A tab whose only
// content already appears on the screen before it is a navigation step that buys nothing.
// 2026-08-29, Founder-directed: a third screen, deliberately, after two rounds of
// simplification cut the app from seven screens to two. It earns its tab because it answers a
// question the other two cannot -- "run the whole thing now and show me every step" -- and
// because it is how updates get tested on the emulator without waiting for the worker's
// hourly schedule. It is a run log, not a dashboard, so it does not belong on the Briefing.
const SCREENS = ['ExecutiveBriefing', 'Portfolio', 'RunCycle'];
const SCREEN_LABELS = { ExecutiveBriefing: 'Executive Briefing', RunCycle: 'Run a Cycle' };

export default function App() {
  const [screen, setScreen] = useState('ExecutiveBriefing');
  const [selectedExchange, setSelectedExchange] = useState('All');
  const [askMessages, setAskMessages] = useState([
    {
      role: 'assistant',
      text: 'Ask me about balances, open positions, trades, reports, recommendations, or what AI Trader learned. I am read-only and cannot place trades.',
    },
  ]);

  const {
    status,
    portfolio,
    recommendations,
    notifications,
    performanceAttribution,
    marketForecast,
    dailyLearning,
    latestReport,
    activity,
    activityPeriod,
    setActivityPeriod,
    tradeScorecard,
    declineReasons,
    loading,
    bootstrapping,
    lastRefreshedAt,
    lastRefreshError,
    snapshotInfo,
    dataSourceState,
    dataSourceBadge,
    cacheBanner,
    isRetrying,
    inProgressMessage,
    refresh,
    command,
    reportCommand,
  } = useFounderEvidence();

  // AT-ED-011.5: the ExecutiveBriefing/Operations founder-brief each own an endpoint no other
  // screen consumes, so each gets its own independent loading/refresh, separate from the shared
  // founder-evidence core above and from each other - see hooks/useMarketData.js and
  // hooks/useFounderBrief.js for why these were split out and why they still live here (in
  // App.js, constructed once) rather than inside their screen components.
  // APP SIMPLIFICATION (2026-08-21): useMarketData used to also back its own dedicated Market
  // screen; now that Market is gone, its themes are folded directly into the Executive
  // Briefing's own refresh (see SCREEN_DATA_SOURCES.ExecutiveBriefing in lib/screenRefresh.js)
  // rather than kept as a separate, un-refreshable screen-less data source.
  const marketData = useMarketData();
  const founderBrief = useFounderBrief();

  // AT-ED-011.5 requirement 5 (see mobile/lib/screenRefresh.js and the ownership table in
  // architecture/ARCHITECTURE_DELTA.md / Data_Freshness_Findings.md): every screen's own
  // refresh/loading/last-refreshed/error is composed here, once, from only the source(s)
  // SCREEN_DATA_SOURCES actually lists for it. Activity/Portfolio/Learning use the compact
  // shared Founder projection; ExecutiveBriefing also owns founderBrief and market (themes).
  const screenRefresh = useMemo(
    () =>
      buildScreenRefreshRegistry({
        shared: { refresh, loading, lastRefreshedAt, lastRefreshError },
        market: { refresh: marketData.refresh, loading: marketData.loading, lastRefreshedAt: marketData.lastRefreshedAt, lastRefreshError: marketData.lastRefreshError },
        founderBrief: { refresh: founderBrief.refresh, loading: founderBrief.loading, lastRefreshedAt: founderBrief.lastRefreshedAt, lastRefreshError: founderBrief.lastRefreshError },
      }),
    [
      refresh,
      loading,
      lastRefreshedAt,
      lastRefreshError,
      marketData.refresh,
      marketData.loading,
      marketData.lastRefreshedAt,
      marketData.lastRefreshError,
      founderBrief.refresh,
      founderBrief.loading,
      founderBrief.lastRefreshedAt,
      founderBrief.lastRefreshError,
    ]
  );
  const activeScreenRefresh = screenRefresh[screen] || screenRefresh.ExecutiveBriefing;
  const activeRefreshing = activeScreenRefresh.loading;
  const activeOnRefresh = activeScreenRefresh.refresh;

  const content = useMemo(() => {
    if (screen === 'ExecutiveBriefing') {
      return (
        // AT-ED-015.1 Section 5: defence-in-depth around the Executive Briefing subtree only -
        // the app shell (header, tab bar) is rendered outside `content` in App.js's own JSX
        // below, so a render exception here unmounts only this screen, never the whole app.
        <ErrorBoundary
          label="ExecutiveBriefing"
          title="The Executive Briefing could not be displayed."
          message="Something went wrong while preparing your briefing. Your other data and navigation are unaffected."
          onRetry={() => screenRefresh.ExecutiveBriefing.refresh()}
          onOpenOperations={() => setScreen('Operations')}
        >
          <ExecutiveBriefing
            status={status}
            portfolio={portfolio}
            recommendations={recommendations}
            activity={activity}
            themes={marketData.themes}
            dailyLearning={dailyLearning}
            performanceAttribution={performanceAttribution}
            marketForecast={marketForecast}
            tradeScorecard={tradeScorecard}
            declineReasons={declineReasons}
            onCommand={command}
            onRefresh={screenRefresh.ExecutiveBriefing.refresh}
            askMessages={askMessages}
            setAskMessages={setAskMessages}
            request={apiRequest}
          />
        </ErrorBoundary>
      );
    }
    if (screen === 'RunCycle') {
      // Own ErrorBoundary: this screen polls a backend endpoint on a timer, and a render
      // failure here must not take down the Briefing or Portfolio with it.
      return (
        <ErrorBoundary
          label="RunCycle"
          title="The cycle screen could not be displayed."
          message="Something went wrong showing the run log. Your other data and navigation are unaffected."
          onRetry={() => setScreen('ExecutiveBriefing')}
        >
          <RunCycleScreen />
        </ErrorBoundary>
      );
    }
    // Portfolio is the only remaining alternative to the Briefing, so it is the fallback
    // rather than a branch with an unreachable Ask screen behind it.
    return (
      <PortfolioCommandCentre
        status={status}
        portfolio={portfolio}
        recommendations={recommendations}
        performanceAttribution={performanceAttribution}
        latestReport={latestReport}
        selectedExchange={selectedExchange}
        setSelectedExchange={setSelectedExchange}
        onCommand={command}
        onReport={reportCommand}
      />
    );
  }, [
    activity,
    activityPeriod,
    askMessages,
    dailyLearning,
    declineReasons,
    founderBrief.brief,
    founderBrief.lastRefreshError,
    founderBrief.loading,
    latestReport,
    marketData.themes,
    notifications,
    performanceAttribution,
    portfolio,
    recommendations,
    screenRefresh,
    screen,
    status,
    selectedExchange,
    tradeScorecard,
  ]);


  return (
    <SafeAreaView style={styles.safe}>
      <StatusBar barStyle="light-content" backgroundColor="#0b1220" translucent={false} />
      <View style={styles.header}>
        <View style={styles.headerTopRow}>
          <Text style={styles.title}>AI Trader</Text>
          <StatusPill label={dataSourceBadge.label} tone={dataSourceBadge.tone} />
        </View>
        <Text style={styles.subtitle}>
          {lastRefreshedAt ? `Last refreshed ${formatDateTime(lastRefreshedAt)}` : `Backend: ${shortApiBase()}`}
        </Text>
        {/* AT-ED-011.6: once the bootstrap spinner above has cleared, a later refresh (manual,
            pull-to-refresh, or the 2-minute auto-refresh) only drives the header's small
            "Refreshing" StatusPill with no further detail - this surfaces the same truthful
            in-progress message (e.g. "Backend slow to respond - retrying...") the bootstrap
            spinner shows, instead of leaving the Founder guessing why a refresh is taking a
            while. */}
        {!bootstrapping && inProgressMessage && (
          <Text style={styles.subtitle}>{inProgressMessage}</Text>
        )}
        {/* AT-ED-011.5: the backend evidence-snapshot-age line and the AsyncStorage cache
            banner both describe the shared founder-evidence source. */}
        {snapshotInfo.known && (
          <Text style={styles.subtitle}>
            Evidence as of {formatDateTime(snapshotInfo.generatedAt)}
            {typeof snapshotInfo.ageSeconds === 'number' ? ` (${formatAgeSeconds(snapshotInfo.ageSeconds)})` : ''}
            {snapshotInfo.stale ? ' - backend snapshot stale' : ''}
          </Text>
        )}
        {cacheBanner && (
          <View style={styles.cacheBanner}>
            <Text style={styles.cacheBannerHeadline}>{cacheBanner.headline}</Text>
            {cacheBanner.captured && (
              <Text style={styles.cacheBannerDetail}>Captured: {formatDateTime(cacheBanner.captured)}</Text>
            )}
            {cacheBanner.age && <Text style={styles.cacheBannerDetail}>Age: {cacheBanner.age}</Text>}
            <Text style={styles.cacheBannerDetail}>{cacheBanner.reason}</Text>
            <TouchableOpacity onPress={refresh} disabled={loading}>
              <Text style={styles.cacheBannerRetry}>
                {loading ? (isRetrying ? 'Waking backend service...' : 'Retrying...') : 'Retry now'}
              </Text>
            </TouchableOpacity>
          </View>
        )}
        {/* AT-ED-011.6: this is the state the Founder saw as an unexplained "No Data Available"
            banner directly under a "Refresh Failed" StatusPill (the exact AT-ED-011.6 bug
            report) - both were technically accurate but gave no indication of *why*, or that a
            retry was already happening automatically. Renamed to name the actual condition and,
            when a prior successful refresh exists this session, show when that was so the
            Founder can judge how stale the last-known values are even though nothing is
            currently displayed from this source. */}
        {dataSourceState === DISPLAY_STATE.REFRESH_FAILED && (
          <View style={styles.cacheBanner}>
            <Text style={styles.cacheBannerHeadline}>Backend temporarily unavailable</Text>
            <Text style={styles.cacheBannerDetail}>
              {friendlyRefreshFailureReason(lastRefreshError)}
            </Text>
            {lastRefreshedAt && (
              <Text style={styles.cacheBannerDetail}>
                Last successful refresh: {formatDateTime(lastRefreshedAt)}
              </Text>
            )}
            <TouchableOpacity onPress={activeOnRefresh} disabled={activeRefreshing}>
              <Text style={styles.cacheBannerRetry}>
                {activeRefreshing
                  ? isRetrying
                    ? 'Waking backend service...'
                    : 'Retrying...'
                  : 'Retry now'}
              </Text>
            </TouchableOpacity>
          </View>
        )}
      </View>
      {/* AT-ED-015 Section 11: the Executive Briefing is the Founder's primary entry point, not
          one equal-weight tab among seven - a distinct, full-width button above the regular tab
          row, so it is always the first thing the Founder sees and can always return to. */}
      <TouchableOpacity
        style={[styles.primaryTab, screen === 'ExecutiveBriefing' && styles.primaryTabActive]}
        onPress={() => setScreen('ExecutiveBriefing')}
      >
        <Text style={[styles.primaryTabText, screen === 'ExecutiveBriefing' && styles.primaryTabTextActive]}>
          Executive Briefing
        </Text>
      </TouchableOpacity>
      <View style={styles.tabs}>
        {SCREENS.filter((item) => item !== 'ExecutiveBriefing').map((item) => (
          <TouchableOpacity
            key={item}
            style={[styles.tab, screen === item && styles.activeTab]}
            onPress={() => setScreen(item)}
          >
            <Text
              numberOfLines={2}
              style={[styles.tabText, screen === item && styles.activeTabText]}
            >
              {SCREEN_LABELS[item] || item}
            </Text>
          </TouchableOpacity>
        ))}
      </View>
      {/* AT-ED-011.5 requirement 13/14: the full-screen indicator is reserved for the initial
          app bootstrap (no founder-evidence data has ever loaded yet). A normal background or
          manual refresh after that only drives the small per-screen RefreshControl spinner
          below, plus the header's own "Refreshing" status pill - never this full-screen one. */}
      {bootstrapping && (
        <View style={styles.loading}>
          <ActivityIndicator />
          {/* AT-ED-011.6: the bootstrap spinner previously gave no indication of what it was
              waiting for. inProgressMessage distinguishes "first attempt in flight" from "the
              first attempt failed and this is the bounded retry" - see
              lib/refreshState.js's connectionMessage. */}
          <Text style={[styles.subtitle, styles.loadingText]}>
            {inProgressMessage || 'Connecting to AI Trader...'}
          </Text>
        </View>
      )}
      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={<RefreshControl refreshing={activeRefreshing} onRefresh={activeOnRefresh} />}
      >
        {content}
      </ScrollView>
    </SafeAreaView>
  );
}
