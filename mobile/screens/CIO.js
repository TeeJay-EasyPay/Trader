// AT-ED-014: the Chief Investment Officer workspace - AI Trader's primary experience (Section 1:
// "The CIO is NOT a card. The CIO is NOT embedded within Dashboard... The CIO becomes the
// executive front door to AI Trader"). Assembled from modular, single-purpose components
// (Section 2), each backed by real evidence already computed elsewhere in the app or by the new
// pure lib/cio.js, lib/forecasting.js, lib/investmentThesis.js, lib/investmentRhythm.js, and
// lib/investmentCommittee.js modules - nothing here is a new AI system, a new data source, or a
// fabricated number. Every module distinguishes Facts from Interpretation/Scenario/Forecast
// (Section 6's four layers) and every forecast that this backend's evidence cannot honestly
// support is shown as an explained gap, never a fabricated figure.

'use strict';

const React = require('react');
const { Text, View } = require('react-native');
const { styles } = require('../styles');
const { Section, CollapsibleSection, StatusPill, Metric, TextBlock, Button } = require('../components/shared');
const { notAvailable, explainMissing } = require('../lib/notAvailable');
const { formatDateTime } = require('../lib/datetime');
const { moneyOrText } = require('../lib/money');
const { summaryTone, riskTone, connectedFounderBrokers } = require('../lib/founderPresentation');
const { unreadNotifications } = require('../lib/notifications');
const {
  cioGreeting,
  cioExecutiveSummary,
  cioOvernightActivity,
  cioMarketOutlook,
  cioAverageConfidence,
  portfolioProjection,
  cioPrincipalRisks,
  cioPrincipalOpportunities,
  cioFounderActionRequired,
} = require('../lib/cio');
const { currentInvestmentThesis, alternativeThesis } = require('../lib/investmentThesis');
const { deriveConviction, autoTradeScenario, portfolioForecast } = require('../lib/forecasting');
const { buildInvestmentRhythm } = require('../lib/investmentRhythm');
const { buildInvestmentCommittee } = require('../lib/investmentCommittee');

// marketCentre uses the founder-evidence field names (market_health/current_market_regime/
// crypto_health/upcoming_risks); cioMarketOutlook() takes the mapped shape - one small adapter
// here rather than changing cioMarketOutlook's contract, which Dashboard.js and Market.js also
// depend on.
function marketOutlookText(marketCentre) {
  return cioMarketOutlook({
    marketHealth: marketCentre?.market_health,
    currentRegime: marketCentre?.current_market_regime,
    cryptoHealth: marketCentre?.crypto_health,
    upcomingRisks: marketCentre?.upcoming_risks,
  });
}

// --- CIOHeader ---------------------------------------------------------------------------

function CIOHeader({ status }) {
  const evidence = status?.world_class_evidence || {};
  return (
    <View style={styles.summaryCard}>
      <Text style={styles.cardTitle}>{cioGreeting()}</Text>
      <StatusPill label={notAvailable(evidence.first_conclusion)} tone={summaryTone(evidence.first_conclusion)} />
    </View>
  );
}

// --- MorningBriefCard (Section 3: the ten-question executive brief) ----------------------

function MorningBriefCard({ status, activity, recommendations, positionsAtLossCount, marketCentre }) {
  const executive = status?.founder_experience?.executive_dashboard || {};
  const activitySummary = activity?.summary || {};
  const outstanding = (recommendations || []).filter((item) => item.freshness_status !== 'Expired').length;
  const incidents = status?.operations_health?.incidents?.length || 0;
  return (
    <CollapsibleSection title="Morning Brief" subtitle="What happened, why, and what it means - answered in order." defaultExpanded={true}>
      <Text style={styles.bodyText}>
        {cioExecutiveSummary({ headline: executive.headline, whatToDo: executive.what_to_do, whatToWorryAbout: executive.what_to_worry_about })}
      </Text>
      <Text style={styles.metricLabel}>Overnight Activity</Text>
      <Text style={styles.bodyText}>
        {cioOvernightActivity({
          researchRuns: activitySummary.research?.runs,
          recommendationsCreated: activitySummary.research?.recommendations_created,
          ordersSubmitted: activitySummary.execution?.orders_submitted,
        })}
      </Text>
      <Text style={styles.metricLabel}>Market Outlook</Text>
      <Text style={styles.bodyText}>{marketOutlookText(marketCentre)}</Text>
      <Text style={styles.metricLabel}>Principal Risks</Text>
      <Text style={styles.bodyText}>{cioPrincipalRisks({ upcomingRisks: status?.founder_experience?.market_intelligence_centre?.upcoming_risks, positionsAtLossCount })}</Text>
      <Text style={styles.metricLabel}>Founder Action</Text>
      <Text style={styles.bodyText}>{cioFounderActionRequired({ outstandingRecommendationsCount: outstanding, unresolvedIncidentCount: incidents })}</Text>
    </CollapsibleSection>
  );
}

