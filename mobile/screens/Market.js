// Market screen: market intelligence, research status, daily learning, benchmark traders,
// themes, and monitored companies. Extracted from App.js as part of AT-ED-011 Phase 2.

'use strict';

const React = require('react');
const { Text, TouchableOpacity, View } = require('react-native');
const { styles } = require('../styles');
const { Section, CollapsibleSection, StatusPill, Metric, TextBlock, Empty } = require('../components/shared');
const { notAvailable } = require('../lib/notAvailable');
const { formatDateTime, formatPercent } = require('../lib/datetime');
const { formatList } = require('../lib/lists');
const { moneyOrText } = require('../lib/money');
const { riskTone, yesNo } = require('../lib/founderPresentation');
const { marketsOpenText, latestLearningText, companiesForThemeList, findRecommendationForCompany } = require('../lib/market');

function MonitoredCompaniesLinks({ theme, companies, recommendations, onOpenRecommendation }) {
  const matches = companiesForThemeList(theme, companies);
  if (!matches.length) {
    return <TextBlock label="Monitored companies" value={null} />;
  }
  return (
    <View style={styles.textBlock}>
      <Text style={styles.metricLabel}>Monitored companies</Text>
      {matches.map((company) => {
        const recommendation = findRecommendationForCompany(company, recommendations);
        if (!recommendation) {
          return (
            <Text key={`${company.ticker}-plain`} style={styles.bodyText}>
              - {company.company_name} ({company.ticker})
            </Text>
          );
        }
        return (
          <TouchableOpacity key={`${company.ticker}-link`} onPress={() => onOpenRecommendation?.(recommendation.proposal_id)}>
            <Text style={styles.linkText}>- {company.company_name} ({company.ticker})</Text>
          </TouchableOpacity>
        );
      })}
    </View>
  );
}

function LinkedCompanyTitle({ company, recommendations, onOpenRecommendation }) {
  const recommendation = findRecommendationForCompany(company, recommendations);
  const text = `${notAvailable(company.company_name)} (${notAvailable(company.ticker)})`;
  if (!recommendation) {
    return <Text style={styles.cardTitle}>{text}</Text>;
  }
  return (
    <TouchableOpacity onPress={() => onOpenRecommendation?.(recommendation.proposal_id)}>
      <Text style={[styles.cardTitle, styles.linkText]}>{text}</Text>
    </TouchableOpacity>
  );
}

function brokerRow(status, brokerName) {
  return (status?.brokers || []).find((item) => String(item.broker).toLowerCase() === brokerName) || {};
}

