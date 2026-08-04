// AT-ED-015: the Executive Briefing - AI Trader's primary experience (formerly "CIO",
// screens/CIO.js; renamed per Section 11 - "The Founder should always begin here"). Redesigned
// from AT-ED-014's seventeen same-weight, self-repeating cards into a single flowing briefing
// that follows Section 2's exact structure: Overall Position, Current Market Environment, what
// happened and why, current and alternative thesis, expected outlook (Section 3's Yesterday ->
// Year End journey), principal risks and opportunities as individual cards, Founder actions
// required, and a closing recommendation. Supporting detail (Trading Organisation, Investment
// Committee, Investment Rhythm, Executive Messages) lives below the main briefing, available to
// drill into, not interleaved with the narrative.
//
// Every number and sentence still traces to real evidence via lib/cio.js, lib/forecasting.js,
// lib/forecastEngine.js, lib/investmentThesis.js, lib/principalRisks.js,
// lib/principalOpportunities.js, lib/founderActions.js, lib/investmentRhythm.js, and
// lib/investmentCommittee.js - nothing here is a new AI system or a fabricated claim. See
// Executive_Communication_Review.md for the redesign rationale and
// Forecasting_Engine_Architecture.md for how the new evidence-based horizon projections work.

'use strict';

const React = require('react');
const { Text, View } = require('react-native');
const { styles } = require('../styles');
const { Section, CollapsibleSection, StatusPill, Metric, TextBlock, Button } = require('../components/shared');
const { notAvailable, explainMissing } = require('../lib/notAvailable');
const { moneyOrText } = require('../lib/money');
const { summaryTone, riskTone, connectedFounderBrokers } = require('../lib/founderPresentation');
const {
  cioGreeting,
  cioExecutiveSummary,
  cioOvernightActivity,
  cioMarketOutlook,
  cioAverageConfidence,
  cioFounderActionRequired,
  cioClosingRecommendation,
} = require('../lib/cio');
const { currentInvestmentThesis, alternativeThesis } = require('../lib/investmentThesis');
const { deriveConviction } = require('../lib/forecasting');
const { normalizeClosedTradesFromAttribution, projectPortfolioHorizons } = require('../lib/forecastEngine');
const { buildInvestmentRhythm } = require('../lib/investmentRhythm');
const { buildInvestmentCommittee } = require('../lib/investmentCommittee');
const { buildRiskCards } = require('../lib/principalRisks');
const { buildOpportunityCards } = require('../lib/principalOpportunities');
const { buildFounderActions } = require('../lib/founderActions');

// marketCentre uses the founder-evidence field names (market_health/current_market_regime/
// crypto_health/upcoming_risks); cioMarketOutlook() takes the mapped shape - one small adapter,
// shared with Dashboard/Market's own use of the same function.
function marketOutlookText(marketCentre) {
  return cioMarketOutlook({
    marketHealth: marketCentre?.market_health,
    currentRegime: marketCentre?.current_market_regime,
    cryptoHealth: marketCentre?.crypto_health,
    upcomingRisks: marketCentre?.upcoming_risks,
  });
}

// --- Header / Overall Position (Section 2) --------------------------------------------------

function ExecutiveHeader({ status }) {
  const evidence = status?.world_class_evidence || {};
  const executive = status?.founder_experience?.executive_dashboard || {};
  return (
    <View style={styles.summaryCard}>
      <Text style={styles.cardTitle}>{cioGreeting()}</Text>
      <StatusPill label={notAvailable(evidence.first_conclusion)} tone={summaryTone(evidence.first_conclusion)} />
      <Text style={styles.summaryReason}>
        {cioExecutiveSummary({ headline: executive.headline, whatToDo: executive.what_to_do, whatToWorryAbout: executive.what_to_worry_about })}
      </Text>
    </View>
  );
}