// --- InvestmentSummaryCard ------------------------------------------------------------------

function InvestmentSummaryCard({ status, portfolio, brokerPanels }) {
  const executive = status?.founder_experience?.executive_dashboard || {};
  return (
    <Section title="Investment Summary">
      <Metric label="Portfolio Health" value={executive.portfolio_health || explainMissing('portfolio health', 'broker portfolio values or exposure evidence are incomplete')} />
      <Metric label="Portfolio Value" value={moneyOrText(portfolio?.portfolio_value)} />
      <Metric label="Today's P&L" value={moneyOrText(portfolio?.todays_pnl)} />
      <Metric label="Open Positions" value={(portfolio?.open_positions || []).length} />
      <Metric label="Brokers" value={brokerPanels.length ? `${brokerPanels.map((item) => item.label || item.broker).join(', ')} connected` : explainMissing('broker status', 'Alpaca and Kraken are not both visible from the hosted API')} />
    </Section>
  );
}

// --- InvestmentThesisCard / AlternativeThesisCard -----------------------------------------

function InvestmentThesisCard({ themes, recommendations }) {
  const thesis = currentInvestmentThesis({ themes, recommendations });
  return (
    <Section title="Current Investment Thesis">
      <Text style={styles.bodyText}>{thesis.statement}</Text>
      {thesis.available ? <TextBlock label="Evidence" value={thesis.evidence.join('\n')} /> : null}
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

// --- PortfolioOutlookCard / ForecastCard (Section 6/7) -------------------------------------

function PortfolioOutlookCard({ portfolio, recommendations }) {
  const forecast = portfolioForecast({ portfolio, recommendations, valueProjection: portfolioProjection() });
  return (
    <Section title="Portfolio Outlook">
      <Text style={styles.metricLabel}>Facts</Text>
      <Metric label="Portfolio Value" value={moneyOrText(forecast.facts.portfolioValue)} />
      <Metric label="Cash Available" value={moneyOrText(forecast.facts.cashAvailable)} />
      <Metric label="Deployed Capital" value={moneyOrText(forecast.facts.deployedCapital)} />
      <Metric label="Open Positions" value={forecast.facts.openPositionCount} />
      <Text style={styles.metricLabel}>Scenario</Text>
      <Text style={styles.bodyText}>{forecast.executionScenario.available ? forecast.executionScenario.statement : forecast.executionScenario.reason}</Text>
    </Section>
  );
}

function ForecastCard({ portfolio, recommendations }) {
  const forecast = portfolioForecast({ portfolio, recommendations, valueProjection: portfolioProjection() });
  return (
    <CollapsibleSection title="Forecast" subtitle="7 / 30 / 90-day portfolio projection, where evidence supports it." defaultExpanded={true}>
      <TextBlock label="7/30/90-Day Portfolio Value Projection" value={forecast.valueProjection.reason} />
      <TextBlock label="Expected Drawdown" value={forecast.expectedDrawdown.reason} />
      <TextBlock label="Expected Volatility" value={forecast.expectedVolatility.reason} />
      <Text style={styles.smallText}>Every forecast above is labelled by evidence layer, never presented as a fact.</Text>
    </CollapsibleSection>
  );
}

// --- ConvictionCard / ConfidenceCard --------------------------------------------------------

function ConvictionCard({ marketCentre, averageConfidence, winRate }) {
  const conviction = deriveConviction({ marketHealthTone: riskTone(marketCentre?.market_health), averageConfidence, winRate });
  return (
    <Section title="Conviction">
      <StatusPill label={conviction.level} tone={conviction.level === 'High' ? 'good' : conviction.level === 'Low' ? 'danger' : conviction.level === 'Medium' ? 'warn' : 'neutral'} />
      <Text style={styles.bodyText}>{conviction.reason}</Text>
    </Section>
  );
}

function ConfidenceCard({ recommendations }) {
  const confidence = cioAverageConfidence(recommendations);
  return (
    <Section title="Confidence">
      <Metric label="Current Recommendations" value={confidence === null ? 'Not enough active recommendations to average yet' : `${confidence}%`} />
    </Section>
  );
}

// --- MarketOutlookCard ----------------------------------------------------------------------

function MarketOutlookCard({ marketCentre, themesCount }) {
  return (
    <Section title="Market Outlook">
      <Text style={styles.bodyText}>{marketOutlookText(marketCentre)}</Text>
      <Metric label="Themes Tracked" value={themesCount} />
    </Section>
  );
}

// --- InvestmentCommitteeCard (Section 5) ----------------------------------------------------

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

// --- DailyRhythmCard (Section 4) -------------------------------------------------------------

function DailyRhythmCard({ status, founderBriefCreatedAt }) {
  const rhythm = buildInvestmentRhythm({
    lastEquityResearchCompletedAt: status?.operations_health?.last_equity_research?.completed_at,
    lastCryptoResearchCompletedAt: status?.operations_health?.last_crypto_research?.completed_at,
    founderBriefCreatedAt,
  });
  return (
    <CollapsibleSection title="Investment Rhythm" subtitle="AI Trader's published daily schedule and each stage's real completion evidence.">
      <Metric label="Scheduled Now" value={rhythm.scheduledCurrent ? rhythm.scheduledCurrent.name : 'Before today\'s first scheduled stage'} />
      <Metric label="Next Scheduled" value={rhythm.scheduledNext ? `${rhythm.scheduledNext.name} (${rhythm.scheduledNext.scheduledTime})` : 'None remaining today'} />
      {rhythm.stages.map((stage) => (
        <View key={stage.key} style={styles.compactRow}>
          <Text style={styles.cardTitle}>{stage.scheduledTime} {stage.name}</Text>
          <StatusPill
            label={stage.status === 'completed' ? 'Confirmed Complete' : stage.status === 'pending' ? 'Pending' : 'Not Tracked'}
            tone={stage.status === 'completed' ? 'good' : stage.status === 'pending' ? 'neutral' : 'neutral'}
          />
          <Text style={styles.smallText}>{stage.completedAt ? `Confirmed ${formatDateTime(stage.completedAt)}` : stage.note}</Text>
        </View>
      ))}
    </CollapsibleSection>
  );
}

// --- FounderActionsCard ----------------------------------------------------------------------

function FounderActionsCard({ recommendations, onOpenRecommendations, onRefresh }) {
  const outstanding = (recommendations || []).filter((item) => item.freshness_status !== 'Expired').length;
  return (
    <Section title="Founder Actions">
      <Text style={styles.bodyText}>{cioFounderActionRequired({ outstandingRecommendationsCount: outstanding, unresolvedIncidentCount: 0 })}</Text>
      <View style={styles.buttonGrid}>
        <Button label="Review Recommendations" onPress={onOpenRecommendations} />
        <Button label="Refresh" tone="neutral" onPress={onRefresh} />
      </View>
    </Section>
  );
}

// --- ExecutiveMessagesCard --------------------------------------------------------------------

function ExecutiveMessagesCard({ status, unreadNotificationsCount }) {
  const evidence = status?.world_class_evidence || {};
  const messages = evidence.unavailable || [];
  if (!messages.length && !unreadNotificationsCount) {
    return null;
  }
  return (
    <CollapsibleSection title="Executive Messages" subtitle="Items the CIO wants to flag directly." defaultExpanded={Boolean(unreadNotificationsCount)}>
      {unreadNotificationsCount ? <Metric label="Unread Notifications" value={unreadNotificationsCount} /> : null}
      {messages.map((item) => (
        <View key={item.field} style={styles.compactRow}>
          <Text style={styles.cardTitle}>{item.field}</Text>
          <Text style={styles.bodyText}>{item.reason}</Text>
        </View>
      ))}
    </CollapsibleSection>
  );
}

// --- PrincipalRisksCard / PrincipalOpportunitiesCard --------------------------------------

function PrincipalRisksCard({ marketCentre, positionsAtLossCount }) {
  return (
    <Section title="Principal Risks">
      <Text style={styles.bodyText}>{cioPrincipalRisks({ upcomingRisks: marketCentre?.upcoming_risks, positionsAtLossCount })}</Text>
    </Section>
  );
}

function PrincipalOpportunitiesCard({ recommendations, themes }) {
  const freshCount = (recommendations || []).filter((item) => item.freshness_status !== 'Expired').length;
  const topTheme = (themes || []).slice().sort((a, b) => (Number(b.confidence) || 0) - (Number(a.confidence) || 0))[0];
  return (
    <Section title="Principal Opportunities">
      <Text style={styles.bodyText}>
        {cioPrincipalOpportunities({
          freshRecommendationsCount: freshCount,
          topThemeSummary: topTheme ? `${topTheme.theme}: ${topTheme.summary || topTheme.current_outlook || ''}`.trim() : null,
        })}
      </Text>
    </Section>
  );
}

// --- TradingOrganisationCard -----------------------------------------------------------------

function TradingOrganisationCard({ status, onOpenOperations }) {
  const operations = status?.operations_health || {};
  return (
    <CollapsibleSection title="Trading Organisation" subtitle="A condensed operational-health read. Open Operations for full detail.">
      <Text style={styles.bodyText}>{operations.plain_english || explainMissing('operations health', 'no background worker heartbeat or scheduled job evidence has been returned yet')}</Text>
      <Metric label="Worker Health" value={operations.worker_health} />
      <Metric label="Database Durability" value={operations.database_durability} />
      <View style={styles.buttonGrid}>
        <Button label="Open Operations" tone="neutral" onPress={onOpenOperations} />
      </View>
    </CollapsibleSection>
  );
}

// --- CIOWorkspace (assembly) -------------------------------------------------------------------

function CIOWorkspace({
  status,
  portfolio,
  recommendations,
  activity,
  themes,
  dailyLearning,
  brief,
  notifications,
  onRefresh,
  onOpenOperations,
  onOpenRecommendations,
}) {
  const brokerPanels = connectedFounderBrokers(status?.brokers || []);
  const marketCentre = status?.founder_experience?.market_intelligence_centre || {};
  const positionsAtLossCount = (portfolio?.open_positions || []).filter((position) => Number(position.unrealized_pl || 0) < 0).length;
  const confidence = cioAverageConfidence(recommendations);
  const winRate = dailyLearning?.trade_outcomes?.win_rate;
  const connectionReadiness = status?.connection_readiness;
  const unreadNotificationsCount = unreadNotifications(notifications).length;

  return (
    <View>
      <CIOHeader status={status} />
      <MorningBriefCard status={status} activity={activity} recommendations={recommendations} positionsAtLossCount={positionsAtLossCount} marketCentre={marketCentre} />
      <InvestmentSummaryCard status={status} portfolio={portfolio} brokerPanels={brokerPanels} />
      <InvestmentThesisCard themes={themes} recommendations={recommendations} />
      <AlternativeThesisCard themes={themes} />
      <PortfolioOutlookCard portfolio={portfolio} recommendations={recommendations} />
      <ForecastCard portfolio={portfolio} recommendations={recommendations} />
      <ConvictionCard marketCentre={marketCentre} averageConfidence={confidence} winRate={winRate} />
      <ConfidenceCard recommendations={recommendations} />
      <MarketOutlookCard marketCentre={marketCentre} themesCount={(themes || []).length} />
      <InvestmentCommitteeCard status={status} dailyLearning={dailyLearning} activity={activity} connectionReadiness={connectionReadiness} />
      <DailyRhythmCard status={status} founderBriefCreatedAt={brief?.created_at} />
      <FounderActionsCard recommendations={recommendations} onOpenRecommendations={onOpenRecommendations} onRefresh={onRefresh} />
      <ExecutiveMessagesCard status={status} unreadNotificationsCount={unreadNotificationsCount} />
      <PrincipalRisksCard marketCentre={marketCentre} positionsAtLossCount={positionsAtLossCount} />
      <PrincipalOpportunitiesCard recommendations={recommendations} themes={themes} />
      <TradingOrganisationCard status={status} onOpenOperations={onOpenOperations} />
    </View>
  );
}

module.exports = {
  CIOWorkspace,
  CIOHeader,
  MorningBriefCard,
  InvestmentSummaryCard,
  InvestmentThesisCard,
  AlternativeThesisCard,
  PortfolioOutlookCard,
  ForecastCard,
  ConvictionCard,
  ConfidenceCard,
  MarketOutlookCard,
  InvestmentCommitteeCard,
  DailyRhythmCard,
  FounderActionsCard,
  ExecutiveMessagesCard,
  PrincipalRisksCard,
  PrincipalOpportunitiesCard,
  TradingOrganisationCard,
};
