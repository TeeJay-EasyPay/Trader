// Dashboard screen (Command Centre): executive summary, 24-hour operations, connection
// readiness, and broker panels. Extracted from App.js as part of AT-ED-011 Phase 2.

'use strict';

const React = require('react');
const { Text, View } = require('react-native');
const { styles } = require('../styles');
const { Section, CollapsibleSection, StatusPill, Metric, TextBlock, Button, Empty } = require('../components/shared');
const { BrokerPanel } = require('../components/BrokerPanel');
const { ReportPanel } = require('../components/ReportPanel');
const { notAvailable, explainMissing } = require('../lib/notAvailable');
const { formatDateTime, todayIso } = require('../lib/datetime');
const {
  summaryTone,
  operationsTone,
  activityStatusTone,
  enabledDisabled,
  connectedFounderBrokers,
  futureBrokerPanels,
  formatUnavailableReasons,
  latestJobTime,
  sumRecentJobs,
  operationsIncidentText,
} = require('../lib/founderPresentation');
const { API_TOKEN, API_TOKEN_MASK } = require('../api/client');

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

function ConnectionReadinessCard({ readiness }) {
  const checks = readiness?.checks || [];
  return (
    <CollapsibleSection
      title="Connection & Trading Readiness"
      subtitle="Technical checks behind the summary above - the app's connection to Render, the background worker, and each broker."
      badge={{ label: readiness?.trade_ready ? 'Ready' : 'Attention needed', tone: readiness?.trade_ready ? 'good' : 'warn' }}
    >
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
    </CollapsibleSection>
  );
}

// AT-ED-012: replaces the previous "Command Summary" + separate "Executive Summary" sections,
// which independently summarised the same underlying state back to back. One card, one story:
// a status pill, a 2-4 sentence plain-English summary (headline + recommendation + what to
// watch, exactly as the backend already computes them - nothing invented here), then the
// supporting at-a-glance metrics. Uses the same summaryCard/summaryReason treatment as the
// Activity/Portfolio/Learning screens' top cards, so every screen's "here's the story" card
// looks and reads the same way.
function CommandSummaryCard({ status, brokerPanels }) {
  const executive = status?.founder_experience?.executive_dashboard || {};
  const evidence = status?.world_class_evidence || {};
  const marketHealth = status?.founder_experience?.market_intelligence_centre?.market_health;
  const sentences = [executive.headline, executive.what_to_do, executive.what_to_worry_about].filter(Boolean);
  return (
    <View style={styles.summaryCard}>
      <StatusPill label={notAvailable(evidence.first_conclusion)} tone={summaryTone(evidence.first_conclusion)} />
      <Text style={styles.summaryReason}>
        {sentences.length ? sentences.join(' ') : 'No executive summary is available yet - check back after the next refresh.'}
      </Text>
      <Metric label="Market" value={marketHealth || explainMissing('market health', 'market intelligence has not produced a fresh regime summary yet')} />
      <Metric label="Portfolio" value={executive.portfolio_health || explainMissing('portfolio health', 'broker portfolio values or exposure evidence are incomplete')} />
      <Metric label="Brokers" value={brokerPanels.length ? `${brokerPanels.map((item) => item.label || item.broker).join(', ')} connected` : explainMissing('broker status', 'Alpaca and Kraken are not both visible from the hosted API')} />
      <Metric label="Research" value={status?.research_status || explainMissing('research status', 'no research run has been recorded yet')} />
      <Metric label="Learning" value={evidence.experience_learning?.boundary || executive.learning_progress} />
      {(evidence.unavailable || []).length ? (
        <TextBlock label="Needs Explanation" value={formatUnavailableReasons(evidence.unavailable)} />
      ) : null}
    </View>
  );
}

function FounderBriefCard({ brief, briefLoading, briefError }) {
  // AT-ED-011.5 finding (Data_Freshness_Findings.md): `/founder-brief` was already being
  // fetched on every refresh but the resulting report text was never rendered anywhere -
  // wiring it in here is the mapping correction, not a new feature.
  if (!brief && briefLoading) {
    return (
      <Section title="Founder Brief">
        <Text style={styles.bodyText}>Loading the latest founder brief...</Text>
      </Section>
    );
  }
  if (!brief) {
    return (
      <Section title="Founder Brief">
        <Text style={styles.bodyText}>
          {briefError ? `Founder brief unavailable: ${briefError}` : 'No founder brief has been generated yet.'}
        </Text>
      </Section>
    );
  }
  return (
    <CollapsibleSection
      title="Founder Brief"
      subtitle={brief.created_at ? `Generated ${formatDateTime(brief.created_at)}` : 'Latest generated founder brief report.'}
    >
      {briefError ? <Text style={styles.smallText}>Showing the last successfully loaded brief; the latest refresh failed: {briefError}</Text> : null}
      <TextBlock label="Report" value={brief.report_markdown} />
    </CollapsibleSection>
  );
}

function ExecutiveDashboard({ status, portfolio, brief, briefLoading, briefError, latestReport, onRefresh, onCommand, onReport, activity, onOpenActivity }) {
  const evidence = status?.world_class_evidence || {};
  const operations = status?.operations_health || {};
  const readiness = withMobileTokenReadiness(status?.connection_readiness || localConnectionReadiness(status, status?.brokers || []));
  const brokerPanels = connectedFounderBrokers(status?.brokers || []);
  const futureConnections = evidence.future_connections || futureBrokerPanels(status?.brokers || []);
  return (
    <View>
      <CommandSummaryCard status={status} brokerPanels={brokerPanels} />
      <AutonomousActivitySummaryCard activity={activity} onOpenActivity={onOpenActivity} />
      <CollapsibleSection
        title="24-Hour Operations"
        subtitle="Background worker, research, and job infrastructure detail - not needed day-to-day unless something above says otherwise."
        badge={{
          label: operationsTone(operations) === 'good' ? 'Healthy' : 'Check',
          tone: operationsTone(operations),
        }}
      >
        <Text style={styles.bodyText}>{operations.plain_english || explainMissing('operations health', 'no background worker heartbeat or scheduled job evidence has been returned yet')}</Text>
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
      </CollapsibleSection>
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
      <FounderBriefCard brief={brief} briefLoading={briefLoading} briefError={briefError} />
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

module.exports = { ExecutiveDashboard };
