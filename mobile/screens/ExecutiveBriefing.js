// AT-ED-016: the Executive Briefing evolves from AT-ED-015's flowing-but-still-siloed structure
// into the directive's exact 11-section CIO-meeting format: Executive Summary, Current Position,
// What Happened Overnight, Market Assessment, Investment Thesis, Forecast Centre, Principal
// Risks, Principal Opportunities, Founder Actions, Investment Organisation, Closing
// Recommendation. This is an evolution, not a rewrite - every AT-ED-013/014/015/015.1 module is
// retained and extended (see Executive_Briefing_Evolution_Design_Review.md for the full
// old-section -> new-section mapping and the Part 2 forecast-engine evidence-availability audit).
// Investment Rhythm and Executive Messages remain as below-the-fold supporting detail, not part
// of the ~3-minute main read. The Trading Organisation card AT-ED-015 introduced is retired this
// pass - Section 10's Investment Organisation now covers "is my organisation healthy" with real
// per-department evidence, so the two cards would otherwise say the same thing twice.
//
// Every number and sentence still traces to real evidence via lib/cio.js, lib/forecasting.js,
// lib/forecastEngine.js, lib/forecastFactors.js, lib/forecastHistory.js,
// lib/forecastAccountability.js, lib/investmentThesis.js, lib/principalRisks.js,
// lib/principalOpportunities.js, lib/founderActions.js, lib/portfolioPosition.js, and
// lib/investmentCommittee.js - nothing here is a new AI system or a fabricated claim.

'use strict';

const React = require('react');
const { Text, View } = require('react-native');
const { styles } = require('../styles');
const { Section, CollapsibleSection, StatusPill, Metric, TextBlock, Button } = require('../components/shared');
const { notAvailable, explainMissing } = require('../lib/notAvailable');
const { moneyOrText } = require('../lib/money');
const { formatPercent } = require('../lib/datetime');
const { summaryTone, riskTone, connectedFounderBrokers } = require('../lib/founderPresentation');
const {
  cioGreeting,
  cioExecutiveSummary,
  cioOvernightActivity,
  cioMarketOutlook,
  cioAverageConfidence,
  cioFounderActionRequired,
  cioNoActionReason,
  cioClosingRecommendation,
  cioExecutiveBriefingSummary,
} = require('../lib/cio');
const { currentInvestmentThesis, alternativeThesis, evidenceStrength } = require('../lib/investmentThesis');
const { deriveConviction } = require('../lib/forecasting');
const { normalizeClosedTradesFromAttribution, projectPortfolioHorizons, tradeStatistics } = require('../lib/forecastEngine');
const { evaluateFactors, summarizeFactors } = require('../lib/forecastFactors');
const { buildInvestmentRhythm } = require('../lib/investmentRhythm');
const { buildInvestmentCommittee } = require('../lib/investmentCommittee');
const { buildRiskCards } = require('../lib/principalRisks');
const { buildOpportunityCards } = require('../lib/principalOpportunities');
const { buildFounderActions } = require('../lib/founderActions');
const { weekToDatePnl, monthToDatePnl, largestPosition } = require('../lib/portfolioPosition');
const { useForecastHistory } = require('../hooks/useForecastHistory');

function marketOutlookText(marketCentre) {
  return cioMarketOutlook({
    marketHealth: marketCentre?.market_health,
    currentRegime: marketCentre?.current_market_regime,
    cryptoHealth: marketCentre?.crypto_health,
    upcomingRisks: marketCentre?.upcoming_risks,
  });
}

function convictionTone(level) {
  return level === 'High' ? 'good' : level === 'Low' ? 'danger' : level === 'Medium' ? 'warn' : 'neutral';
}

// --- Section 1: Executive Summary --------------------------------------------------------------

function ExecutiveSummaryCard({ status, activity, marketCentre }) {
  const evidence = status?.world_class_evidence || {};
  const executive = status?.founder_experience?.executive_dashboard || {};
  const activitySummary = activity?.summary || {};
  const headlineSummary = cioExecutiveSummary({ headline: executive.headline, whatToDo: executive.what_to_do, whatToWorryAbout: executive.what_to_worry_about });
  const overnightSummary = cioOvernightActivity({
    researchRuns: activitySummary.research?.runs,
    recommendationsCreated: activitySummary.research?.recommendations_created,
    ordersSubmitted: activitySummary.execution?.orders_submitted,
  });
  const marketSummary = marketOutlookText(marketCentre);
  const comfortSentence = executive.portfolio_health ? `I currently read our position as: ${executive.portfolio_health}.` : null;
  return (
    <View style={styles.summaryCard}>
      <Text style={styles.cardTitle}>{cioGreeting()}</Text>
      <StatusPill label={notAvailable(evidence.first_conclusion)} tone={summaryTone(evidence.first_conclusion)} />
      <Text style={styles.summaryReason}>
        {cioExecutiveBriefingSummary({ greeting: null, headlineSummary, overnightSummary, marketSummary, comfortSentence })}
      </Text>
    </View>
  );
}

