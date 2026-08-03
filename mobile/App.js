import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Linking,
  RefreshControl,
  SafeAreaView,
  ScrollView,
  StatusBar,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { styles } from './styles';
import { Section, CollapsibleSection, Metric, TextBlock, Button, StatusPill, Empty } from './components/shared';
const {
  operationalRollup,
  operationalLevelTone,
  brokerOverallReadiness,
  groupActivity,
  recommendationLifecycle,
  positionOwnership,
  learningSummary,
  formatGuardrailFailures,
} = require('./lib/founderPresentation');
const {
  DISPLAY_STATE,
  classifyDisplayState,
  snapshotFreshness,
  formatAgeSeconds,
  cacheBannerDetails,
  displayStateBadge,
} = require('./lib/refreshState');
const { brokerKey, money, gbp, moneyOrText, gbpOrText, brokerMoney, historyMoneyOrText } = require('./lib/money');
const { dateMs, formatDateTime, formatPercent } = require('./lib/datetime');
const { formatList, formatListInline } = require('./lib/lists');
const { notAvailable, explainMissing } = require('./lib/notAvailable');
const {
  unavailableStatus,
  unavailableActivity,
  statusFromFounderEvidence,
  activityFromFounderEvidence,
  productionTradeForMobile,
  brokerResearchStatus,
  founderHeadline,
  founderAction,
  founderLearningForMobile,
  sortByConfidence,
} = require('./lib/founderEvidenceMapping');
const {
  API_BASE,
  API_TOKEN,
  API_TOKEN_MASK,
  PRIMARY_REFRESH_TIMEOUT_MS,
  SECONDARY_REFRESH_TIMEOUT_MS,
  COMMAND_TIMEOUT_MS,
  shortApiBase,
  absoluteApiUrl,
  apiRequest,
} = require('./api/client');

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

const SCREENS = ['Dashboard', 'Activity', 'Recommendations', 'Portfolio', 'Market', 'Learning'];

