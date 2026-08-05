// AT-ED-016.1: Executive Communication Layer Refinement. This is an editorial pass only - no
// calculation, no committee logic, no execution logic, and no new functionality changed. Every
// number rendered on this screen comes from the exact same, unmodified functions AT-ED-016
// already computed (lib/forecastEngine.js's Base/Bull/Bear cases, lib/forecastFactors.js's eight
// factors, lib/investmentThesis.js, lib/principalRisks.js, lib/principalOpportunities.js,
// lib/founderActions.js, lib/investmentCommittee.js) - only the words around those numbers
// changed. The specific things this pass removed: internal field names leaking through fallback
// text (e.g. "week_pnl"), six-field label grids collapsed to the four fields a CIO would actually
// say for risks/opportunities, database-sounding fallback sentences ("has not produced a fresh
// regime summary"), and every remaining wall of stacked Metric rows that used to stand in for a
// paragraph. Every card now answers exactly one question and fits on one phone screen.

'use strict';

const React = require('react');
const { Text, View } = require('react-native');
const { styles } = require('../styles');
const { Section, CollapsibleSection, StatusPill, Button } = require('../components/shared');
const { moneyOrText } = require('../lib/money');
const { formatList } = require('../lib/lists');
const { riskTone, connectedFounderBrokers } = require('../lib/founderPresentation');
const {
  cioGreeting,
  cioExecutiveSummary,
  cioOvernightActivity,
  cioTodaysMoneyBreakdown,
  cioAutonomyStatement,
  cioActivityFunnel,
  cioMarketOutlook,
  cioAverageConfidence,
  cioNoActionReason,
  cioClosingRecommendation,
  cioExecutiveBriefingSummary,
} = require('../lib/cio');
const { currentInvestmentThesis, alternativeThesis } = require('../lib/investmentThesis');
const { deriveConviction } = require('../lib/forecasting');
const { normalizeClosedTradesFromAttribution, projectPortfolioHorizons, tradeStatistics } = require('../lib/forecastEngine');
const { evaluateFactors } = require('../lib/forecastFactors');
const { buildInvestmentRhythm } = require('../lib/investmentRhythm');
const { buildInvestmentCommittee } = require('../lib/investmentCommittee');
const { buildRiskCards } = require('../lib/principalRisks');
const { buildOpportunityCards } = require('../lib/principalOpportunities');
const { buildFounderActions } = require('../lib/founderActions');
const {
  weekToDatePnl,
  monthToDatePnl,
  largestPosition,
  unrealizedPnlByBroker,
  totalUnrealizedPnl,
  realizedPnlToday,
  exitsTodayCount,
} = require('../lib/portfolioPosition');
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

// A short list reads as a natural sentence; anything longer becomes bullets, matching the
// directive's "more than three items -> bullets" rule.
function proseOrBullets(items) {
  const list = (items || []).filter(Boolean);
  if (!list.length) {
    return null;
  }
  if (list.length <= 2) {
    return list.join('\n\n');
  }
  return formatList(list);
}

// --- Section 1: Executive Summary ---------------------------------------------------------------
// "Would I genuinely present this exact wording to my CEO?" - pure narrative, no metrics, no
// percentages, no labels. Several short paragraphs, not one long block.

function ExecutiveSummaryCard({ status, activity, marketCentre }) {
  const executive = status?.founder_experience?.executive_dashboard || {};
  const activitySummary = activity?.summary || {};
  const headlineSummary = cioExecutiveSummary({ headline: executive.headline, whatToDo: executive.what_to_do, whatToWorryAbout: executive.what_to_worry_about });
  const overnightSummary = cioOvernightActivity({
    researchRuns: activitySummary.research?.runs,
    recommendationsCreated: activitySummary.research?.recommendations_created,
    ordersSubmitted: activitySummary.execution?.orders_submitted,
  });
  const marketSummary = marketOutlookText(marketCentre);
  const hasEvidence = Boolean(executive.headline || activitySummary.research || marketCentre?.market_health);
  return (
    <View style={styles.summaryCard}>
      <Text style={styles.cardTitle}>{cioGreeting()}</Text>
      {hasEvidence ? (
        <>
          <Text style={styles.summaryReason}>{headlineSummary}</Text>
          <Text style={styles.summaryReason}>{overnightSummary}</Text>
          <Text style={styles.summaryReason}>{marketSummary}</Text>
        </>
      ) : (
        <Text style={styles.summaryReason}>{cioExecutiveBriefingSummary({})}</Text>
      )}
    </View>
  );
}