// --- Section 2: Current Position ----------------------------------------------------------------

function CurrentPositionCard({ portfolio, status, brokerPanels }) {
  const wtd = weekToDatePnl(status?.brokers);
  const mtd = monthToDatePnl(status?.brokers);
  const winner = largestPosition(portfolio?.open_positions, 'winning');
  const loser = largestPosition(portfolio?.open_positions, 'losing');
  const deployedPct = status?.founder_experience?.portfolio_command?.portfolio_allocation?.deployed_pct;
  return (
    <Section title="Current Position">
      <Metric label="Portfolio Value" value={moneyOrText(portfolio?.portfolio_value)} />
      <Metric label="Today's P&L" value={moneyOrText(portfolio?.todays_pnl)} />
      <Metric label="Week-to-Date P&L" value={wtd !== null ? moneyOrText(wtd) : explainMissing('week-to-date P&L', 'no broker has reported a week_pnl figure yet')} />
      <Metric label="Month-to-Date P&L" value={mtd !== null ? moneyOrText(mtd) : explainMissing('month-to-date P&L', 'no broker has reported a month_pnl figure yet')} />
      <Metric label="Open Positions" value={(portfolio?.open_positions || []).length} />
      <Metric label="Cash Available" value={moneyOrText(portfolio?.cash_available)} />
      <Metric label="Capital Deployed" value={moneyOrText(portfolio?.deployed_capital)} />
      <Metric label="Current Allocation" value={typeof deployedPct === 'number' ? formatPercent(deployedPct) : explainMissing('current allocation', 'deployed-capital evidence is incomplete')} />
      <Metric label="Largest Winning Position" value={winner ? `${winner.symbol}: ${moneyOrText(winner.unrealizedPl)}` : explainMissing('largest winning position', 'no open position currently shows an unrealised gain')} />
      <Metric label="Largest Losing Position" value={loser ? `${loser.symbol}: ${moneyOrText(loser.unrealizedPl)}` : explainMissing('largest losing position', 'no open position currently shows an unrealised loss')} />
      <Metric label="Brokers" value={brokerPanels.length ? `${brokerPanels.map((item) => item.label || item.broker).join(', ')} connected` : explainMissing('broker status', 'Alpaca and Kraken are not both visible from the hosted API')} />
    </Section>
  );
}

// --- Section 3: What Happened Overnight ---------------------------------------------------------

function OvernightNarrativeCard({ activity, connectionReadiness }) {
  const activitySummary = activity?.summary || {};
  const noTrade = activity?.why_no_trade || {};
  const overnightSummary = cioOvernightActivity({
    researchRuns: activitySummary.research?.runs,
    recommendationsCreated: activitySummary.research?.recommendations_created,
    ordersSubmitted: activitySummary.execution?.orders_submitted,
  });
  return (
    <Section title="What Happened Overnight">
      <Text style={styles.bodyText}>{overnightSummary}</Text>
      <TextBlock label="Trades Considered and Rejected" value={noTrade.conclusion || 'No no-trade evidence recorded for this period.'} />
      <Metric
        label="Risk Review"
        value={connectionReadiness
          ? (connectionReadiness.trade_ready ? 'Completed - all readiness checks currently pass.' : (connectionReadiness.note || 'Completed - one or more checks flagged for attention.'))
          : explainMissing('risk review', 'no readiness evidence has been returned yet')}
      />
    </Section>
  );
}

// --- Section 4: Market Assessment ---------------------------------------------------------------

function MarketAssessmentCard({ marketCentre, themesCount }) {
  return (
    <Section title="Market Assessment">
      <Text style={styles.bodyText}>{marketOutlookText(marketCentre)}</Text>
      <Metric label="Themes Tracked" value={themesCount} />
    </Section>
  );
}

