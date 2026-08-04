// Pure mapping/shaping functions between the /founder-evidence API payload and the shapes the
// mobile screens expect. No React, no fetch, no AsyncStorage - see founderEvidenceMapping.test.js.
// Extracted from App.js as part of AT-ED-011 (mobile modularisation).

'use strict';

const { moneyOrText } = require('./money');
const { formatDateTime, dateMs } = require('./datetime');
const { operationalRollup, learningSummary } = require('./founderPresentation');

function unavailableStatus(reason) {
  return {
    system_status: 'partial',
    engine_health: 'Status endpoint timed out before the app finished refreshing.',
    research_status: `Not available - ${reason}`,
    brokers: [],
    connection_readiness: {
      trade_ready: false,
      note: 'The app is showing a degraded status because the hosted status endpoint did not respond quickly enough. Check the Activity screen for persisted autonomous evidence.',
      checks: [
        {
          component: 'Render API',
          status: 'timeout',
          ready: false,
          detail: reason,
        },
      ],
    },
    founder_experience: {
      executive_dashboard: {
        portfolio_health: 'Status unavailable',
        headline: 'The status endpoint was slow, so AI Trader is showing partial evidence instead of blocking the app.',
        good_morning: [reason],
        what_to_do: 'Open Activity or refresh again after Render has warmed up.',
        what_to_worry_about: 'If this persists after repeated refreshes, check Render logs and API health.',
      },
    },
    world_class_evidence: {
      first_conclusion: 'Data issue requires attention',
      unavailable: [
        {
          field: 'Hosted status',
          reason,
          required: 'The /status endpoint must respond within the mobile refresh timeout.',
          expected_or_error: 'Expected during Render cold start; an error if persistent.',
        },
      ],
    },
  };
}

function unavailableActivity(reason) {
  return {
    generated_at: new Date().toISOString(),
    fetch_error: reason,
    status: {
      state: 'STATUS UNKNOWN',
      plain_english: `Activity evidence could not be loaded from the hosted API: ${reason}`,
      last_meaningful_activity: null,
      worker_status: 'Not available - Activity API request failed.',
      scheduler_status: 'Not available - Activity API request failed.',
      database_status: 'Not available - Activity API request failed.',
      last_successful_research: null,
      last_broker_poll: null,
      last_report_generated: null,
      unresolved_incident_count: 0,
    },
    summary: {},
    timeline: {
      items: [],
      returned: 0,
      total: 0,
      source_event_count: 0,
      empty_state: reason,
    },
    why_no_trade: {
      state: 'unknown',
      conclusion: 'No-trade evidence could not be loaded because the Activity API request failed.',
      counts: {},
      top_reasons: [],
    },
    broker_activity: { brokers: [] },
    founder_attention: {
      plain_english: 'Founder attention items could not be loaded because the Activity API request failed.',
      items: [],
    },
    latest_completed_actions: [],
    truthfulness: {
      source: 'Activity API request failed',
      mock_data_used: false,
      synthetic_activity_used: false,
    },
  };
}

function productionTradeForMobile(trade) {
  return {
    ...trade,
    created_at: trade.observed_at,
    updated_at: trade.observed_at,
    qty: trade.quantity,
    filled_avg_price: trade.average_fill_price || trade.price,
    profit_loss: trade.realized_pnl,
    raw: trade.payload || {},
  };
}

function brokerResearchStatus(rows, broker) {
  const row = (rows || []).find((item) => String(item.broker).toLowerCase() === String(broker).toLowerCase());
  return row
    ? `${row.status || 'recorded'} - ${row.assets_analysed || 0} asset(s), ${formatDateTime(row.completed_at)}`
    : 'No research evidence recorded for this broker in the selected period';
}

function founderHeadline(evidence) {
  const pnl = evidence?.portfolio?.todays_pnl;
  const tradeCount = evidence?.trades?.length || 0;
  const state = evidence?.status?.state || 'STATUS UNKNOWN';
  const pnlText = pnl == null ? 'Daily P&L is awaiting comparable broker evidence.' : `Today is ${pnl >= 0 ? 'up' : 'down'} ${moneyOrText(Math.abs(pnl))}.`;
  return `${state}. ${pnlText} ${tradeCount} broker order or fill event(s) are visible in this period.`;
}

