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
const { moneyOrText, money, gbp, formatByCurrency, brokerMoney } = require('../lib/money');
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
const { describeDailyPlan } = require('../lib/todaysStrategy');
const { deriveConviction } = require('../lib/forecasting');
// projectPortfolioHorizons is deliberately NOT imported: the trade-averaging projection it
// produced was retired from this screen in Phase 7 (2026-08-20) per the Founder's decision.
// normalizeClosedTradesFromAttribution/tradeStatistics remain -- they feed the AI's own
// track-record stats in InvestmentOrganisationCard, a separate and still-wanted feature.
const { normalizeClosedTradesFromAttribution, tradeStatistics } = require('../lib/forecastEngine');
const { marketForecastCards } = require('../lib/marketForecast');
const { tradeScorecardCard } = require('../lib/tradeScorecard');
const { declineReasonsCard } = require('../lib/declineReasons');
const { evaluateFactors } = require('../lib/forecastFactors');
const { buildInvestmentCommittee } = require('../lib/investmentCommittee');
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

// --- Section: Today's Strategy ("What is the plan for today, and how is it going?") ------------
// The Founder's stated ask, 2026-08-14: like a real trader, decide a strategy each morning and
// either execute it or explicitly stand aside -- visible here, not buried in a log. Sourced from
// production_evidence.py's daily_plan key (src/ai_trader/daily_plan.py), generated once each
// morning by the premarket-equity job and reconciled live against the day's actual trades on
// every read (never a stale second write). Alpaca-only for now -- crypto research already runs
// continuously, with no single "morning" to decide against.

