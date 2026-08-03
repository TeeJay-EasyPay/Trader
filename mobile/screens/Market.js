// Market screen: market intelligence, research status, daily learning, benchmark traders,
// themes, and monitored companies. Extracted from App.js as part of AT-ED-011 Phase 2.

'use strict';

const React = require('react');
const { Text, TouchableOpacity, View } = require('react-native');
const { styles } = require('../styles');
const { Section, StatusPill, Metric, TextBlock, Empty } = require('../components/shared');
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
      <Section title="Market Intelligence Centre">
        <Text style={styles.bodyText}>This screen answers: what kind of market are we in, what matters now, and where should AI Trader focus?</Text>
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
      </Section>
      <Section title="24/7 Research Status">
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
      </Section>
      <Section title="Daily Trading Learning Update">
        {!dailyLearning ? (
          <Empty />
        ) : (
          <View>
            <Metric label="Learning Date" value={dailyLearning.date} />
            <TextBlock label="Summary" value={dailyLearning.summary} />
            <Metric label="Closed Trades" value={dailyLearning.trade_outcomes?.closed_trades} />
            <Metric label="Win Rate" value={formatPercent(dailyLearning.trade_outcomes?.win_rate)} />
            <Metric label="Total P&L" value={moneyOrText(dailyLearning.trade_outcomes?.total_profit_loss)} />
            <TextBlock label="Trade Lessons" value={formatList(dailyLearning.trade_lessons)} />
            <TextBlock label="Successful Trader / Benchmark Lessons" value={formatList(dailyLearning.benchmark_learning)} />
            <TextBlock label="Recommendations For Founder" value={formatList(dailyLearning.recommendations_for_founder)} />
            <Text style={styles.smallText}>{notAvailable(dailyLearning.note)}</Text>
          </View>
        )}
      </Section>
      <Section title="Alpaca Intelligence">
        <Metric label="Research Running" value={alpaca.research_status} />
        <Metric label="Due Diligence Running" value={alpaca.due_diligence_status} />
        <Metric label="Last Update" value={formatDateTime(equityResearch?.completed_at || equityResearch?.created_at)} />
        <Metric label="Next Update" value={formatDateTime(status?.next_scheduled_research_run)} />
        <Metric label="Companies Reviewed" value={equityResearch?.assets_analysed} />
        <Metric label="Themes" value={themes.length} />
        <Metric label="Benchmark Investors" value={items.length} />
        <TextBlock label="Latest Learnings" value={latestLearningText(status, benchmark)} />
        <Metric label="Research Freshness" value={alpaca.research_status} />
      </Section>
      <Section title="Kraken Intelligence">
        <Metric label="Research Running" value={kraken.research_status} />
        <Metric label="Due Diligence Running" value={kraken.due_diligence_status} />
        <Metric label="Last Update" value={formatDateTime(cryptoResearch?.completed_at || cryptoResearch?.created_at)} />
        <Metric label="Next Update" value={formatDateTime(status?.next_scheduled_research_run)} />
        <Metric label="Crypto Projects Reviewed" value={status?.crypto_projects_reviewed} />
        <Metric label="Research Freshness" value={kraken.research_status} />
        <TextBlock label="Latest Learnings" value="Crypto trading remains disabled until Founder approval and complete project due diligence." />
      </Section>
      <Section title="Daily Benchmark Intelligence Brief">
        <Text style={styles.bodyText}>{notAvailable(benchmark?.summary)}</Text>
      </Section>
      <Section title="Benchmark Traders Monitored Today">
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
      </Section>
      <Section title="Theme Definitions">
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
      </Section>
      <Section title="Companies Monitored">
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
      </Section>
    </View>
  );
}

module.exports = { MarketIntelligence };