function OverallPositionCard({ portfolio, brokerPanels }) {
  return (
    <Section title="Overall Position">
      <Metric label="Portfolio Value" value={moneyOrText(portfolio?.portfolio_value)} />
      <Metric label="Today's P&L" value={moneyOrText(portfolio?.todays_pnl)} />
      <Metric label="Open Positions" value={(portfolio?.open_positions || []).length} />
      <Metric label="Brokers" value={brokerPanels.length ? `${brokerPanels.map((item) => item.label || item.broker).join(', ')} connected` : explainMissing('broker status', 'Alpaca and Kraken are not both visible from the hosted API')} />
    </Section>
  );
}

// --- Current Market Environment (single source of truth - not repeated elsewhere) -----------

function MarketEnvironmentCard({ marketCentre, themesCount }) {
  return (
    <Section title="Current Market Environment">
      <Text style={styles.bodyText}>{marketOutlookText(marketCentre)}</Text>
      <Metric label="Themes Tracked" value={themesCount} />
    </Section>
  );
}

// --- What happened overnight / actions taken / why (Section 2) ------------------------------

function OvernightActionsCard({ activity }) {
  const activitySummary = activity?.summary || {};
  return (
    <Section title="What Happened Overnight">
      <Text style={styles.bodyText}>
        {cioOvernightActivity({
          researchRuns: activitySummary.research?.runs,
          recommendationsCreated: activitySummary.research?.recommendations_created,
          ordersSubmitted: activitySummary.execution?.orders_submitted,
        })}
      </Text>
    </Section>
  );
}

// --- Current / Alternative Thesis, with Conviction embedded (Section 8) ---------------------

function ThesisCard({ themes, recommendations, marketCentre, averageConfidence, winRate }) {
  const thesis = currentInvestmentThesis({ themes, recommendations });
  const conviction = deriveConviction({ marketHealthTone: riskTone(marketCentre?.market_health), averageConfidence, winRate });
  return (
    <Section title="Current Investment Thesis">
      <Text style={styles.bodyText}>{thesis.statement}</Text>
      {thesis.available ? <TextBlock label="Evidence" value={thesis.evidence.join('\n')} /> : null}
      <StatusPill
        label={`Conviction: ${conviction.level}`}
        tone={conviction.level === 'High' ? 'good' : conviction.level === 'Low' ? 'danger' : conviction.level === 'Medium' ? 'warn' : 'neutral'}
      />
      <Text style={styles.smallText}>{conviction.reason}</Text>
    </Section>
  );
}

function AlternativeThesisCard({ themes }) {
  const thesis = alternativeThesis({ themes });
  return (
    <CollapsibleSection title="Alternative Thesis" subtitle="What would make our current thinking wrong.">
      <Text style={styles.bodyText}>{thesis.statement}</Text>
    </CollapsibleSection>
  );
}

// --- Expected Outlook: the Yesterday -> Year End journey (Section 3), forecasts carry their ---
// --- own confidence beside them (Section 8) --------------------------------------------------

function OutlookJourneyCard({ activity, portfolio, performanceAttribution }) {
  const activitySummary = activity?.summary || {};
  const closedTrades = normalizeClosedTradesFromAttribution(performanceAttribution);
  const horizons = projectPortfolioHorizons({ closedTrades, currentPortfolioValue: portfolio?.portfolio_value });
  return (
    <CollapsibleSection title="Expected Outlook" subtitle="Where AI Trader believes it is travelling, from yesterday through to year end." defaultExpanded={true}>
      <View style={styles.compactRow}>
        <Text style={styles.cardTitle}>Yesterday</Text>
        <Text style={styles.bodyText}>
          {cioOvernightActivity({
            researchRuns: activitySummary.research?.runs,
            recommendationsCreated: activitySummary.research?.recommendations_created,
            ordersSubmitted: activitySummary.execution?.orders_submitted,
          })}
        </Text>
      </View>
      <View style={styles.compactRow}>
        <Text style={styles.cardTitle}>Today</Text>
        <Metric label="Portfolio Value" value={moneyOrText(portfolio?.portfolio_value)} />
        <Metric label="Today's P&L" value={moneyOrText(portfolio?.todays_pnl)} />
      </View>
      {horizons.map((horizon) => (
        <View key={horizon.horizonKey} style={styles.compactRow}>
          <Text style={styles.cardTitle}>{horizon.horizon}</Text>
          {horizon.available ? (
            <>
              <Metric label="Expected Value" value={moneyOrText(horizon.expectedValue)} />
              <StatusPill label={`Confidence: ${horizon.confidence}`} tone={horizon.confidence === 'High' ? 'good' : horizon.confidence === 'Low' ? 'warn' : 'neutral'} />
              <Text style={styles.smallText}>{horizon.confidenceReason}</Text>
              <TextBlock label="Supporting Evidence" value={horizon.evidence.join('\n')} />
              <TextBlock label="Principal Assumptions" value={horizon.assumptions.join('\n')} />
              <TextBlock label="Principal Risks" value={horizon.principalRisks.join('\n')} />
              <TextBlock label="Alternative Scenario" value={`${horizon.alternativeScenario.description}${horizon.alternativeScenario.expectedValue !== null ? ` (${moneyOrText(horizon.alternativeScenario.expectedValue)})` : ''}`} />
            </>
          ) : (
            <Text style={styles.bodyText}>{horizon.reason}</Text>
          )}
        </View>
      ))}
    </CollapsibleSection>
  );
}