// --- Section 2: Current Position ("Where do we stand today?") ----------------------------------
// Facts only, real numbers, missing ones simply omitted rather than apologised for with
// technical-sounding fallback text.

function PositionLine({ label, value }) {
  if (value === null || value === undefined) {
    return null;
  }
  return (
    <Text style={styles.bodyText}>
      <Text style={styles.metricLabel}>{label}: </Text>
      {value}
    </Text>
  );
}

// AT-ED-017 Part 3: "how much has Alpaca made, how much has Kraken made?" - status.brokers[]
// already carries each broker's own todays_pnl (see founderEvidenceMapping.js); this just names
// them separately instead of only ever showing the combined figure. Paper/live wording matches
// lib/founderPresentation.js's brokerReadinessSentence() convention, since the Founder's real
// capital risk is completely different between the two, not just a bookkeeping split.
function brokerMoneyTodayText(brokers) {
  const list = (brokers || []).filter((broker) => broker.todays_pnl !== null && broker.todays_pnl !== undefined && Number.isFinite(Number(broker.todays_pnl)));
  if (!list.length) {
    return null;
  }
  return list.map((broker) => {
    const value = Number(broker.todays_pnl);
    const isKraken = String(broker.broker || '').toLowerCase() === 'kraken';
    const mode = isKraken ? 'live trading' : 'paper trading';
    const label = broker.label || broker.broker;
    return `${label} (${mode}) is ${value >= 0 ? 'up' : 'down'} ${moneyOrText(Math.abs(value))} today.`;
  }).join(' ');
}

function CurrentPositionCard({ portfolio, status, performanceAttribution }) {
  const executive = status?.founder_experience?.executive_dashboard || {};
  const wtd = weekToDatePnl(status?.brokers);
  const mtd = monthToDatePnl(status?.brokers);
  const winner = largestPosition(portfolio?.open_positions, 'winning');
  const loser = largestPosition(portfolio?.open_positions, 'losing');
  const openPositions = portfolio?.open_positions || [];
  const realizedToday = realizedPnlToday(performanceAttribution);
  const unrealizedTotal = totalUnrealizedPnl(openPositions);
  const moneyBreakdown = cioTodaysMoneyBreakdown({
    realizedToday,
    realizedTodayText: realizedToday !== null ? moneyOrText(Math.abs(realizedToday)) : null,
    unrealizedTotal,
    unrealizedTotalText: unrealizedTotal !== null ? moneyOrText(Math.abs(unrealizedTotal)) : null,
    exitsToday: exitsTodayCount(performanceAttribution),
    openPositionsCount: openPositions.length,
  });
  const brokerMoneyToday = brokerMoneyTodayText(status?.brokers);
  return (
    <Section title="Current Position">
      {/* AT-ED-016.2: a plain-English brief leads every fact card, with the numbers below it -
          the numbers alone were reading as "just data" with nothing to tell the Founder what
          they mean, even though the card correctly answers a facts question. */}
      {executive.portfolio_health ? <Text style={styles.bodyText}>In short: {executive.portfolio_health}.</Text> : null}
      {moneyBreakdown ? <Text style={styles.bodyText}>{moneyBreakdown}</Text> : null}
      {brokerMoneyToday ? <Text style={styles.bodyText}>{brokerMoneyToday}</Text> : null}
      <PositionLine label="Portfolio value" value={portfolio?.portfolio_value !== undefined && portfolio?.portfolio_value !== null ? moneyOrText(portfolio.portfolio_value) : null} />
      <PositionLine label="Today" value={portfolio?.todays_pnl !== undefined && portfolio?.todays_pnl !== null ? moneyOrText(portfolio.todays_pnl) : null} />
      <PositionLine label="This week" value={wtd !== null ? moneyOrText(wtd) : null} />
      <PositionLine label="This month" value={mtd !== null ? moneyOrText(mtd) : null} />
      <PositionLine label="Open positions" value={(portfolio?.open_positions || []).length || null} />
      <PositionLine label="Cash available" value={portfolio?.cash_available !== undefined && portfolio?.cash_available !== null ? moneyOrText(portfolio.cash_available) : null} />
      <PositionLine label="Best performer" value={winner ? `${winner.symbol}, up ${moneyOrText(winner.unrealizedPl)}` : null} />
      <PositionLine label="Worst performer" value={loser ? `${loser.symbol}, down ${moneyOrText(Math.abs(loser.unrealizedPl))}` : null} />
    </Section>
  );
}

