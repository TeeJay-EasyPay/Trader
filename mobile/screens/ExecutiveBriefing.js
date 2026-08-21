// AT-ED-016.1: Executive Communication Layer Refinement. This is an editorial pass only - no
// calculation, no committee logic, no execution logic, and no new functionality changed. Every
// number rendered on this screen comes from the exact same, unmodified functions AT-ED-016
// already computed (lib/forecastEngine.js's Base/Bull/Bear cases, lib/forecastFactors.js's eight
// factors, lib/investmentThesis.js, lib/principalRisks.js, lib/principalOpportunities.js,
// lib/founderActions.js, lib/investmentCommittee.js) - only the words around those numbers
// changed.
//
// APP SIMPLIFICATION (Founder-agreed 2026-08-21): the screen used to carry ~15 separate section
// renders. The Founder asked for exactly 6: (1) Where We Stand [Executive Summary + Current
// Position], (2) What I Did [overnight activity, absorbing the former standalone Today's
// Strategy render], (3) Trade Scorecard [absorbs How My Forecasts Have Held Up], (4) The View
// Ahead [absorbs Forecast Centre + Market Assessment + Investment Thesis + Principal Risks +
// Principal Opportunities - five cards all answering "what happens next?"], (5) Trades I Turned
// Down [collapsed], (6) What I Need From You [Founder Actions + Executive Messages, hidden when
// empty]. Investment Organisation and Closing Remarks were cut outright - not absorbed anywhere,
// no longer rendered. None of the underlying computation changed in this pass either; only which
// component renders which already-computed field, and under which heading.

'use strict';