export default function App() {
  const [screen, setScreen] = useState('Dashboard');
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState(null);
  const [portfolio, setPortfolio] = useState(null);
  const [brief, setBrief] = useState(null);
  const [recommendations, setRecommendations] = useState([]);
  const [benchmark, setBenchmark] = useState(null);
  const [themes, setThemes] = useState([]);
  const [companies, setCompanies] = useState([]);
  const [amounts, setAmounts] = useState({});
  const [selectedExchange, setSelectedExchange] = useState('All');
  const [lastRefreshedAt, setLastRefreshedAt] = useState(null);
  // AT-ED-010 data-freshness state (mobile/lib/refreshState.js owns the derived
  // classification - these four are the raw signals it's computed from).
  const [hasAttempted, setHasAttempted] = useState(false);
  const [lastRefreshSucceeded, setLastRefreshSucceeded] = useState(null);
  const [lastRefreshError, setLastRefreshError] = useState(null);
  const [cachedAt, setCachedAt] = useState(null);
  const [snapshotMeta, setSnapshotMeta] = useState(null);
  const [targetRecommendationId, setTargetRecommendationId] = useState(null);
  const [notifications, setNotifications] = useState([]);
  const [performanceAttribution, setPerformanceAttribution] = useState([]);
  const [dailyLearning, setDailyLearning] = useState(null);
  const [latestReport, setLatestReport] = useState(null);
  const [activity, setActivity] = useState(null);
  const [activityPeriod, setActivityPeriod] = useState('24h');
  const [askMessages, setAskMessages] = useState([
    {
      role: 'assistant',
      text: 'Ask me about balances, open positions, trades, reports, recommendations, or what AI Trader learned. I am read-only and cannot place trades.',
    },
  ]);

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

function ExecutiveDashboard({ status, portfolio, brief, latestReport, onRefresh, onCommand, onReport, activity, onOpenActivity }) {
  const executive = status?.founder_experience?.executive_dashboard || {};
  const evidence = status?.world_class_evidence || {};
  const operations = status?.operations_health || {};
  const readiness = withMobileTokenReadiness(status?.connection_readiness || localConnectionReadiness(status, status?.brokers || []));
  const brokerPanels = connectedFounderBrokers(status?.brokers || []);
  const futureConnections = evidence.future_connections || futureBrokerPanels(status?.brokers || []);
  return (
    <View>
      <Section title="Command Summary">
        <StatusPill label={evidence.first_conclusion || 'No action required'} tone={summaryTone(evidence.first_conclusion)} />
        <Metric label="Market" value={status?.founder_experience?.market_intelligence_centre?.market_health || explainMissing('market health', 'market intelligence has not produced a fresh regime summary yet')} />
        <Metric label="Portfolio" value={executive.portfolio_health || explainMissing('portfolio health', 'broker portfolio values or exposure evidence are incomplete')} />
        <Metric label="Brokers" value={brokerPanels.length ? `${brokerPanels.map((item) => item.label || item.broker).join(', ')} connected or visible` : explainMissing('broker status', 'Alpaca and Kraken are not both visible from the hosted API')} />
        <Metric label="Data" value={(evidence.unavailable || []).length ? `${evidence.unavailable.length} value(s) need explanation` : 'Measured values are currently usable'} />
        <Metric label="Research" value={status?.research_status || explainMissing('research status', 'no research run has been recorded yet')} />
        <Metric label="Learning" value={evidence.experience_learning?.boundary || executive.learning_progress} />
        <TextBlock label="Attention Required" value={formatUnavailableReasons(evidence.unavailable)} />
      </Section>
      <AutonomousActivitySummaryCard activity={activity} onOpenActivity={onOpenActivity} />
      <Section title="Executive Summary">
        <StatusPill label={notAvailable(executive.portfolio_health)} tone={riskTone(executive.portfolio_risk)} />
        <Text style={styles.cardTitle}>{notAvailable(executive.headline)}</Text>
        <TextBlock label="What changed overnight" value={formatList(executive.good_morning)} />
        <TextBlock label="What I recommend" value={executive.what_to_do} />
        <TextBlock label="What to worry about" value={executive.what_to_worry_about} />
      </Section>
      <Section title="24-Hour Operations">
        <StatusPill label={operations.plain_english || explainMissing('operations health', 'no background worker heartbeat or scheduled job evidence has been returned yet')} tone={operationsTone(operations)} />
        <Metric label="API Health" value={operations.api_health || explainMissing('API health', 'the status endpoint did not include operations health yet')} />
        <Metric label="Worker Health" value={operations.worker_health || explainMissing('worker health', 'no durable worker heartbeat has been recorded yet')} />
        <Metric label="Database Durability" value={operations.database_durability || explainMissing('database durability', 'database path has not been checked by the operations module')} />
        <Metric label="Last Equity Research" value={formatDateTime(operations.last_equity_research?.created_at)} />
        <Metric label="Last Crypto Research" value={formatDateTime(operations.last_crypto_research?.created_at)} />
        <Metric label="Last Broker Poll" value={latestJobTime(operations.last_job_runs, 'broker-poll')} />
        <Metric label="Last Auto-Execution Check" value={latestJobTime(operations.last_job_runs, 'auto-execution')} />
        <Metric label="Assets Reviewed Overnight" value={operations.last_equity_research?.symbols_examined || operations.last_crypto_research?.symbols_examined} />
        <Metric label="Shadow Decisions Overnight" value={sumRecentJobs(operations.last_job_runs, 'shadow_decisions_created')} />
        <Metric label="Alpaca Paper Orders" value={sumRecentJobs(operations.last_job_runs, 'paper_orders_submitted')} />
        <Metric label="Kraken Orders" value={connectedFounderBrokers(status?.brokers || []).find((item) => item.broker === 'kraken')?.trades_today} />
        <TextBlock label="Incidents" value={operationsIncidentText(operations.incidents)} />
      </Section>
      <ConnectionReadinessCard readiness={readiness} />
      <Section title="Broker Panels">
        {brokerPanels.length ? brokerPanels.map((broker) => (
          <BrokerPanel key={`${broker.broker}-dashboard`} broker={broker} onCommand={onCommand} onReport={onReport} />
        )) : <Empty />}
      </Section>
      {futureConnections.length ? (
        <Section title="Future Connections">
          {futureConnections.map((item) => (
            <Metric key={`future-${item.broker || item.label}`} label={item.label || item.broker} value={item.status || 'Not connected'} />
          ))}
        </Section>
      ) : null}
      <Section title="Founder Actions">
        <View style={styles.buttonGrid}>
          <Button label="Refresh" onPress={onRefresh} tone="neutral" />
          <Button label="Run Analysis" onPress={() => onCommand('/run-analysis', { limit: 10 })} />
          <Button label="Today Report" onPress={() => onReport({ type: 'daily', date: todayIso(), broker: 'all' })} tone="neutral" />
          <Button label="Emergency Stop All" tone="danger" onPress={() => onCommand('/stop-trading')} />
        </View>
        {latestReport ? <ReportPanel report={latestReport} /> : null}
      </Section>
    </View>
  );
}

function PortfolioCommandCentre({ status, portfolio, recommendations, performanceAttribution, latestReport, selectedExchange, setSelectedExchange, onCommand, onReport }) {
  const portfolioCommand = status?.founder_experience?.portfolio_command || {};
  const evidence = status?.world_class_evidence || {};
  const trades = combinedTransactions(status, portfolio, selectedExchange, performanceAttribution, 200);
  const summary = tradeHistorySummary(status, trades, selectedExchange);
  const brokerPanels = connectedFounderBrokers(status?.brokers || []);

  // AI-managed positions only ever come from a broker's own managed_exits (an explicit,
  // open MANAGED_TRADE_EXITS row) - never inferred from the raw position list, so a manual
  // Kraken holding can never be mislabeled as AI-managed.
  const aiManagedPositions = brokerPanels.flatMap((broker) =>
    (broker.open_positions_detail || [])
      .map((position) => ({ position, broker, ownership: positionOwnership(position, broker.managed_exits) }))
      .filter((row) => row.ownership.isAiManaged)
  );
  const positionsRequiringAttention = (portfolio?.open_positions || []).filter((position) => Number(position.unrealized_pl || 0) < 0);

  return (
    <View>
      <View style={styles.summaryCard}>
        <Text style={styles.summaryReason}>Where is capital, where is risk, and what needs attention?</Text>
        <Metric label="Portfolio Value" value={moneyOrText(portfolio?.portfolio_value)} />
        <Metric label="Cash Available" value={moneyOrText(portfolio?.cash_available)} />
        <Metric label="Deployed Capital" value={moneyOrText(portfolio?.deployed_capital)} />
        <Metric label="Today's P&L" value={moneyOrText(portfolio?.todays_pnl)} />
        <Metric label="Open Positions" value={(portfolio?.open_positions || []).length} />
        <Metric label="Positions Requiring Attention" value={positionsRequiringAttention.length} />
        {positionsRequiringAttention.length ? (
          <TextBlock
            label="At a Loss"
            value={positionsRequiringAttention.map((position) => `${position.symbol || 'Unknown'}: ${moneyOrText(position.unrealized_pl)}`).join('\n')}
          />
        ) : null}
      </View>

      <CollapsibleSection
        title="AI-Managed Positions"
        subtitle="Positions the AI opened and is tracking to a stop-loss/take-profit exit. Manual holdings are never included here."
        defaultExpanded={true}
        badge={{ label: `${aiManagedPositions.length}`, tone: aiManagedPositions.length ? 'good' : 'neutral' }}
      >
        {aiManagedPositions.length === 0 ? (
          <Empty />
        ) : aiManagedPositions.map(({ position, broker, ownership }, index) => {
          const proposalId = ownership.managedExit?.payload?.proposal_id || null;
          const recommendation = proposalId ? (recommendations || []).find((item) => item.proposal_id === proposalId) : null;
          return (
            <View key={`ai-managed-${broker.broker}-${position.symbol || index}`} style={styles.compactRow}>
              <Text style={styles.cardTitle}>{position.symbol || 'Unknown symbol'}</Text>
              <Metric label="Broker" value={broker.label} />
              <Metric label="Originating Recommendation" value={proposalId || 'Not linked in this evidence'} />
              <Metric label="Strategy" value={recommendation?.strategy_name || recommendation?.strategy_id || 'Not available'} />
              <Metric label="Entry Time" value={formatDateTime(ownership.managedExit?.created_at)} />
              <Metric label="Current State" value={ownership.managedExit?.status} />
              <Metric label="Managed-Exit Status" value={ownership.managedExit?.status === 'open' ? 'Monitoring for stop-loss/take-profit' : ownership.managedExit?.status} />
              <Metric label="Unrealised Result" value={moneyOrText(position.unrealized_pl)} />
              <Metric label="Latest Learning State" value="Not available yet - learning only follows a closed, reconciled trade." />
            </View>
          );
        })}
      </CollapsibleSection>

      <CollapsibleSection title="Trade History" subtitle="Every order, fill, and closed trade across brokers.">
        <View style={styles.buttonGrid}>
          {tradeHistoryBrokers(status).map((item) => (
            <Button key={`history-${item}`} label={item} tone={selectedExchange === item ? 'primary' : 'neutral'} onPress={() => setSelectedExchange(item)} />
          ))}
        </View>
        <Metric label="Daily P&L" value={moneyOrText(summary.dailyPnl)} />
        <Metric label="Completed Trades Today" value={summary.completedTradesToday} />
        <Metric label="Open Positions" value={summary.openPositions} />
        {trades.slice(0, 20).map((item, index) => (
          <TradeHistoryRow key={tradeKey(item, index)} item={item} onCommand={onCommand} />
        ))}
      </CollapsibleSection>

      <CollapsibleSection title="Broker Diagnostics" subtitle="Per-broker connection, governance, and balance detail.">
        {brokerPanels.length ? brokerPanels.map((broker) => (
          <BrokerPanel key={`${broker.broker}-portfolio`} broker={broker} onCommand={onCommand} onReport={onReport} />
        )) : <Empty />}
      </CollapsibleSection>

      <CollapsibleSection title="Exposure and Operational Detail" subtitle="Diversification, exposure checks, and reconciliation health.">
        <Metric label="Diversification" value={portfolioCommand.diversification} />
        <Metric label="Portfolio Risk" value={portfolioCommand.portfolio_risk} />
        <Metric label="Expected Portfolio Return" value={portfolioCommand.expected_portfolio_return} />
        <TextBlock label="Rebalancing Suggestions" value={formatList(portfolioCommand.rebalancing_suggestions)} />
        <Metric label="Sector Exposure" value={portfolioCommand.sector_exposure} />
        <Metric label="Country Exposure" value={portfolioCommand.country_exposure} />
        <Metric label="Currency Exposure" value={portfolioCommand.currency_exposure} />
        <Metric label="Correlation" value={portfolioCommand.correlation} />
        <Metric label="Lifecycle Events" value={evidence.operational_truth?.canonical_lifecycle_events} />
        <Metric label="Illegal Transition Rejections" value={evidence.operational_truth?.illegal_transition_rejections} />
        <TextBlock label="Reconciliation Health" value={formatReconciliation(evidence.operational_truth?.reconciliation_health)} />
        <TextBlock label="Portfolio Intelligence Notes" value={evidence.portfolio_intelligence?.plain_english} />
        <TextBlock label="Warnings" value={formatList(evidence.portfolio_intelligence?.warnings)} />
      </CollapsibleSection>

      {latestReport ? <ReportPanel report={latestReport} /> : null}
    </View>
  );
}

function BrokerPanel({ broker, onCommand, onReport }) {
  const label = broker.label || notAvailable(broker.broker);
  const readiness = brokerOverallReadiness(broker);
  const isKraken = broker.broker === 'kraken';
  return (
    <View style={styles.compactRow}>
      <Text style={styles.cardTitle}>{label}</Text>
      <StatusPill label={`Overall Readiness: ${readiness.label}`} tone={readiness.tone} />
      <Metric label="Mode" value={isKraken ? 'Live' : 'Paper'} />
      <Metric label="Connection Status" value={broker.connection_status} />
      <Metric label="Auto Trading" value={broker.auto_trading_status || enabledDisabled(broker.auto_trading_enabled)} />
      <Metric label="New Entries Allowed" value={readiness.newEntriesAllowed === null ? 'Unknown' : yesNo(readiness.newEntriesAllowed)} />
      {broker.block_reason ? <Metric label="Block Reason" value={broker.block_reason} /> : null}
      <Metric label="Latest Successful Poll" value={broker.latest_successful_poll ? formatDateTime(broker.latest_successful_poll) : 'Not available yet'} />
      <Metric
        label={isKraken ? 'Latest Confirmed AI-Managed Trade' : 'Latest Confirmed Paper Trade'}
        value={broker.latest_confirmed_trade ? describeLatestTrade({
          type: 'fill',
          symbol: broker.latest_confirmed_trade.symbol,
          side: broker.latest_confirmed_trade.side,
          qty: broker.latest_confirmed_trade.qty,
          price: broker.latest_confirmed_trade.filled_avg_price,
          status: broker.latest_confirmed_trade.status,
        }) : 'None recorded yet'}
      />
      <Metric label="Portfolio" value={brokerMoney(broker, broker.portfolio_value)} />
      <Metric label="Cash" value={brokerMoney(broker, broker.cash_available)} />
      <Metric label="Estimated In Positions" value={brokerMoney(broker, broker.estimated_in_positions)} />
      <Metric label="Buying Power" value={brokerMoney(broker, broker.buying_power)} />
      <Metric label="Open Positions" value={broker.open_positions} />
      <Metric label="Today's P&L" value={moneyOrText(broker.todays_pnl)} />
      <Metric label="Week P&L" value={moneyOrText(broker.week_pnl)} />
      <Metric label="Month P&L" value={moneyOrText(broker.month_pnl)} />
      <Metric label="Trades Today" value={broker.trades_today} />
      {broker.balance_summary ? (
        <>
          <Metric label="Total Estimated Balance" value={gbpOrText(broker.balance_summary.total_estimated_gbp)} />
          <Metric label="GBP Cash" value={gbpOrText(broker.balance_summary.gbp_cash)} />
          <Metric label="AI Trading Allocation" value={gbpOrText(broker.balance_summary.trading_allocation_gbp)} />
          <TextBlock label="Converted Assets" value={formatKrakenAssets(broker.balance_summary.converted_assets, true)} />
          <TextBlock label="Unpriced / Excluded Assets" value={formatKrakenAssets(broker.balance_summary.unpriced_assets, false)} />
          <TextBlock label="Raw Kraken Balances Seen By API" value={formatRawKrakenBalances(broker.balance_summary.raw_balance_rows)} />
          <TextBlock label="Balance Note" value={broker.balance_summary.valuation_note} />
        </>
      ) : null}
      <Metric label="Research Status" value={broker.research_status} />
      <Metric label="Due Diligence Status" value={broker.due_diligence_status} />
      <TradingPermissions permissions={broker.trading_permissions} />
      <View style={styles.buttonGrid}>
        <Button label={`Run Analysis (${label})`} onPress={() => onCommand('/run-analysis', { limit: 30, broker: broker.broker })} />
        <Button label={`Daily Report (${label})`} onPress={() => onReport({ type: 'daily', date: todayIso(), broker: broker.broker })} tone="neutral" />
        <Button label={`Enable Auto Trading (${label})`} onPress={() => onCommand('/broker-auto-trading', { broker: broker.broker, enabled: true })} tone="warn" />
        <Button label={`Disable Auto Trading (${label})`} onPress={() => onCommand('/broker-auto-trading', { broker: broker.broker, enabled: false })} tone="danger" />
        {broker.broker === 'kraken' ? (
          <Button
            label="Reconcile Kraken Evidence"
            onPress={() => onCommand('/kraken-reconciliation/replay', { limit: 1000 })}
            tone="neutral"
          />
        ) : null}
      </View>
    </View>
  );
}

function AutonomousActivitySummaryCard({ activity, onOpenActivity }) {
  const status = activity?.status || {};
  const summary = activity?.summary || {};
  const noTrade = activity?.why_no_trade || {};
  const latest = status.last_meaningful_activity;
  return (
    <Section title="Autonomous Activity">
      <StatusPill label={status.state || 'Status unknown'} tone={activityStatusTone(status.state)} />
      <Text style={styles.bodyText}>
        {status.plain_english || 'No persisted autonomous activity status has been returned yet.'}
      </Text>
      <Metric label="Last Action" value={latest ? `${latest.title} - ${formatDateTime(latest.timestamp)}` : 'Not available - no meaningful activity recorded in this period.'} />
      <Metric label="Research Runs" value={summary.research?.runs} />
      <Metric label="Recommendations" value={summary.research?.recommendations_created} />
      <Metric label="Orders Submitted" value={summary.execution?.orders_submitted} />
      <TextBlock label="No Trade" value={noTrade.conclusion} />
      <View style={styles.buttonGrid}>
        <Button label="Open Activity" onPress={onOpenActivity} />
      </View>
    </Section>
  );
}

function AutonomousActivity({ activity, period, setPeriod, onRefresh }) {
  const [filterCategory, setFilterCategory] = useState('All');
  const [attentionOnly, setAttentionOnly] = useState(false);
  const status = activity?.status || {};
  const noTrade = activity?.why_no_trade || {};
  const items = activity?.timeline?.items || [];
  const decisionCounts = activity?.summary?.decisions || {};
  const hasDecisionCounts = Object.values(decisionCounts).some((value) => Number(value) > 0);

  // Groups derived from raw timeline items (worker jobs, research runs, trades, learning
  // runs). Governance decision counts have no per-decision timeline entry in the current
  // evidence model (only an aggregate), so a single synthesized summary event represents them
  // in the Decisions bucket instead of leaving it silently empty when decisions did happen.
  let groups = groupActivity(items);
  if (hasDecisionCounts) {
    groups = groups.map((group) => {
      if (group.category !== 'Decisions') return group;
      const summaryLine = Object.entries(decisionCounts)
        .filter(([, value]) => Number(value) > 0)
        .map(([key, value]) => `${key.replaceAll('_', ' ')}: ${value}`)
        .join(', ');
      const syntheticEvent = {
        what: 'Governance decisions this period',
        why: 'Governance decisions are the final gate before any capital is committed.',
        outcome: summaryLine,
        actionRequired: false,
        count: 1,
        latestAt: activity?.generated_at || null,
        broker: null,
        symbol: null,
      };
      return { ...group, totalCount: group.totalCount + 1, events: [syntheticEvent, ...group.events] };
    });
  }

  const visibleGroups = groups.filter((group) => filterCategory === 'All' || group.category === filterCategory);
  const anyRequiresAttention = groups.some((group) => group.requiresAttention);

  return (
    <View>
      <View style={styles.summaryCard}>
        <StatusPill label={status.state || 'Status Unknown'} tone={activityStatusTone(status.state)} />
        <Text style={styles.summaryReason}>{status.plain_english || 'No autonomous status evidence was returned.'}</Text>
        <Metric label="Last Refreshed" value={formatDateTime(activity?.generated_at)} />
        {anyRequiresAttention ? <StatusPill label="Some categories require attention" tone="warn" /> : null}
        <View style={styles.buttonGrid}>
          {[
            ['1h', 'Last Hour'],
            ['24h', 'Last 24 Hours'],
            ['7d', 'Last 7 Days'],
            ['30d', 'Last 30 Days'],
          ].map(([key, label]) => (
            <Button key={key} label={label} tone={period === key ? 'primary' : 'neutral'} onPress={() => setPeriod(key)} />
          ))}
          <Button label="Refresh" tone="neutral" onPress={onRefresh} />
        </View>
      </View>

      <Section title="Filter">
        <View style={styles.buttonGrid}>
          {['All', ...groups.map((group) => group.category)].map((item) => (
            <Button key={item} label={item} tone={filterCategory === item ? 'primary' : 'neutral'} onPress={() => setFilterCategory(item)} />
          ))}
        </View>
        <View style={styles.buttonGrid}>
          <Button
            label={attentionOnly ? 'Showing: Requires Attention Only' : 'Show: Everything'}
            tone={attentionOnly ? 'warn' : 'neutral'}
            onPress={() => setAttentionOnly((value) => !value)}
          />
        </View>
      </Section>

      {visibleGroups.map((group) => {
        const events = attentionOnly ? group.events.filter((event) => event.actionRequired) : group.events;
        return (
          <CollapsibleSection
            key={group.category}
            title={group.category}
            subtitle={`${group.totalCount} event(s) in this period`}
            defaultExpanded={group.requiresAttention}
            badge={{
              label: group.requiresAttention ? 'Requires Attention' : (group.totalCount ? 'Normal' : 'No Activity'),
              tone: group.requiresAttention ? 'warn' : (group.totalCount ? 'good' : 'neutral'),
            }}
          >
            {events.length === 0 ? (
              <Empty />
            ) : events.map((event, index) => (
              <View key={`${group.category}-${index}`} style={styles.compactRow}>
                <Text style={styles.cardTitle}>{event.what}{event.count > 1 ? ` (x${event.count})` : ''}</Text>
                <Text style={styles.smallText}>Latest: {formatDateTime(event.latestAt)}</Text>
                <Text style={styles.bodyText}>{event.why}</Text>
                <Metric label="Outcome" value={event.outcome} />
                <Metric label="Founder Action Required" value={event.actionRequired ? 'Yes' : 'No'} />
                {event.broker ? <Metric label="Related Broker" value={event.broker} /> : null}
                {event.symbol ? <Metric label="Related Symbol" value={event.symbol} /> : null}
              </View>
            ))}
          </CollapsibleSection>
        );
      })}

      <CollapsibleSection title="Why No Trade?" subtitle="Aggregate reasons recommendations did not execute in this period.">
        <StatusPill label={noTrade.state || 'unknown'} tone={noTradeTone(noTrade.state)} />
        <Text style={styles.bodyText}>{noTrade.conclusion || 'No no-trade funnel evidence has been returned yet.'}</Text>
        {Object.entries(noTrade.counts || {}).map(([key, value]) => (
          <Metric key={key} label={key.replaceAll('_', ' ')} value={value} />
        ))}
        <TextBlock label="Top Reasons" value={(noTrade.top_reasons || []).map((item) => `${item.reason}: ${item.count}`).join('\n') || 'No rejection reasons recorded in this period.'} />
      </CollapsibleSection>

      <CollapsibleSection title="Technical Details" subtitle="Every raw, unfiltered evidence row behind the summaries above. All underlying audit data is retained regardless of what this screen groups or collapses.">
        {items.length === 0 ? (
          <Empty />
        ) : items.map((item) => (
          <View key={item.activity_id} style={styles.compactRow}>
            <Text style={styles.cardTitle}>{item.title}</Text>
            <Text style={styles.smallText}>{formatDateTime(item.timestamp)} - {item.component}</Text>
            <Text style={styles.bodyText}>{item.summary}</Text>
            <StatusPill label={`${item.severity} - ${item.outcome}`} tone={activitySeverityTone(item.severity)} />
            {item.broker ? <Metric label="Broker" value={item.broker} /> : null}
            {item.symbol ? <Metric label="Symbol" value={item.symbol} /> : null}
          </View>
        ))}
        <Text style={styles.smallText}>{items.length} raw event(s) retained for this period.</Text>
      </CollapsibleSection>
    </View>
  );
}

function ReportPanel({ report }) {
  return (
    <View style={styles.compactRow}>
      <Text style={styles.cardTitle}>{notAvailable(report.report_type).toUpperCase()} report - {notAvailable(report.broker)} - {notAvailable(report.date)}</Text>
      <Text style={styles.bodyText}>{notAvailable(report.summary)}</Text>
      {report.report_url ? (
        <View style={styles.buttonGrid}>
          <Button label="Open Report" onPress={() => Linking.openURL(absoluteApiUrl(report.report_url))} />
        </View>
      ) : null}
      <TextBlock label="Report" value={report.report_markdown} />
      {report.path ? <Text style={styles.smallText}>Saved: {report.path}</Text> : null}
    </View>
  );
}

function TradingPermissions({ permissions }) {
  if (!permissions) {
    return null;
  }
  return (
    <View style={styles.textBlock}>
      <Text style={styles.cardTitle}>Trading Permissions & Seatbelts</Text>
      <Metric label="Trading Status" value={permissions.status} />
      <Metric label="Auto Trading" value={enabledDisabled(permissions.auto_trading_enabled)} />
      <Metric label="Broker Trading Enabled" value={yesNo(permissions.trading_enabled)} />
      <Metric label="Live Trading Approved" value={yesNo(permissions.live_trading_approved)} />
      <Metric label="Submit Real Orders" value={yesNo(permissions.submit_real_orders)} />
      <Metric label="Can Submit Real Orders Now" value={yesNo(permissions.can_submit_real_orders)} />
      {permissions.paper_only !== undefined ? <Metric label="Paper Only" value={yesNo(permissions.paper_only)} /> : null}
      {permissions.trading_allocation_gbp !== undefined ? <Metric label="Trading Allocation" value={gbpOrText(permissions.trading_allocation_gbp)} /> : null}
      {permissions.max_order_gbp !== undefined ? <Metric label="Max Order" value={gbpOrText(permissions.max_order_gbp)} /> : null}
      {permissions.min_order_gbp !== undefined ? <Metric label="Min Order" value={gbpOrText(permissions.min_order_gbp)} /> : null}
      {permissions.max_open_trades !== undefined ? <Metric label="Max Open Trades" value={permissions.max_open_trades} /> : null}
      {permissions.ai_managed_open_trades !== undefined ? <Metric label="AI-Managed Open Trades" value={permissions.ai_managed_open_trades} /> : null}
      {permissions.remaining_ai_trade_slots !== undefined ? <Metric label="Remaining AI Trade Slots" value={permissions.remaining_ai_trade_slots} /> : null}
      {permissions.buy_only_entries !== undefined ? <Metric label="Buy-only Entries" value={enabledDisabled(permissions.buy_only_entries)} /> : null}
      <Metric label="Allowed Pairs / Symbols" value={formatListInline(permissions.allowed_pairs)} />
      {permissions.broker === 'kraken' ? (
        <View style={styles.textBlock}>
          <Text style={styles.cardTitle}>Kraken Reconciliation & £100 Ledger</Text>
          <Metric label="New Entries Paused" value={yesNo(permissions.reconciliation_hold_active)} />
          <Metric label="Reconciliation Status" value={permissions.reconciliation_status} />
          <TextBlock label="Hold Reason" value={permissions.reconciliation_hold_reason} />
          <Metric label="Founder Allocation" value={gbpOrText(permissions.ai_capital_ledger?.allocation_gbp)} />
          <Metric label="Available AI Cash" value={gbpOrText(permissions.ai_capital_ledger?.available_cash_gbp)} />
          <Metric label="AI Capital Deployed" value={gbpOrText(permissions.ai_capital_ledger?.deployed_capital_gbp)} />
          <Metric label="Realised Gross P&L" value={gbpOrText(permissions.ai_capital_ledger?.realized_gross_pnl_gbp)} />
          <Metric label="Realised Net P&L" value={gbpOrText(permissions.ai_capital_ledger?.realized_net_pnl_gbp)} />
          <Metric
            label="Unrealised P&L"
            value={
              permissions.ai_capital_ledger?.unrealized_pnl_gbp === null
                ? permissions.ai_capital_ledger?.unrealized_pnl_status
                : gbpOrText(permissions.ai_capital_ledger?.unrealized_pnl_gbp)
            }
          />
          <Metric label="Personal Holdings Included" value={yesNo(permissions.ai_capital_ledger?.personal_holdings_included)} />
        </View>
      ) : null}
      {permissions.notes?.length ? <TextBlock label="Notes" value={permissions.notes.map((item) => `- ${item}`).join('\n')} /> : null}
    </View>
  );
}

function TradeHistoryRow({ item, onCommand }) {
  const [open, setOpen] = useState(false);
  return (
    <View style={styles.compactRow}>
      <TouchableOpacity onPress={() => setOpen((value) => !value)}>
        <Text style={styles.cardTitle}>{open ? 'v' : '>'} {describeTransaction(item)}</Text>
        <Text style={styles.smallText}>{formatDateTime(normalizeTradeRow(item).eventTime)}</Text>
      </TouchableOpacity>
      {open ? (
        <TradeDetail
          item={item}
          onForceExit={(trade) => onCommand('/force-managed-exit', { managed_exit_id: normalizeTradeRow(trade).managedExitId })}
        />
      ) : null}
    </View>
  );
}

function TradeDetail({ item, onForceExit }) {
  const raw = item.raw || item.payload || {};
  const normalized = normalizeTradeRow(item);
  const tradeMoney = (value) => historyMoneyOrText(normalized.broker, value);
  const isOpen = isOpenTrade(normalized);
  const [showTechnicalData, setShowTechnicalData] = useState(false);
  return (
    <View>
      <Metric label="Broker" value={normalized.broker} />
      <Metric label="Symbol" value={normalized.symbol} />
      <Metric label="Side" value={normalized.side} />
      <Metric label="Status" value={isOpen ? 'Holding / unsold' : (normalized.status || item.event_type)} />
      <Metric label="Quantity" value={normalized.quantity} />
      <Metric label="Entry Price" value={tradeMoney(normalized.entryPrice)} />
      <Metric label="Target Price" value={tradeMoney(normalized.targetPrice) || unavailableReason(normalized, 'target')} />
      <Metric label="Current Live Price" value={tradeMoney(normalized.currentPrice) || unavailableReason(normalized, 'current')} />
      <Metric label="Stop Loss" value={tradeMoney(normalized.stopLoss) || unavailableReason(normalized, 'stop')} />
      <Metric label="Exit Price" value={isOpen ? 'Unsold' : tradeMoney(normalized.exitPrice)} />
      <Metric label="P&L" value={isOpen ? 'Unsold' : tradeMoney(normalized.profitLoss)} />
      <Metric label="Entry Date & Time" value={formatDateTime(normalized.openedAt)} />
      <Metric label="Exit Date & Time" value={isOpen ? 'Unsold' : formatDateTime(normalized.closedAt)} />
      <Metric label="Time Held" value={formatHoldingDuration(normalized.openedAt, normalized.closedAt, isOpen)} />
      <TextBlock label="Entry Reason" value={normalized.entryReason || unavailableReason(normalized, 'entryReason')} />
      <TextBlock label="Exit Reason" value={normalized.exitReason || unavailableReason(normalized, 'exitReason')} />
      <TextBlock label="Learning Factors" value={formatJsonText(item.primary_factors_json || item.primary_factors)} />
      <View style={styles.buttonGrid}>
        <Button
          label={showTechnicalData ? 'Hide Technical Data' : 'Show Technical Data'}
          tone="neutral"
          onPress={() => setShowTechnicalData((value) => !value)}
        />
      </View>
      {showTechnicalData ? <TextBlock label="Technical Broker Data" value={formatJsonText(raw)} /> : null}
      {isOpen && normalized.managedExitId ? (
        <View style={styles.buttonGrid}>
          <Button label="Exit Trade Now" tone="danger" onPress={() => onForceExit?.(item)} />
        </View>
      ) : null}
    </View>
  );
}

function ConnectionReadinessCard({ readiness }) {
  const checks = readiness?.checks || [];
  return (
    <Section title="Connection & Trading Readiness">
      <Metric label="Overall" value={readiness?.trade_ready ? 'Ready - connections visible' : 'Attention needed'} />
      <Text style={styles.smallText}>{notAvailable(readiness?.note)}</Text>
      {!checks.length ? (
        <Empty />
      ) : (
        checks.map((item) => (
          <View key={item.component} style={styles.compactRow}>
            <Metric label={item.component} value={`${item.ready ? 'OK' : 'Check'} - ${notAvailable(item.status)}`} />
            {item.auto_trading_enabled !== undefined ? <Metric label="Auto Trading" value={enabledDisabled(item.auto_trading_enabled)} /> : null}
            {item.block_reason ? <Metric label="Block Reason" value={item.block_reason} /> : null}
            <Text style={styles.smallText}>{notAvailable(item.detail)}</Text>
          </View>
        ))
      )}
    </Section>
  );
}

function localConnectionReadiness(status, brokerPanels) {
  const panels = brokerPanels || [];
  const checks = [
    {
      component: 'Render API',
      status: status ? 'connected' : 'not connected',
      ready: !!status,
      detail: status ? 'The app received a status response from the hosted API.' : 'No hosted API status response is available yet.',
    },
  ];
  panels.forEach((broker) => {
    const connected = String(broker.connection_status || '').toLowerCase() === 'connected';
    checks.push({
      component: broker.label || broker.broker || 'Broker',
      status: broker.connection_status || 'not connected',
      ready: connected,
      auto_trading_enabled: broker.auto_trading_enabled === undefined ? undefined : broker.auto_trading_enabled,
      block_reason: broker.block_reason,
      detail: broker.source || broker.connection_status || 'No broker detail returned.',
    });
  });
  return {
    trade_ready: checks.length > 1 && checks.every((item) => item.ready),
    checks,
    note: 'Local readiness summary. Every trade still requires orchestrator and guardrail validation.',
  };
}

function withMobileTokenReadiness(readiness) {
  const checks = readiness?.checks || [];
  const hasMobileToken = checks.some((item) => item.component === 'Mobile Command Token');
  const mobileTokenCheck = {
    component: 'Mobile Command Token',
    status: API_TOKEN ? 'configured' : 'missing',
    ready: !!API_TOKEN,
    detail: API_TOKEN
      ? `The installed app has a command token loaded (${API_TOKEN_MASK}). It must match AI_TRADER_API_TOKEN in Render.`
      : 'The installed app does not have EXPO_PUBLIC_AI_TRADER_API_TOKEN loaded, so protected hosted API calls will be unauthorized.',
  };
  const nextChecks = hasMobileToken ? checks : [mobileTokenCheck, ...checks];
  return {
    ...(readiness || {}),
    checks: nextChecks,
    trade_ready: !!readiness?.trade_ready && !!API_TOKEN,
  };
}

function Recommendations({ recommendations, trades, amounts, setAmounts, onApprove, onRefresh, onRunAnalysis, onAutoExecute, targetRecommendationId, clearTargetRecommendation }) {
  const [expanded, setExpanded] = useState({});
  const [brokerFilter, setBrokerFilter] = useState('All');
  const [confidenceFilter, setConfidenceFilter] = useState('All');
  const [assetTypeFilter, setAssetTypeFilter] = useState('All');
  const [statusFilter, setStatusFilter] = useState('All');
  useEffect(() => {
    if (targetRecommendationId) {
      setExpanded((prev) => ({ ...prev, [targetRecommendationId]: true }));
      setBrokerFilter('All');
      setConfidenceFilter('All');
      setAssetTypeFilter('All');
      setStatusFilter('All');
      clearTargetRecommendation?.();
    }
  }, [targetRecommendationId, clearTargetRecommendation]);
  if (!recommendations.length) {
    return (
      <Section title="AI Recommendation History">
        <Text style={styles.bodyText}>
          No recommendation history is available yet. Tap Run New Analysis to scan the watchlist. If the AI finds no
          safe trade, the activity history will show that analysis ran but no trade was suggested.
        </Text>
        <View style={styles.buttonGrid}>
          <Button label="Refresh" onPress={onRefresh} tone="neutral" />
          <Button label="Run Kraken Analysis" onPress={() => onRunAnalysis('kraken')} />
          <Button label="Run Stock Analysis" onPress={() => onRunAnalysis('alpaca')} tone="neutral" />
        </View>
      </Section>
    );
  }
  return (
    <View>
      <Section title="AI Recommendation History">
        <Text style={styles.bodyText}>
          Showing the live recommendation and governance record, ordered from highest confidence to lowest. Expired ideas stay visible
          for reference, but execution is blocked until fresh analysis creates a new trade idea.
        </Text>
      </Section>
      <Section title="Filters">
        <View style={styles.buttonGrid}>
          {['All', ...uniqueValues(recommendations.map((item) => item.suggested_broker || item.exchange).filter(Boolean))].map((item) => (
            <Button key={`broker-${item}`} label={item} tone={brokerFilter === item ? 'primary' : 'neutral'} onPress={() => setBrokerFilter(item)} />
          ))}
        </View>
        <View style={styles.buttonGrid}>
          {['All', '85%+', '90%+'].map((item) => (
            <Button key={`confidence-${item}`} label={item} tone={confidenceFilter === item ? 'primary' : 'neutral'} onPress={() => setConfidenceFilter(item)} />
          ))}
        </View>
        <View style={styles.buttonGrid}>
          {['All', ...uniqueValues(recommendations.map((item) => item.asset_type).filter(Boolean))].map((item) => (
            <Button key={`asset-${item}`} label={item} tone={assetTypeFilter === item ? 'primary' : 'neutral'} onPress={() => setAssetTypeFilter(item)} />
          ))}
        </View>
        <View style={styles.buttonGrid}>
          {['All', 'Fresh', 'Stale', 'Expired'].map((item) => (
            <Button key={`status-${item}`} label={item} tone={statusFilter === item ? 'primary' : 'neutral'} onPress={() => setStatusFilter(item)} />
          ))}
        </View>
      </Section>
      <View style={styles.buttonGrid}>
        <Button label="Refresh" onPress={onRefresh} tone="neutral" />
        <Button label="Run Kraken Analysis" onPress={() => onRunAnalysis('kraken')} />
        <Button label="Run Stock Analysis" onPress={() => onRunAnalysis('alpaca')} tone="neutral" />
        <Button label="Auto Execute 85%+" onPress={onAutoExecute} tone="warn" />
      </View>
      {Object.entries(groupRecommendations(filterRecommendations(recommendations, brokerFilter, confidenceFilter, assetTypeFilter, statusFilter))).map(([broker, items]) => (
        <Section key={`group-${broker}`} title={broker}>
          {items.map((item) => {
            const open = !!expanded[item.proposal_id];
            const lifecycle = recommendationLifecycle(item, trades);
            return (
              <View key={item.proposal_id}>
                <TouchableOpacity style={styles.recommendationHeader} onPress={() => setExpanded((prev) => ({ ...prev, [item.proposal_id]: !open }))}>
                  <Text style={styles.cardTitle}>{open ? 'v' : '>'} {notAvailable(item.ticker)} {formatPercent(item.confidence)}</Text>
                  <StatusPill label={lifecycle.stage} tone={lifecycle.tone} />
                  <Text style={styles.smallText}>{lifecycle.reason}</Text>
                </TouchableOpacity>
                {open && (
                  <RecommendationCard
                    item={item}
                    lifecycle={lifecycle}
                    amount={amounts[item.proposal_id] || ''}
                    setAmount={(value) => setAmounts((prev) => ({ ...prev, [item.proposal_id]: value }))}
                    onApprove={() => onApprove(item.proposal_id, item.ticker)}
                  />
                )}
              </View>
            );
          })}
        </Section>
      ))}
    </View>
  );
}

function RecommendationCard({ item, lifecycle, amount, setAmount, onApprove }) {
  const enriched = withRecommendationFreshness(item);
  return (
    <View style={styles.card}>
      <Text style={styles.cardTitle}>{notAvailable(enriched.company)} ({notAvailable(enriched.ticker)})</Text>
      <Section title="Decision Summary">
        <StatusPill label={lifecycle.stage} tone={lifecycle.tone} />
        <Text style={styles.bodyText}>{lifecycle.reason}</Text>
        <Metric label="Action" value={item.side || 'Review'} />
        <Metric label="Broker" value={item.suggested_broker} />
        <Metric label="Generated" value={formatDateTime(enriched.created_at)} />
        <Metric label="Expires" value={formatDateTime(enriched.expires_at)} />
        <Metric label="Selected Strategy" value={item.strategy_name || item.strategy_id} />
        <TextBlock label="One-Sentence Thesis" value={item.reason_for_recommendation} />
      </Section>
      <Section title="Why This Trade">
        <TextBlock label="Strongest Argument For" value={item.strongest_argument_for} />
        <TextBlock label="Strongest Argument Against" value={item.strongest_argument_against} />
      </Section>
      <TextInput
        style={styles.input}
        keyboardType="decimal-pad"
        placeholder="Optional amount note"
        value={amount}
        onChangeText={setAmount}
      />
      <Button
        label={lifecycle.stage === 'Expired' ? 'Expired - Run Analysis' : 'Approve & Execute'}
        onPress={onApprove}
        disabled={lifecycle.stage === 'Expired'}
      />
      <CollapsibleSection title="Full Evidence Dossier" subtitle="Every score, guardrail check, and intelligence field behind the decision above.">
        <TextBlock label="What Would Invalidate It" value={formatList(item.invalidation)} />
        <TextBlock label="Why Waiting May Be Better" value={item.why_no_action_may_be_better} />
        <Metric label="Freshness" value={enriched.freshness_status} />
        <TextBlock label="Freshness Note" value={enriched.freshness_note} />
        <Metric label="Sector" value={item.sector} />
        <Metric label="Country" value={item.country} />
        <Metric label="Asset Availability" value={yesNo(item.asset_available)} />
        <Metric label="Exchange" value={item.exchange} />
        <Metric label="Market Open" value={yesNo(item.market_open)} />
        <Metric label="Market Regime" value={marketRegimeText(item.market_regime)} />
        <Metric label="Probability Range" value={probabilityRange(item.probability_of_success)} />
        <Metric label="Probability Of Success" value={formatPercent(item.probability_of_success)} />
        <Metric label="Expected Return" value={rMultiple(item.expected_return_r)} />
        <Metric label="Calibration" value={item.calibration_status} />
        <TextBlock label="Committee View" value={committeeSummary(item.committee)} />
        <TextBlock label="Signal Evidence" value={signalSummary(item.signals)} />
        <TextBlock label="Lifecycle" value={lifecycleSummary(item.trade_lifecycle)} />
        <Metric label="Confidence" value={formatPercent(item.confidence)} />
        <Metric label="Investment Score" value={formatPercent(item.investment_score?.overall_confidence)} />
        <Metric label="Fundamental Score" value={formatPercent(item.investment_score?.fundamental_score)} />
        <Metric label="Technical Score" value={formatPercent(item.investment_score?.technical_score)} />
        <Metric label="Market Score" value={formatPercent(item.investment_score?.market_score)} />
        <Metric label="Macro Score" value={formatPercent(item.investment_score?.macro_score)} />
        <Metric label="Behavioural Score" value={formatPercent(item.investment_score?.behavioural_score)} />
        <Metric label="Policy Score" value={formatPercent(item.investment_score?.investment_policy_score)} />
        <Metric label="Risk Score" value={formatPercent(item.investment_score?.risk_score)} />
        <Metric label="Investment Philosophy Fit" value={item.investment_philosophy_fit} />
        <TextBlock label="Investment Thesis" value={item.investment_thesis} />
        <TextBlock label="Key Risks" value={item.key_risks} />
        <Metric label="Suggested Stop Loss" value={item.suggested_stop_loss} />
        <Metric label="Suggested Take Profit" value={item.suggested_take_profit} />
        <Metric label="Suggested Position Size" value={item.suggested_position_size} />
        <Metric label="Due Diligence Status" value={item.due_diligence_status} />
        <Metric label="Guardrail Result" value={yesNo(item.guardrails_passed)} />
        <TextBlock label="Passed Guardrails" value={formatGuardrailChecks(enriched.guardrail_checks, 'passed') || formatList(enriched.guardrail_passes)} />
        <TextBlock label="Failed Guardrails" value={formatGuardrailChecks(enriched.guardrail_checks, 'failed') || enriched.guardrail_summary || formatGuardrailFailures(enriched.guardrail_failures)} />
        <TextBlock label="Exit Plan" value={exitPlan(item)} />
        <TextBlock label="Manual Trade Amount" value="For manual approval, the amount box sets the requested trade notional. Guardrails, broker caps, and allocation limits still control execution." />
      </CollapsibleSection>
    </View>
  );
}

function MarketIntelligence({ benchmark, themes, companies, status, recommendations, dailyLearning, onOpenRecommendation }) {
  const marketCentre = status?.founder_experience?.market_intelligence_centre || {};
  const items = benchmark?.items || [];
  return (
    <View>
      <Section title="Market Intelligence Centre">
        <Text style={styles.bodyText}>This screen answers: what kind of market are we in, what matters now, and where should AI Trader focus?</Text>
        <StatusPill label={notAvailable(marketCentre.market_health)} tone={riskTone(marketCentre.market_health)} />
        <Metric label="Current Market Regime" value={marketCentre.current_market_regime} />
        <Metric label="Volatility" value={marketCentre.volatility} />
        <Metric label="Momentum" value={marketCentre.momentum} />
        <Metric label="Market Breadth" value={marketCentre.breadth} />
        <Metric label="Fear / Greed" value={marketCentre.fear_greed} />
        <Metric label="Crypto Health" value={marketCentre.crypto_health} />
        <TextBlock label="Sector Rotation" value={formatList(marketCentre.sector_rotation)} />
        <TextBlock label="Major Themes" value={formatList(marketCentre.major_themes)} />
        <TextBlock label="Important News" value={formatList(marketCentre.important_news)} />
        <TextBlock label="Upcoming Risks" value={formatList(marketCentre.upcoming_risks)} />
        <TextBlock label="Watch List" value={formatList(marketCentre.watch_list)} />
      </Section>
      <Section title="24/7 Research Status">
        <Metric label="Research Status" value={status?.research_status} />
        <Metric label="Last Research Run" value={formatDateTime(status?.last_research_run?.completed_at || status?.last_research_run?.started_at)} />
        <Metric label="Assets Reviewed" value={status?.research_assets_reviewed} />
        <Metric label="Crypto Projects Reviewed" value={status?.crypto_projects_reviewed} />
        <Metric label="Recommendations Created" value={status?.research_recommendations_created} />
        <Metric label="Auto Trading Enabled" value={yesNo(status?.auto_trading_enabled)} />
        <Metric label="Paper/Sandbox Mode" value={yesNo(status?.paper_or_sandbox_mode)} />
        <Metric label="Markets Currently Open" value={marketsOpenText(status)} />
        <Metric label="Next Research Run" value={formatDateTime(status?.next_scheduled_research_run)} />
        <TextBlock label="What AI Learned Since Last Brief" value={latestLearningText(status, benchmark)} />
      </Section>
      <Section title="Daily Trading Learning Update">
        {!dailyLearning ? (
          <Empty />
        ) : (
          <View>
            <Metric label="Learning Date" value={dailyLearning.date} />
            <TextBlock label="Summary" value={dailyLearning.summary} />
            <Metric label="Closed Trades" value={dailyLearning.trade_outcomes?.closed_trades} />
            <Metric label="Win Rate" value={formatPercent(dailyLearning.trade_outcomes?.win_rate)} />
            <Metric label="Total P&L" value={moneyOrText(dailyLearning.trade_outcomes?.total_profit_loss)} />
            <TextBlock label="Trade Lessons" value={formatList(dailyLearning.trade_lessons)} />
            <TextBlock label="Successful Trader / Benchmark Lessons" value={formatList(dailyLearning.benchmark_learning)} />
            <TextBlock label="Recommendations For Founder" value={formatList(dailyLearning.recommendations_for_founder)} />
            <Text style={styles.smallText}>{notAvailable(dailyLearning.note)}</Text>
          </View>
        )}
      </Section>
      <Section title="Alpaca Intelligence">
        <Metric label="Research Running" value={status?.research_status} />
        <Metric label="Due Diligence Running" value={status?.due_diligence_status} />
        <Metric label="Last Update" value={formatDateTime(status?.last_research_run?.completed_at || status?.last_research_run?.started_at)} />
        <Metric label="Next Update" value={formatDateTime(status?.next_scheduled_research_run)} />
        <Metric label="Companies Reviewed" value={status?.last_research_run?.companies_reviewed} />
        <Metric label="Themes" value={themes.length} />
        <Metric label="Benchmark Investors" value={items.length} />
        <TextBlock label="Latest Learnings" value={latestLearningText(status, benchmark)} />
        <Metric label="Research Freshness" value={status?.research_status} />
      </Section>
      <Section title="Kraken Intelligence">
        <Metric label="Research Running" value={status?.research_status} />
        <Metric label="Due Diligence Running" value={status?.due_diligence_status} />
        <Metric label="Last Update" value={formatDateTime(status?.last_research_run?.completed_at || status?.last_research_run?.started_at)} />
        <Metric label="Next Update" value={formatDateTime(status?.next_scheduled_research_run)} />
        <Metric label="Crypto Projects Reviewed" value={status?.crypto_projects_reviewed} />
        <Metric label="Research Freshness" value={status?.research_status} />
        <TextBlock label="Latest Learnings" value="Crypto trading remains disabled until Founder approval and complete project due diligence." />
      </Section>
      <Section title="Daily Benchmark Intelligence Brief">
        <Text style={styles.bodyText}>{notAvailable(benchmark?.summary)}</Text>
      </Section>
      <Section title="Benchmark Traders Monitored Today">
        {!items.length ? (
          <Empty />
        ) : (
          items.map((item, index) => (
            <View key={`${item.trader_name}-${index}`} style={styles.card}>
              <Text style={styles.cardTitle}>{notAvailable(item.trader_name)}</Text>
              <Metric label="Source / Platform" value={item.platform || item.source} />
              <Metric label="Confidence" value={item.confidence} />
              <TextBlock label="Public activity" value={item.observed_trade_or_portfolio_change} />
              <TextBlock label="AI learned" value={item.ai_interpretation} />
              <TextBlock label="Risk lessons" value={item.risk_lesson} />
              <TextBlock label="Market lessons" value={item.market_lesson} />
              <Metric label="Related sector" value={item.related_sector} />
              <Metric label="Related theme" value={item.related_theme} />
            </View>
          ))
        )}
      </Section>
      <Section title="Theme Definitions">
        {!themes.length ? (
          <Empty />
        ) : (
          themes.map((item) => (
            <View key={item.id || item.theme} style={styles.card}>
              <Text style={styles.cardTitle}>{notAvailable(item.theme)}</Text>
              <Metric label="Outlook" value={item.current_outlook} />
              <Metric label="Confidence" value={item.confidence} />
              <TextBlock label="What it means" value={item.summary} />
              <TextBlock label="Key drivers" value={item.key_drivers} />
              <TextBlock label="Key risks" value={item.key_risks} />
              <MonitoredCompaniesLinks
                theme={item}
                companies={companies}
                recommendations={recommendations}
                onOpenRecommendation={onOpenRecommendation}
              />
            </View>
          ))
        )}
      </Section>
      <Section title="Companies Monitored">
        {!companies.length ? (
          <Empty />
        ) : (
          companies.map((item) => (
            <View key={item.id || item.ticker} style={styles.card}>
              <LinkedCompanyTitle company={item} recommendations={recommendations} onOpenRecommendation={onOpenRecommendation} />
              <Metric label="Sector" value={item.sector} />
              <Metric label="Country" value={item.country} />
              <Metric label="Watchlist Priority" value={item.current_watchlist_priority} />
              <Metric label="Investment Fit" value={item.current_investment_philosophy_fit} />
              <TextBlock label="Investment Thesis" value={item.investment_thesis} />
            </View>
          ))
        )}
      </Section>
    </View>
  );
}

function LearningStrategyLab({ status, dailyLearning, messages, setMessages, request }) {
  const lab = status?.founder_experience?.learning_lab || {};
  const strategyRows = lab.strategy_rankings || [];
  const signalRows = lab.signal_rankings || [];
  const summary = dailyLearning?.evidence_summary || {
    completedTradesReviewed: dailyLearning?.trade_outcomes?.closed_trades || 0,
    strategiesEvaluated: 0,
    latestLesson: null,
    hasEnoughEvidence: false,
    missingEvidence: 'Learning evidence has not loaded yet.',
  };
  const hasInstitutionalTestData = Boolean(lab.backtest_results || lab.walk_forward_results || lab.committee_performance);

  return (
    <View>
      <View style={styles.summaryCard}>
        <Text style={styles.summaryReason}>Is AI Trader learning, and what needs Founder approval before behaviour changes?</Text>
        <Metric label="Completed Trades Reviewed" value={summary.completedTradesReviewed} />
        <Metric label="Strategies Evaluated" value={summary.strategiesEvaluated} />
        <Metric label="Latest Lesson" value={summary.latestLesson || 'No lesson recorded yet.'} />
        <Metric label="Latest Strategy-Change Proposal" value={summary.latestProposal || 'Not yet exposed in this evidence projection.'} />
        <Metric label="Proposal Approved" value={summary.proposalApproved === null ? 'Not applicable yet' : yesNo(summary.proposalApproved)} />
        {!summary.hasEnoughEvidence ? (
          <View style={styles.compactRow}>
            <Text style={styles.cardTitle}>Why learning has not progressed further</Text>
            <Text style={styles.bodyText}>{summary.missingEvidence}</Text>
          </View>
        ) : (
          <TextBlock label="Evidence Note" value={summary.missingEvidence} />
        )}
      </View>

      <CollapsibleSection title="Trade Outcomes" subtitle="Closed-trade win rate and realized P&L behind the summary above.">
        <Metric label="Closed Trades" value={dailyLearning?.trade_outcomes?.closed_trades} />
        <Metric label="Win Rate" value={formatPercent(dailyLearning?.trade_outcomes?.win_rate)} />
        <Metric label="Total Realized P&L" value={moneyOrText(dailyLearning?.trade_outcomes?.total_profit_loss)} />
        <TextBlock label="Lessons Learned" value={formatList(dailyLearning?.trade_lessons)} />
        <TextBlock label="Recommendations for Founder" value={formatList(dailyLearning?.recommendations_for_founder)} />
      </CollapsibleSection>

      {(strategyRows.length || signalRows.length || hasInstitutionalTestData) ? (
        <CollapsibleSection title="Strategy and Signal Rankings" subtitle="Institutional-grade backtest and ranking evidence, where available.">
          {strategyRows.map((item, index) => (
            <View key={`${item.strategy_id || item.strategy_name}-${index}`} style={styles.compactRow}>
              <Text style={styles.cardTitle}>{notAvailable(item.strategy_name || item.strategy_id)}</Text>
              <Metric label="Sample Size" value={item.sample_size} />
              <Metric label="Win Rate" value={formatPercent(item.win_rate)} />
              <Metric label="Expectancy" value={item.expectancy_r !== undefined ? `${Number(item.expectancy_r).toFixed(2)}R` : null} />
              <Metric label="Recommendation" value={item.recommendation} />
            </View>
          ))}
          {signalRows.map((item, index) => (
            <View key={`${item.signal_name || item.signal}-${index}`} style={styles.compactRow}>
              <Text style={styles.cardTitle}>{notAvailable(item.signal_name || item.signal)}</Text>
              <Metric label="Score" value={formatPercent(item.score)} />
              <Metric label="Weight" value={formatPercent(item.weight)} />
              <Metric label="Direction" value={item.direction} />
            </View>
          ))}
          {hasInstitutionalTestData ? (
            <>
              <TextBlock label="Backtest Results" value={formatJsonText(lab.backtest_results)} />
              <TextBlock label="Walk-forward Results" value={formatJsonText(lab.walk_forward_results)} />
              <TextBlock label="Committee Performance" value={formatJsonText(lab.committee_performance)} />
            </>
          ) : null}
        </CollapsibleSection>
      ) : null}

      <AskAiTrader messages={messages} setMessages={setMessages} request={request} />
    </View>
  );
}

function AskAiTrader({ messages, setMessages, request }) {
  const [question, setQuestion] = useState('');
  const [askLoading, setAskLoading] = useState(false);
  const [askStatus, setAskStatus] = useState('Ready');
  const ask = async (text) => {
    const finalQuestion = String(text || question || '').trim();
    if (!finalQuestion || askLoading) {
      return;
    }
    setQuestion('');
    setMessages((prev) => [...prev, { role: 'user', text: normalizeChatText(finalQuestion) }]);
    setAskLoading(true);
    setAskStatus('Thinking...');
    const controller = new AbortController();
    const timeoutMs = 25000;
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const result = await withTimeout(
        request('/ask-ai-trader', {
          method: 'POST',
          body: JSON.stringify({ question: finalQuestion }),
          signal: controller.signal,
        }),
        timeoutMs + 2000
      );
      const answerText = normalizeChatText(result.answer);
      const note = result.note ? `\n\n${normalizeChatText(result.note)}` : '';
      setMessages((prev) => [...prev, { role: 'assistant', text: normalizeChatText(`${answerText}${note}`) }]);
      setAskStatus(`Answered using ${result.model || 'local evidence'}.`);
    } catch (error) {
      const message = String(error.message || error);
      const friendly = message.includes('AbortError') || message.includes('aborted') || message.includes('timed out')
        ? 'The Ask request timed out before the backend replied. Render or OpenAI may still be waking up. Try again in a moment, or ask a shorter question.'
        : `I could not answer that yet: ${message}`;
      setMessages((prev) => [...prev, { role: 'assistant', text: normalizeChatText(friendly) }]);
      setAskStatus('Ask failed or timed out.');
    } finally {
      clearTimeout(timeout);
      setAskLoading(false);
    }
  };
  const suggestions = [
    'Am I up or down today, and why?',
    'What open positions do I have?',
    'Which recent trades made or lost money?',
    'What has AI Trader learned today?',
    'Is AI Trader getting better at trading?',
  ];
  return (
    <View>
      <Section title="Ask AI Trader">
        <Text style={styles.bodyText}>
          Ask for a plain-English explanation of AI Trader data. This chat is read-only and cannot place trades, approve trades, enable auto trading, or change guardrails.
        </Text>
        <Metric label="Ask Status" value={askStatus} />
        <View style={styles.buttonGrid}>
          {suggestions.map((item) => (
            <Button key={item} label={item} tone="neutral" onPress={() => ask(item)} disabled={askLoading} />
          ))}
        </View>
        <TextInput
          style={[styles.input, styles.multilineInput]}
          multiline
          placeholder="Ask AI Trader a question..."
          value={question}
          onChangeText={setQuestion}
        />
        <Button label={askLoading ? 'Thinking...' : 'Ask'} onPress={() => ask()} disabled={askLoading || !question.trim()} />
      </Section>
      <Section title="Conversation">
        {messages.length ? (
          chatTurnsNewestFirst(messages).map((turn, turnIndex) => (
            <View key={`turn-${turnIndex}`} style={styles.chatTurn}>
              {turn.map((item, messageIndex) => (
                <View key={`${item.role}-${turnIndex}-${messageIndex}`} style={[styles.chatBubble, item.role === 'user' ? styles.chatUser : styles.chatAssistant]}>
                  <Text style={styles.metricLabel}>{item.role === 'user' ? 'You' : 'AI Trader'}</Text>
                  <Text style={styles.bodyText} selectable>{chatMessageText(item.text)}</Text>
                </View>
              ))}
            </View>
          ))
        ) : (
          <Text style={styles.bodyText}>Ask me about balances, open positions, trades, reports, recommendations, or what AI Trader learned.</Text>
        )}
      </Section>
    </View>
  );
}