// --- Section 5: Investment Thesis (positive/negative factors, unknowns, assumptions, ---------
// --- catalysts, evidence strength, alternative view) ------------------------------------------

function FactorList({ label, factors }) {
  if (!factors.length) {
    return <TextBlock label={label} value={null} />;
  }
  return <TextBlock label={label} value={factors.map((factor) => `${factor.name}: ${factor.note}`).join('\n')} />;
}

function InvestmentThesisSection({ themes, recommendations, marketCentre, factors, factorSummary, conviction }) {
  const thesis = currentInvestmentThesis({ themes, recommendations });
  const alternative = alternativeThesis({ themes });
  const positiveFactors = factors.filter((factor) => factor.available && factor.direction === 'positive');
  const negativeFactors = factors.filter((factor) => factor.available && factor.direction === 'negative');
  const unknowns = factors.filter((factor) => !factor.available);
  const catalysts = (themes || []).filter((item) => item && item.theme).slice(0, 1).map((item) => item.current_outlook || item.summary).filter(Boolean);
  return (
    <Section title="Investment Thesis">
      <Text style={styles.bodyText}>{thesis.statement}</Text>
      <StatusPill label={`Conviction: ${conviction.level}`} tone={convictionTone(conviction.level)} />
      <Text style={styles.smallText}>{conviction.reason}</Text>
      <FactorList label="Positive Factors" factors={positiveFactors} />
      <FactorList label="Negative Factors" factors={negativeFactors} />
      <FactorList label="Unknowns" factors={unknowns} />
      <TextBlock
        label="Assumptions"
        value={['Assumes the historical evidence behind each factor above remains representative going forward.', 'Does not assume any factor not listed above (e.g. macro events, economic calendar) - no evidence source exists for those in this app yet.'].join('\n')}
      />
      <TextBlock label="Expected Catalysts" value={catalysts.length ? catalysts.join('\n') : null} />
      <Metric label="Evidence Strength" value={evidenceStrength(factorSummary)} />
      <TextBlock label="Alternative View" value={alternative.statement} />
    </Section>
  );
}

// --- Section 6: Forecast Centre -----------------------------------------------------------------

function ForecastHorizonCard({ horizon }) {
  return (
    <View style={styles.compactRow}>
      <Text style={styles.cardTitle}>{horizon.horizon}</Text>
      {horizon.available ? (
        <>
          <Metric label="Base Case" value={moneyOrText(horizon.baseCase.expectedValue)} />
          <Metric label="Bull Case" value={moneyOrText(horizon.bullCase.expectedValue)} />
          <Metric label="Bear Case" value={moneyOrText(horizon.bearCase.expectedValue)} />
          <Metric label="Expected Return" value={horizon.expectedReturnPct !== null ? formatPercent(horizon.expectedReturnPct) : explainMissing('expected return', 'no current portfolio value is available yet')} />
          <Metric label="Probability (historical win rate)" value={formatPercent(horizon.probability)} />
          <StatusPill label={`Confidence: ${horizon.confidence}`} tone={horizon.confidence === 'High' ? 'good' : horizon.confidence === 'Low' ? 'warn' : 'neutral'} />
          <Text style={styles.smallText}>{horizon.confidenceReason}</Text>
          <TextBlock label="Expected Volatility" value={horizon.expectedVolatility.reason} />
          <TextBlock label="Expected Drawdown" value={horizon.expectedDrawdown.reason} />
          <TextBlock label="Why This Forecast Exists" value={horizon.explanation} />
        </>
      ) : (
        <Text style={styles.bodyText}>{horizon.reason}</Text>
      )}
    </View>
  );
}

function ForecastCentreCard({ portfolio, performanceAttribution }) {
  const closedTrades = normalizeClosedTradesFromAttribution(performanceAttribution);
  const horizons = projectPortfolioHorizons({ closedTrades, currentPortfolioValue: portfolio?.portfolio_value });
  return (
    <CollapsibleSection title="Forecast Centre" subtitle="Tomorrow, 7 days, 30 days, quarter, and year end - base, bull, and bear cases, each with a written explanation." defaultExpanded={true}>
      {horizons.map((horizon) => <ForecastHorizonCard key={horizon.horizonKey} horizon={horizon} />)}
    </CollapsibleSection>
  );
}