// --- Section 3: What Happened Overnight -----------------------------------------------------

function OvernightNarrativeCard({ activity, connectionReadiness, unresolvedIncidentCount }) {
  const activitySummary = activity?.summary || {};
  const noTrade = activity?.why_no_trade || {};
  const overnightSummary = cioOvernightActivity({
    researchRuns: activitySummary.research?.runs,
    recommendationsCreated: activitySummary.research?.recommendations_created,
    ordersSubmitted: activitySummary.execution?.orders_submitted,
  });
  // AT-ED-017 Part 5: "what has AI Trader actually done today" as a real funnel of structured
  // counts (reviewed -> approved -> rejected -> submitted) - never the raw internal reason codes
  // AT-ED-016.3 already removed from Founder-facing text elsewhere on this screen.
  const funnelLine = cioActivityFunnel(noTrade.counts);
  // Replaces the old generic "risk checks came back clean" line with an explicit autonomy
  // statement (Part 5: the Founder must immediately know whether AI Trader is operating
  // autonomously) - still gated on connectionReadiness actually being present, so absence of
  // evidence is never presented as a caution signal.
  const autonomyLine = connectionReadiness
    ? cioAutonomyStatement({ tradeReady: Boolean(connectionReadiness.trade_ready), unresolvedIncidentCount: unresolvedIncidentCount || 0 })
    : null;
  return (
    <Section title="What Happened Overnight">
      <Text style={styles.bodyText}>{overnightSummary}</Text>
      {noTrade.conclusion ? <Text style={styles.bodyText}>{noTrade.conclusion}</Text> : null}
      {funnelLine ? <Text style={styles.bodyText}>{funnelLine}</Text> : null}
      {autonomyLine ? <Text style={styles.bodyText}>{autonomyLine}</Text> : null}
    </Section>
  );
}

// --- Section 4: Market Assessment ("What do I currently believe?") -----------------------------

function MarketAssessmentCard({ marketCentre }) {
  return (
    <Section title="Market Assessment">
      <Text style={styles.bodyText}>{marketOutlookText(marketCentre)}</Text>
    </Section>
  );
}

// --- Section 5: Investment Thesis ("Why do I believe it?") -------------------------------------
// Exactly five fields, nothing else: Current view / Why / Supporting evidence / What could
// invalidate this / Overall confidence.

function InvestmentThesisSection({ themes, recommendations, factors, conviction }) {
  const thesis = currentInvestmentThesis({ themes, recommendations });
  const alternative = alternativeThesis({ themes });
  const positiveNotes = factors.filter((factor) => factor.available && factor.direction === 'positive').map((factor) => factor.note);
  return (
    <Section title="Investment Thesis">
      <Text style={styles.metricLabel}>Current view</Text>
      <Text style={styles.bodyText}>{thesis.statement}</Text>
      <Text style={styles.metricLabel}>Why</Text>
      <Text style={styles.bodyText}>{proseOrBullets(positiveNotes) || 'This is still an emerging view - I do not yet have strong supporting signals.'}</Text>
      {thesis.available && thesis.evidence.length ? (
        <>
          <Text style={styles.metricLabel}>Supporting evidence</Text>
          <Text style={styles.bodyText}>{proseOrBullets(thesis.evidence)}</Text>
        </>
      ) : null}
      <Text style={styles.metricLabel}>What could invalidate this</Text>
      <Text style={styles.bodyText}>{alternative.statement}</Text>
      <Text style={styles.metricLabel}>Overall confidence</Text>
      <StatusPill label={conviction.level} tone={convictionTone(conviction.level)} />
      <Text style={styles.bodyText}>{conviction.reason}</Text>
    </Section>
  );
}