function MonitoredCompaniesLinks({ theme, companies, recommendations, onOpenRecommendation }) {
  const matches = companiesForThemeList(theme, companies);
  if (!matches.length) {
    return <TextBlock label="Monitored companies" value={null} />;
  }
  return (
    <View style={styles.textBlock}>
      <Text style={styles.metricLabel}>Monitored companies</Text>
      {matches.map((company) => {
        const recommendation = findRecommendationForCompany(company, recommendations);
        if (!recommendation) {
          return (
            <Text key={`${company.ticker}-plain`} style={styles.bodyText}>
              - {company.company_name} ({company.ticker})
            </Text>
          );
        }
        return (
          <TouchableOpacity key={`${company.ticker}-link`} onPress={() => onOpenRecommendation?.(recommendation.proposal_id)}>
            <Text style={styles.linkText}>- {company.company_name} ({company.ticker})</Text>
          </TouchableOpacity>
        );
      })}
    </View>
  );
}

function LinkedCompanyTitle({ company, recommendations, onOpenRecommendation }) {
  const recommendation = findRecommendationForCompany(company, recommendations);
  const text = `${notAvailable(company.company_name)} (${notAvailable(company.ticker)})`;
  if (!recommendation) {
    return <Text style={styles.cardTitle}>{text}</Text>;
  }
  return (
    <TouchableOpacity onPress={() => onOpenRecommendation?.(recommendation.proposal_id)}>
      <Text style={[styles.cardTitle, styles.linkText]}>{text}</Text>
    </TouchableOpacity>
  );
}