function ForecastAccountabilityCard({ summary }) {
  return (
    <CollapsibleSection title="Forecast Accountability" subtitle="Every forecast becomes a promise - tracked here against what actually happened.">
      {summary.available ? (
        <>
          <Metric label="Forecasts Tracked" value={summary.trackRecord.length} />
          <Metric label="Directional Accuracy" value={summary.accuracy !== null ? formatPercent(summary.accuracy) : explainMissing('directional accuracy', 'no forecast has been resolved against a real outcome yet')} />
        </>
      ) : (
        <Text style={styles.bodyText}>{summary.reason}</Text>
      )}
    </CollapsibleSection>
  );
}

// --- Section 7: Principal Risks -------------------------------------------------------------

function RiskCard({ risk }) {
  return (
    <View style={styles.compactRow}>
      <Text style={styles.cardTitle}>⚠ {risk.title}</Text>
      <Metric label="Impact" value={risk.impact} />
      <Metric label="Likelihood" value={risk.likelihood} />
      <Metric label="Monitoring Owner" value={risk.monitoringOwner} />
      <Metric label="Estimated Portfolio Effect" value={risk.estimatedPortfolioEffect} />
      <TextBlock label="Potential Effect" value={risk.potentialEffect} />
      <TextBlock label="Mitigation" value={risk.mitigation} />
    </View>
  );
}

function PrincipalRisksSection({ marketCentre, portfolio }) {
  const positionsAtLoss = (portfolio?.open_positions || [])
    .filter((position) => Number(position.unrealized_pl) < 0)
    .map((position) => ({ symbol: position.symbol, unrealizedPl: position.unrealized_pl }));
  const risks = buildRiskCards({ upcomingRisks: marketCentre?.upcoming_risks, positionsAtLoss, portfolioValue: portfolio?.portfolio_value });
  return (
    <Section title="Principal Risks">
      {risks.length ? risks.map((risk, index) => <RiskCard key={`${risk.title}-${index}`} risk={risk} />) : <Text style={styles.bodyText}>No principal risks are currently flagged in the evidence.</Text>}
    </Section>
  );
}

// --- Section 8: Principal Opportunities -----------------------------------------------------

function OpportunityCard({ opportunity }) {
  return (
    <View style={styles.compactRow}>
      <Text style={styles.cardTitle}>{opportunity.title}</Text>
      <TextBlock label="Why" value={opportunity.why} />
      <TextBlock label="Catalyst" value={opportunity.catalyst} />
      <Metric label="Evidence" value={opportunity.evidence} />
      <Metric label="Expected Benefit" value={opportunity.expectedBenefit} />
      <Metric label="Confidence" value={opportunity.confidence} />
      <Metric label="Time Horizon" value={opportunity.timeHorizon} />
    </View>
  );
}

function PrincipalOpportunitiesSection({ recommendations, themes }) {
  const opportunities = buildOpportunityCards({ recommendations, themes });
  return (
    <Section title="Principal Opportunities">
      {opportunities.length ? opportunities.map((opportunity, index) => <OpportunityCard key={`${opportunity.title}-${index}`} opportunity={opportunity} />) : <Text style={styles.bodyText}>No new opportunities currently clear our evidence bar.</Text>}
    </Section>
  );
}

// --- Section 9: Founder Actions (never bare "no action required") ---------------------------

function FounderActionCard({ action }) {
  return (
    <View style={styles.compactRow}>
      <Text style={styles.cardTitle}>{action.what}</Text>
      <TextBlock label="Why" value={action.why} />
      <Metric label="Expected Benefit" value={action.expectedBenefit} />
      <Metric label="Risk" value={action.risk} />
      <Metric label="Deadline" value={action.deadline} />
      <TextBlock label="If You Do Nothing" value={action.ifNothing} />
    </View>
  );
}

function FounderActionsSection({ recommendations, unresolvedIncidentCount, connectionReadiness, onOpenRecommendations, onRefresh }) {
  const actions = buildFounderActions({ recommendations, unresolvedIncidentCount });
  const outstanding = (recommendations || []).filter((item) => item.freshness_status !== 'Expired').length;
  const noActionReason = cioNoActionReason({
    tradeReady: Boolean(connectionReadiness?.trade_ready),
    outstandingRecommendationsCount: outstanding,
    unresolvedIncidentCount,
    readinessNote: connectionReadiness?.note,
  });
  return (
    <Section title="Founder Actions">
      {actions.length ? (
        actions.map((action, index) => <FounderActionCard key={`${action.what}-${index}`} action={action} />)
      ) : (
        <Text style={styles.bodyText}>{noActionReason || cioFounderActionRequired({ outstandingRecommendationsCount: outstanding, unresolvedIncidentCount })}</Text>
      )}
      <View style={styles.buttonGrid}>
        <Button label="Review Recommendations" onPress={onOpenRecommendations} />
        <Button label="Refresh" tone="neutral" onPress={onRefresh} />
      </View>
    </Section>
  );
}

