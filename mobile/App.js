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
import { ExecutiveDashboard } from './screens/Dashboard';
import { AutonomousActivity } from './screens/Activity';
import { Recommendations } from './screens/Recommendations';
import { PortfolioCommandCentre } from './screens/Portfolio';
import { MarketIntelligence } from './screens/Market';
import { LearningStrategyLab } from './screens/Learning';
import { useFounderEvidence } from './hooks/useFounderEvidence';
import { useMarketData } from './hooks/useMarketData';
import { useFounderBrief } from './hooks/useFounderBrief';
const {
  DISPLAY_STATE,
  classifyDisplayState,
  displayStateBadge,
  formatAgeSeconds,
} = require('./lib/refreshState');
const { buildScreenRefreshRegistry } = require('./lib/screenRefresh');
const { formatDateTime } = require('./lib/datetime');
const { shortApiBase, apiRequest } = require('./api/client');

const SCREENS = ['Dashboard', 'Activity', 'Recommendations', 'Portfolio', 'Market', 'Learning'];

export default function App() {
  const [screen, setScreen] = useState('Dashboard');
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
    refresh,
    command,
    reportCommand,
  } = useFounderEvidence();

  // AT-ED-011.5: Market and the Dashboard founder-brief each own an endpoint no other screen
  // consumes, so each gets its own independent loading/refresh, separate from the shared
  // founder-evidence core above and from each other - see hooks/useMarketData.js and
  // hooks/useFounderBrief.js for why these were split out and why they still live here (in
  // App.js, constructed once) rather than inside their screen components.
  const marketData = useMarketData();
  const founderBrief = useFounderBrief();

  // AT-ED-011.5 requirement 5 (see mobile/lib/screenRefresh.js and the ownership table in
  // architecture/ARCHITECTURE_DELTA.md / Data_Freshness_Findings.md): every screen's own
  // refresh/loading/last-refreshed/error is composed here, once, from only the source(s)
  // SCREEN_DATA_SOURCES actually lists for it - Activity/Portfolio/Recommendations/Learning
  // genuinely share the one founder-evidence payload (no narrower backend endpoint would
  // reduce a real network/DB cost - see the ownership table), so they compose to that shared
  // source only; Market and Dashboard's founder-brief are screen-exclusive and never appear in
  // another screen's composition.
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
  const activeScreenRefresh = screenRefresh[screen] || screenRefresh.Dashboard;
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
  };

  const content = useMemo(() => {
    if (screen === 'Dashboard') {
      return (
        <ExecutiveDashboard
          status={status}
          portfolio={portfolio}
          brief={founderBrief.brief}
          briefLoading={founderBrief.loading}
          briefError={founderBrief.lastRefreshError}
          latestReport={latestReport}
          onRefresh={screenRefresh.Dashboard.refresh}
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
          period={activityPeriod}
          setPeriod={setActivityPeriod}
          onRefresh={screenRefresh.Activity.refresh}
          notifications={notifications}
          onCommand={command}
        />
      );
    }
    if (screen === 'Recommendations') {
      return (
        <Recommendations
          recommendations={recommendations}
          trades={performanceAttribution}
          dailyLearning={dailyLearning}
          amounts={amounts}
          setAmounts={setAmounts}
          onApprove={approve}
          onRefresh={screenRefresh.Recommendations.refresh}
          onRunAnalysis={(broker = 'kraken') => {
            if (String(broker).toLowerCase() === 'kraken') {
              return command('/run-crypto-analysis', { broker: 'kraken', limit: 10 });
            }
            return command('/run-analysis', { broker: 'alpaca', limit: 10 });
          }}
          onAutoExecute={() => command('/auto-execute-recommendations')}
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
              <Text style={styles.cacheBannerRetry}>Retry now</Text>
            </TouchableOpacity>
          </View>
        )}
        {activeDataSourceState === DISPLAY_STATE.REFRESH_FAILED && (
          <View style={styles.cacheBanner}>
            <Text style={styles.cacheBannerHeadline}>No Data Available</Text>
            <Text style={styles.cacheBannerDetail}>
              {activeLastRefreshError ? `Live refresh failed: ${activeLastRefreshError}` : 'Live refresh failed.'}
            </Text>
            <TouchableOpacity onPress={activeOnRefresh} disabled={activeRefreshing}>
              <Text style={styles.cacheBannerRetry}>Retry now</Text>
            </TouchableOpacity>
          </View>
        )}
      </View>
      <View style={styles.tabs}>
        {SCREENS.map((item) => (
          <TouchableOpacity
            key={item}
            style={[styles.tab, screen === item && styles.activeTab]}
            onPress={() => setScreen(item)}
          >
            <Text
              numberOfLines={2}
              style={[styles.tabText, screen === item && styles.activeTabText]}
            >
              {item}
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