function riskTone(value) {
  const text = String(value || '').toLowerCase();
  if (text.includes('high') || text.includes('poor') || text.includes('weak') || text.includes('attention') || text.includes('risk')) {
    return 'danger';
  }
  if (text.includes('medium') || text.includes('mixed') || text.includes('developing') || text.includes('caution')) {
    return 'warn';
  }
  if (text.includes('healthy') || text.includes('good') || text.includes('ready') || text.includes('low')) {
    return 'good';
  }
  return 'neutral';
}

function formatKrakenAssets(items, converted) {
  if (!items || !items.length) {
    return converted ? 'No priced crypto assets converted.' : 'No excluded assets reported.';
  }
  return items.map((item) => {
    if (converted) {
      return `- ${item.normalized_asset || item.asset}: ${item.quantity} via ${item.pair}, value ${gbpOrText(item.value_gbp)}`;
    }
    return `- ${item.normalized_asset || item.asset}: ${item.quantity}, reason ${item.reason || 'not valued'}`;
  }).join('\n');
}

function formatRawKrakenBalances(items) {
  if (!items || !items.length) {
    return 'No non-zero Kraken balances were returned by the API.';
  }
  return items.map((item) => `- ${item.normalized_asset || item.asset}: ${item.quantity} (${item.asset})`).join('\n');
}

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