// AT-ED-011.7: evidence.status.database_status is a raw backend identifier ("postgres" /
// "sqlite") meant for the technical database_backend.active_backend diagnostic field below -
// it must never be shown to the Founder as a bare status word, since a non-"postgres" value
// (which should only ever occur transiently, e.g. moments after a worker restart) would
// otherwise render literally as the word "sqlite" in a founder-facing status card, unexplained
// and alarming, exactly like an implementation detail leaking through a raw error message.
function databaseStatusLabel(databaseStatus) {
  return databaseStatus === 'postgres' ? 'Connected' : 'Not Postgres - needs attention';
}

function founderAction(evidence) {
  if (evidence?.status?.state !== 'OPERATING NORMALLY') {
    return 'Open Activity and review the latest worker, research, or broker warning before changing trading permissions.';
  }
  if (evidence?.recommendations?.length) {
    return `Review ${evidence.recommendations.length} persisted recommendation(s); governance remains the execution authority.`;
  }
  return evidence?.why_no_trade?.conclusion || 'No action is required.';
}

function statusFromFounderEvidence(evidence) {
  const operating = evidence?.status || {};
  const portfolio = evidence?.portfolio || {};
  const researchRows = evidence?.research || [];
  const latestResearch = researchRows[0] || null;
  const trades = evidence?.trades || [];
  const recommendations = evidence?.recommendations || [];
  const learning = evidence?.learning || [];
  const brokerPanels = (evidence?.brokers || []).map((row) => {
    const raw = row.payload || {};
    const brokerTrades = trades.filter((trade) => String(trade.broker).toLowerCase() === String(row.broker).toLowerCase());
    return {
      ...raw,
      broker: row.broker,
      label: String(row.broker || '').toLowerCase() === 'alpaca' ? 'Alpaca' : 'Kraken',
      connection_status: row.connection_status,
      account_mode: row.account_mode,
      currency: row.currency,
      portfolio_value: row.portfolio_value,
      cash_available: row.cash,
      buying_power: row.buying_power,
      estimated_in_positions: row.deployed_capital,
      todays_pnl: row.day_pnl,
      week_pnl: row.week_pnl,
      month_pnl: row.month_pnl,
      open_positions: row.open_positions,
      open_positions_detail: row.positions || [],
      // Explicitly AI-owned open positions (MANAGED_TRADE_EXITS) - a strict subset of
      // open_positions_detail. Never used to infer that a position NOT in this list is
      // AI-managed; the absence of a managed-exit row means "not confirmed AI-managed",
      // not "assume it is anyway" (see positionOwnership() in lib/founderPresentation.js).
      managed_exits: row.managed_exits || [],
      reconciliation_status: row.reconciliation_status,
      source: `${row.source || 'broker adapter'}; captured ${formatDateTime(row.captured_at)}`,
      latest_error: row.error,
      trades_today: brokerTrades.length,
      trade_history: brokerTrades.map(productionTradeForMobile),
      research_status: brokerResearchStatus(researchRows, row.broker),
      due_diligence_status: recommendations.some((item) => String(item.suggested_broker || item.broker).toLowerCase() === String(row.broker).toLowerCase())
        ? 'Completed - recommendation evidence is available'
        : 'No recommendation passed due diligence in the selected period',
      // raw.auto_trading_enabled is a true tri-state (true/false/undefined) from the
      // backend snapshot payload - undefined means the governance snapshot has not
      // captured this broker yet, and must never be shown as "Disabled" (AT-ED-003
      // Section 3). auto_trading_status/block_reason carry the plain-language reason.
      auto_trading_enabled: raw.auto_trading_enabled === undefined ? null : Boolean(raw.auto_trading_enabled),
      auto_trading_status: raw.auto_trading_status || (raw.auto_trading_enabled === undefined ? 'Unknown' : (raw.auto_trading_enabled ? 'Enabled' : 'Disabled')),
      block_reason: raw.block_reason ?? null,
      trading_permissions: raw.trading_permissions,
      // SCHEDULED_JOB_RUNS is ordered completed_at/scheduled_for DESC by the query that
      // populates evidence.jobs, so the first match is genuinely the latest.
      latest_successful_poll: (evidence?.jobs || []).find(
        (job) => job.job_name === `broker-poll-${String(row.broker).toLowerCase()}` && job.status === 'completed'
      )?.completed_at || null,
      // PRODUCTION_TRADE_EVIDENCE is ordered observed_at DESC, and brokerTrades preserves
      // that order, so the first entry is the latest confirmed trade for this broker.
      latest_confirmed_trade: brokerTrades[0] || null,
    };
  });
  const deployed = portfolio.deployed_capital;
  const total = portfolio.portfolio_value;
  const dayPnl = portfolio.todays_pnl;
  const researchSummary = evidence?.summary?.research || {};
  const learningCount = learning.length;
  const operations = {
    generated_at: evidence?.generated_at,
    overall: operating.state === 'OPERATING NORMALLY' ? 'healthy' : 'attention_needed',
    plain_english: operating.plain_english,
    api_health: 'available',
    worker_health: operating.worker_status,
    database_durability: operating.database_status === 'postgres' ? 'Durable shared Postgres evidence is active' : databaseStatusLabel(operating.database_status),
    database_backend: {
      requested_backend: 'postgres',
      active_backend: operating.database_status,
      plain_english: operating.database_status === 'postgres'
        ? 'The API and background worker share production evidence in Supabase Postgres.'
        : 'Production evidence is not currently reporting Postgres as the active backend.',
    },
    last_equity_research: researchRows.find((item) => String(item.broker).toLowerCase() === 'alpaca'),
    last_crypto_research: researchRows.find((item) => String(item.broker).toLowerCase() === 'kraken'),
    last_research_run: latestResearch,
    last_job_runs: evidence?.jobs || [],
    incidents: operating.unresolved_incident_count ? [{ title: `${operating.unresolved_incident_count} unresolved incident(s)` }] : [],
  };
  const portfolioHealth = total == null
    ? 'Awaiting a successful broker snapshot'
    : dayPnl == null
      ? 'Broker balances are current; daily P&L awaits a comparison snapshot'
      : `${dayPnl >= 0 ? 'Up' : 'Down'} ${moneyOrText(Math.abs(dayPnl))} today`;
  const researchHealth = latestResearch
    ? `${latestResearch.broker || 'Market'} research ${latestResearch.status || 'recorded'} at ${formatDateTime(latestResearch.completed_at)}`
    : 'No production research evidence has been recorded in this period';
  return {
    system_status: operating.state,
    paper_live_mode: 'Alpaca paper; Kraken controlled live permissions',
    engine_health: operating.plain_english,
    job_health: evidence?.summary?.operations?.job_health || [],
    live_worker: operating.worker || null,
    research_status: researchHealth,
    due_diligence_status: recommendations.length
      ? `${recommendations.length} persisted recommendation(s) available for review`
      : evidence?.why_no_trade?.conclusion,
    last_analysis_time: operating.last_successful_research_run,
    last_research_run: latestResearch,
    research_assets_reviewed: researchSummary.assets_analysed,
    crypto_projects_reviewed: researchRows
      .filter((item) => String(item.broker).toLowerCase() === 'kraken')
      .reduce((totalCount, item) => totalCount + Number(item.assets_analysed || 0), 0),
    research_recommendations_created: researchSummary.recommendations_created,
    next_scheduled_research_run: null,
    brokers: brokerPanels,
    operations_health: operations,
    recommendation_summary: {
      active: recommendations.filter((item) => item.freshness_status !== 'Expired').length,
      expired: recommendations.filter((item) => item.freshness_status === 'Expired').length,
      auto_trade_mode: 'Broker-specific permissions and governance gates apply',
    },
    selected_active_brokers: brokerPanels.map((item) => item.broker),
    connection_readiness: {
      trade_ready: operating.worker_status === 'healthy' && operating.database_status === 'postgres',
      note: 'This readiness view is derived from shared production evidence. Every order still requires orchestrator, portfolio, strategy, and risk approval.',
      checks: [
        { component: 'Render API', status: 'connected', ready: true, detail: 'The Founder evidence endpoint responded.' },
        { component: 'Background Worker', status: operating.worker_status, ready: operating.worker_status === 'healthy', detail: operating.plain_english },
        { component: 'Supabase Postgres', status: databaseStatusLabel(operating.database_status), ready: operating.database_status === 'postgres', detail: operations.database_backend.plain_english },
        ...brokerPanels.map((broker) => ({
          component: broker.label,
          status: broker.connection_status,
          ready: String(broker.connection_status).toLowerCase() === 'connected',
          auto_trading_enabled: broker.auto_trading_enabled,
          block_reason: broker.block_reason,
          detail: broker.latest_error || broker.source,
        })),
      ],
    },
    founder_experience: {
      executive_dashboard: {
        portfolio_health: portfolioHealth,
        headline: founderHeadline(evidence),
        good_morning: [operating.plain_english, evidence?.why_no_trade?.conclusion].filter(Boolean),
        what_to_do: founderAction(evidence),
        what_to_worry_about: operating.state === 'OPERATING NORMALLY'
          ? 'No operational fault is visible. Review individual broker and trade evidence before changing capital.'
          : operating.plain_english,
        todays_recommendation_count: recommendations.length,
        open_positions: portfolio.open_positions?.length || 0,
        capital_deployed: deployed,
        cash_available: portfolio.cash_available,
        learning_progress: learningCount ? `${learningCount} learning cycle(s) completed in this period` : 'No completed learning cycle in this period',
      },
      portfolio_command: {
        portfolio_allocation: {
          total,
          deployed,
          cash: portfolio.cash_available,
          deployed_pct: total ? deployed / total : null,
        },
        diversification: portfolio.open_positions?.length
          ? `${portfolio.open_positions.length} broker position(s) captured; detailed diversification requires normalized metadata`
          : 'No open broker positions captured',
        portfolio_risk: 'Governed per recommendation; aggregate risk attribution is not yet present in this evidence projection',
        expected_portfolio_return: 'Not estimated - no forecast is fabricated from broker balances',
        positions_requiring_attention: [],
        rebalancing_suggestions: [],
      },
      market_intelligence_centre: {
        market_health: latestResearch ? `Fresh production research evidence from ${latestResearch.broker}` : 'No fresh production research evidence',
        current_market_regime: latestResearch?.summary || 'Not calculated in the production evidence projection',
        volatility: 'See recommendation evidence where available',
        momentum: 'See recommendation evidence where available',
        breadth: `${researchSummary.assets_analysed || 0} asset review(s) recorded in this period`,
        crypto_health: brokerResearchStatus(researchRows, 'kraken'),
        sector_rotation: [],
        major_themes: [],
        important_news: [],
        upcoming_risks: evidence?.why_no_trade?.top_reasons?.map((item) => `${item.reason}: ${item.count}`) || [],
        watch_list: recommendations.map((item) => item.symbol).filter(Boolean),
      },
      learning_lab: {
        learning_progress: learningCount ? `${learningCount} completed learning processor run(s)` : 'No completed learning run in this period',
        prediction_accuracy: null,
        calibration: learningCount ? 'Learning evidence exists; statistical calibration requires completed attributed trades' : 'Insufficient completed trade evidence',
        best_strategy: null,
        weakest_strategy: null,
        strategy_validation_status: 'Governed strategy promotion remains separate from production evidence display',
        lessons_learned: learning.map((item) => item.summary).filter(Boolean),
        founder_suggestions: learning.length ? ['Review completed learning evidence before approving any strategy change.'] : [],
        strategy_rankings: [],
        signal_rankings: [],
      },
    },
    world_class_evidence: {
      first_conclusion: operating.state === 'OPERATING NORMALLY' ? 'No action required' : 'Operational attention required',
      unavailable: [],
      future_connections: [],
      operational_truth: {
        canonical_lifecycle_events: trades.length,
        illegal_transition_rejections: 0,
        reconciliation_health: brokerPanels.map((item) => `${item.label}: ${item.reconciliation_status}`),
      },
      portfolio_intelligence: {
        plain_english: portfolioHealth,
        warnings: dayPnl == null ? ['Daily P&L needs at least two comparable broker snapshots or broker-reported P&L.'] : [],
      },
    },
    operational_summary: operationalRollup({
      operatingState: operating.state,
      plainEnglish: operating.plain_english,
      liveWorker: operating.worker || null,
      brokerPanels,
      generatedAt: evidence?.generated_at,
    }),
  };
}