const React = require('react');
const { Text, View } = require('react-native');
const { styles } = require('../styles');
const { Section, CollapsibleSection, StatusPill, Button } = require('../components/shared');
const { money, gbp, formatByCurrency, brokerMoney } = require('../lib/money');
const { formatList } = require('../lib/lists');
const { riskTone } = require('../lib/founderPresentation');
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
  cioExecutiveBriefingSummary,
} = require('../lib/cio');
const { currentInvestmentThesis, alternativeThesis } = require('../lib/investmentThesis');
const { describeDailyPlan } = require('../lib/todaysStrategy');
const { deriveConviction } = require('../lib/forecasting');
// projectPortfolioHorizons is deliberately NOT imported: the trade-averaging projection it
// produced was retired from this screen in Phase 7 (2026-08-20) per the Founder's decision.
// normalizeClosedTradesFromAttribution/tradeStatistics remain -- they feed the Investment
// Thesis factors below.
const { normalizeClosedTradesFromAttribution, tradeStatistics } = require('../lib/forecastEngine');
const { marketForecastCards } = require('../lib/marketForecast');
const { tradeScorecardCard } = require('../lib/tradeScorecard');
const { declineReasonsCard } = require('../lib/declineReasons');
const { evaluateFactors } = require('../lib/forecastFactors');
const { buildRiskCards } = require('../lib/principalRisks');
const { buildOpportunityCards } = require('../lib/principalOpportunities');
const { buildFounderActions } = require('../lib/founderActions');
const {
  largestPosition,
  sumBrokerFieldByCurrency,
  unrealizedPnlByCurrency,
  realizedPnlByCurrencyToday,
  exitsTodayCountByCurrency,
  openPositionsCountByCurrency,
  realizedPnlByCurrencyThisMonth,
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

// --- Section 1: Where We Stand -------------------------------------------------------------
// "Would I genuinely present this exact wording to my CEO?" - pure narrative up top, no metrics,
// no percentages, no labels; the real numbers follow immediately below under the same heading.

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

// AT-ED-017 (Founder request, 2026-08-05): "I have to be able to trust the numbers - if the
// final value is in dollars then Kraken numbers should have been converted to dollars before
// adding them together. In fact I should have 2 totals, one in pounds and one in dollars." Alpaca
// trades USD, Kraken trades GBP, and this backend has no live FX rate - converting would need a
// rate this app can't verify, so every combined figure on this card now groups by real currency
// (lib/portfolioPosition.js's *ByCurrency helpers, lib/money.js's formatByCurrency/
// brokerMoneySentence) instead of summing across brokers regardless of currency.
function currencyLabel(currency) {
  return currency === 'GBP' ? 'In pounds (Kraken)' : 'In dollars (Alpaca)';
}

function currencyBreakdownText({ performanceAttribution, openPositions }) {
  const realizedByCurrency = realizedPnlByCurrencyToday(performanceAttribution);
  const unrealizedByCurrency = unrealizedPnlByCurrency(openPositions);
  const exitsByCurrency = exitsTodayCountByCurrency(performanceAttribution);
  const openByCurrency = openPositionsCountByCurrency(openPositions);
  const currencies = Array.from(new Set([...Object.keys(realizedByCurrency), ...Object.keys(unrealizedByCurrency)]));
  if (!currencies.length) {
    return null;
  }
  const sentences = currencies.map((currency) => {
    const formatFn = currency === 'GBP' ? gbp : money;
    const realized = realizedByCurrency[currency] ?? null;
    const unrealized = unrealizedByCurrency[currency] ?? null;
    const text = cioTodaysMoneyBreakdown({
      realizedToday: realized,
      realizedTodayText: realized !== null ? formatFn(Math.abs(realized)) : null,
      unrealizedTotal: unrealized,
      unrealizedTotalText: unrealized !== null ? formatFn(Math.abs(unrealized)) : null,
      exitsToday: exitsByCurrency[currency] || 0,
      openPositionsCount: openByCurrency[currency] || 0,
    });
    return `${currencyLabel(currency)}: ${text}`;
  });
  return sentences.join('\n\n');
}

// Section title "Where We Stand" (renamed from "Current Position") - this card is the facts
// half of the merged Section 1, directly beneath ExecutiveSummaryCard's narrative half.
function CurrentPositionCard({ portfolio, status, performanceAttribution }) {
  const executive = status?.founder_experience?.executive_dashboard || {};
  const openPositions = portfolio?.open_positions || [];
  const winner = largestPosition(openPositions, 'winning');
  const loser = largestPosition(openPositions, 'losing');
  // AT-ED-017: executive.portfolio_health is now itself a real per-broker sentence (see
  // founderEvidenceMapping.js) - it already ends with its own period, so any pre-existing
  // trailing period is stripped before "In short:" adds exactly one, avoiding the double-period
  // bug already found and fixed once this session in a different card.
  const leadingPositionText = [
    executive.portfolio_health ? `In short: ${String(executive.portfolio_health).replace(/\.+$/, '')}.` : null,
    currencyBreakdownText({ performanceAttribution, openPositions }),
  ].filter(Boolean).join('\n\n');
  return (
    <Section title="Where We Stand">
      {/* AT-ED-016.2: a plain-English brief leads every fact card, with the numbers below it.
          AT-ED-017: prose fragments are joined into ONE Text block with real '\n\n' breaks, not
          separate sibling <Text> elements - React Native puts no visual gap between adjacent
          <Text> siblings (only styles.bodyText's own lineHeight applies within one block). */}
      {leadingPositionText ? <Text style={styles.bodyText}>{leadingPositionText}</Text> : null}
      <PositionLine label="Portfolio value" value={formatByCurrency(sumBrokerFieldByCurrency(status?.brokers, 'portfolio_value'))} />
      {/* 2026-08-18 Founder request: labels made explicit after real confusion between "This
          month" and "Realised this month" - both used to just say "This week"/"This month"
          with no indication that one blends unrealised swings with real profit and the other
          doesn't. "(total change)" vs "(closed trades only)" makes the difference readable
          without needing to already know the AT-ED-017 history behind the two figures. */}
      <PositionLine label="This week (total change)" value={formatByCurrency(sumBrokerFieldByCurrency(status?.brokers, 'week_pnl'))} />
      <PositionLine label="This month (total change)" value={formatByCurrency(sumBrokerFieldByCurrency(status?.brokers, 'month_pnl'))} />
      {/* 2026-08-19 Founder request: "Realised this month" existed but there was no daily
          equivalent - the leading prose sentence above states today's realised/unrealised
          split in words, but nothing put a real number next to it the same way the monthly
          figure gets one. Same real data (realizedPnlByCurrencyToday, already computed for
          the prose sentence), just also surfaced as its own line. */}
      <PositionLine label="Realised today (closed trades only)" value={formatByCurrency(realizedPnlByCurrencyToday(performanceAttribution))} />
      {/* AT-ED-017 (Founder request, 2026-08-05): "This month" above is a portfolio-value delta
          (realised + unrealised mixed, like "Today"), not specifically realised gains - a
          distinct line so the Founder can watch realised profit accumulate through the month
          without it being obscured by day-to-day unrealised swings. */}
      <PositionLine label="Realised this month (closed trades only)" value={formatByCurrency(realizedPnlByCurrencyThisMonth(performanceAttribution, status?.brokers))} />
      <PositionLine label="Open positions" value={openPositions.length || null} />
      <PositionLine label="Cash available" value={formatByCurrency(sumBrokerFieldByCurrency(status?.brokers, 'cash_available'))} />
      <PositionLine label="Best performer (unrealised)" value={winner ? `${winner.symbol}, up ${brokerMoney({ broker: winner.broker }, winner.unrealizedPl)}` : null} />
      <PositionLine label="Worst performer (unrealised)" value={loser ? `${loser.symbol}, down ${brokerMoney({ broker: loser.broker }, Math.abs(loser.unrealizedPl))}` : null} />
    </Section>
  );
}

// --- Section 2: What I Did ("What was today's plan, and what actually happened overnight?") ---
// Merges the former standalone "Today's Strategy" card (the Founder's 2026-08-14 request: like a
// real trader, decide a strategy each morning and either execute it or explicitly stand aside)
// with the overnight activity narrative - both answer the same underlying question, so as of the
// 2026-08-21 simplification they read as one section instead of two separate, overlapping cards.

function TodaysPlanBlock({ activity }) {
  const described = describeDailyPlan(activity?.daily_plan);
  if (described.status === 'not_yet_generated') {
    return <Text style={styles.bodyText}>{described.plainEnglish}</Text>;
  }
  return (
    <View style={styles.compactRow}>
      <StatusPill label={described.decisionLabel} tone={described.decisionTone} />
      <Text style={styles.bodyText}>{described.reasoning}</Text>
      <Text style={styles.metricLabel}>How today is going</Text>
      <Text style={styles.bodyText}>{described.outcomeText}</Text>
      {described.scope ? <Text style={styles.smallText}>{described.scope}</Text> : null}
    </View>
  );
}

function WhatIDidCard({ activity, connectionReadiness, unresolvedIncidentCount }) {
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
  // AT-ED-017 live-review fix: noTrade.state === 'approved_but_not_submitted' is the one funnel
  // state whose own conclusion already says "This requires attention." - without checking it
  // here, autonomyLine would claim "no Founder action required" directly under that exact
  // sentence.
  const autonomyLine = connectionReadiness
    ? cioAutonomyStatement({
      tradeReady: Boolean(connectionReadiness.trade_ready),
      unresolvedIncidentCount: unresolvedIncidentCount || 0,
      executionAnomaly: noTrade.state === 'approved_but_not_submitted',
    })
    : null;
  const overnightText = [overnightSummary, noTrade.conclusion, funnelLine, autonomyLine].filter(Boolean).join('\n\n');
  return (
    <Section title="What I Did">
      <TodaysPlanBlock activity={activity} />
      <Text style={styles.bodyText}>{overnightText}</Text>
    </Section>
  );
}

// --- Section 3: Trade Scorecard --------------------------------------------------------------
// Founder-requested 2026-08-20: "a small card on the executive briefing screen with how many
// trades each day, week and month were successful and how many were not with them a short ai
// summary of one or two sentences on the lessons learned." As of the 2026-08-21 simplification
// this also absorbs the former standalone "How My Forecasts Have Held Up" accountability card -
// both are scorekeeping on the AI's own past calls, so they now read as one section.
function TradeScorecardCard({ tradeScorecard, forecastAccountability }) {
  const card = tradeScorecardCard(tradeScorecard);
  const accuracyText = forecastAccountability?.available
    ? (forecastAccountability.accuracy !== null
      ? `So far I have called the direction correctly ${Math.round(forecastAccountability.accuracy * 100)}% of the time.`
      : 'None of my earlier forecasts have come due yet to grade.')
    : null;
  return (
    <CollapsibleSection
      title="Trade Scorecard"
      subtitle="How many of my trades worked out, and what I have learned from them."
      defaultExpanded={true}
    >
      {card.rows.map((row) => (
        <View key={row.key} style={styles.compactRow}>
          <Text style={styles.metricLabel}>{row.label}</Text>
          <Text style={styles.bodyText}>
            {row.counts}
            {row.net ? ` (${row.net})` : ''}
          </Text>
          {row.winRate ? <Text style={styles.smallText}>{row.winRate}</Text> : null}
          {/* Closed but not yet reconciled: shown separately so it can never be mistaken
              for a win or a loss. */}
          {row.pending ? <Text style={styles.smallText}>{row.pending}</Text> : null}
        </View>
      ))}
      <Text style={styles.summaryReason}>{card.lessons}</Text>
      {/* Founder-requested 2026-08-20: track what commission is actually being paid. */}
      {card.fees ? <Text style={styles.smallText}>{card.fees}</Text> : null}
      {accuracyText ? (
        <View style={styles.compactRow}>
          <Text style={styles.metricLabel}>Forecast accuracy</Text>
          <Text style={styles.bodyText}>{accuracyText}</Text>
        </View>
      ) : null}
    </CollapsibleSection>
  );
}

// --- Section 4: The View Ahead ("What do I currently believe, and what happens next?") --------
// Absorbs five former standalone cards (Market Assessment, Investment Thesis, Forecast Centre,
// Principal Risks, Principal Opportunities) that all answered some version of the same question.
// Kept as distinct labelled subsections within one Section rather than blended into a single
// paragraph, since each still carries genuinely distinct evidence.

function MarketForecastCard({ forecast }) {
  if (!forecast.available) {
    return (
      <View style={styles.compactRow}>
        <Text style={styles.cardTitle}>{forecast.horizon}</Text>
        <Text style={styles.bodyText}>{forecast.reason}</Text>
      </View>
    );
  }
  return (
    <View style={styles.compactRow}>
      <Text style={styles.cardTitle}>{forecast.horizon}</Text>
      <Text style={styles.metricLabel}>What I expect</Text>
      <Text style={styles.bodyText}>{forecast.whatIExpect}</Text>
      <Text style={styles.metricLabel}>Why</Text>
      <Text style={styles.bodyText}>{forecast.why}</Text>
      <Text style={styles.metricLabel}>What could change it</Text>
      <Text style={styles.bodyText}>{forecast.whatCouldChange}</Text>
      <Text style={styles.metricLabel}>Confidence</Text>
      <StatusPill
        label={forecast.confidence}
        tone={forecast.confidence === 'High' ? 'good' : forecast.confidence === 'Low' ? 'warn' : 'neutral'}
      />
    </View>
  );
}

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

function TheViewAheadSection({ marketCentre, themes, recommendations, factors, conviction, marketForecast, portfolio }) {
  const thesis = currentInvestmentThesis({ themes, recommendations });
  const alternative = alternativeThesis({ themes });
  const positiveNotes = factors.filter((factor) => factor.available && factor.direction === 'positive').map((factor) => factor.note);
  const forecastCards = marketForecastCards({ forecasts: marketForecast });
  const positionsAtLoss = (portfolio?.open_positions || [])
    .filter((position) => Number(position.unrealized_pl) < 0)
    .map((position) => ({ symbol: position.symbol, unrealizedPl: position.unrealized_pl }));
  const risks = buildRiskCards({ upcomingRisks: marketCentre?.upcoming_risks, positionsAtLoss, portfolioValue: portfolio?.portfolio_value });
  const opportunities = buildOpportunityCards({ recommendations, themes });
  return (
    // 2026-08-21 Founder feedback: happy with the length given the per-asset detail, but wants
    // it collapsible since it is the longest of the 6 sections - defaultExpanded keeps today's
    // first-read content identical, this only adds the ability to collapse it on repeat visits.
    <CollapsibleSection title="The View Ahead" defaultExpanded={true}>
      <Text style={styles.metricLabel}>Market assessment</Text>
      <Text style={styles.bodyText}>{marketOutlookText(marketCentre)}</Text>

      <Text style={styles.metricLabel}>Investment thesis - current view</Text>
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

      <Text style={styles.metricLabel}>Forecast Centre - built from real price history and technical analysis, not from my own past trade results</Text>
      {forecastCards.map((forecast) => <MarketForecastCard key={forecast.horizonKey} forecast={forecast} />)}

      <Text style={styles.metricLabel}>Principal risks</Text>
      {risks.length ? risks.map((risk, index) => <RiskCard key={`${risk.title}-${index}`} risk={risk} />) : <Text style={styles.bodyText}>Nothing stands out as a principal risk right now.</Text>}

      <Text style={styles.metricLabel}>Principal opportunities</Text>
      {opportunities.length ? opportunities.map((opportunity, index) => <OpportunityCard key={`${opportunity.title}-${index}`} opportunity={opportunity} />) : <Text style={styles.bodyText}>Nothing currently clears my bar for a new opportunity.</Text>}
    </CollapsibleSection>
  );
}

// --- Section 5: Trades I Turned Down ---------------------------------------------------------
// Founder-requested 2026-08-20: "AIs decline reasoning should be available but in a short easy
// to understand answers." The reviewer vetoes real trades that cleared every mechanical gate;
// until now the Founder could see that a trade did not happen but never why. Mechanical gates
// are excluded here - they are already covered elsewhere and would only pad the card. Collapsed
// by default per the Founder-agreed section list.
function DeclineReasonsCard({ declineReasons }) {
  const card = declineReasonsCard(declineReasons);
  return (
    <CollapsibleSection
      title="Trades I Turned Down"
      subtitle="Where I judged a trade was not worth taking, and why."
      defaultExpanded={false}
    >
      {card.rows.length === 0 ? (
        <Text style={styles.bodyText}>{card.emptyMessage}</Text>
      ) : (
        card.rows.map((row) => (
          <View key={row.key} style={styles.compactRow}>
            <Text style={styles.metricLabel}>{row.symbol} - {row.outcome}</Text>
            <Text style={styles.bodyText}>{row.why}</Text>
            {row.assessment ? <Text style={styles.smallText}>{row.assessment}</Text> : null}
            {row.confidence ? <Text style={styles.smallText}>{row.confidence}</Text> : null}
          </View>
        ))
      )}
    </CollapsibleSection>
  );
}

// --- Section 6: What I Need From You ("What do I recommend you do?") ---------------------------
// This is advice, not status - never a bare "no action required". Executive Messages (items that
// materially affect an investment decision) render directly beneath it, in the same section, and
// stay hidden entirely when there is nothing to say.

function FounderActionCard({ action }) {
  return (
    <View style={styles.compactRow}>
      <Text style={styles.cardTitle}>{action.title}</Text>
      <Text style={styles.bodyText}>{action.recommendation}</Text>
      <Text style={styles.smallText}>{action.ifNothing}</Text>
    </View>
  );
}

function FounderActionsSection({ recommendations, unresolvedIncidentCount, connectionReadiness, onRefresh }) {
  const actions = buildFounderActions({ recommendations, unresolvedIncidentCount });
  const outstanding = (recommendations || []).filter((item) => item.freshness_status !== 'Expired').length;
  const noActionReason = cioNoActionReason({
    tradeReady: Boolean(connectionReadiness?.trade_ready),
    outstandingRecommendationsCount: outstanding,
    unresolvedIncidentCount,
    readinessNote: connectionReadiness?.note,
  });
  return (
    <Section title="What I Need From You">
      {actions.length ? (
        actions.map((action, index) => <FounderActionCard key={`${action.title}-${index}`} action={action} />)
      ) : (
        <Text style={styles.bodyText}>{noActionReason}</Text>
      )}
      <View style={styles.buttonGrid}>
        <Button label="Refresh" tone="neutral" onPress={onRefresh} />
      </View>
    </Section>
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
  marketForecast,
  tradeScorecard,
  declineReasons,
  onRefresh,
}) {
  const marketCentre = status?.founder_experience?.market_intelligence_centre || {};
  const confidence = cioAverageConfidence(recommendations);
  const winRate = dailyLearning?.trade_outcomes?.win_rate;
  const connectionReadiness = status?.connection_readiness;
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

  // Phase 7 (2026-08-20): projectPortfolioHorizons (the trade-averaging projection the
  // Founder retired) is deliberately no longer called here. Accountability for the NEW
  // directional per-symbol forecasts needs a genuinely different grading mechanism (symbol
  // price at horizon end vs at forecast time, rather than portfolio value vs a point
  // estimate) - tracked as a follow-up rather than bodged onto a tracker built for a
  // different shape. Empty horizons here just mean "nothing to grade yet", not "broken".
  const { summary: forecastAccountabilitySummary } = useForecastHistory({
    horizons: [],
    currentPortfolioValue: portfolio?.portfolio_value,
  });

  return (
    <View>
      <ExecutiveSummaryCard status={status} activity={activity} marketCentre={marketCentre} />
      <CurrentPositionCard portfolio={portfolio} status={status} performanceAttribution={performanceAttribution} />
      <WhatIDidCard activity={activity} connectionReadiness={connectionReadiness} unresolvedIncidentCount={unresolvedIncidentCount} />
      <TradeScorecardCard tradeScorecard={tradeScorecard} forecastAccountability={forecastAccountabilitySummary} />
      <TheViewAheadSection
        marketCentre={marketCentre}
        themes={themes}
        recommendations={recommendations}
        factors={factors}
        conviction={conviction}
        marketForecast={marketForecast}
        portfolio={portfolio}
      />
      <DeclineReasonsCard declineReasons={declineReasons} />
      <FounderActionsSection recommendations={recommendations} unresolvedIncidentCount={unresolvedIncidentCount} connectionReadiness={connectionReadiness} onRefresh={onRefresh} />
      <ExecutiveMessagesCard status={status} />
    </View>
  );
}

module.exports = {
  ExecutiveBriefing,
  ExecutiveSummaryCard,
  CurrentPositionCard,
  WhatIDidCard,
  TradeScorecardCard,
  TheViewAheadSection,
  DeclineReasonsCard,
  FounderActionsSection,
  ExecutiveMessagesCard,
};