function selectedBrokerKey(selectedExchange) {
  if (!selectedExchange || selectedExchange === 'All') {
    return 'all';
  }
  return String(selectedExchange).toLowerCase();
}

function withTimeout(promise, timeoutMs) {
  let timeoutId;
  const timeoutPromise = new Promise((_, reject) => {
    timeoutId = setTimeout(() => reject(new Error(`Request timed out after ${Math.round(timeoutMs / 1000)} seconds.`)), timeoutMs);
  });
  return Promise.race([promise, timeoutPromise]).finally(() => clearTimeout(timeoutId));
}

function normalizeChatText(value) {
  if (value === null || value === undefined) {
    return '';
  }
  const text = typeof value === 'string' ? value : JSON.stringify(value, null, 2);
  return text
    .replace(/\r\n/g, '\n')
    .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g, '')
    .replace(/\n{4,}/g, '\n\n\n')
    .trim();
}

function chatMessageText(value) {
  const text = normalizeChatText(value);
  return text || 'No message text was returned. Try asking again, or check Render logs for the /ask-ai-trader response.';
}

function chatTurnsNewestFirst(messages) {
  const turns = [];
  let current = [];
  (messages || []).forEach((message) => {
    if (message.role === 'user' && current.length) {
      turns.push(current);
      current = [];
    }
    current.push(message);
  });
  if (current.length) {
    turns.push(current);
  }
  return turns.reverse();
}

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