function MarketIntelligence({ benchmark, themes, companies, status, recommendations, dailyLearning, onOpenRecommendation }) {
  const marketCentre = status?.founder_experience?.market_intelligence_centre || {};
  const items = benchmark?.items || [];
  // AT-ED-011.5 data-freshness fix (Data_Freshness_Findings.md, API MAPPING BUG): the Alpaca
  // and Kraken Intelligence sections below used to both read the same generic
  // status.research_status/status.due_diligence_status/status.last_research_run - a single
  // combined value, identical under both headings, giving the false impression of two
  // distinct broker readings. status.brokers[].research_status/due_diligence_status and
  // status.operations_health.last_equity_research/last_crypto_research are already computed
  // per broker (see statusFromFounderEvidence in founderEvidenceMapping.js) and are used here
  // instead so each section shows that broker's own evidence.
  const alpaca = brokerRow(status, 'alpaca');
  const kraken = brokerRow(status, 'kraken');
  const equityResearch = status?.operations_health?.last_equity_research;
  const cryptoResearch = status?.operations_health?.last_crypto_research;
  return (
    <View>
      <View style={styles.summaryCard}>
        <Text style={styles.summaryReason}>What kind of market are we in, what matters right now, and where is AI Trader focused?</Text>
        <StatusPill label={notAvailable(marketCentre.market_health)} tone={riskTone(marketCentre.market_health)} />
        <Metric label="Current Market Regime" value={marketCentre.current_market_regime} />
        <Metric label="Volatility" value={marketCentre.volatility} />
        <Metric label="Momentum" value={marketCentre.momentum} />
        <Metric label="Market Breadth" value={marketCentre.breadth} />
        <Metric label="Fear / Greed" value={marketCentre.fear_greed} />
        <Metric label="Crypto Health" value={marketCentre.crypto_health} />
        <TextBlock label="Sector Rotation" value={formatList(marketCentre.sector_rotation)} />
        <TextBlock label="Major Themes" value={formatList(marketCentre.major_themes)} />
        <TextBlock label="Important News" value={formatList(marketCentre.important_news)} />
        <TextBlock label="Upcoming Risks" value={formatList(marketCentre.upcoming_risks)} />
        <TextBlock label="Watch List" value={formatList(marketCentre.watch_list)} />
      </View>
      <Section title="Alpaca Intelligence">
        <Metric label="Research Running" value={alpaca.research_status} />
        <Metric label="Due Diligence Running" value={alpaca.due_diligence_status} />
        <Metric label="Last Update" value={formatDateTime(equityResearch?.completed_at || equityResearch?.created_at)} />
        <Metric label="Next Update" value={formatDateTime(status?.next_scheduled_research_run)} />
        <Metric label="Companies Reviewed" value={equityResearch?.assets_analysed} />
        <Metric label="Themes" value={themes.length} />
        <Metric label="Benchmark Investors" value={items.length} />
        <TextBlock label="Latest Learnings" value={latestLearningText(status, benchmark)} />
      </Section>
      <Section title="Kraken Intelligence">
        <Metric label="Research Running" value={kraken.research_status} />
        <Metric label="Due Diligence Running" value={kraken.due_diligence_status} />
        <Metric label="Last Update" value={formatDateTime(cryptoResearch?.completed_at || cryptoResearch?.created_at)} />
        <Metric label="Next Update" value={formatDateTime(status?.next_scheduled_research_run)} />
        <Metric label="Crypto Projects Reviewed" value={status?.crypto_projects_reviewed} />
        <TextBlock label="Latest Learnings" value="Crypto trading remains disabled until Founder approval and complete project due diligence." />
      </Section>
      <Section title="Daily Benchmark Intelligence Brief">
        <Text style={styles.bodyText}>{notAvailable(benchmark?.summary)}</Text>
      </Section>
      {/* AT-ED-012: this used to duplicate the entire Learning screen (closed trades, win
          rate, P&L, trade lessons, benchmark lessons, Founder recommendations - the same
          dailyLearning object Learning's "Trade Outcomes" card already owns). A market/research
          screen isn't the place to re-tell that whole story; a one-line pointer plus the single
          headline number is enough for a Founder scanning this screen to know whether to go
          check Learning. */}
      {dailyLearning ? (
        <Section title="Today's Learning, In Brief">
          <Text style={styles.bodyText}>
            {dailyLearning.summary || 'AI Trader recorded a learning update today.'} See the Learning tab for the full trade-outcome and lesson detail.
          </Text>
          <Metric label="Closed Trades Reviewed" value={dailyLearning.trade_outcomes?.closed_trades} />
          <Metric label="Win Rate" value={formatPercent(dailyLearning.trade_outcomes?.win_rate)} />
        </Section>
      ) : null}
      <CollapsibleSection
        title="24/7 Research Status"
        subtitle="Scheduling and coverage detail behind the research activity above."
      >
        <Metric label="Research Status" value={status?.research_status} />
        <Metric label="Last Research Run" value={formatDateTime(status?.last_research_run?.completed_at || status?.last_research_run?.started_at)} />
        <Metric label="Assets Reviewed" value={status?.research_assets_reviewed} />
        <Metric label="Crypto Projects Reviewed" value={status?.crypto_projects_reviewed} />
        <Metric label="Recommendations Created" value={status?.research_recommendations_created} />
        <Metric label="Auto Trading Enabled" value={yesNo(status?.auto_trading_enabled)} />
        <Metric label="Paper/Sandbox Mode" value={yesNo(status?.paper_or_sandbox_mode)} />
        <Metric label="Markets Currently Open" value={marketsOpenText(status)} />
        <Metric label="Next Research Run" value={formatDateTime(status?.next_scheduled_research_run)} />
        <TextBlock label="What AI Learned Since Last Brief" value={latestLearningText(status, benchmark)} />
      </CollapsibleSection>
      <CollapsibleSection title="Benchmark Traders Monitored Today" subtitle={`${items.length} trader(s) AI Trader is watching for lessons, not copying.`}>
        {!items.length ? (
          <Empty />
        ) : (
          items.map((item, index) => (
            <View key={`${item.trader_name}-${index}`} style={styles.card}>
              <Text style={styles.cardTitle}>{notAvailable(item.trader_name)}</Text>
              <Metric label="Source / Platform" value={item.platform || item.source} />
              <Metric label="Confidence" value={item.confidence} />
              <TextBlock label="Public activity" value={item.observed_trade_or_portfolio_change} />
              <TextBlock label="AI learned" value={item.ai_interpretation} />
              <TextBlock label="Risk lessons" value={item.risk_lesson} />
              <TextBlock label="Market lessons" value={item.market_lesson} />
              <Metric label="Related sector" value={item.related_sector} />
              <Metric label="Related theme" value={item.related_theme} />
            </View>
          ))
        )}
      </CollapsibleSection>
      <CollapsibleSection title="Theme Definitions" subtitle={`${themes.length} theme(s) currently defined.`}>
        {!themes.length ? (
          <Empty />
        ) : (
          themes.map((item) => (
            <View key={item.id || item.theme} style={styles.card}>
              <Text style={styles.cardTitle}>{notAvailable(item.theme)}</Text>
              <Metric label="Outlook" value={item.current_outlook} />
              <Metric label="Confidence" value={item.confidence} />
              <TextBlock label="What it means" value={item.summary} />
              <TextBlock label="Key drivers" value={item.key_drivers} />
              <TextBlock label="Key risks" value={item.key_risks} />
              <MonitoredCompaniesLinks
                theme={item}
                companies={companies}
                recommendations={recommendations}
                onOpenRecommendation={onOpenRecommendation}
              />
            </View>
          ))
        )}
      </CollapsibleSection>
      <CollapsibleSection title="Companies Monitored" subtitle={`${companies.length} ${companies.length === 1 ? 'company' : 'companies'} on the watchlist.`}>
        {!companies.length ? (
          <Empty />
        ) : (
          companies.map((item) => (
            <View key={item.id || item.ticker} style={styles.card}>
              <LinkedCompanyTitle company={item} recommendations={recommendations} onOpenRecommendation={onOpenRecommendation} />
              <Metric label="Sector" value={item.sector} />
              <Metric label="Country" value={item.country} />
              <Metric label="Watchlist Priority" value={item.current_watchlist_priority} />
              <Metric label="Investment Fit" value={item.current_investment_philosophy_fit} />
              <TextBlock label="Investment Thesis" value={item.investment_thesis} />
            </View>
          ))
        )}
      </CollapsibleSection>
    </View>
  );
}

module.exports = { MarketIntelligence };
