// Recommendations screen: filterable recommendation history plus the full evidence dossier
// for each idea. Extracted from App.js as part of AT-ED-011 Phase 2 (mobile modularisation).

'use strict';

const React = require('react');
const { useState, useEffect } = React;
const { Text, TextInput, TouchableOpacity, View } = require('react-native');
const { styles } = require('../styles');
const { Section, CollapsibleSection, StatusPill, Metric, TextBlock, Button } = require('../components/shared');
const { notAvailable } = require('../lib/notAvailable');
const { formatDateTime, formatPercent } = require('../lib/datetime');
const { formatList } = require('../lib/lists');
const { recommendationLifecycle, yesNo, formatGuardrailFailures } = require('../lib/founderPresentation');
const {
  uniqueValues,
  groupRecommendations,
  filterRecommendations,
  withRecommendationFreshness,
  formatGuardrailChecks,
  marketRegimeText,
  rMultiple,
  committeeSummary,
  signalSummary,
  lifecycleSummary,
  exitPlan,
  probabilityRange,
  recommendationsSummaryText,
} = require('../lib/recommendations');

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
      <View style={styles.summaryCard}>
        <Text style={styles.summaryReason}>{recommendationsSummaryText(recommendations)}</Text>
        <Text style={styles.smallText}>
          Ordered from highest confidence to lowest. Expired ideas stay visible for reference, but execution is blocked until fresh
          analysis creates a new trade idea.
        </Text>
      </View>
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

module.exports = { Recommendations };