function combinedTransactions(status, portfolio, selectedExchange = 'All', performanceAttribution = [], limit = 20) {
  const selected = brokerKey(selectedExchange);
  const attribution = (performanceAttribution || [])
    .filter((item) => selected === 'all' || brokerKey(item.broker) === selected)
    .map((item) => ({
      ...item,
      event_type: 'performance_attribution',
      status: 'closed',
      created_at: item.closed_at || item.created_at,
      raw: parseMaybeJson(item.primary_factors_json),
    }));
  const brokerTrades = (status?.brokers || [])
    .filter((panel) => selected === 'all' || brokerKey(panel.broker || panel.label) === selected)
    .flatMap((panel) => (panel.trade_history || []).map((item) => ({
      ...item,
      broker: item.broker || panel.broker,
      event_type: 'broker_trade',
      created_at: item.closed_at || item.opened_at || item.updated_at,
      raw: parseMaybeJson(item.payload_json) || item,
    })));
  const managedExits = (status?.brokers || [])
    .filter((panel) => selected === 'all' || brokerKey(panel.broker || panel.label) === selected)
    .flatMap((panel) => (panel.managed_exits || []).map((item) => ({
      ...item,
      broker: item.broker || panel.broker,
      event_type: 'managed_open_trade',
      status: item.status || 'open',
      created_at: item.created_at || item.updated_at,
      raw: parseMaybeJson(item.payload_json) || item,
    })));
  const auditRows = (status?.recent_transactions || []).filter((item) => (
    item.event_type === 'execution_approved' || item.event_type === 'execution_rejected'
  ) && (selected === 'all' || brokerKey(item.broker) === selected));
  const fills = (portfolio?.recent_activities || []).map((item) => ({
    event_type: 'broker_fill',
    broker: 'alpaca',
    symbol: item.symbol,
    side: item.side,
    position_size: item.qty,
    price: item.price,
    created_at: item.transaction_time || item.date || item.updated_at,
    raw: item,
  }));
  const orders = (portfolio?.recent_orders || []).map((item) => ({
    event_type: 'broker_order',
    broker: 'alpaca',
    symbol: item.symbol,
    side: item.side,
    position_size: item.qty,
    status: item.status,
    created_at: item.submitted_at || item.updated_at || item.created_at,
    raw: item,
  }));
  const alpacaRows = selected === 'all' || selected === 'alpaca' ? [...fills, ...orders] : [];
  return [...managedExits, ...attribution, ...brokerTrades, ...auditRows, ...alpacaRows]
    .filter((item) => item.created_at || item.symbol || item.event_type)
    .sort((a, b) => dateMs(normalizeTradeRow(b).eventTime) - dateMs(normalizeTradeRow(a).eventTime))
    .slice(0, limit);
}

