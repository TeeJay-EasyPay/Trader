import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Linking,
  RefreshControl,
  SafeAreaView,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';

const API_BASE = process.env.EXPO_PUBLIC_AI_TRADER_API_URL || 'https://trader-no0f.onrender.com';
const API_TOKEN = process.env.EXPO_PUBLIC_AI_TRADER_API_TOKEN || '';
const RECOMMENDATION_CACHE_KEY = 'ai-trader:last-recommendations';

const SCREENS = ['Command', 'Recommendations', 'Intelligence'];

export default function App() {
  const [screen, setScreen] = useState('Command');
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
  const [targetRecommendationId, setTargetRecommendationId] = useState(null);
  const [notifications, setNotifications] = useState([]);
  const [performanceAttribution, setPerformanceAttribution] = useState([]);
  const [dailyLearning, setDailyLearning] = useState(null);
  const [latestReport, setLatestReport] = useState(null);

  const request = useCallback(async (path, options) => {
    const headers = {
      'Content-Type': 'application/json',
      ...(API_TOKEN ? { Authorization: `Bearer ${API_TOKEN}` } : {}),
    };
    const response = await fetch(`${API_BASE}${path}`, {
      headers,
      ...options,
    });
    const text = await response.text();
    let json = {};
    if (text) {
      try {
        json = JSON.parse(text);
      } catch (error) {
        throw new Error(
          `Backend returned non-JSON data from ${path} (${response.status}). ${bodyPreview(text)}`
        );
      }
    }
    if (!response.ok) {
      throw new Error(json.message || json.error || `Request failed: ${response.status}`);
    }
    return json;
  }, []);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const optional = (path, fallback) => request(path).catch(() => fallback);
      const [nextStatus, nextPortfolio, nextBrief, nextRecommendations, nextBenchmark, nextThemes, nextCompanies, nextNotifications, nextPerformance, nextLearning] = await Promise.all([
        request('/status'),
        optional('/portfolio', {
          portfolio_value: 'Not available',
          cash_available: 'Not available',
          open_positions: [],
          executive_summary: [],
        }),
        optional('/founder-brief', { report_markdown: 'Not available - founder brief endpoint did not respond.' }),
        optional('/recommendations', { recommendations: [] }),
        optional(`/benchmark-daily-brief?date=${todayIso()}`, null),
        optional('/intelligence/themes', { themes: [] }),
        optional('/intelligence/companies', { companies: [] }),
        optional('/notifications', { notifications: [] }),
        optional('/performance-attribution', { performance_attribution: [] }),
        optional('/daily-learning-update', null),
      ]);
      setStatus(nextStatus);
      setPortfolio(nextPortfolio);
      setBrief(nextBrief);
      setNotifications(nextNotifications.notifications || []);
      setPerformanceAttribution(nextPerformance.performance_attribution || []);
      setDailyLearning(nextLearning);
      const nextRecommendationItems = sortByConfidence(nextRecommendations.recommendations || []);
      if (nextRecommendationItems.length) {
        setRecommendations(nextRecommendationItems);
        await AsyncStorage.setItem(RECOMMENDATION_CACHE_KEY, JSON.stringify(nextRecommendationItems));
      } else {
        const cached = await loadCachedRecommendations();
        setRecommendations(cached.length ? cached : []);
      }
      setBenchmark(nextBenchmark);
      setThemes(nextThemes.themes || []);
      setCompanies(nextCompanies.companies || []);
      setLastRefreshedAt(new Date().toISOString());
    } catch (error) {
      Alert.alert('Backend unavailable', `${String(error.message || error)}\n\nAPI: ${API_BASE}`);
    } finally {
      setLoading(false);
    }
  }, [request]);

  useEffect(() => {
    loadCachedRecommendations().then((cached) => {
      if (cached.length) {
        setRecommendations(cached);
      }
    });
    refresh();
  }, [refresh]);

  const command = async (path, body = {}, fallbackPath = null) => {
    setLoading(true);
    try {
      let result;
      try {
        result = await request(path, { method: 'POST', body: JSON.stringify(body) });
      } catch (error) {
        if (fallbackPath && String(error.message || error) === 'not_found') {
          result = await request(fallbackPath, { method: 'POST', body: JSON.stringify(body) });
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
      const result = await request(`/trading-report?${query}`);
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

  const approve = async (proposalId) => {
    await command('/approve-and-execute', {
      proposal_id: proposalId,
      amount: amounts[proposalId] || null,
    });
  };

  const content = useMemo(() => {
    if (screen === 'Command') {
      return (
        <CommandCentre
          status={status}
          portfolio={portfolio}
          brief={brief}
          notifications={notifications}
          performanceAttribution={performanceAttribution}
          latestReport={latestReport}
          selectedExchange={selectedExchange}
          setSelectedExchange={setSelectedExchange}
          onRefresh={refresh}
          onCommand={command}
          onReport={reportCommand}
          onAckNotifications={(ids) => command('/notifications/ack', { notification_ids: ids })}
        />
      );
    }
    if (screen === 'Recommendations') {
      return (
        <Recommendations
          recommendations={recommendations}
          dailyLearning={dailyLearning}
          amounts={amounts}
          setAmounts={setAmounts}
          onApprove={approve}
          onRefresh={refresh}
          onRunAnalysis={() => command('/run-analysis', { limit: 30 })}
          onAutoExecute={() => command('/auto-execute-recommendations')}
          targetRecommendationId={targetRecommendationId}
          clearTargetRecommendation={() => setTargetRecommendationId(null)}
        />
      );
    }
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
  }, [amounts, benchmark, brief, companies, dailyLearning, latestReport, notifications, performanceAttribution, portfolio, recommendations, screen, status, themes, targetRecommendationId]);

  return (
    <SafeAreaView style={styles.safe}>
      <View style={styles.header}>
        <Text style={styles.title}>AI Trader</Text>
        <Text style={styles.subtitle}>
          {lastRefreshedAt ? `Last refreshed ${formatDateTime(lastRefreshedAt)}` : `Backend: ${shortApiBase()}`}
        </Text>
      </View>
      <View style={styles.tabs}>
        {SCREENS.map((item) => (
          <TouchableOpacity
            key={item}
            style={[styles.tab, screen === item && styles.activeTab]}
            onPress={() => setScreen(item)}
          >
            <Text style={[styles.tabText, screen === item && styles.activeTabText]}>{item}</Text>
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

function CommandCentre({ status, portfolio, brief, notifications, performanceAttribution, latestReport, selectedExchange, setSelectedExchange, onRefresh, onCommand, onReport, onAckNotifications }) {
  const positions = portfolio?.open_positions || [];
  const recentTransactions = combinedTransactions(status, portfolio, selectedExchange, performanceAttribution);
  const recommendationSummary = status?.recommendation_summary || {};
  const executiveSummary = status?.executive_summary || portfolio?.executive_summary || [];
  const founderSummary = status?.founder_executive_summary || null;
  const brokerPanels = status?.brokers || [];
  const selectedSummary = exchangeSummary(executiveSummary, selectedExchange);
  const policy = status?.trading_policy || {};
  const unreadNotifications = (notifications || []).filter((item) => item.delivery_status === 'queued');
  return (
    <View>
      <Section title={`Notifications${unreadNotifications.length ? ` (${unreadNotifications.length} unread)` : ''}`}>
        {!notifications || !notifications.length ? (
          <Empty />
        ) : (
          <View>
            {notifications.slice(0, 15).map((item) => (
              <View key={item.notification_id} style={styles.compactRow}>
                <Text style={styles.cardTitle}>
                  {item.delivery_status === 'queued' ? '● ' : ''}
                  {notAvailable(item.title)}
                </Text>
                <Text style={styles.bodyText}>{notAvailable(item.message)}</Text>
                <Text style={styles.smallText}>{formatDateTime(item.created_at)}</Text>
              </View>
            ))}
            {unreadNotifications.length ? (
              <View style={styles.buttonGrid}>
                <Button
                  label="Mark all read"
                  tone="neutral"
                  onPress={() => onAckNotifications(unreadNotifications.map((item) => item.notification_id))}
                />
              </View>
            ) : null}
          </View>
        )}
      </Section>
      <Section title="Risk Limits">
        <Text style={styles.bodyText}>
          These are the Founder-approved limits the Investment Orchestrator enforces before any autonomous trade.
        </Text>
        <Metric label="Max Daily Loss" value={formatPercent(policy.max_daily_loss_pct)} />
        <Metric label="Max Weekly Loss" value={formatPercent(policy.max_weekly_loss_pct)} />
        <Metric label="Max Monthly Loss" value={formatPercent(policy.max_monthly_loss_pct)} />
        <Metric label="Max Drawdown" value={formatPercent(policy.max_drawdown_pct)} />
        <Metric label="Max Position Size" value={formatPercent(policy.max_position_size_pct)} />
        <Metric label="Max Capital Allocation" value={formatPercent(policy.max_capital_allocation_pct)} />
        <Metric label="Max Concurrent Exposure" value={formatPercent(policy.max_concurrent_exposure_pct)} />
        <Metric label="Max Concurrent Positions" value={policy.max_concurrent_positions} />
        <Metric label="Min Confidence Required" value={formatPercent(policy.min_ai_confidence)} />
        <Metric label="Trailing Stops" value={policy.trailing_stop_enabled ? `Enabled (${formatPercent(policy.trailing_stop_pct)})` : 'Disabled'} />
        <Metric label="Crypto Trading" value={policy.crypto_enabled ? 'Enabled by policy' : 'Disabled - requires Founder approval'} />
      </Section>
      <Section title="Executive Summary">
        {founderSummary ? (
          <View style={styles.compactRow}>
            <Text style={styles.cardTitle}>{notAvailable(founderSummary.headline)}</Text>
            {(founderSummary.plain_english || []).map((line, index) => (
              <Text key={`${line}-${index}`} style={styles.bodyText}>- {line}</Text>
            ))}
          </View>
        ) : null}
        {!executiveSummary.length ? (
          <Empty />
        ) : (
          executiveSummary.map((item) => (
            <View key={item.broker} style={styles.compactRow}>
              <Text style={styles.cardTitle}>{notAvailable(item.broker)}</Text>
              <Metric label="Balance" value={moneyOrText(item.portfolio_balance)} />
              <Metric label="Cash" value={moneyOrText(item.cash_balance)} />
              <Metric label="Estimated In Positions" value={moneyOrText(item.estimated_in_positions)} />
              <Metric label="Day P&L" value={moneyOrText(item.last_day_pnl)} />
              <Metric label="Week P&L" value={moneyOrText(item.last_week_pnl)} />
              <Metric label="Month P&L" value={moneyOrText(item.last_month_pnl)} />
              <Metric label="Traded Today" value={moneyOrText(item.amount_traded_today)} />
              <Metric label="Month Start" value={moneyOrText(item.month_start_portfolio_balance)} />
              <Metric label="Open Positions" value={item.open_positions} />
              <Metric label="Status" value={item.status} />
            </View>
          ))
        )}
      </Section>
      <Section title="Exchange Filter">
        <View style={styles.buttonGrid}>
          {['All', 'Alpaca', 'Kraken', 'Coinbase'].map((item) => (
            <Button
              key={item}
              label={item}
              tone={selectedExchange === item ? 'primary' : 'neutral'}
              onPress={() => setSelectedExchange(item)}
            />
          ))}
        </View>
      </Section>
      <Section title="Trading Command Centre">
        <Metric label="System Status" value={status?.system_status} />
        <Metric label="Paper / Live Mode" value={status?.paper_live_mode} />
        <Metric label="Engine Health" value={status?.engine_health} />
        <Metric label="Due Diligence Status" value={status?.due_diligence_status} />
        <Metric label="Last Analysis Time" value={formatDateTime(status?.last_analysis_time)} />
        <Metric label="Portfolio Value" value={selectedPortfolioValue(selectedExchange, selectedSummary, portfolio, 'portfolio')} />
        <Metric label="Cash Available" value={selectedPortfolioValue(selectedExchange, selectedSummary, portfolio, 'cash')} />
        <Metric label="Estimated In Positions" value={selectedPortfolioValue(selectedExchange, selectedSummary, portfolio, 'invested')} />
        <Metric label="Today's P&L" value={selectedPortfolioValue(selectedExchange, selectedSummary, portfolio, 'dayPnl')} />
        <Metric label="Open Positions" value={selectedPortfolioValue(selectedExchange, selectedSummary, portfolio, 'positions') || (positions.length ? `${positions.length}` : 'Not available')} />
        <Metric label="Active Recommendations" value={recommendationSummary.active} />
        <Metric label="Latest Trade" value={describeLatestTrade(portfolio?.latest_trade)} />
        <Metric label="Expired Recommendations" value={recommendationSummary.expired} />
        <Metric label="Auto Trade Mode" value={recommendationSummary.auto_trade_mode} />
        <Metric label="Auto Paper Trading Status" value={status?.auto_paper_trading_status} />
        <Metric label="Selected Active Brokers" value={formatListInline(status?.selected_active_brokers)} />
        <Metric label="Next Research Run" value={formatDateTime(status?.next_scheduled_research_run)} />
        <Metric label="Last Orchestrator Decision" value={describeDecision(status?.last_orchestrator_decision)} />
        <Metric label="Cloud API Health" value={status?.cloud_api_health} />
      </Section>
      <Section title="Reports">
        <View style={styles.buttonGrid}>
          <Button label="Today Report" onPress={() => onReport({ type: 'daily', date: todayIso(), broker: selectedBrokerKey(selectedExchange) })} />
          <Button label="Yesterday Report" onPress={() => onReport({ type: 'daily', date: yesterdayIso(), broker: selectedBrokerKey(selectedExchange) })} />
          <Button label="Morning Report" onPress={() => onReport({ type: 'morning', date: todayIso(), broker: selectedBrokerKey(selectedExchange) })} tone="neutral" />
          <Button label="Evening Report" onPress={() => onReport({ type: 'evening', date: todayIso(), broker: selectedBrokerKey(selectedExchange) })} tone="neutral" />
          <Button label="Weekly Report" onPress={() => onReport({ type: 'weekly', date: todayIso(), broker: selectedBrokerKey(selectedExchange) })} tone="neutral" />
          <Button label="Monthly Report" onPress={() => onReport({ type: 'monthly', date: todayIso(), broker: selectedBrokerKey(selectedExchange) })} tone="neutral" />
        </View>
        <Text style={styles.smallText}>
          Reports explain P&L movement using broker snapshots, closed trades, orders, guardrail rejections, and learning notes.
        </Text>
        {latestReport ? <ReportPanel report={latestReport} /> : null}
      </Section>
      <Section title="Broker Panels">
        {brokerPanels.length ? brokerPanels.map((broker) => {
          const label = broker.label || notAvailable(broker.broker);
          return (
            <View key={`${broker.broker}-panel`} style={styles.compactRow}>
              <Text style={styles.cardTitle}>{label}</Text>
              <Metric label="Connection Status" value={broker.connection_status} />
              <Metric label="Portfolio" value={moneyOrText(broker.portfolio_value)} />
              <Metric label="Cash" value={moneyOrText(broker.cash_available)} />
              <Metric label="Estimated In Positions" value={moneyOrText(broker.estimated_in_positions)} />
              <Metric label="Buying Power" value={moneyOrText(broker.buying_power)} />
              <Metric label="Open Positions" value={broker.open_positions} />
              <Metric label="Today's P&L" value={moneyOrText(broker.todays_pnl)} />
              <Metric label="Week P&L" value={moneyOrText(broker.week_pnl)} />
              <Metric label="Month P&L" value={moneyOrText(broker.month_pnl)} />
              <Metric label="Trades Today" value={broker.trades_today} />
              {broker.balance_summary ? (
                <>
                  <Metric label="Total Estimated Balance" value={moneyOrText(broker.balance_summary.total_estimated_gbp)} />
                  <Metric label="GBP Cash" value={moneyOrText(broker.balance_summary.gbp_cash)} />
                  <Metric label="AI Trading Allocation" value={moneyOrText(broker.balance_summary.trading_allocation_gbp)} />
                  <TextBlock label="Balance Note" value={broker.balance_summary.valuation_note} />
                </>
              ) : null}
              <Metric label="Research Status" value={broker.research_status} />
              <Metric label="Due Diligence Status" value={broker.due_diligence_status} />
              <Metric label="Auto Trading Status" value={broker.auto_trading_enabled ? 'Enabled' : 'Disabled'} />
              <View style={styles.buttonGrid}>
                <Button label={`Run Analysis (${label})`} onPress={() => onCommand('/run-analysis', { limit: 30, broker: broker.broker })} />
                <Button label={`Daily Report (${label})`} onPress={() => onReport({ type: 'daily', date: todayIso(), broker: broker.broker })} tone="neutral" />
                <Button label={`Enable Auto Trading (${label})`} onPress={() => onCommand('/broker-auto-trading', { broker: broker.broker, enabled: true })} tone="warn" />
                <Button label={`Disable Auto Trading (${label})`} onPress={() => onCommand('/broker-auto-trading', { broker: broker.broker, enabled: false })} tone="danger" />
              </View>
            </View>
          );
        }) : <Empty />}
      </Section>
      <View style={styles.buttonGrid}>
        <Button label="Run Analysis" onPress={() => onCommand('/run-analysis', { limit: 30 })} />
        <Button label="Resume All Trading" onPress={() => onCommand('/start-trading', {}, '/resume-trading')} />
        <Button label="Emergency Stop All" onPress={() => onCommand('/stop-trading')} tone="danger" />
        <Button label="Refresh" onPress={onRefresh} tone="neutral" />
      </View>
      <Text style={styles.smallText}>
        Emergency Stop All halts new autonomous entries and manual approvals across every broker. It does not disable
        stop-loss/take-profit protection on positions already open - those continue to be monitored and closed
        automatically regardless of trading state.
      </Text>
      <TradeHistorySection title={`${selectedExchange === 'All' ? 'All Brokers' : selectedExchange} Trade History`} trades={recentTransactions} />
      <Section title="Analysis Activity">
        {analysisActivity(status).length === 0 ? (
          <Empty />
        ) : (
          analysisActivity(status).map((item, index) => (
            <Text key={`${item.created_at}-${index}`} style={styles.bodyText}>
              {formatDateTime(item.created_at)} - {friendlyEvent(item.event_type)} {item.symbol ? `(${item.symbol})` : ''}
            </Text>
          ))
        )}
      </Section>
      <Section title="Morning Brief">
        <Text style={styles.bodyText}>{notAvailable(status?.morning_brief?.summary)}</Text>
      </Section>
      <Section title="Evening Brief">
        <Text style={styles.bodyText}>{notAvailable(status?.evening_brief?.summary)}</Text>
      </Section>
      <Section title="Founder Brief">
        <Text style={styles.bodyText}>{notAvailable(brief?.report_markdown)}</Text>
      </Section>
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

function TradeHistorySection({ title, trades }) {
  const [expanded, setExpanded] = useState({});
  return (
    <Section title={title}>
      {!trades.length ? (
        <Empty />
      ) : (
        trades.map((item, index) => {
          const key = tradeKey(item, index);
          const open = !!expanded[key];
          return (
            <View key={key} style={styles.compactRow}>
              <TouchableOpacity onPress={() => setExpanded((prev) => ({ ...prev, [key]: !open }))}>
                <Text style={styles.cardTitle}>{open ? 'v' : '>'} {describeTransaction(item)}</Text>
                <Text style={styles.smallText}>{formatDateTime(item.created_at || item.closed_at || item.updated_at || item.opened_at)}</Text>
              </TouchableOpacity>
              {open ? <TradeDetail item={item} /> : null}
            </View>
          );
        })
      )}
    </Section>
  );
}

function TradeDetail({ item }) {
  const raw = item.raw || item.payload || {};
  return (
    <View>
      <Metric label="Broker" value={item.broker} />
      <Metric label="Symbol" value={item.symbol} />
      <Metric label="Side" value={item.side} />
      <Metric label="Status" value={item.status || item.event_type} />
      <Metric label="Quantity" value={item.quantity || item.position_size || item.qty} />
      <Metric label="Entry" value={moneyOrText(item.entry_price || item.entry)} />
      <Metric label="Exit" value={moneyOrText(item.exit_price || item.exit)} />
      <Metric label="Price" value={moneyOrText(item.price)} />
      <Metric label="P&L" value={moneyOrText(item.profit_loss || item.realised_pnl)} />
      <Metric label="Opened" value={formatDateTime(item.opened_at)} />
      <Metric label="Closed" value={formatDateTime(item.closed_at)} />
      <TextBlock label="Entry Reason" value={item.entry_reason} />
      <TextBlock label="Exit Reason" value={item.exit_reason} />
      <TextBlock label="Learning Factors" value={formatJsonText(item.primary_factors_json || item.primary_factors)} />
      <TextBlock label="Broker Payload" value={formatJsonText(raw)} />
    </View>
  );
}

function Recommendations({ recommendations, amounts, setAmounts, onApprove, onRefresh, onRunAnalysis, onAutoExecute, targetRecommendationId, clearTargetRecommendation }) {
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
          <Button label="Run New Analysis" onPress={onRunAnalysis} />
        </View>
      </Section>
    );
  }
  return (
    <View>
      <Section title="AI Recommendation History">
        <Text style={styles.bodyText}>
          Showing saved SQLite recommendations, ordered from highest confidence to lowest. Expired ideas stay visible
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
        <Button label="Run New Analysis" onPress={onRunAnalysis} />
        <Button label="Auto Execute 85%+" onPress={onAutoExecute} tone="warn" />
      </View>
      {Object.entries(groupRecommendations(filterRecommendations(recommendations, brokerFilter, confidenceFilter, assetTypeFilter, statusFilter))).map(([broker, items]) => (
        <Section key={`group-${broker}`} title={broker}>
          {items.map((item) => {
            const open = !!expanded[item.proposal_id];
            return (
              <View key={item.proposal_id}>
                <TouchableOpacity style={styles.recommendationHeader} onPress={() => setExpanded((prev) => ({ ...prev, [item.proposal_id]: !open }))}>
                  <Text style={styles.cardTitle}>{open ? 'v' : '>'} {notAvailable(item.ticker)} {formatPercent(item.confidence)}</Text>
                </TouchableOpacity>
                {open && (
                  <RecommendationCard
                    item={item}
                    amount={amounts[item.proposal_id] || ''}
                    setAmount={(value) => setAmounts((prev) => ({ ...prev, [item.proposal_id]: value }))}
                    onApprove={() => onApprove(item.proposal_id)}
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

function RecommendationCard({ item, amount, setAmount, onApprove }) {
  const enriched = withRecommendationFreshness(item);
  return (
    <View style={styles.card}>
      <Text style={styles.cardTitle}>{notAvailable(enriched.company)} ({notAvailable(enriched.ticker)})</Text>
      <Metric label="Freshness" value={enriched.freshness_status} />
      <Metric label="Generated" value={formatDateTime(enriched.created_at)} />
      <Metric label="Expires" value={formatDateTime(enriched.expires_at)} />
      <TextBlock label="Freshness Note" value={enriched.freshness_note} />
      <Metric label="Sector" value={item.sector} />
      <Metric label="Country" value={item.country} />
      <Metric label="Asset Availability" value={yesNo(item.asset_available)} />
      <Metric label="Suggested Broker" value={item.suggested_broker} />
      <Metric label="Exchange" value={item.exchange} />
      <Metric label="Market Open" value={yesNo(item.market_open)} />
      <Metric label="Auto Eligible" value={yesNo(enriched.auto_trade_eligible)} />
      <TextBlock label="Rejection Reason" value={item.orchestrator_rejection_reason || enriched.auto_trade_reason} />
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
      <TextBlock label="Reason for Recommendation" value={item.reason_for_recommendation} />
      <TextBlock label="Key Risks" value={item.key_risks} />
      <Metric label="Suggested Stop Loss" value={item.suggested_stop_loss} />
      <Metric label="Suggested Take Profit" value={item.suggested_take_profit} />
      <Metric label="Suggested Position Size" value={item.suggested_position_size} />
      <Metric label="Recommended Position Size" value={item.recommended_position_size} />
      <Metric label="Due Diligence Status" value={item.due_diligence_status} />
      <Metric label="Guardrail Result" value={yesNo(item.guardrails_passed)} />
      <TextBlock label="Passed Guardrails" value={formatGuardrailChecks(enriched.guardrail_checks, 'passed') || formatList(enriched.guardrail_passes)} />
      <TextBlock label="Failed Guardrails" value={formatGuardrailChecks(enriched.guardrail_checks, 'failed') || enriched.guardrail_summary || formatGuardrails(enriched.guardrail_failures)} />
      <Metric label="Auto Trade Eligible" value={yesNo(enriched.auto_trade_eligible)} />
      <TextBlock label="Auto Trade Reason" value={enriched.auto_trade_reason} />
      <TextBlock label="Exit Plan" value={exitPlan(item)} />
      <TextBlock label="Auto Trade Uses" value="The suggested position size. The amount box is only for manual approval notes; guardrails still control execution." />
      <TextInput
        style={styles.input}
        keyboardType="decimal-pad"
        placeholder="Optional amount note"
        value={amount}
        onChangeText={setAmount}
      />
      <Button
        label={enriched.freshness_status === 'Expired' ? 'Expired - Run Analysis' : 'Approve & Execute'}
        onPress={onApprove}
        disabled={enriched.freshness_status === 'Expired'}
      />
    </View>
  );
}

function MarketIntelligence({ benchmark, themes, companies, status, recommendations, dailyLearning, onOpenRecommendation }) {
  const items = benchmark?.items || [];
  return (
    <View>
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

function Section({ title, children }) {
  return (
    <View style={styles.section}>
      <Text style={styles.sectionTitle}>{title}</Text>
      {children}
    </View>
  );
}

function Metric({ label, value }) {
  return (
    <View style={styles.metric}>
      <Text style={styles.metricLabel}>{label}</Text>
      <Text style={styles.metricValue}>{notAvailable(value)}</Text>
    </View>
  );
}

function TextBlock({ label, value }) {
  return (
    <View style={styles.textBlock}>
      <Text style={styles.metricLabel}>{label}</Text>
      <Text style={styles.bodyText}>{notAvailable(value)}</Text>
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

function Button({ label, onPress, tone = 'primary', disabled = false }) {
  return (
    <TouchableOpacity style={[styles.button, styles[tone], disabled && styles.disabledButton]} onPress={onPress} disabled={disabled}>
      <Text style={styles.buttonText}>{label}</Text>
    </TouchableOpacity>
  );
}

function Empty() {
  return <Text style={styles.bodyText}>Not available</Text>;
}

function money(value) {
  if (value === null || value === undefined || value === '') {
    return null;
  }
  return `$${Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

function moneyOrText(value) {
  if (typeof value === 'string' && value.startsWith('Not available')) {
    return value;
  }
  return money(value);
}

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

function yesterdayIso() {
  const value = new Date();
  value.setDate(value.getDate() - 1);
  return value.toISOString().slice(0, 10);
}

function selectedBrokerKey(selectedExchange) {
  if (!selectedExchange || selectedExchange === 'All') {
    return 'all';
  }
  return String(selectedExchange).toLowerCase();
}

function bodyPreview(text) {
  const trimmed = String(text || '').replace(/\s+/g, ' ').trim();
  if (!trimmed) {
    return 'The response body was empty.';
  }
  return `Response started with: ${trimmed.slice(0, 80)}`;
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
  if (path === '/broker-auto-trading') {
    return `${notAvailable(result.broker)} auto trading ${result.auto_trading_enabled ? 'enabled' : 'disabled'}.`;
  }
  if (path === '/generate-report' || path === '/trading-report') {
    return `${notAvailable(result.report_type)} report generated for ${notAvailable(result.broker)} on ${notAvailable(result.date)}.\n\n${notAvailable(result.summary)}`;
  }
  return result.message || result.status || 'Done';
}

function shortApiBase() {
  return API_BASE.replace(/^https?:\/\//, '');
}

function absoluteApiUrl(path) {
  if (!path) {
    return API_BASE;
  }
  if (String(path).startsWith('http')) {
    return path;
  }
  return `${API_BASE}${String(path).startsWith('/') ? '' : '/'}${path}`;
}

function combinedTransactions(status, portfolio, selectedExchange = 'All', performanceAttribution = []) {
  const attribution = (performanceAttribution || [])
    .filter((item) => selectedExchange === 'All' || String(item.broker || '').toLowerCase() === selectedExchange.toLowerCase())
    .map((item) => ({
      ...item,
      event_type: 'performance_attribution',
      status: 'closed',
      created_at: item.closed_at || item.created_at,
      raw: parseMaybeJson(item.primary_factors_json),
    }));
  if (selectedExchange === 'Kraken' || selectedExchange === 'Coinbase') {
    const broker = String(selectedExchange).toLowerCase();
    const panel = (status?.brokers || []).find((item) => String(item.broker || '').toLowerCase() === broker);
    const brokerTrades = (panel?.trade_history || []).map((item) => ({
      ...item,
      broker,
      event_type: 'broker_trade',
      created_at: item.closed_at || item.opened_at || item.updated_at,
      raw: parseMaybeJson(item.payload_json) || item,
    }));
    return [...attribution, ...brokerTrades]
      .filter((item) => item.created_at || item.symbol || item.event_type)
      .sort((a, b) => dateMs(b.created_at) - dateMs(a.created_at))
      .slice(0, 20);
  }
  const auditRows = (status?.recent_transactions || []).filter((item) => (
    item.event_type === 'execution_approved' || item.event_type === 'execution_rejected'
  ));
  const fills = (portfolio?.recent_activities || []).map((item) => ({
    event_type: 'broker_fill',
    symbol: item.symbol,
    side: item.side,
    position_size: item.qty,
    price: item.price,
    created_at: item.transaction_time || item.date || item.updated_at,
    raw: item,
  }));
  const orders = (portfolio?.recent_orders || []).map((item) => ({
    event_type: 'broker_order',
    symbol: item.symbol,
    side: item.side,
    position_size: item.qty,
    status: item.status,
    created_at: item.submitted_at || item.updated_at || item.created_at,
    raw: item,
  }));
  return [...attribution, ...auditRows, ...fills, ...orders]
    .filter((item) => item.created_at || item.symbol || item.event_type)
    .sort((a, b) => dateMs(b.created_at) - dateMs(a.created_at))
    .slice(0, 20);
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

function analysisActivity(status) {
  return (status?.latest_activity || [])
    .filter((item) => item.event_type !== 'agent_no_trade')
    .slice(0, 8);
}

function sortByConfidence(items) {
  return [...items].sort((a, b) => {
    const confidenceDelta = Number(b.confidence || 0) - Number(a.confidence || 0);
    if (confidenceDelta !== 0) {
      return confidenceDelta;
    }
    return dateMs(b.created_at) - dateMs(a.created_at);
  });
}

function dateMs(value) {
  const ms = Date.parse(value || '');
  return Number.isFinite(ms) ? ms : 0;
}

function formatDateTime(value) {
  if (!value) {
    return null;
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString(undefined, {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function formatPercent(value) {
  if (value === null || value === undefined || value === '') {
    return null;
  }
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return value;
  }
  const percent = number <= 1 ? number * 100 : number;
  return `${percent.toFixed(0)}%`;
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
    guardrail_summary: item.guardrail_summary || formatGuardrails(item.guardrail_failures),
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
    const guardrails = formatGuardrails(item.guardrail_failures);
    if (guardrails) {
      return `Execution guardrails failed: ${guardrails}.`;
    }
    return 'Execution guardrails did not pass, so auto-trade is blocked.';
  }
  return 'Eligible for paper auto-trade.';
}

function formatGuardrails(failures) {
  if (!failures || !failures.length) {
    return null;
  }
  return failures.map((item) => String(item).replaceAll('_', ' ')).join(', ');
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

function formatList(items) {
  if (!items || !items.length) {
    return null;
  }
  return items.map((item) => `- ${item}`).join('\n');
}

function formatListInline(items) {
  if (!items || !items.length) {
    return null;
  }
  return items.join(', ');
}

function describeDecision(decision) {
  if (!decision) {
    return null;
  }
  return `${notAvailable(decision.symbol)} ${notAvailable(decision.decision)}${decision.rejection_reason ? `: ${decision.rejection_reason}` : ''}`;
}

function exchangeSummary(items, selectedExchange) {
  if (!items || selectedExchange === 'All') {
    return null;
  }
  return items.find((item) => String(item.broker || '').toLowerCase() === selectedExchange.toLowerCase()) || null;
}

function selectedPortfolioValue(selectedExchange, summary, portfolio, field) {
  if (selectedExchange === 'Kraken' || selectedExchange === 'Coinbase') {
    if (!summary) {
      return `${selectedExchange} not configured`;
    }
    if (summary.status && !summary.portfolio_balance) {
      return summary.status;
    }
    if (field === 'portfolio') return moneyOrText(summary.portfolio_balance);
    if (field === 'cash') return moneyOrText(summary.cash_balance);
    if (field === 'invested') return moneyOrText(summary.estimated_in_positions ?? estimateInvested(summary.portfolio_balance, summary.cash_balance));
    if (field === 'dayPnl') return moneyOrText(summary.last_day_pnl);
    if (field === 'positions') return summary.open_positions;
  }
  if (field === 'portfolio') return moneyOrText(portfolio?.portfolio_value);
  if (field === 'cash') return moneyOrText(portfolio?.cash_available);
  if (field === 'invested') return moneyOrText(portfolio?.estimated_in_positions ?? estimateInvested(portfolio?.portfolio_value, portfolio?.cash_available));
  if (field === 'dayPnl') return moneyOrText(portfolio?.todays_pnl);
  if (field === 'positions') return portfolio?.open_positions_summary;
  return null;
}

function estimateInvested(portfolioValue, cashValue) {
  const portfolioNumber = numberValue(portfolioValue);
  const cashNumber = numberValue(cashValue);
  if (portfolioNumber === null || cashNumber === null) {
    return null;
  }
  return portfolioNumber - cashNumber;
}

function numberValue(value) {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value;
  }
  if (typeof value !== 'string') {
    return null;
  }
  const parsed = Number(value.replace(/[^0-9.-]/g, ''));
  return Number.isFinite(parsed) ? parsed : null;
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

function companiesForTheme(theme, companies) {
  return companiesForThemeList(theme, companies)
    .slice(0, 8)
    .map((company) => `- ${company.company_name} (${company.ticker})`)
    .join('\n') || null;
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
    performance_attribution: 'Closed trade',
  };
  return labels[eventType] || notAvailable(eventType);
}

function describeTransaction(item) {
  const symbol = item.symbol ? ` ${item.symbol}` : '';
  const side = item.side ? ` ${item.side.toUpperCase()}` : '';
  const sizeValue = item.position_size || item.quantity || item.qty;
  const size = sizeValue ? ` for ${sizeValue}` : '';
  const status = item.status ? ` (${item.status})` : '';
  const priceValue = item.exit_price || item.price || item.entry_price;
  const price = priceValue ? ` at ${money(priceValue)}` : '';
  const pnl = item.profit_loss !== undefined && item.profit_loss !== null ? ` P&L ${money(item.profit_loss)}` : '';
  const confidence = item.ai_confidence ? ` at ${formatPercent(item.ai_confidence)} confidence` : '';
  return `${friendlyEvent(item.event_type)}${side}${symbol}${size}${price}${pnl}${confidence}${status}.`;
}

function yesNo(value) {
  if (value === null || value === undefined) {
    return null;
  }
  return value ? 'Yes' : 'No';
}

function notAvailable(value) {
  if (value === null || value === undefined || value === '') {
    return 'Not available';
  }
  return String(value);
}

const styles = StyleSheet.create({
  safe: {
    flex: 1,
    backgroundColor: '#f6f7f9',
  },
  header: {
    paddingHorizontal: 18,
    paddingTop: 10,
    paddingBottom: 8,
    backgroundColor: '#ffffff',
    borderBottomColor: '#dde1e7',
    borderBottomWidth: 1,
  },
  title: {
    fontSize: 24,
    fontWeight: '800',
    color: '#17202a',
  },
  subtitle: {
    marginTop: 2,
    fontSize: 13,
    color: '#667085',
  },
  tabs: {
    flexDirection: 'row',
    gap: 8,
    padding: 10,
    backgroundColor: '#ffffff',
  },
  tab: {
    flex: 1,
    minHeight: 38,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#cfd6df',
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 6,
  },
  activeTab: {
    backgroundColor: '#1f6feb',
    borderColor: '#1f6feb',
  },
  tabText: {
    fontSize: 12,
    fontWeight: '700',
    color: '#344054',
    textAlign: 'center',
  },
  activeTabText: {
    color: '#ffffff',
  },
  loading: {
    paddingVertical: 6,
  },
  content: {
    padding: 14,
    paddingBottom: 32,
  },
  section: {
    marginBottom: 14,
  },
  sectionTitle: {
    fontSize: 17,
    fontWeight: '800',
    color: '#17202a',
    marginBottom: 8,
  },
  metric: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    gap: 12,
    paddingVertical: 7,
    borderBottomColor: '#e6e9ee',
    borderBottomWidth: 1,
  },
  metricLabel: {
    flex: 1,
    fontSize: 13,
    color: '#667085',
    fontWeight: '700',
  },
  metricValue: {
    flex: 1,
    fontSize: 13,
    color: '#17202a',
    textAlign: 'right',
  },
  bodyText: {
    fontSize: 13,
    lineHeight: 19,
    color: '#243142',
  },
  linkText: {
    color: '#1f6feb',
    fontWeight: '800',
  },
  textBlock: {
    marginTop: 8,
  },
  compactRow: {
    borderBottomColor: '#e6e9ee',
    borderBottomWidth: 1,
    paddingVertical: 8,
  },
  recommendationHeader: {
    backgroundColor: '#ffffff',
    borderWidth: 1,
    borderColor: '#dde1e7',
    borderRadius: 8,
    padding: 12,
    marginBottom: 8,
  },
  smallText: {
    marginTop: 3,
    fontSize: 12,
    lineHeight: 17,
    color: '#667085',
  },
  buttonGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
    marginBottom: 16,
  },
  button: {
    minHeight: 42,
    borderRadius: 8,
    paddingHorizontal: 14,
    alignItems: 'center',
    justifyContent: 'center',
  },
  primary: {
    backgroundColor: '#1f6feb',
  },
  warn: {
    backgroundColor: '#9a6700',
  },
  danger: {
    backgroundColor: '#cf222e',
  },
  neutral: {
    backgroundColor: '#57606a',
  },
  buttonText: {
    color: '#ffffff',
    fontSize: 13,
    fontWeight: '800',
  },
  disabledButton: {
    backgroundColor: '#98a2b3',
  },
  card: {
    backgroundColor: '#ffffff',
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#dde1e7',
    padding: 12,
    marginBottom: 12,
  },
  cardTitle: {
    fontSize: 16,
    fontWeight: '800',
    color: '#17202a',
    marginBottom: 8,
  },
  input: {
    minHeight: 42,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#cfd6df',
    backgroundColor: '#ffffff',
    paddingHorizontal: 12,
    marginVertical: 12,
    fontSize: 14,
  },
});