function TodaysStrategyCard({ activity }) {
  const described = describeDailyPlan(activity?.daily_plan);
  if (described.status === 'not_yet_generated') {
    return (
      <Section title="Today's Strategy">
        <Text style={styles.bodyText}>{described.plainEnglish}</Text>
      </Section>
    );
  }
  return (
    <Section title="Today's Strategy">
      <StatusPill label={described.decisionLabel} tone={described.decisionTone} />
      <Text style={styles.bodyText}>{described.reasoning}</Text>
      <Text style={styles.metricLabel}>How today is going</Text>
      <Text style={styles.bodyText}>{described.outcomeText}</Text>
      {described.scope ? <Text style={styles.smallText}>{described.scope}</Text> : null}
    </Section>
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
    <Section title="Current Position">
      {/* AT-ED-016.2: a plain-English brief leads every fact card, with the numbers below it -
          the numbers alone were reading as "just data" with nothing to tell the Founder what
          they mean, even though the card correctly answers a facts question.
          AT-ED-017: prose fragments are joined into ONE Text block with real '\n\n' breaks, not
          separate sibling <Text> elements - React Native puts no visual gap between adjacent
          <Text> siblings (only styles.bodyText's own lineHeight applies within one block), so
          separate elements here ran together into one dense paragraph on the emulator, the same
          bug class AT-ED-016.2 fixed in lib/cio.js's composers. */}
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
  // AT-ED-017 live-review fix: noTrade.state === 'approved_but_not_submitted' is the one funnel
  // state whose own conclusion already says "This requires attention." - without checking it
  // here, autonomyLine would claim "no Founder action required" directly under that exact
  // sentence (a real contradiction caught visually on the emulator, not a hypothetical).
  const autonomyLine = connectionReadiness
    ? cioAutonomyStatement({
      tradeReady: Boolean(connectionReadiness.trade_ready),
      unresolvedIncidentCount: unresolvedIncidentCount || 0,
      executionAnomaly: noTrade.state === 'approved_but_not_submitted',
    })
    : null;
  // AT-ED-017: joined into one Text block with real '\n\n' breaks, not separate sibling <Text>
  // elements - this card had the same no-visual-gap-between-siblings bug as CurrentPositionCard
  // even before this pass added funnelLine/autonomyLine (overnightSummary and noTrade.conclusion
  // already ran together); fixed for all four fragments at once while here.
  const overnightText = [overnightSummary, noTrade.conclusion, funnelLine, autonomyLine].filter(Boolean).join('\n\n');
  return (
    <Section title="What Happened Overnight">
      <Text style={styles.bodyText}>{overnightText}</Text>
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
  // AT-ED-017: joined into one Text block with a real '\n\n' break, not two sibling <Text>
  // elements - see the identical fix and rationale in CurrentPositionCard above.
  const whatIExpect = [range, exitTiming].filter(Boolean).join('\n\n');
  return (
    <View style={styles.compactRow}>
      <Text style={styles.cardTitle}>{horizon.horizon}</Text>
      <Text style={styles.metricLabel}>What I expect</Text>
      <Text style={styles.bodyText}>{whatIExpect}</Text>
      <Text style={styles.metricLabel}>Why</Text>
      <Text style={styles.bodyText}>{why}</Text>
      <Text style={styles.metricLabel}>What could change it</Text>
      <Text style={styles.bodyText}>{whatCouldChange}</Text>
      <Text style={styles.metricLabel}>Confidence</Text>
      <StatusPill label={horizon.confidence} tone={horizon.confidence === 'High' ? 'good' : horizon.confidence === 'Low' ? 'warn' : 'neutral'} />
    </View>
  );
}

// Phase 7 of the CIO-level forecasting build (2026-08-20, Founder-directed).
//
// This card used to project the AVERAGE of the AI's own past closed trades forward. The
// Founder rejected that outright -- "that's not forecasting... forecasting is about
// planning, looking at market trends, looking at whether there is a bull run coming or
// not" -- and explicitly decided the same day to REPLACE it rather than keep it as a
// secondary panel. It now renders the real backend market forecast (/market-forecast,
// built from genuine multi-timeframe technical analysis; see forecasting.py).
//
// Note the deliberately different shape: this is a per-symbol directional view with a
// confidence and an invalidation level, NOT a portfolio-value point estimate. It is not
// dressed up as one -- see marketForecast.js's honest-disclosure note.
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

function ForecastCentreCard({ marketForecast }) {
  const cards = marketForecastCards({ forecasts: marketForecast });
  return (
    <CollapsibleSection
      title="Forecast Centre"
      subtitle="Where I believe each market is heading, and why. Built from real price history and technical analysis, not from my own past trade results."
      defaultExpanded={true}
    >
      {cards.map((forecast) => <MarketForecastCard key={forecast.horizonKey} forecast={forecast} />)}
    </CollapsibleSection>
  );
}

// Founder-requested 2026-08-20: "a small card on the executive briefing screen with how
// many trades each day, week and month were successful and how many were not with them a
// short ai summary of one or two sentences on the lessons learned."
//
// Deliberately compact. The briefing already suffers from long generated text burying the
// short high-value sections, so this stays to three lines plus a lessons sentence.
function TradeScorecardCard({ tradeScorecard }) {
  const card = tradeScorecardCard(tradeScorecard);
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
    </CollapsibleSection>
  );
}

// Founder-requested 2026-08-20: "AIs decline reasoning should be available but in a short
// easy to understand answers." The reviewer vetoes real trades that cleared every
// mechanical gate; until now the Founder could see that a trade did not happen but never
// why. Mechanical gates are excluded here -- they are already covered elsewhere and would
// only pad the card.
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

  // Phase 7 (2026-08-20): projectPortfolioHorizons (the trade-averaging projection the
  // Founder retired) is deliberately no longer called here. It previously fed BOTH the
  // Forecast Centre and this accountability tracker; continuing to grade a model that is
  // no longer shown anywhere would be scoring a retired forecast, which tells the Founder
  // nothing useful. Accountability for the NEW directional per-symbol forecasts is real
  // and worth having, but needs a genuinely different grading mechanism (symbol price at
  // horizon end vs at forecast time, rather than portfolio value vs a point estimate) --
  // tracked as a follow-up rather than bodged onto a tracker built for a different shape.
  const { summary: forecastAccountabilitySummary } = useForecastHistory({
    horizons: [],
    currentPortfolioValue: portfolio?.portfolio_value,
  });

  return (
    <View>
      <ExecutiveSummaryCard status={status} activity={activity} marketCentre={marketCentre} />
      <TodaysStrategyCard activity={activity} />
      <CurrentPositionCard portfolio={portfolio} status={status} performanceAttribution={performanceAttribution} />
      <OvernightNarrativeCard activity={activity} connectionReadiness={connectionReadiness} unresolvedIncidentCount={unresolvedIncidentCount} />
      <MarketAssessmentCard marketCentre={marketCentre} />
      <InvestmentThesisSection themes={themes} recommendations={recommendations} factors={factors} conviction={conviction} />
      <ForecastCentreCard marketForecast={marketForecast} />
      <TradeScorecardCard tradeScorecard={tradeScorecard} />
      <DeclineReasonsCard declineReasons={declineReasons} />
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

      <ExecutiveMessagesCard status={status} />
    </View>
  );
}

module.exports = {
  ExecutiveBriefing,
  ExecutiveSummaryCard,
  TodaysStrategyCard,
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
  ExecutiveMessagesCard,
};