function describeLatestTrade(value) {
  if (!value || typeof value === 'string') {
    return value;
  }
  return describeTransaction({
    event_type: value.type === 'fill' ? 'broker_fill' : 'broker_order',
    symbol: value.symbol,
    side: value.side,
    position_size: value.qty,
    price: value.price,
    status: value.status,
  });
}

function withRecommendationFreshness(item) {
  if (item.freshness_status && item.expires_at) {
    return item;
  }
  const generatedAt = item.created_at ? new Date(item.created_at) : null;
  if (!generatedAt || Number.isNaN(generatedAt.getTime())) {
    return {
      ...item,
      freshness_status: item.freshness_status || null,
      freshness_note: item.freshness_note || null,
      auto_trade_eligible: item.auto_trade_eligible,
    };
  }
  const confidence = Number(item.confidence || 0);
  const lifetimeHours = confidence >= 0.85 ? 4 : confidence >= 0.75 ? 12 : 24;
  const expiresAt = new Date(generatedAt.getTime() + lifetimeHours * 60 * 60 * 1000);
  const now = new Date();
  const halfLife = new Date(generatedAt.getTime() + (lifetimeHours / 2) * 60 * 60 * 1000);
  const freshness = now > expiresAt ? 'Expired' : now > halfLife ? 'Stale' : 'Fresh';
  return {
    ...item,
    expires_at: item.expires_at || expiresAt.toISOString(),
    freshness_status: item.freshness_status || freshness,
    freshness_note: item.freshness_note || `${freshness}. This trade idea expires after ${lifetimeHours} hours.`,
    auto_trade_eligible:
      item.auto_trade_eligible ?? (
        freshness !== 'Expired'
        && confidence >= 0.85
        && item.guardrails_passed !== false
        && item.already_executed !== true
      ),
    auto_trade_reason: item.auto_trade_reason || clientAutoTradeReason(item, confidence, freshness),
    guardrail_summary: item.guardrail_summary || formatGuardrailFailures(item.guardrail_failures),
  };
}

function clientAutoTradeReason(item, confidence, freshness) {
  if (item.already_executed) {
    return 'Already executed.';
  }
  if (freshness === 'Expired') {
    return 'Expired. Run new analysis before execution.';
  }
  if (confidence < 0.85) {
    return 'Confidence is below 85%.';
  }
  if (item.guardrails_passed === false) {
    const guardrails = formatGuardrailFailures(item.guardrail_failures);
    if (guardrails) {
      return `Execution guardrails failed: ${guardrails}.`;
    }
    return 'Execution guardrails did not pass, so auto-trade is blocked.';
  }
  return 'Eligible for paper auto-trade.';
}

function formatGuardrailChecks(checks, status) {
  if (!checks || !checks.length) {
    return null;
  }
  const matching = checks.filter((item) => item.status === status);
  if (!matching.length) {
    return status === 'failed' ? 'None' : null;
  }
  return matching.map((item) => `- ${item.label || String(item.key).replaceAll('_', ' ')}`).join('\n');
}

function marketRegimeText(regime) {
  if (!regime) {
    return null;
  }
  const primary = regime.primary_regime || 'unknown';
  const trend = regime.trend_regime || 'unknown trend';
  const risk = regime.risk_regime || 'neutral';
  return `${primary}; ${trend}; ${risk}`;
}

function rMultiple(value) {
  if (value === null || value === undefined || value === '') {
    return null;
  }
  const number = Number(value);
  if (Number.isNaN(number)) {
    return String(value);
  }
  return `${number.toFixed(2)}R`;
}

function committeeSummary(committee) {
  if (!committee) {
    return null;
  }
  const result = committee.committee_result ? `Result: ${committee.committee_result}` : null;
  const votes = Array.isArray(committee.member_votes) ? committee.member_votes : [];
  const voteText = votes
    .slice(0, 6)
    .map((vote) => `${vote.member}: ${vote.vote} (${formatPercent(vote.score)})`)
    .join('\n');
  return [result, voteText].filter(Boolean).join('\n');
}

function signalSummary(signals) {
  if (!Array.isArray(signals) || !signals.length) {
    return null;
  }
  return signals
    .slice(0, 6)
    .map((signal) => `${signal.signal_name}: ${formatPercent(signal.score)} weight ${formatPercent(signal.weight)}`)
    .join('\n');
}

function lifecycleSummary(stages) {
  if (!Array.isArray(stages) || !stages.length) {
    return null;
  }
  return stages
    .slice(-5)
    .map((stage) => `${formatDateTime(stage.created_at)} - ${stage.stage}: ${stage.stage_reason}`)
    .join('\n');
}

function describeDecision(decision) {
  if (!decision) {
    return null;
  }
  return `${notAvailable(decision.symbol)} ${notAvailable(decision.decision)}${decision.rejection_reason ? `: ${decision.rejection_reason}` : ''}`;
}

function marketsOpenText(status) {
  const decision = status?.last_orchestrator_decision;
  if (!decision) {
    return 'Not available';
  }
  return decision.market_open ? `${decision.exchange || 'Market'} open` : `${decision.exchange || 'Market'} closed`;
}

function latestLearningText(status, benchmark) {
  const observed = benchmark?.items?.[0]?.ai_interpretation;
  const decision = status?.last_orchestrator_decision;
  if (observed && decision) {
    return `${observed}\nLast orchestrator decision: ${describeDecision(decision)}`;
  }
  return observed || describeDecision(decision);
}

function companiesForThemeList(theme, companies) {
  if (!companies || !companies.length) {
    return [];
  }
  const themeText = `${theme.theme || ''} ${theme.summary || ''} ${theme.key_drivers || ''}`.toLowerCase();
  const matches = companies.filter((company) => {
    const sector = String(company.sector || '').toLowerCase();
    const name = String(company.company_name || '').toLowerCase();
    return themeText.includes(sector) || sector.includes(String(theme.theme || '').toLowerCase()) || themeText.includes(name);
  });
  return matches.slice(0, 8);
}

function findRecommendationForCompany(company, recommendations) {
  const ticker = String(company?.ticker || '').toUpperCase();
  if (!ticker || !recommendations?.length) {
    return null;
  }
  return recommendations.find((item) => String(item.ticker || '').toUpperCase() === ticker) || null;
}

function uniqueValues(items) {
  return [...new Set(items.map((item) => String(item)).filter(Boolean))];
}

function tradeKey(item, index) {
  return String(item.attribution_id || item.trade_history_id || item.external_id || item.proposal_id || `${item.created_at}-${item.symbol}-${index}`);
}

function parseMaybeJson(value) {
  if (!value) {
    return null;
  }
  if (typeof value === 'object') {
    return value;
  }
  try {
    return JSON.parse(String(value));
  } catch (error) {
    return null;
  }
}

function formatJsonText(value) {
  const parsed = parseMaybeJson(value);
  if (!parsed) {
    return typeof value === 'string' ? value : null;
  }
  return JSON.stringify(parsed, null, 2);
}

function groupRecommendations(items) {
  return items.reduce((groups, item) => {
    const broker = item.suggested_broker || item.exchange || 'Unassigned';
    if (!groups[broker]) {
      groups[broker] = [];
    }
    groups[broker].push(item);
    groups[broker].sort((a, b) => (Number(b.confidence || 0) - Number(a.confidence || 0)));
    return groups;
  }, {});
}

function filterRecommendations(items, brokerFilter, confidenceFilter, assetTypeFilter, statusFilter) {
  return items.filter((item) => {
    const broker = item.suggested_broker || item.exchange || 'Unassigned';
    if (brokerFilter !== 'All' && broker !== brokerFilter) {
      return false;
    }
    if (assetTypeFilter !== 'All' && item.asset_type !== assetTypeFilter) {
      return false;
    }
    if (statusFilter !== 'All' && item.freshness_status !== statusFilter) {
      return false;
    }
    const confidence = Number(item.confidence || 0);
    if (confidenceFilter === '85%+' && confidence < 0.85) {
      return false;
    }
    if (confidenceFilter === '90%+' && confidence < 0.9) {
      return false;
    }
    return true;
  });
}

function exitPlan(item) {
  const stop = notAvailable(item.suggested_stop_loss);
  const take = notAvailable(item.suggested_take_profit);
  return `If executed, the broker order is submitted as a bracket order with stop loss ${stop} and take profit ${take}.`;
}

function friendlyEvent(eventType) {
  const labels = {
    agent_proposal: 'AI suggested a trade',
    execution_approved: 'Trade placed',
    execution_rejected: 'Trade rejected',
    agent_no_trade: 'No trade suggested',
    analysis_completed: 'Analysis completed',
    engine_control: 'Trading control changed',
    broker_fill: 'Broker fill',
    broker_order: 'Broker order',
    broker_trade: 'Broker trade',
    managed_open_trade: 'AI-managed open trade',
    performance_attribution: 'Closed trade',
  };
  return labels[eventType] || notAvailable(eventType);
}

function tradeHistoryBrokers(status) {
  const names = (status?.brokers || [])
    .map((broker) => broker.label || broker.broker)
    .filter(Boolean);
  return ['All', ...Array.from(new Set(names.map((item) => titleCaseBroker(item))))];
}