// --- Section 6: Forecast Centre ("Where do I believe we are heading?") -------------------------
// Exactly four fields per horizon: What I expect / Why I expect it / What could change it /
// Confidence level. Same unchanged Base/Bull/Bear numbers from lib/forecastEngine.js, spoken as
// sentences instead of a metric grid.

function ForecastHorizonCard({ horizon }) {
  if (!horizon.available) {
    return (
      <View style={styles.compactRow}>
        <Text style={styles.cardTitle}>{horizon.horizon}</Text>
        <Text style={styles.bodyText}>{horizon.reason}</Text>
      </View>
    );
  }
  const range = `I expect the portfolio to be around ${moneyOrText(horizon.expectedValue)}, though realistically it could land anywhere between ${moneyOrText(horizon.bearCase.expectedValue)} and ${moneyOrText(horizon.bullCase.expectedValue)}.`;
  // AT-ED-017 Part 2/4: "when do we expect positions to close, and what would that realise?" -
  // the same closed-trade pace behind `range` also implies an exit count and realised-profit
  // estimate (lib/forecastEngine.js's new expectedExitCount/nextExpectedExitInDays/
  // expectedRealisedProfit) - said as its own sentence so the Founder gets the journey of the
  // capital (per directive Part 4's own worked example), not just an end-state number.
  const exitTiming = horizon.expectedExitCount > 0
    ? `Based on the recent pace, I expect roughly ${horizon.expectedExitCount} position${horizon.expectedExitCount === 1 ? '' : 's'} to close in this window${horizon.nextExpectedExitInDays !== null ? `, with the next exit likely in about ${horizon.nextExpectedExitInDays} day${horizon.nextExpectedExitInDays === 1 ? '' : 's'}` : ''}. If that happens as expected, I estimate realised profit of around ${moneyOrText(horizon.expectedRealisedProfit)}.`
    : null;
  const why = `That's based on ${horizon.evidence[0]}, with ${horizon.evidence[1]}.`;
  const whatCouldChange = horizon.principalRisks[0];
  return (
    <View style={styles.compactRow}>
      <Text style={styles.cardTitle}>{horizon.horizon}</Text>
      <Text style={styles.metricLabel}>What I expect</Text>
      <Text style={styles.bodyText}>{range}</Text>
      {exitTiming ? <Text style={styles.bodyText}>{exitTiming}</Text> : null}
      <Text style={styles.metricLabel}>Why</Text>
      <Text style={styles.bodyText}>{why}</Text>
      <Text style={styles.metricLabel}>What could change it</Text>
      <Text style={styles.bodyText}>{whatCouldChange}</Text>
      <Text style={styles.metricLabel}>Confidence</Text>
      <StatusPill label={horizon.confidence} tone={horizon.confidence === 'High' ? 'good' : horizon.confidence === 'Low' ? 'warn' : 'neutral'} />
    </View>
  );
}

function ForecastCentreCard({ portfolio, performanceAttribution }) {
  const closedTrades = normalizeClosedTradesFromAttribution(performanceAttribution);
  const horizons = projectPortfolioHorizons({ closedTrades, currentPortfolioValue: portfolio?.portfolio_value });
  return (
    <CollapsibleSection title="Forecast Centre" subtitle="Where I believe we are heading, and why." defaultExpanded={true}>
      {horizons.map((horizon) => <ForecastHorizonCard key={horizon.horizonKey} horizon={horizon} />)}
    </CollapsibleSection>
  );
}

function ForecastAccountabilityCard({ summary }) {
  if (!summary.available) {
    return null;
  }
  const accuracyText = summary.accuracy !== null
    ? `So far I have called the direction correctly ${Math.round(summary.accuracy * 100)}% of the time.`
    : 'None of my earlier forecasts have come due yet to grade.';
  return (
    <CollapsibleSection title="How My Forecasts Have Held Up" subtitle="I keep score on my own predictions.">
      <Text style={styles.bodyText}>{accuracyText}</Text>
    </CollapsibleSection>
  );
}

// --- Section 7: Principal Risks -------------------------------------------------------------
// Exactly four fields: Risk / Why It Matters / Probability / What I Am Doing About It.

