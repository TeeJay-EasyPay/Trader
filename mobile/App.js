import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  SafeAreaView,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';

const API_BASE = process.env.EXPO_PUBLIC_AI_TRADER_API_URL || 'http://127.0.0.1:8765';

const SCREENS = ['Command', 'Recommendations', 'Intelligence'];

export default function App() {
  const [screen, setScreen] = useState('Command');
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState(null);
  const [portfolio, setPortfolio] = useState(null);
  const [brief, setBrief] = useState(null);
  const [recommendations, setRecommendations] = useState([]);
  const [benchmark, setBenchmark] = useState(null);
  const [amounts, setAmounts] = useState({});

  const request = useCallback(async (path, options) => {
    const response = await fetch(`${API_BASE}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...options,
    });
    const json = await response.json();
    if (!response.ok) {
      throw new Error(json.error || `Request failed: ${response.status}`);
    }
    return json;
  }, []);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [nextStatus, nextPortfolio, nextBrief, nextRecommendations, nextBenchmark] = await Promise.all([
        request('/status'),
        request('/portfolio'),
        request('/founder-brief'),
        request('/recommendations'),
        request('/benchmark-daily-brief?date=2026-07-02'),
      ]);
      setStatus(nextStatus);
      setPortfolio(nextPortfolio);
      setBrief(nextBrief);
      setRecommendations(nextRecommendations.recommendations || []);
      setBenchmark(nextBenchmark);
    } catch (error) {
      Alert.alert('Local API unavailable', String(error.message || error));
    } finally {
      setLoading(false);
    }
  }, [request]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const command = async (path, body = {}) => {
    setLoading(true);
    try {
      const result = await request(path, { method: 'POST', body: JSON.stringify(body) });
      Alert.alert('Command sent', result.message || result.status || 'Done');
      await refresh();
    } catch (error) {
      Alert.alert('Command failed', String(error.message || error));
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
          onRefresh={refresh}
          onCommand={command}
        />
      );
    }
    if (screen === 'Recommendations') {
      return (
        <Recommendations
          recommendations={recommendations}
          amounts={amounts}
          setAmounts={setAmounts}
          onApprove={approve}
        />
      );
    }
    return <MarketIntelligence benchmark={benchmark} />;
  }, [amounts, benchmark, brief, portfolio, recommendations, screen, status]);

  return (
    <SafeAreaView style={styles.safe}>
      <View style={styles.header}>
        <Text style={styles.title}>AI Trader</Text>
        <Text style={styles.subtitle}>Local command centre</Text>
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
      <ScrollView contentContainerStyle={styles.content}>{content}</ScrollView>
    </SafeAreaView>
  );
}

function CommandCentre({ status, portfolio, brief, onRefresh, onCommand }) {
  const positions = portfolio?.open_positions || [];
  return (
    <View>
      <Section title="Trading Command Centre">
        <Metric label="System Status" value={status?.system_status} />
        <Metric label="Paper / Live Mode" value={status?.paper_live_mode} />
        <Metric label="Engine Health" value={status?.engine_health} />
        <Metric label="Last Analysis Time" value={status?.last_analysis_time} />
        <Metric label="Portfolio Value" value={money(portfolio?.portfolio_value)} />
        <Metric label="Cash Available" value={money(portfolio?.cash_available)} />
        <Metric label="Today's P&L" value={money(portfolio?.todays_pnl)} />
        <Metric label="Open Positions" value={positions.length ? `${positions.length}` : 'Not available'} />
      </Section>
      <View style={styles.buttonGrid}>
        <Button label="Run Analysis" onPress={() => onCommand('/run-analysis')} />
        <Button label="Pause Trading" onPress={() => onCommand('/pause-trading')} tone="warn" />
        <Button label="Resume Trading" onPress={() => onCommand('/resume-trading')} />
        <Button label="Stop Trading" onPress={() => onCommand('/stop-trading')} tone="danger" />
        <Button label="Refresh" onPress={onRefresh} tone="neutral" />
      </View>
      <Section title="Latest Activity">
        {(status?.latest_activity || []).length === 0 ? (
          <Empty />
        ) : (
          status.latest_activity.map((item, index) => (
            <Text key={`${item.created_at}-${index}`} style={styles.bodyText}>
              {notAvailable(item.created_at)} - {notAvailable(item.event_type)} {item.symbol ? `(${item.symbol})` : ''}
            </Text>
          ))
        )}
      </Section>
      <Section title="Founder Brief">
        <Text style={styles.bodyText}>{notAvailable(brief?.report_markdown)}</Text>
      </Section>
    </View>
  );
}

function Recommendations({ recommendations, amounts, setAmounts, onApprove }) {
  if (!recommendations.length) {
    return (
      <Section title="AI Recommendations">
        <Empty />
      </Section>
    );
  }
  return (
    <View>
      {recommendations.map((item) => (
        <View key={item.proposal_id} style={styles.card}>
          <Text style={styles.cardTitle}>{notAvailable(item.company)} ({notAvailable(item.ticker)})</Text>
          <Metric label="Sector" value={item.sector} />
          <Metric label="Country" value={item.country} />
          <Metric label="Confidence" value={item.confidence} />
          <Metric label="Investment Philosophy Fit" value={item.investment_philosophy_fit} />
          <TextBlock label="Investment Thesis" value={item.investment_thesis} />
          <TextBlock label="Reason for Recommendation" value={item.reason_for_recommendation} />
          <TextBlock label="Key Risks" value={item.key_risks} />
          <Metric label="Suggested Stop Loss" value={item.suggested_stop_loss} />
          <Metric label="Suggested Take Profit" value={item.suggested_take_profit} />
          <Metric label="Suggested Position Size" value={item.suggested_position_size} />
          <TextInput
            style={styles.input}
            keyboardType="decimal-pad"
            placeholder="Amount to invest"
            value={amounts[item.proposal_id] || ''}
            onChangeText={(value) => setAmounts((prev) => ({ ...prev, [item.proposal_id]: value }))}
          />
          <Button label="Approve & Execute" onPress={() => onApprove(item.proposal_id)} />
        </View>
      ))}
    </View>
  );
}

function MarketIntelligence({ benchmark }) {
  const items = benchmark?.items || [];
  return (
    <View>
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

function Button({ label, onPress, tone = 'primary' }) {
  return (
    <TouchableOpacity style={[styles.button, styles[tone]]} onPress={onPress}>
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
  textBlock: {
    marginTop: 8,
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
