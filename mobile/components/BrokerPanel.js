// Per-broker evidence card, shared by the Dashboard and Portfolio screens.
// Extracted from App.js as part of AT-ED-011 Phase 2 (mobile modularisation).

'use strict';

const React = require('react');
const { Text, View } = require('react-native');
const { styles } = require('../styles');
const { StatusPill, Metric, TextBlock, Button, CollapsibleSection } = require('./shared');
const { notAvailable } = require('../lib/notAvailable');
const {
  brokerOverallReadiness,
  brokerReadinessSentence,
  krakenWholeAccountNote,
  enabledDisabled,
  yesNo,
  formatKrakenAssets,
  formatRawKrakenBalances,
} = require('../lib/founderPresentation');
const { brokerMoney, gbpOrText } = require('../lib/money');
const { formatDateTime, todayIso } = require('../lib/datetime');
const { formatListInline } = require('../lib/lists');
const { describeLatestTrade } = require('../lib/tradeHistory');

// AT-ED-012: restructured so the Founder gets the story (is it connected, is it trading, where
// is the money) before the raw evidence. The deep governance/ledger/raw-balance detail that
// used to render fully open (roughly 30-45 fields per broker) now lives behind one collapsed
// "Full Broker Diagnostics" section - the numbers themselves are unchanged, only what's shown
// by default. Kraken's money fields are relabelled, not recalculated - see the Phase 4
// financial-terminology audit in Founder_Experience_Review.md for why "Buying Power" next to
// "Cash" was misleading (one is a whole personal account's real cash, the other a static
// allocation ceiling) and where the actual AI-buying-power figure already existed in the data.
function BrokerPanel({ broker, onCommand, onReport }) {
  const label = broker.label || notAvailable(broker.broker);
  const readiness = brokerOverallReadiness(broker);
  const isKraken = broker.broker === 'kraken';
  const aiCapitalLedger = broker.trading_permissions?.ai_capital_ledger;
  return (
    <View style={styles.compactRow}>
      <Text style={styles.cardTitle}>{label}</Text>
      <StatusPill label={readiness.label} tone={readiness.tone} />
      <Text style={styles.bodyText}>{brokerReadinessSentence(broker)}</Text>

      {isKraken ? (
        <>
          <Text style={styles.smallText}>{krakenWholeAccountNote(broker)}</Text>
          <Metric label="Whole Kraken Account Value" value={brokerMoney(broker, broker.portfolio_value)} />
          <Metric label="Whole Account Cash" value={brokerMoney(broker, broker.cash_available)} />
          <Metric
            label="AI Buying Power"
            value={aiCapitalLedger?.available_cash_gbp !== undefined ? gbpOrText(aiCapitalLedger.available_cash_gbp) : 'Not available yet'}
          />
          <Metric label="AI Allocation Limit" value={brokerMoney(broker, broker.buying_power)} />
        </>
      ) : (
        <>
          <Metric label="Portfolio Value" value={brokerMoney(broker, broker.portfolio_value)} />
          <Metric label="Cash Available" value={brokerMoney(broker, broker.cash_available)} />
          <Metric label="Buying Power" value={brokerMoney(broker, broker.buying_power)} />
        </>
      )}
      <Metric label="Estimated In Positions" value={brokerMoney(broker, broker.estimated_in_positions)} />
      <Metric label="Open Positions" value={broker.open_positions} />
      <Metric label="Today's P&L" value={brokerMoney(broker, broker.todays_pnl)} />

      <Metric label="Latest Successful Check-in" value={broker.latest_successful_poll ? formatDateTime(broker.latest_successful_poll) : 'Not available yet'} />
      <Metric
        label={isKraken ? 'Latest AI-Managed Trade' : 'Latest Paper Trade'}
        value={broker.latest_confirmed_trade ? describeLatestTrade({
          type: 'fill',
          symbol: broker.latest_confirmed_trade.symbol,
          side: broker.latest_confirmed_trade.side,
          qty: broker.latest_confirmed_trade.qty,
          price: broker.latest_confirmed_trade.filled_avg_price,
          status: broker.latest_confirmed_trade.status,
        }) : 'None recorded yet'}
      />
      <Metric label="Research Status" value={broker.research_status} />

      <CollapsibleSection
        title="Full Broker Diagnostics"
        subtitle="Every governance, permission, ledger, and raw-balance detail behind the summary above."
      >
        <Metric label="Mode" value={isKraken ? 'Live' : 'Paper'} />
        <Metric label="Connection Status" value={broker.connection_status} />
        <Metric label="Auto Trading" value={broker.auto_trading_status || enabledDisabled(broker.auto_trading_enabled)} />
        <Metric label="New Entries Allowed" value={readiness.newEntriesAllowed === null ? 'Unknown' : yesNo(readiness.newEntriesAllowed)} />
        {broker.block_reason ? <Metric label="Block Reason" value={broker.block_reason} /> : null}
        <Metric label="Week P&L" value={brokerMoney(broker, broker.week_pnl)} />
        <Metric label="Month P&L" value={brokerMoney(broker, broker.month_pnl)} />
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
        <Metric label="Due Diligence Status" value={broker.due_diligence_status} />
        <TradingPermissions permissions={broker.trading_permissions} />
      </CollapsibleSection>

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

module.exports = { BrokerPanel, TradingPermissions };
