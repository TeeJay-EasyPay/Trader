// Portfolio screen: capital/risk summary, AI-managed positions, trade history, broker
// diagnostics, and exposure detail. Extracted from App.js as part of AT-ED-011 Phase 2.

'use strict';

const React = require('react');
const { useState } = React;
const { Text, TouchableOpacity, View } = require('react-native');
const { styles } = require('../styles');
const { CollapsibleSection, Metric, TextBlock, Button, Empty } = require('../components/shared');
const { BrokerPanel } = require('../components/BrokerPanel');
const { ReportPanel } = require('../components/ReportPanel');
const { moneyOrText, historyMoneyOrText, formatByCurrency } = require('../lib/money');
const { formatDateTime } = require('../lib/datetime');
const { formatList } = require('../lib/lists');
const { formatJsonText } = require('../lib/json');
const { connectedFounderBrokers, formatReconciliation, positionOwnership, portfolioHeadline } = require('../lib/founderPresentation');
const { portfolioProjection } = require('../lib/cio');
const { sumBrokerFieldByCurrency } = require('../lib/portfolioPosition');
const {
  combinedTransactions,
  tradeHistorySummary,
  tradeHistoryBrokers,
  tradeKey,
  tradeTableRow,
  normalizeTradeRow,
  isOpenTrade,
  unavailableReason,
  formatHoldingDuration,
} = require('../lib/tradeHistory');

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

// 2026-08-21 Founder request: Trade History rebuilt as a real column table (Date | Symbol |
// Side | Price | P&L) instead of one dense sentence per trade - tapping a row still expands
// the same full TradeDetail below it (quantity, entry/exit reason, stop/target, etc.), which a
// five-column summary row was never meant to replace.
function TradeHistoryHeaderRow() {
  return (
    <View style={styles.tradeTableHeaderRow}>
      <Text style={[styles.tradeTableHeaderText, styles.tradeTableCellDate]}>Date</Text>
      <Text style={[styles.tradeTableHeaderText, styles.tradeTableCellSymbol]}>Symbol</Text>
      <Text style={[styles.tradeTableHeaderText, styles.tradeTableCellSide]}>Side</Text>
      <Text style={[styles.tradeTableHeaderText, styles.tradeTableCellPrice, styles.tradeTableCellTextRight]}>Price</Text>
      <Text style={[styles.tradeTableHeaderText, styles.tradeTableCellAmount, styles.tradeTableCellTextRight]}>Amount</Text>
      <Text style={[styles.tradeTableHeaderText, styles.tradeTableCellCommissionPct, styles.tradeTableCellTextRight]}>Comm %</Text>
      <Text style={[styles.tradeTableHeaderText, styles.tradeTableCellCommission, styles.tradeTableCellTextRight]}>Comm</Text>
      <Text style={[styles.tradeTableHeaderText, styles.tradeTableCellPnl, styles.tradeTableCellTextRight]}>P&L</Text>
    </View>
  );
}