// --- Section 10: Investment Organisation (nine departments) ---------------------------------

function InvestmentOrganisationCard({ status, dailyLearning, activity, connectionReadiness, forecastStats, brokerPanels, onOpenOperations }) {
  const departments = buildInvestmentCommittee({
    operationsHealth: status?.operations_health,
    learningSummary: dailyLearning?.evidence_summary,
    marketCentre: status?.founder_experience?.market_intelligence_centre,
    recommendationSummary: status?.recommendation_summary,
    connectionReadiness,
    activitySummary: activity?.summary?.execution,
    forecastStats,
    brokerPanels,
    portfolioIntelligence: status?.world_class_evidence?.portfolio_intelligence,
  });
  const reportingCount = departments.filter((department) => department.hasEvidence).length;
  return (
    <Section title="Investment Organisation">
      <Text style={styles.bodyText}>
        {reportingCount} of {departments.length} departments currently report real evidence. This is how each contributed today.
      </Text>
      {departments.map((department) => (
        <View key={department.name} style={styles.compactRow}>
          <Text style={styles.cardTitle}>{department.name}</Text>
          <StatusPill label={department.hasEvidence ? 'Reporting' : 'No Evidence Yet'} tone={department.hasEvidence ? 'good' : 'neutral'} />
          <Text style={styles.bodyText}>{department.conclusion}</Text>
        </View>
      ))}
      <View style={styles.buttonGrid}>
        <Button label="Open Operations" tone="neutral" onPress={onOpenOperations} />
      </View>
    </Section>
  );
}

// --- Section 11: Closing Recommendation -------------------------------------------------------

function ClosingRecommendationCard({ themes, recommendations, marketCentre, averageConfidence, winRate, outstandingCount, unresolvedIncidentCount }) {
  const thesis = currentInvestmentThesis({ themes, recommendations });
  const conviction = deriveConviction({ marketHealthTone: riskTone(marketCentre?.market_health), averageConfidence, winRate });
  return (
    <View style={styles.summaryCard}>
      <Text style={styles.cardTitle}>Closing Recommendation</Text>
      <Text style={styles.summaryReason}>
        {cioClosingRecommendation({
          convictionLevel: conviction.level,
          thesisAvailable: thesis.available,
          actionRequired: Boolean(outstandingCount || unresolvedIncidentCount),
        })}
      </Text>
    </View>
  );
}

// --- Below the fold: Investment Rhythm, Executive Messages -----------------------------------

function rhythmMark(stage, isCurrent) {
  if (stage.status === 'completed') return '✓';
  if (isCurrent) return '▶';
  return '○';
}

function InvestmentRhythmTimeline({ status, founderBriefCreatedAt }) {
  const rhythm = buildInvestmentRhythm({
    lastEquityResearchCompletedAt: status?.operations_health?.last_equity_research?.completed_at,
    lastCryptoResearchCompletedAt: status?.operations_health?.last_crypto_research?.completed_at,
    founderBriefCreatedAt,
  });
  return (
    <CollapsibleSection title="Investment Rhythm" subtitle="Today's schedule, current stage highlighted.">
      {rhythm.stages.map((stage) => {
        const isCurrent = rhythm.scheduledCurrent?.key === stage.key;
        return (
          <View key={stage.key} style={styles.compactRow}>
            <Text style={isCurrent ? styles.cardTitle : styles.bodyText}>
              {rhythmMark(stage, isCurrent)} {stage.name}{isCurrent ? ' (current stage)' : ''}
            </Text>
          </View>
        );
      })}
    </CollapsibleSection>
  );
}

function ExecutiveMessagesCard({ status }) {
  const evidence = status?.world_class_evidence || {};
  const messages = evidence.unavailable || [];
  if (!messages.length) {
    return null;
  }
  return (
    <CollapsibleSection title="Executive Messages" subtitle="Items that materially affect an investment decision.">
      {messages.map((item) => (
        <View key={item.field} style={styles.compactRow}>
          <Text style={styles.cardTitle}>{item.field}</Text>
          <Text style={styles.bodyText}>{item.reason}</Text>
        </View>
      ))}
    </CollapsibleSection>
  );
}

