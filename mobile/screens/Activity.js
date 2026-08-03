// Activity screen: grouped autonomous timeline, why-no-trade funnel, and raw technical
// details. Extracted from App.js as part of AT-ED-011 Phase 2 (mobile modularisation).

'use strict';

const React = require('react');
const { useState } = React;
const { Text, View } = require('react-native');
const { styles } = require('../styles');
const { Section, CollapsibleSection, StatusPill, Metric, TextBlock, Button, Empty } = require('../components/shared');
const { formatDateTime } = require('../lib/datetime');
const { groupActivity, activityStatusTone, activitySeverityTone, noTradeTone } = require('../lib/founderPresentation');

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

module.exports = { AutonomousActivity };