function TradeHistoryRow({ item, onCommand }) {
  const [open, setOpen] = useState(false);
  const row = tradeTableRow(item);
  const pnlStyle = row.pnlSign === 'positive' ? styles.tradeTablePnlPositive : row.pnlSign === 'negative' ? styles.tradeTablePnlNegative : null;
  return (
    <View style={styles.tradeTableRow}>
      <TouchableOpacity style={styles.tradeTableRowTouchable} onPress={() => setOpen((value) => !value)}>
        <View style={styles.tradeTableRowCells}>
          <Text style={[styles.tradeTableCellText, styles.tradeTableCellDate]} numberOfLines={2}>{row.dateText}</Text>
          <Text style={[styles.tradeTableCellText, styles.tradeTableCellSymbol]} numberOfLines={1} adjustsFontSizeToFit>{row.symbol}</Text>
          <Text style={[styles.tradeTableCellText, styles.tradeTableCellSide]}>{row.side}</Text>
          <Text style={[styles.tradeTableCellTextRight, styles.tradeTableCellPrice]} numberOfLines={1} adjustsFontSizeToFit>{row.priceText}</Text>
          <Text style={[styles.tradeTableCellTextRight, styles.tradeTableCellAmount]} numberOfLines={1} adjustsFontSizeToFit>{row.amountText}</Text>
          <Text style={[styles.tradeTableCellTextRight, styles.tradeTableCellCommissionPct]} numberOfLines={1} adjustsFontSizeToFit>{row.commissionPctText}</Text>
          <Text style={[styles.tradeTableCellTextRight, styles.tradeTableCellCommission]} numberOfLines={1} adjustsFontSizeToFit>{row.commissionText}</Text>
          <Text style={[styles.tradeTableCellTextRight, styles.tradeTableCellPnl, pnlStyle]} numberOfLines={1} adjustsFontSizeToFit>{row.pnlText}</Text>
        </View>
        <Text style={styles.smallText}>{open ? 'Tap to collapse' : 'Tap for full detail'}</Text>
      </TouchableOpacity>
      {open ? (
        <View style={styles.tradeTableExpandedDetail}>
          <TradeDetail
            item={item}
            onForceExit={(trade) => onCommand('/force-managed-exit', { managed_exit_id: normalizeTradeRow(trade).managedExitId })}
          />
        </View>
      ) : null}
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
  // 2026-08-21 bug: this read `open_positions_detail`, a field NO broker panel actually
  // provides -- production payloads carry `positions`. The result was an AI-managed
  // positions list that was permanently empty for BOTH brokers, which is why the Founder
  // saw no Kraken holdings here despite holding 13 of them. Reads `positions` with the old
  // name kept first as a harmless fallback in case any payload shape still supplies it.
  const aiManagedPositions = brokerPanels.flatMap((broker) =>
    (broker.open_positions_detail || broker.positions || [])
      .map((position) => ({ position, broker, ownership: positionOwnership(position, broker.managed_exits) }))
      .filter((row) => row.ownership.isAiManaged)
  );
  const positionsRequiringAttention = (portfolio?.open_positions || []).filter((position) => Number(position.unrealized_pl || 0) < 0);
  const todaysPnl = portfolio?.todays_pnl;
  const headline = portfolioHeadline({
    openPositionsCount: portfolio?.open_positions ? portfolio.open_positions.length : null,
    pnlText: typeof todaysPnl === 'number' ? moneyOrText(Math.abs(todaysPnl)) : null,
    pnlIsPositive: typeof todaysPnl === 'number' ? todaysPnl >= 0 : null,
    atLossCount: positionsRequiringAttention.length,
  });

  // AT-ED-013 Section 8: 7/30/90-day figures only where evidence supports them - this backend
  // has no portfolio-value forecasting model, so portfolioProjection() always returns the
  // honest unavailable state (see lib/cio.js). Calculations above are untouched; this only adds
  // a clearly-labelled Forecast line beneath the Facts, per the directive's "distinguish Facts
  // from Forecasts" and "do NOT alter calculations, improve clarity only" instructions.
  const projection = portfolioProjection();

  return (
    <View>
      <View style={styles.summaryCard}>
        <Text style={styles.summaryReason}>{headline}</Text>
        {/* 2026-08-22 Founder-flagged: these four used moneyOrText() directly against
            `portfolio`, a figure blended across brokers regardless of currency -- Alpaca
            (USD) and Kraken (GBP) summed under one $ sign, the exact mistake AT-ED-017
            already fixed on Executive Briefing's equivalent card via sumBrokerFieldByCurrency/
            formatByCurrency. Sourced from status.brokers here for the same reason. */}
        <Metric label="Portfolio Value (Fact)" value={formatByCurrency(sumBrokerFieldByCurrency(status?.brokers, 'portfolio_value'))} />
        <Metric label="Cash Available (Fact)" value={formatByCurrency(sumBrokerFieldByCurrency(status?.brokers, 'cash_available'))} />
        <Metric label="Deployed Capital (Fact)" value={formatByCurrency(sumBrokerFieldByCurrency(status?.brokers, 'estimated_in_positions'))} />
        <Metric label="Today's P&L (Fact)" value={formatByCurrency(sumBrokerFieldByCurrency(status?.brokers, 'todays_pnl'))} />
        <Metric label="Open Positions" value={(portfolio?.open_positions || []).length} />
        <Metric label="Positions Requiring Attention" value={positionsRequiringAttention.length} />
        {positionsRequiringAttention.length ? (
          <TextBlock
            label="At a Loss"
            value={positionsRequiringAttention.map((position) => `${position.symbol || 'Unknown'}: ${moneyOrText(position.unrealized_pl)}`).join('\n')}
          />
        ) : null}
        <TextBlock label="Portfolio Projection (Forecast - 7/30/90 Day)" value={projection.reason} />
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
              <Metric label="Quantity" value={position.qty ?? position.quantity ?? 'Not available'} />
              {position.unrealized_pl !== undefined && position.unrealized_pl !== null ? (
                <Metric label="Unrealised Result" value={moneyOrText(position.unrealized_pl)} />
              ) : null}
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
        <Metric label="Daily P&L" value={formatByCurrency(summary.dailyPnlByCurrency)} />
        {/* Calendar day since midnight, deliberately distinct from the Trade Scorecard's
            rolling 24-hour window on the briefing -- see lib/tradeScorecard.js. */}
        <Metric label="Completed today (since midnight)" value={summary.completedTradesToday} />
        <Metric label="Open Positions" value={summary.openPositions} />
        {trades.length ? (
          <View style={styles.tradeTable}>
            <TradeHistoryHeaderRow />
            {trades.slice(0, 20).map((item, index) => (
              <TradeHistoryRow key={tradeKey(item, index)} item={item} onCommand={onCommand} />
            ))}
          </View>
        ) : (
          <Empty />
        )}
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

module.exports = { PortfolioCommandCentre };