function titleCaseBroker(value) {
  const text = String(value || '').replaceAll('_', ' ');
  if (!text) {
    return 'Unknown';
  }
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function tradeHistorySummary(status, trades, selectedExchange) {
  const selected = brokerKey(selectedExchange);
  const brokerPanels = (status?.brokers || []).filter((broker) => (
    selected === 'all' || brokerKey(broker.broker || broker.label) === selected
  ));
  const normalized = (trades || []).map(normalizeTradeRow);
  const todaysClosed = normalized.filter((item) => isToday(item.closedAt || item.eventTime) && terminalTradeStatus(item.status) && !isOpenTrade(item));
  const realisedPnl = todaysClosed
    .map((item) => numeric(item.profitLoss))
    .filter((value) => value !== null)
    .reduce((sum, value) => sum + value, 0);
  const brokerDayPnl = brokerPanels
    .map((broker) => numeric(broker.todays_pnl))
    .filter((value) => value !== null)
    .reduce((sum, value) => sum + value, 0);
  const openPositions = brokerPanels
    .map((broker) => Number(broker.open_positions || 0))
    .filter(Number.isFinite)
    .reduce((sum, value) => sum + value, 0);
  return {
    dailyPnl: todaysClosed.some((item) => numeric(item.profitLoss) !== null) ? realisedPnl : brokerDayPnl,
    completedTradesToday: todaysClosed.length,
    openPositions,
  };
}

function normalizeTradeRow(item) {
  const raw = item?.raw || item?.payload || parseMaybeJson(item?.payload_json) || {};
  const descr = raw.descr || {};
  const side = firstValue(item?.side, raw.side, raw.order_side, raw.type, descr.type);
  const status = firstValue(item?.status, raw.status, raw.order_status);
  const price = firstNumber(
    item?.price,
    raw.price,
    raw.price2,
    raw.execution_price,
    raw.average_price,
    raw.filled_avg_price,
    raw.avg_price
  );
  const entryPrice = firstNumber(item?.entry_price, item?.entry, raw.entry_price, raw.entryPrice, isBuy(side) ? price : null);
  const exitPrice = firstNumber(item?.exit_price, item?.exit, raw.exit_price, raw.exitPrice, isSell(side) ? price : null);
  const openedAt = firstValue(item?.opened_at, item?.entry_time, raw.opened_at, raw.opentm, raw.entry_time, raw.submitted_at, raw.time);
  const closedAt = firstValue(item?.closed_at, item?.exit_time, raw.closed_at, raw.closetm, raw.exit_time);
  const eventTime = firstValue(item?.created_at, item?.updated_at, item?.closed_at, item?.opened_at, raw.transaction_time, raw.time, raw.date, raw.created_at, raw.updated_at);
  return {
    managedExitId: firstNumber(item?.managed_exit_id, raw.managed_exit_id),
    broker: titleCaseBroker(firstValue(item?.broker, raw.broker)),
    symbol: firstValue(item?.symbol, raw.symbol, raw.pair, raw.asset_pair, raw.instrument, descr.pair),
    side,
    status,
    quantity: firstNumber(item?.position_size, item?.quantity, item?.qty, raw.quantity, raw.qty, raw.vol_exec, raw.vol, raw.volume),
    price,
    entryPrice,
    exitPrice,
    targetPrice: firstNumber(item?.take_profit, item?.target_price, raw.take_profit, raw.target_price),
    stopLoss: firstNumber(item?.stop_loss, raw.stop_loss),
    currentPrice: firstNumber(item?.current_price, raw.current_price, raw.last_price),
    profitLoss: firstNumber(item?.profit_loss, item?.pnl, item?.realized_pnl, raw.profit_loss, raw.pnl, raw.realized_pnl),
    openedAt,
    closedAt,
    eventTime,
    entryReason: firstValue(item?.entry_reason, item?.ai_reasoning, raw.entry_reason, raw.reasoning),
    exitReason: firstValue(item?.exit_reason, item?.lessons_learned, raw.exit_reason, raw.reason),
  };
}

function isOpenTrade(item) {
  const status = String(item?.status || '').toLowerCase();
  if (status === 'open') {
    return true;
  }
  if (item?.managedExitId && !item?.closedAt) {
    return true;
  }
  if (isBuy(item?.side) && status === 'filled' && !item?.closedAt && !item?.exitPrice) {
    return true;
  }
  if (isBuy(item?.side) && status === 'closed' && !item?.exitPrice) {
    return true;
  }
  return false;
}

function unavailableReason(item, field) {
  if (item?.managedExitId) {
    return 'Not recorded yet';
  }
  if (field === 'target' || field === 'stop') {
    return 'Only available for AI-managed trades';
  }
  if (field === 'current') {
    return 'Live price not returned by broker yet';
  }
  if (field === 'entryReason') {
    return 'Raw broker row - AI reason is stored only on linked AI-managed trades';
  }
  if (field === 'exitReason') {
    return isOpenTrade(item) ? 'Unsold' : 'No exit reason recorded by broker';
  }
  return 'Not recorded';
}

function firstValue(...values) {
  return values.find((value) => value !== null && value !== undefined && value !== '');
}

function firstNumber(...values) {
  for (const value of values) {
    const parsed = numeric(value);
    if (parsed !== null) {
      return parsed;
    }
  }
  return null;
}

function numeric(value) {
  if (value === null || value === undefined || value === '') {
    return null;
  }
  const number = Number(String(value).replace(/[,$£]/g, ''));
  return Number.isFinite(number) ? number : null;
}

function isBuy(side) {
  return String(side || '').toLowerCase() === 'buy';
}

function isSell(side) {
  return String(side || '').toLowerCase() === 'sell';
}

function terminalTradeStatus(status) {
  const text = String(status || '').toLowerCase();
  return ['closed', 'sold', 'cancelled', 'canceled'].includes(text);
}

function isToday(value) {
  const date = new Date(value || '');
  if (Number.isNaN(date.getTime())) {
    return false;
  }
  const today = new Date();
  return date.getFullYear() === today.getFullYear()
    && date.getMonth() === today.getMonth()
    && date.getDate() === today.getDate();
}

function formatDuration(start, end) {
  const startMs = dateMs(start);
  const endMs = dateMs(end);
  if (!startMs || !endMs || endMs < startMs) {
    return null;
  }
  const minutes = Math.round((endMs - startMs) / 60000);
  if (minutes < 60) {
    return `${minutes} min`;
  }
  const hours = minutes / 60;
  if (hours < 48) {
    return `${hours.toFixed(1)} hours`;
  }
  return `${(hours / 24).toFixed(1)} days`;
}

function formatHoldingDuration(start, end, isOpen) {
  if (isOpen) {
    const startMs = dateMs(start);
    if (!startMs) {
      return null;
    }
    return `${formatDuration(start, new Date().toISOString()) || '0 min'} so far`;
  }
  return formatDuration(start, end);
}

function activityStatusTone(state) {
  const text = String(state || '').toLowerCase();
  if (text.includes('normal')) {
    return 'good';
  }
  if (text.includes('warning') || text.includes('partial') || text.includes('unknown')) {
    return 'warn';
  }
  if (text.includes('blocked') || text.includes('not operating')) {
    return 'danger';
  }
  return 'neutral';
}

function activitySeverityTone(severity) {
  const text = String(severity || '').toLowerCase();
  if (text === 'success' || text === 'recovered') {
    return 'good';
  }
  if (text === 'warning' || text === 'blocked') {
    return 'warn';
  }
  if (text === 'failure' || text === 'failed' || text === 'error') {
    return 'danger';
  }
  return 'neutral';
}

function noTradeTone(state) {
  const text = String(state || '').toLowerCase();
  if (text.includes('submitted') || text.includes('completed')) {
    return 'good';
  }
  if (text.includes('did_not_run') || text.includes('not_submitted')) {
    return 'warn';
  }
  return 'neutral';
}

function describeTransaction(item) {
  const normalized = normalizeTradeRow(item);
  const symbol = normalized.symbol ? ` ${normalized.symbol}` : '';
  const side = normalized.side ? ` ${String(normalized.side).toUpperCase()}` : '';
  const sizeValue = normalized.quantity;
  const size = sizeValue ? ` for ${sizeValue}` : '';
  const status = normalized.status ? ` (${normalized.status})` : '';
  const displayStatus = isOpenTrade(normalized) ? ' (holding/unsold)' : status;
  const priceValue = normalized.exitPrice || normalized.price || normalized.entryPrice;
  const price = priceValue ? ` at ${historyMoneyOrText(normalized.broker, priceValue)}` : '';
  const pnl = normalized.profitLoss !== undefined && normalized.profitLoss !== null ? ` P&L ${historyMoneyOrText(normalized.broker, normalized.profitLoss)}` : '';
  const confidence = item.ai_confidence ? ` at ${formatPercent(item.ai_confidence)} confidence` : '';
  return `${friendlyEvent(item.event_type)}${side}${symbol}${size}${price}${pnl}${confidence}${displayStatus}.`;
}

function yesNo(value) {
  if (value === null || value === undefined) {
    return null;
  }
  return value ? 'Yes' : 'No';
}

function enabledDisabled(value) {
  if (value === null || value === undefined) {
    return null;
  }
  return value ? 'Enabled' : 'Disabled';
}

function connectedFounderBrokers(brokers) {
  return (brokers || []).filter((item) => ['alpaca', 'kraken'].includes(String(item.broker || '').toLowerCase()));
}

function futureBrokerPanels(brokers) {
  return (brokers || [])
    .filter((item) => !['alpaca', 'kraken'].includes(String(item.broker || '').toLowerCase()))
    .map((item) => ({
      broker: item.broker,
      label: item.label || item.broker,
      status: item.connection_status || item.source || 'Not connected',
    }));
}

function formatUnavailableReasons(items) {
  if (!items || !items.length) {
    return 'No explained missing values currently require attention.';
  }
  return items.slice(0, 5).map((item) => `${item.field}: ${item.why} Required: ${item.required}`).join('\n');
}

function formatReconciliation(items) {
  if (!items || !items.length) {
    return 'Awaiting broker reconciliation - no reconciliation run has been recorded yet.';
  }
  return items.slice(0, 5).map((item) => `${item.broker}: ${item.status}. ${item.summary}`).join('\n');
}

function summaryTone(value) {
  const text = String(value || '').toLowerCase();
  if (text.includes('no action')) return 'good';
  if (text.includes('review')) return 'warn';
  if (text.includes('issue') || text.includes('unsuitable')) return 'danger';
  return 'neutral';
}

function operationsTone(operations) {
  const text = String(operations?.overall || operations?.plain_english || '').toLowerCase();
  if (text.includes('healthy') || text.includes('persisted research')) return 'good';
  if (text.includes('attention') || text.includes('incident') || text.includes('stale')) return 'danger';
  return 'warn';
}

function latestJobTime(jobs, jobName) {
  const row = (jobs || []).find((item) => item.job_name === jobName);
  return row ? formatDateTime(row.completed_at || row.started_at || row.scheduled_for) : explainMissing(jobName, 'no durable job-run record has been returned yet');
}

function sumRecentJobs(jobs, key) {
  const total = (jobs || []).reduce((sum, item) => sum + Number(item?.[key] || 0), 0);
  return Number.isFinite(total) ? total : 0;
}

function operationsIncidentText(items) {
  if (!items || !items.length) {
    return 'No open operations incidents recorded.';
  }
  return items.slice(0, 5).map((item) => `${item.severity || 'issue'}: ${item.title || item.message}`).join('\n');
}

function probabilityRange(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return 'Not available - probability model did not return a value.';
  const lower = Math.max(0, number - 0.05);
  const upper = Math.min(1, number + 0.05);
  return `${Math.round(lower * 100)}%-${Math.round(upper * 100)}%`;
}