function activityFromFounderEvidence(evidence) {
  const timeline = evidence?.timeline || { items: [], total: 0 };
  return {
    ...evidence,
    timeline: {
      ...timeline,
      returned: timeline.items?.length || 0,
      source_event_count: timeline.total || timeline.items?.length || 0,
      empty_state: timeline.items?.length ? null : 'No autonomous activity has been recorded in the selected period.',
    },
    // Broker status is intentionally not recomputed here. The Activity screen never renders
    // its own broker-status view - it reuses status.brokers (via BrokerPanel) exactly like
    // Command and Portfolio do, so there is one authoritative broker-status computation, not
    // several that could disagree (see brokerOverallReadiness() in lib/founderPresentation.js).
    founder_attention: {
      plain_english: evidence?.status?.state === 'OPERATING NORMALLY'
        ? 'No Founder action is currently required.'
        : evidence?.status?.plain_english || 'Operational evidence requires review.',
      items: [],
    },
    latest_completed_actions: (timeline.items || []).slice(0, 8).map((item) => ({
      label: item.category || item.component,
      title: item.title,
      timestamp: item.timestamp,
      outcome: item.outcome,
    })),
  };
}

function founderLearningForMobile(evidence) {
  const learning = evidence?.learning || [];
  const performance = evidence?.performance || {};
  const trades = evidence?.trades || [];
  const closed = trades.filter((trade) => ['closed', 'target_exit', 'stop_exit', 'manual_exit'].includes(String(trade.status).toLowerCase()));
  const winners = closed.filter((trade) => Number(trade.realized_pnl) > 0).length;
  return {
    date: String(evidence?.generated_at || '').slice(0, 10),
    summary: learning.length
      ? `${learning.length} durable learning processor run(s) completed in the selected period.`
      : 'No completed learning run is recorded in the selected period. Learning only follows terminal, reconciled trade evidence.',
    trade_outcomes: {
      closed_trades: closed.length,
      win_rate: closed.length ? winners / closed.length : null,
      total_profit_loss: performance.realized_pnl,
    },
    trade_lessons: learning.map((item) => item.summary).filter(Boolean),
    benchmark_learning: [],
    recommendations_for_founder: learning.length
      ? ['Review learning evidence before approving any governed strategy change.']
      : ['Allow terminal trades to reconcile before judging strategy improvement.'],
    note: 'This view is derived from shared production evidence. Learning cannot silently change trading policy or production parameters.',
    evidence_summary: learningSummary(evidence),
  };
}

function sortByConfidence(items) {
  return [...items].sort((a, b) => {
    const confidenceDelta = Number(b.confidence || 0) - Number(a.confidence || 0);
    if (confidenceDelta !== 0) {
      return confidenceDelta;
    }
    return dateMs(b.created_at) - dateMs(a.created_at);
  });
}

module.exports = {
  unavailableStatus,
  unavailableActivity,
  statusFromFounderEvidence,
  activityFromFounderEvidence,
  productionTradeForMobile,
  brokerResearchStatus,
  founderHeadline,
  founderAction,
  founderLearningForMobile,
  sortByConfidence,
};