function RiskCard({ risk }) {
  return (
    <View style={styles.compactRow}>
      <Text style={styles.cardTitle}>⚠ {risk.title}</Text>
      <Text style={styles.metricLabel}>Why it matters</Text>
      <Text style={styles.bodyText}>{risk.whyItMatters}</Text>
      <Text style={styles.metricLabel}>Probability</Text>
      <Text style={styles.bodyText}>{risk.probability}</Text>
      <Text style={styles.metricLabel}>What I am doing about it</Text>
      <Text style={styles.bodyText}>{risk.whatImDoing}</Text>
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
      {risks.length ? risks.map((risk, index) => <RiskCard key={`${risk.title}-${index}`} risk={risk} />) : <Text style={styles.bodyText}>Nothing stands out as a principal risk right now.</Text>}
    </Section>
  );
}

// --- Section 8: Principal Opportunities -----------------------------------------------------
// Exactly four fields: Why I Like It / Potential Upside / Main Catalyst / Confidence.

function OpportunityCard({ opportunity }) {
  return (
    <View style={styles.compactRow}>
      <Text style={styles.cardTitle}>{opportunity.title}</Text>
      <Text style={styles.metricLabel}>Why I like it</Text>
      <Text style={styles.bodyText}>{opportunity.whyILikeIt}</Text>
      <Text style={styles.metricLabel}>Potential upside</Text>
      <Text style={styles.bodyText}>{opportunity.potentialUpside}</Text>
      <Text style={styles.metricLabel}>Main catalyst</Text>
      <Text style={styles.bodyText}>{opportunity.catalyst}</Text>
      <Text style={styles.metricLabel}>Confidence</Text>
      <Text style={styles.bodyText}>{opportunity.confidence}</Text>
    </View>
  );
}

function PrincipalOpportunitiesSection({ recommendations, themes }) {
  const opportunities = buildOpportunityCards({ recommendations, themes });
  return (
    <Section title="Principal Opportunities">
      {opportunities.length ? opportunities.map((opportunity, index) => <OpportunityCard key={`${opportunity.title}-${index}`} opportunity={opportunity} />) : <Text style={styles.bodyText}>Nothing currently clears my bar for a new opportunity.</Text>}
    </Section>
  );
}

// --- Section 9: Founder Actions ("What do I recommend you do?") --------------------------------
// This is advice, not status - never a bare "no action required."

function FounderActionCard({ action }) {
  return (
    <View style={styles.compactRow}>
      <Text style={styles.cardTitle}>{action.title}</Text>
      <Text style={styles.bodyText}>{action.recommendation}</Text>
      <Text style={styles.smallText}>{action.ifNothing}</Text>
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
        actions.map((action, index) => <FounderActionCard key={`${action.title}-${index}`} action={action} />)
      ) : (
        <Text style={styles.bodyText}>{noActionReason}</Text>
      )}
      <View style={styles.buttonGrid}>
        <Button label="Review Recommendations" onPress={onOpenRecommendations} />
        <Button label="Refresh" tone="neutral" onPress={onRefresh} />
      </View>
    </Section>
  );
}

// --- Section 10: Investment Organisation ------------------------------------------------------
// One clean sentence per department - no status pills, no "reporting" language.

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
  return (
    <Section title="Investment Organisation">
      {departments.map((department) => (
        <View key={department.name} style={styles.compactRow}>
          <Text style={styles.cardTitle}>{department.name}</Text>
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
      <Text style={styles.cardTitle}>Closing Remarks</Text>
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
// Supporting detail, not part of the three-minute read.

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
  const conviction = deriveConviction({ marketHealthTone: riskTone(marketCentre?.market_health), averageConfidence: confidence, winRate });

  const horizons = projectPortfolioHorizons({ closedTrades, currentPortfolioValue: portfolio?.portfolio_value });
  const { summary: forecastAccountabilitySummary } = useForecastHistory({ horizons, currentPortfolioValue: portfolio?.portfolio_value });

  return (
    <View>
      <ExecutiveSummaryCard status={status} activity={activity} marketCentre={marketCentre} />
      <CurrentPositionCard portfolio={portfolio} status={status} performanceAttribution={performanceAttribution} />
      <OvernightNarrativeCard activity={activity} connectionReadiness={connectionReadiness} unresolvedIncidentCount={unresolvedIncidentCount} />
      <MarketAssessmentCard marketCentre={marketCentre} />
      <InvestmentThesisSection themes={themes} recommendations={recommendations} factors={factors} conviction={conviction} />
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
