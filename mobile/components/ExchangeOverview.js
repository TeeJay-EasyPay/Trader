'use strict';
const React = require('react');
const { Text, View } = require('react-native');
const { Section, CollapsibleSection, Metric } = require('./shared');
const { styles } = require('../styles');
const { exchangeName, currencyFor, exchangeMoney, activityByExchange, periodLabel } = require('../lib/exchangeOverview');
const { formatDateTime } = require('../lib/datetime');
const { exchangePalette } = require('../lib/palette');
function ExchangeOverview({ brokers = [], activity, detailed = false, children }) {
  return <Section bare={detailed} title={detailed ? 'Your accounts' : 'Activity by exchange'}>
    {!detailed && <Text style={styles.smallText}>{periodLabel(activity?.period)} · evidence updated {activity?.generated_at ? formatDateTime(activity.generated_at) : 'unknown'}</Text>}
    {!brokers.length && <Text style={styles.bodyText}>Account evidence has not loaded.</Text>}
    {brokers.map(broker => {
      const currency = currencyFor(broker), counts = activityByExchange(activity, broker);
      const money = value => exchangeMoney(value, currency);
      return <View key={broker.broker} style={[styles.exchangeCard, exchangePalette(broker.broker)]}>
        <Text style={styles.cardTitle}>{exchangeName(broker)} · {currency || 'Currency unknown'}</Text>
        <Text style={styles.smallText}>{broker.account_mode || 'Account mode unknown'} · whole account</Text>
        {detailed ? <>
          <View style={styles.accountMetricGrid}>
            {[['Account value', broker.portfolio_value], ['Account change today', broker.todays_pnl], ['Cash', broker.cash_available], ['In investments', broker.estimated_in_positions]].map(([label, value], index) => <View key={label} style={[styles.accountMetricTile, { flexBasis: '24%', minWidth: 140 }, index % 2 !== 0 && { borderLeftWidth: 1, borderLeftColor: '#DADDE8', paddingLeft: 12 }]}>
              <Text style={styles.smallText}>{label}</Text>
              <Text style={[styles.accountMetricValue, label === 'Account change today' && typeof value === 'number' && (value > 0 ? styles.tradeTablePnlPositive : value < 0 ? styles.tradeTablePnlNegative : null)]}>{money(value)}</Text>
            </View>)}
          </View>
          <Text style={styles.smallText}>Includes manual holdings · {broker.captured_at ? formatDateTime(broker.captured_at) : 'Snapshot time unavailable'}</Text>
          <Text style={styles.smallText}>Account value includes cash and investments; it is not cash available to trade.</Text>
        </> : counts.available ? <>
          <Text style={styles.smallText}>Snapshot {broker.captured_at ? formatDateTime(broker.captured_at) : 'time unavailable'}</Text>
          <Metric label="Account change today" value={money(broker.todays_pnl)} />
          <Text style={styles.bodyText}>{counts.checks} asset checks · {counts.candidates} candidates</Text>
          <Text style={styles.bodyText}>{counts.fills} orders with fills recorded</Text>
          <CollapsibleSection title="Activity detail" defaultExpanded={false}>
            <Text style={styles.smallText}>Includes manual holdings. Snapshot {broker.captured_at ? formatDateTime(broker.captured_at) : 'time unavailable'}.</Text>
            <Text style={styles.smallText}>{counts.orders} identified orders observed, including protection. Repeated research checks are not unique ideas. Fills may be partial; an observed order is not necessarily a new submission.</Text>
            {!!counts.unidentified && <Text style={styles.smallText}>{counts.unidentified} records lack order IDs and are excluded from order counts.</Text>}
          </CollapsibleSection>
        </> : <><Metric label="Account change today" value={money(broker.todays_pnl)} /><Text style={styles.smallText}>Activity breakdown is unavailable. Includes manual holdings.</Text></>}
      </View>;
    })}
    {children}
  </Section>;
}
module.exports = { ExchangeOverview };
