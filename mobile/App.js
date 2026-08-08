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
import { OperationsCentre } from './screens/Operations';
import { AutonomousActivity } from './screens/Activity';
import { Recommendations } from './screens/Recommendations';
import { PortfolioCommandCentre } from './screens/Portfolio';
import { MarketIntelligence } from './screens/Market';
import { LearningStrategyLab } from './screens/Learning';
import { useFounderEvidence } from './hooks/useFounderEvidence';
import { useMarketData } from './hooks/useMarketData';
import { useFounderBrief } from './hooks/useFounderBrief';
import { useRecommendationDossiers } from './hooks/useRecommendationDossiers';
const {
  DISPLAY_STATE,
  classifyDisplayState,
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
const SCREENS = ['ExecutiveBriefing', 'Operations', 'Activity', 'Recommendations', 'Portfolio', 'Market', 'Learning'];
const SCREEN_LABELS = { ExecutiveBriefing: 'Executive Briefing' };

export default function App() {
  const [screen, setScreen] = useState('ExecutiveBriefing');
  const [amounts, setAmounts] = useState({});
  const [selectedExchange, setSelectedExchange] = useState('All');
  const [targetRecommendationId, setTargetRecommendationId] = useState(null);
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
    dailyLearning,
    latestReport,
    activity,
    activityPeriod,
    setActivityPeriod,
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

  // AT-ED-011.5: Market and the ExecutiveBriefing/Operations founder-brief each own an endpoint no other screen
  // consumes, so each gets its own independent loading/refresh, separate from the shared
  // founder-evidence core above and from each other - see hooks/useMarketData.js and
  // hooks/useFounderBrief.js for why these were split out and why they still live here (in
  // App.js, constructed once) rather than inside their screen components.
  const marketData = useMarketData();
  const founderBrief = useFounderBrief();
  const recommendationDossiers = useRecommendationDossiers(screen === 'Recommendations');

  // AT-ED-011.5 requirement 5 (see mobile/lib/screenRefresh.js and the ownership table in
  // architecture/ARCHITECTURE_DELTA.md / Data_Freshness_Findings.md): every screen's own
  // refresh/loading/last-refreshed/error is composed here, once, from only the source(s)
  // SCREEN_DATA_SOURCES actually lists for it. Activity/Portfolio/Learning use the compact
  // shared Founder projection; Recommendations adds its on-demand full-dossier source. Market
  // and ExecutiveBriefing/Operations' founder-brief remain screen-exclusive.
  const screenRefresh = useMemo(
    () =>
      buildScreenRefreshRegistry({
        shared: { refresh, loading, lastRefreshedAt, lastRefreshError },
        market: { refresh: marketData.refresh, loading: marketData.loading, lastRefreshedAt: marketData.lastRefreshedAt, lastRefreshError: marketData.lastRefreshError },
        founderBrief: { refresh: founderBrief.refresh, loading: founderBrief.loading, lastRefreshedAt: founderBrief.lastRefreshedAt, lastRefreshError: founderBrief.lastRefreshError },
        recommendationDossiers: {
          refresh: recommendationDossiers.refresh,
          loading: recommendationDossiers.loading,
          lastRefreshedAt: recommendationDossiers.lastRefreshedAt,
          lastRefreshError: recommendationDossiers.lastRefreshError,
        },
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
      recommendationDossiers.refresh,
      recommendationDossiers.loading,
      recommendationDossiers.lastRefreshedAt,
      recommendationDossiers.lastRefreshError,
    ]
  );
  const activeScreenRefresh = screenRefresh[screen] || screenRefresh.ExecutiveBriefing;
  const activeRefreshing = activeScreenRefresh.loading;
  const activeOnRefresh = activeScreenRefresh.refresh;

  // AT-ED-011.5 data-truth fix: the header's freshness badge/banner used to always reflect the
  // shared founder-evidence hook, even while viewing Market - so a founder-evidence failure
  // could show "Refresh Failed" over Market's screen even though Market's own independent
  // refresh had just succeeded, and vice versa. Market has no AsyncStorage cache and no backend
  // snapshot-staleness concept (see useMarketData.js), so it only ever occupies four of
  // classifyDisplayState's six states - Live/Refreshing/Refresh-Failed/No-Data-Available -
  // never Cached or Backend-Snapshot-Stale.
  const marketDataSourceState = useMemo(
    () =>
      classifyDisplayState({
        isRefreshing: marketData.loading,
        hasAttempted: !marketData.bootstrapping,
        lastRefreshSucceeded: marketData.bootstrapping ? null : !marketData.lastRefreshError,
        hasCachedData: false,
        backendSnapshotStale: null,
      }),
    [marketData.loading, marketData.bootstrapping, marketData.lastRefreshError]
  );
  const marketDataSourceBadge = useMemo(() => displayStateBadge(marketDataSourceState), [marketDataSourceState]);
  const isMarketScreen = screen === 'Market';
  const activeDataSourceBadge = isMarketScreen ? marketDataSourceBadge : dataSourceBadge;
  const activeLastRefreshedAt = isMarketScreen ? marketData.lastRefreshedAt : lastRefreshedAt;
  const activeDataSourceState = isMarketScreen ? marketDataSourceState : dataSourceState;
  const activeLastRefreshError = isMarketScreen ? marketData.lastRefreshError : lastRefreshError;

  const approve = async (proposalId, symbol = null) => {
    await command('/approve-and-execute', {
      proposal_id: proposalId,
      symbol,
      amount: amounts[proposalId] || null,
    });
    await recommendationDossiers.refresh();
  };

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
            brief={founderBrief.brief}
            onRefresh={screenRefresh.ExecutiveBriefing.refresh}
            onOpenOperations={() => setScreen('Operations')}
            onOpenRecommendations={() => setScreen('Recommendations')}
          />
        </ErrorBoundary>
      );
    }
    if (screen === 'Operations') {
      return (
        <OperationsCentre
          status={status}
          recommendations={recommendations}
          brief={founderBrief.brief}
          briefLoading={founderBrief.loading}
          briefError={founderBrief.lastRefreshError}
          latestReport={latestReport}
          onRefresh={screenRefresh.Operations.refresh}
          onCommand={command}
          onReport={reportCommand}
          activity={activity}
          onOpenActivity={() => setScreen('Activity')}
        />
      );
    }
    if (screen === 'Activity') {
      return (
        <AutonomousActivity
          activity={activity}
          founderStatus={status}
          portfolio={portfolio}
          performanceAttribution={performanceAttribution}
          recommendations={recommendations}
          period={activityPeriod}
          setPeriod={setActivityPeriod}
          onRefresh={screenRefresh.Activity.refresh}
          notifications={notifications}
          onCommand={command}
        />
      );
    }
    if (screen === 'Recommendations') {
      const recommendationItems = recommendationDossiers.recommendations.length
        ? recommendationDossiers.recommendations
        : recommendations;
      return (
        <Recommendations
          recommendations={recommendationItems}
          dossierLoading={recommendationDossiers.loading}
          dossierError={recommendationDossiers.lastRefreshError}
          trades={performanceAttribution}
          dailyLearning={dailyLearning}
          amounts={amounts}
          setAmounts={setAmounts}
          onApprove={approve}
          onRefresh={screenRefresh.Recommendations.refresh}
          onRunAnalysis={(broker = 'kraken') => {
            if (String(broker).toLowerCase() === 'kraken') {
              return command('/run-crypto-analysis', { broker: 'kraken', limit: 10 })
                .then(() => recommendationDossiers.refresh());
            }
            return command('/run-analysis', { broker: 'alpaca', limit: 10 })
              .then(() => recommendationDossiers.refresh());
          }}
          onAutoExecute={() => command('/auto-execute-recommendations').then(() => recommendationDossiers.refresh())}
          targetRecommendationId={targetRecommendationId}
          clearTargetRecommendation={() => setTargetRecommendationId(null)}
        />
      );
    }
    if (screen === 'Portfolio') {
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
    }
    if (screen === 'Market') {
      return (
      <MarketIntelligence
        benchmark={marketData.benchmark}
        themes={marketData.themes}
        companies={marketData.companies}
        status={status}
        recommendations={recommendations}
        dailyLearning={dailyLearning}
        onOpenRecommendation={(proposalId) => {
          setTargetRecommendationId(proposalId);
          setScreen('Recommendations');
        }}
      />
      );
    }
    return (
      <LearningStrategyLab
        status={status}
        dailyLearning={dailyLearning}
        messages={askMessages}
        setMessages={setAskMessages}
        request={apiRequest}
      />
    );
  }, [
    activity,
    activityPeriod,
    amounts,
    askMessages,
    dailyLearning,
    founderBrief.brief,
    founderBrief.lastRefreshError,
    founderBrief.loading,
    latestReport,
    marketData.benchmark,
    marketData.companies,
    marketData.themes,
    notifications,
    performanceAttribution,
    portfolio,
    recommendations,
    recommendationDossiers.recommendations,
    recommendationDossiers.refresh,
    screenRefresh,
    screen,
    status,
    targetRecommendationId,
    selectedExchange,
  ]);


  return (
    <SafeAreaView style={styles.safe}>
      <StatusBar barStyle="light-content" backgroundColor="#0b1220" translucent={false} />
      <View style={styles.header}>
        <View style={styles.headerTopRow}>
          <Text style={styles.title}>AI Trader</Text>
          <StatusPill label={activeDataSourceBadge.label} tone={activeDataSourceBadge.tone} />
        </View>
        <Text style={styles.subtitle}>
          {activeLastRefreshedAt ? `Last refreshed ${formatDateTime(activeLastRefreshedAt)}` : `Backend: ${shortApiBase()}`}
        </Text>
        {/* AT-ED-011.6: once the bootstrap spinner above has cleared, a later refresh (manual,
            pull-to-refresh, or the 2-minute auto-refresh) only drives the header's small
            "Refreshing" StatusPill with no further detail - this surfaces the same truthful
            in-progress message (e.g. "Backend slow to respond - retrying...") the bootstrap
            spinner shows, instead of leaving the Founder guessing why a refresh is taking a
            while. Market has no isRetrying concept (see useMarketData.js), so this is suppressed
            there like the other founder-evidence-specific lines below. */}
        {!isMarketScreen && !bootstrapping && inProgressMessage && (
          <Text style={styles.subtitle}>{inProgressMessage}</Text>
        )}
        {/* AT-ED-011.5: the backend evidence-snapshot-age line and the AsyncStorage cache
            banner both describe the shared founder-evidence source specifically (its
            persisted-snapshot age, its on-phone cache) - Market has neither concept (see
            useMarketData.js), so both are suppressed while viewing Market rather than showing
            the shared source's snapshot/cache state over Market's own independent data. */}
        {!isMarketScreen && snapshotInfo.known && (
          <Text style={styles.subtitle}>
            Evidence as of {formatDateTime(snapshotInfo.generatedAt)}
            {typeof snapshotInfo.ageSeconds === 'number' ? ` (${formatAgeSeconds(snapshotInfo.ageSeconds)})` : ''}
            {snapshotInfo.stale ? ' - backend snapshot stale' : ''}
          </Text>
        )}
        {!isMarketScreen && cacheBanner && (
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
        {activeDataSourceState === DISPLAY_STATE.REFRESH_FAILED && (
          <View style={styles.cacheBanner}>
            <Text style={styles.cacheBannerHeadline}>Backend temporarily unavailable</Text>
            <Text style={styles.cacheBannerDetail}>
              {friendlyRefreshFailureReason(activeLastRefreshError)}
            </Text>
            {activeLastRefreshedAt && (
              <Text style={styles.cacheBannerDetail}>
                Last successful refresh: {formatDateTime(activeLastRefreshedAt)}
              </Text>
            )}
            <TouchableOpacity onPress={activeOnRefresh} disabled={activeRefreshing}>
              <Text style={styles.cacheBannerRetry}>
                {activeRefreshing
                  ? !isMarketScreen && isRetrying
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
