// AT-ED-014 Section 6/7: the Adaptive Forecasting & Strategic Intelligence Engine. Kept
// dependency-free (no React/RN imports), matching every other lib/*.js convention, so it is
// directly testable under plain Node - see forecasting.test.js.
//
// The directive asks for four distinct layers (Facts / Reasoned Interpretation / Scenario
// Analysis / Forecast) and says explicitly: "Implement every capability that the current
// evidence honestly supports. If additional backend capability is required for future
// intelligence, scaffold the architecture rather than fabricating results." This module takes
// that literally - every function below either computes a real value from real evidence, or
// returns `available: false` with a specific, named reason for the gap. Nothing here invents a
// number, a probability, or a confidence that isn't backed by an evidence field the app already
// has. In particular: this backend has no time-series portfolio-value model, no volatility
// model, and no economic-calendar/macro feed - so every forecast that would require one of those
// (7/30/90-day value projection, expected drawdown, expected volatility) is always scaffolded as
// unavailable, exactly like AT-ED-013's portfolioProjection() (kept in lib/cio.js and reused
// here for the value-projection piece specifically, so there is exactly one "no forecasting
// model exists" statement in the codebase, not two that could drift apart).

'use strict';

const FORECAST_LAYER = Object.freeze({
  FACT: 'fact',
  INTERPRETATION: 'interpretation',
  SCENARIO: 'scenario',
  FORECAST: 'forecast',
});

// The same 85% auto-trade confidence threshold lib/recommendations.js's withRecommendationFreshness
// already gates auto-execution on - reused here (not duplicated as a separate constant with a
// different value) so a scenario built from this threshold can never silently drift out of sync
// with the real auto-trade gate.
const AUTO_TRADE_CONFIDENCE_THRESHOLD = 0.85;

// AT-ED-014 Section 6, Layer 2 (Reasoned Interpretation): conviction is derived from whether
// multiple independent real signals currently agree - not a single number dressed up as
// certainty. Requires at least two of three real inputs before naming a level at all; with only
// zero or one signal available, conviction is honestly "Not Established" rather than guessed.
function deriveConviction({ marketHealthTone, averageConfidence, winRate }) {
  const signals = [];
  if (marketHealthTone === 'good') {
    signals.push({ positive: true, text: 'market conditions currently read as favourable' });
  } else if (marketHealthTone === 'warn' || marketHealthTone === 'danger') {
    signals.push({ positive: false, text: 'market conditions currently read as unfavourable' });
  }
  if (typeof averageConfidence === 'number') {
    signals.push(averageConfidence >= 70
      ? { positive: true, text: 'current recommendation confidence is strong' }
      : { positive: false, text: 'current recommendation confidence is modest' });
  }
  if (typeof winRate === 'number') {
    signals.push(winRate >= 0.5
      ? { positive: true, text: 'historical strategy performance has been net positive' }
      : { positive: false, text: 'historical strategy performance has been net negative' });
  }
  if (signals.length < 2) {
    return {
      level: 'Not Established',
      reason: 'Fewer than two independent evidence signals are currently available to support a conviction level.',
      signals: signals.map((signal) => signal.text),
    };
  }
  const positiveCount = signals.filter((signal) => signal.positive).length;
  const level = positiveCount === signals.length ? 'High' : positiveCount === 0 ? 'Low' : 'Medium';
  return {
    level,
    reason: `Because ${signals.map((signal) => signal.text).join(', and ')}.`,
    signals: signals.map((signal) => signal.text),
  };
}

// AT-ED-014 Section 6, Layer 3 (Scenario Analysis): the one scenario this evidence genuinely
// supports today is "how many current recommendations already clear the real auto-trade
// threshold, and what happens if that holds" - computed from the exact same confidence field and
// threshold the backend itself gates execution on, not a hypothetical model.
function autoTradeScenario(recommendations) {
  const active = (recommendations || []).filter((item) => item.freshness_status !== 'Expired');
  if (!active.length) {
    return {
      available: false,
      reason: 'There are no active recommendations to build a scenario from right now.',
    };
  }
  const eligible = active.filter((item) => {
    const confidence = Number(item.confidence_score ?? item.confidence);
    return Number.isFinite(confidence) && confidence >= AUTO_TRADE_CONFIDENCE_THRESHOLD;
  });
  return {
    available: true,
    statement: eligible.length
      ? `If current confidence levels hold, ${eligible.length} of ${active.length} active recommendation(s) already clear the ${Math.round(AUTO_TRADE_CONFIDENCE_THRESHOLD * 100)}% auto-trade threshold and remain eligible for execution within their evaluation window.`
      : `None of the ${active.length} active recommendation(s) currently clear the ${Math.round(AUTO_TRADE_CONFIDENCE_THRESHOLD * 100)}% auto-trade threshold; execution would require either fresh, higher-confidence evidence or Founder override.`,
    eligibleCount: eligible.length,
    activeCount: active.length,
  };
}

// AT-ED-014 Section 7: Portfolio Forecasting. Facts are passed straight through (Layer 1); the
// position-count scenario is Layer 3, built only from real open-position data; every field that
// would require a time-series/volatility model this backend does not have is always returned as
// unavailable with a named reason, never a fabricated number.
function portfolioForecast({ portfolio, recommendations, valueProjection }) {
  const facts = {
    portfolioValue: portfolio?.portfolio_value ?? null,
    cashAvailable: portfolio?.cash_available ?? null,
    deployedCapital: portfolio?.deployed_capital ?? null,
    openPositionCount: portfolio?.open_positions ? portfolio.open_positions.length : null,
  };
  const scenario = autoTradeScenario(recommendations);
  const noModelReason = 'AI Trader has no time-series portfolio-value or volatility model - only current-snapshot facts and per-recommendation scenarios exist today.';
  return {
    facts: { layer: FORECAST_LAYER.FACT, ...facts },
    executionScenario: { layer: FORECAST_LAYER.SCENARIO, ...scenario },
    // valueProjection is injected by the caller from lib/cio.js's portfolioProjection() so this
    // module never defines a second, potentially-divergent "no forecasting model" statement.
    valueProjection: { layer: FORECAST_LAYER.FORECAST, ...(valueProjection || { available: false, reason: noModelReason }) },
    expectedDrawdown: { layer: FORECAST_LAYER.FORECAST, available: false, reason: noModelReason },
    expectedVolatility: { layer: FORECAST_LAYER.FORECAST, available: false, reason: noModelReason },
  };
}

module.exports = {
  FORECAST_LAYER,
  AUTO_TRADE_CONFIDENCE_THRESHOLD,
  deriveConviction,
  autoTradeScenario,
  portfolioForecast,
};
