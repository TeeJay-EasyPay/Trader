'use strict';
const React = require('react');
const { Text, View } = require('react-native');
const { Section, CollapsibleSection, Metric } = require('./shared');
const { styles } = require('../styles');
const { exchangeName, currencyFor, exchangeMoney, activityByExchange, periodLabel } = require('../lib/exchangeOverview');
const { formatDateTime } = require('../lib/datetime');
function ExchangeOverview({ brokers = [], activity, detailed = false, children }) {
  return <Section title={detailed ? 'Your accounts' : 'Activity by exchange'}>
    {!detailed && <Text style={styles.smallText}>{periodLabel(activity?.period)} · evidence updated {activity?.generated_at ? formatDateTime(activity.generated_at) : 'unknown'}</Text>}
    {!brokers.length && <Text style={styles.bodyText}>Account evidence has not loaded.</Text>}
    {brokers.map(broker => {
      const currency = currencyFor(broker), counts = activityByExchange(activity, broker);
      const money = value => exchangeMoney(value, currency);
      return <View key={broker.broker} style={styles.compactRow}>
        <Text style={styles.cardTitle}>{exchangeName(broker)} · {currency || 'Currency unknown'}</Text>
        <Text style={styles.smallText}>{broker.account_mode || 'Account mode unknown'} · whole account, including any manual holdings</Text>
        <Text style={styles.smallText}>Snapshot {broker.captured_at ? formatDateTime(broker.captured_at) : 'time unavailable'}</Text>
        {detailed && <Metric label="Account value" value={money(broker.portfolio_value)} />}
        <Metric label="Account change today" value={money(broker.todays_pnl)} />
        {detailed ? <>
          <Metric label="Cash" value={money(broker.cash_available)} />
          <Metric label="In investments" value={money(broker.estimated_in_positions)} />
        </> : counts.available ? <>
          <Text style={styles.bodyText}>{counts.checks} asset checks · {counts.candidates} candidates</Text>
          <Text style={styles.bodyText}>{counts.fills} orders with fills recorded</Text>
          <CollapsibleSection title="Activity detail" defaultExpanded={false}>
            <Text style={styles.smallText}>{counts.orders} identified orders observed, including protection. Repeated research checks are not unique ideas. Fills may be partial; an observed order is not necessarily a new submission.</Text>
            {!!counts.unidentified && <Text style={styles.smallText}>{counts.unidentified} records lack order IDs and are excluded from order counts.</Text>}
          </CollapsibleSection>
        </> : <Text style={styles.smallText}>Activity breakdown is unavailable.</Text>}
      </View>;
    })}
    {children}
  </Section>;
}
module.exports = { ExchangeOverview };
