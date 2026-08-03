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
const {
  DISPLAY_STATE,
  formatAgeSeconds,
} = require('./lib/refreshState');
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
  } = useFounderEvidence();

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
          brief={brief}
          latestReport={latestReport}
          onRefresh={refresh}
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
          onRefresh={refresh}
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
          onRefresh={refresh}
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
        benchmark={benchmark}
        themes={themes}
        companies={companies}
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
  }, [activity, activityPeriod, amounts, askMessages, benchmark, brief, companies, dailyLearning, latestReport, loading, notifications, performanceAttribution, portfolio, recommendations, screen, status, themes, targetRecommendationId, selectedExchange]);


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
              <Text style={styles.cacheBannerRetry}>Retry now</Text>
            </TouchableOpacity>
          </View>
        )}
        {dataSourceState === DISPLAY_STATE.REFRESH_FAILED && (
          <View style={styles.cacheBanner}>
            <Text style={styles.cacheBannerHeadline}>No Data Available</Text>
            <Text style={styles.cacheBannerDetail}>
              {lastRefreshError ? `Live refresh failed: ${lastRefreshError}` : 'Live refresh failed.'}
            </Text>
            <TouchableOpacity onPress={refresh} disabled={loading}>
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
      {loading && (
        <View style={styles.loading}>
          <ActivityIndicator />
        </View>
      )}
      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={refresh} />}
      >
        {content}
      </ScrollView>
    </SafeAreaView>
  );
}