// --- ExecutiveBriefing (assembly) -------------------------------------------------------------

function ExecutiveBriefing({
  status,
  portfolio,
  recommendations,
  activity,
  themes,
  dailyLearning,
  performanceAttribution,
  brief,
  onRefresh,
  onOpenOperations,
  onOpenRecommendations,
}) {
  const brokerPanels = connectedFounderBrokers(status?.brokers || []);
  const marketCentre = status?.founder_experience?.market_intelligence_centre || {};
  const confidence = cioAverageConfidence(recommendations);
  const winRate = dailyLearning?.trade_outcomes?.win_rate;
  const connectionReadiness = status?.connection_readiness;
  const outstandingCount = (recommendations || []).filter((item) => item.freshness_status !== 'Expired').length;
  const unresolvedIncidentCount = status?.operations_health?.incidents?.length || 0;

  const closedTrades = normalizeClosedTradesFromAttribution(performanceAttribution);
  const stats = tradeStatistics(closedTrades);
  const factors = evaluateFactors({
    stats,
    portfolio,
    marketCentre,
    learningWinRate: winRate,
    averageConfidence: confidence,
    recommendationSummary: status?.recommendation_summary,
    connectionReadiness,
  });
  const factorSummary = summarizeFactors(factors);
  const conviction = deriveConviction({ marketHealthTone: riskTone(marketCentre?.market_health), averageConfidence: confidence, winRate });

  // AT-ED-016 Part 3: real, on-device forecast accountability - stores today's available
  // horizons (deduped to roughly once/day) and resolves any earlier forecast whose target date
  // has passed against the current, real portfolio value.
  const horizons = projectPortfolioHorizons({ closedTrades, currentPortfolioValue: portfolio?.portfolio_value });
  const { summary: forecastAccountabilitySummary } = useForecastHistory({ horizons, currentPortfolioValue: portfolio?.portfolio_value });

  return (
    <View>
      <ExecutiveSummaryCard status={status} activity={activity} marketCentre={marketCentre} />
      <CurrentPositionCard portfolio={portfolio} status={status} brokerPanels={brokerPanels} />
      <OvernightNarrativeCard activity={activity} connectionReadiness={connectionReadiness} />
      <MarketAssessmentCard marketCentre={marketCentre} themesCount={(themes || []).length} />
      <InvestmentThesisSection themes={themes} recommendations={recommendations} marketCentre={marketCentre} factors={factors} factorSummary={factorSummary} conviction={conviction} />
      <ForecastCentreCard portfolio={portfolio} performanceAttribution={performanceAttribution} />
      <ForecastAccountabilityCard summary={forecastAccountabilitySummary} />
      <PrincipalRisksSection marketCentre={marketCentre} portfolio={portfolio} />
      <PrincipalOpportunitiesSection recommendations={recommendations} themes={themes} />
      <FounderActionsSection recommendations={recommendations} unresolvedIncidentCount={unresolvedIncidentCount} connectionReadiness={connectionReadiness} onOpenRecommendations={onOpenRecommendations} onRefresh={onRefresh} />
      <InvestmentOrganisationCard status={status} dailyLearning={dailyLearning} activity={activity} connectionReadiness={connectionReadiness} forecastStats={stats} brokerPanels={status?.brokers} onOpenOperations={onOpenOperations} />
      <ClosingRecommendationCard
        themes={themes}
        recommendations={recommendations}
        marketCentre={marketCentre}
        averageConfidence={confidence}
        winRate={winRate}
        outstandingCount={outstandingCount}
        unresolvedIncidentCount={unresolvedIncidentCount}
      />

      <InvestmentRhythmTimeline status={status} founderBriefCreatedAt={brief?.created_at} />
      <ExecutiveMessagesCard status={status} />
    </View>
  );
}

module.exports = {
  ExecutiveBriefing,
  ExecutiveSummaryCard,
  CurrentPositionCard,
  OvernightNarrativeCard,
  MarketAssessmentCard,
  InvestmentThesisSection,
  ForecastCentreCard,
  ForecastAccountabilityCard,
  PrincipalRisksSection,
  PrincipalOpportunitiesSection,
  FounderActionsSection,
  InvestmentOrganisationCard,
  ClosingRecommendationCard,
  InvestmentRhythmTimeline,
  ExecutiveMessagesCard,
};