// --- Principal Risks / Opportunities as individual cards (Section 6/7) ----------------------

function RiskCard({ risk }) {
  return (
    <View style={styles.compactRow}>
      <Text style={styles.cardTitle}>⚠ {risk.title}</Text>
      <Metric label="Impact" value={risk.impact} />
      <Metric label="Likelihood" value={risk.likelihood} />
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

function OpportunityCard({ opportunity }) {
  return (
    <View style={styles.compactRow}>
      <Text style={styles.cardTitle}>{opportunity.title}</Text>
      <TextBlock label="Why" value={opportunity.why} />
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

// --- Founder Actions Required (Section 10) ---------------------------------------------------

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

function FounderActionsSection({ recommendations, unresolvedIncidentCount, onOpenRecommendations, onRefresh }) {
  const actions = buildFounderActions({ recommendations, unresolvedIncidentCount });
  const outstanding = (recommendations || []).filter((item) => item.freshness_status !== 'Expired').length;
  return (
    <Section title="Founder Actions Required">
      {actions.length ? (
        actions.map((action, index) => <FounderActionCard key={`${action.what}-${index}`} action={action} />)
      ) : (
        <Text style={styles.bodyText}>{cioFounderActionRequired({ outstandingRecommendationsCount: outstanding, unresolvedIncidentCount })}</Text>
      )}
      <View style={styles.buttonGrid}>
        <Button label="Review Recommendations" onPress={onOpenRecommendations} />
        <Button label="Refresh" tone="neutral" onPress={onRefresh} />
      </View>
    </Section>
  );
}

// --- Closing Recommendation (Section 2) --------------------------------------------------------

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

// --- Trading Organisation (Section 12: no engineering language) -----------------------------

function organisationHealthLabel(tone) {
  if (tone === 'good') return 'Healthy';
  if (tone === 'warn') return 'Needs Attention';
  if (tone === 'danger') return 'Requires Action';
  return 'Not Yet Established';
}

function TradingOrganisationCard({ status, activity, dailyLearning, connectionReadiness, onOpenOperations }) {
  const operations = status?.operations_health || {};
  const overallTone = operations.overall === 'healthy' ? 'good' : operations.overall ? 'warn' : 'neutral';
  const departments = [
    { name: 'Research', healthy: Boolean(operations.last_research_run || operations.last_equity_research || operations.last_crypto_research) },
    { name: 'Learning', healthy: Boolean(dailyLearning?.evidence_summary?.hasEnoughEvidence) },
    { name: 'Execution', healthy: (activity?.summary?.execution?.orders_submitted ?? 0) >= 0 },
    { name: 'Risk', healthy: Boolean(connectionReadiness?.trade_ready) },
    { name: 'Infrastructure', healthy: overallTone === 'good' },
    { name: 'Governance', healthy: Boolean(connectionReadiness) },
  ];
  return (
    <CollapsibleSection title="Trading Organisation" subtitle="Is my investment organisation healthy?">
      <StatusPill label={organisationHealthLabel(overallTone)} tone={overallTone} />
      {departments.map((department) => (
        <Metric key={department.name} label={department.name} value={department.healthy ? 'Healthy' : 'Attention Needed'} />
      ))}
      <View style={styles.buttonGrid}>
        <Button label="Open Operations" tone="neutral" onPress={onOpenOperations} />
      </View>
    </CollapsibleSection>
  );
}

// --- Investment Committee (kept - department pipeline) ---------------------------------------

function InvestmentCommitteeCard({ status, dailyLearning, activity, connectionReadiness }) {
  const departments = buildInvestmentCommittee({
    operationsHealth: status?.operations_health,
    learningSummary: dailyLearning?.evidence_summary,
    marketCentre: status?.founder_experience?.market_intelligence_centre,
    recommendationSummary: status?.recommendation_summary,
    connectionReadiness,
    activitySummary: activity?.summary?.execution,
    executiveHeadline: status?.founder_experience?.executive_dashboard?.headline,
  });
  return (
    <CollapsibleSection title="Investment Committee" subtitle="Research -> Learning -> Market Intelligence -> Strategy -> Risk -> Execution -> CIO.">
      {departments.map((department) => (
        <View key={department.name} style={styles.compactRow}>
          <Text style={styles.cardTitle}>{department.name}</Text>
          <StatusPill label={department.hasEvidence ? 'Reporting' : 'No Evidence Yet'} tone={department.hasEvidence ? 'good' : 'neutral'} />
          <Text style={styles.bodyText}>{department.conclusion}</Text>
        </View>
      ))}
    </CollapsibleSection>
  );
}

// --- Investment Rhythm as a checklist/timeline (Section 13) ----------------------------------

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

// --- Executive Messages (Section 9: no notification feed, only material items) --------------

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

  return (
    <View>
      <ExecutiveHeader status={status} />
      <OverallPositionCard portfolio={portfolio} brokerPanels={brokerPanels} />
      <MarketEnvironmentCard marketCentre={marketCentre} themesCount={(themes || []).length} />
      <OvernightActionsCard activity={activity} />
      <ThesisCard themes={themes} recommendations={recommendations} marketCentre={marketCentre} averageConfidence={confidence} winRate={winRate} />
      <AlternativeThesisCard themes={themes} />
      <OutlookJourneyCard activity={activity} portfolio={portfolio} performanceAttribution={performanceAttribution} />
      <PrincipalRisksSection marketCentre={marketCentre} portfolio={portfolio} />
      <PrincipalOpportunitiesSection recommendations={recommendations} themes={themes} />
      <FounderActionsSection recommendations={recommendations} unresolvedIncidentCount={unresolvedIncidentCount} onOpenRecommendations={onOpenRecommendations} onRefresh={onRefresh} />
      <ClosingRecommendationCard
        themes={themes}
        recommendations={recommendations}
        marketCentre={marketCentre}
        averageConfidence={confidence}
        winRate={winRate}
        outstandingCount={outstandingCount}
        unresolvedIncidentCount={unresolvedIncidentCount}
      />

      <TradingOrganisationCard status={status} activity={activity} dailyLearning={dailyLearning} connectionReadiness={connectionReadiness} onOpenOperations={onOpenOperations} />
      <InvestmentCommitteeCard status={status} dailyLearning={dailyLearning} activity={activity} connectionReadiness={connectionReadiness} />
      <InvestmentRhythmTimeline status={status} founderBriefCreatedAt={brief?.created_at} />
      <ExecutiveMessagesCard status={status} />
    </View>
  );
}

module.exports = {
  ExecutiveBriefing,
  ExecutiveHeader,
  OverallPositionCard,
  MarketEnvironmentCard,
  OvernightActionsCard,
  ThesisCard,
  AlternativeThesisCard,
  OutlookJourneyCard,
  PrincipalRisksSection,
  PrincipalOpportunitiesSection,
  FounderActionsSection,
  ClosingRecommendationCard,
  TradingOrganisationCard,
  InvestmentCommitteeCard,
  InvestmentRhythmTimeline,
  ExecutiveMessagesCard,
};
