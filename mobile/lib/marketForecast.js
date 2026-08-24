// Phase 7 of the CIO-level forecasting build (2026-08-20, Founder-directed).
//
// The Founder rejected the previous Forecast Centre outright: it averaged the AI's own
// past closed trades and projected that forward. His words -- "that's not forecasting...
// forecasting is about planning, looking at market trends, looking at whether there is a
// bull run coming or not. I want the forecasting to be at a proper chief investment
// officer level."
//
// This reshapes the backend's real market forecast (/market-forecast, built from genuine
// multi-timeframe technical analysis -- see forecasting.py) into what ForecastCentreCard
// renders. Founder decision the same day: fully REPLACE the trade-averaging view, do not
// keep it as a secondary panel.
//
// Honest-disclosure rule this codebase holds throughout (see forecastEngine.js's
// NO_VOLATILITY_MODEL_REASON for the same principle): where the backend genuinely cannot
// produce a numeric point estimate, say so plainly rather than fabricating a number to
// fill the shape. A direction-and-confidence call IS the honest output of this model; it
// is not a portfolio-value projection and must never be dressed up as one.

'use strict';

const DIRECTION_LABELS = {
  bullish: 'Upward',
  bearish: 'Downward',
  neutral: 'Sideways',
  uncertain: 'Unclear',
};

// Mirrors the backend's own confidence bands so the app never describes a forecast as
// more certain than forecasting.py itself considers it.
function confidenceLabel(confidence) {
  // null/undefined/'' must NOT fall through to a band: Number(null) === 0, which is
  // finite, so without this guard a missing confidence would be displayed as "Low" --
  // asserting low confidence when the truth is that we do not know. Caught by test.
  if (confidence === null || confidence === undefined || confidence === '') {
    return 'Unknown';
  }
  const value = Number(confidence);
  if (!Number.isFinite(value)) {
    return 'Unknown';
  }
  if (value >= 0.75) {
    return 'High';
  }
  if (value >= 0.55) {
    return 'Medium';
  }
  return 'Low';
}

function directionLabel(direction) {
  return DIRECTION_LABELS[String(direction || '').toLowerCase()] || 'Unclear';
}

function parseEvidencePayload(forecast) {
  const raw = forecast?.evidence_json;
  if (!raw) {
    return {};
  }
  if (typeof raw === 'object') {
    return raw;
  }
  try {
    return JSON.parse(raw) || {};
  } catch (error) {
    return {};
  }
}

function ageInHours(createdAt) {
  const created = new Date(createdAt).getTime();
  if (!Number.isFinite(created)) {
    return null;
  }
  return (Date.now() - created) / 3600000;
}

// A forecast older than its own horizon is stale evidence of a past view, not a current
// one. Surfaced rather than hidden -- the Founder should see that it is old, not silently
// be shown an out-of-date call as if it were fresh.
function stalenessNote(forecast) {
  const hours = ageInHours(forecast?.created_at);
  if (hours === null) {
    return null;
  }
  if (hours < 24) {
    return null;
  }
  const days = Math.floor(hours / 24);
  return `This view is ${days} day${days === 1 ? '' : 's'} old and may no longer reflect current conditions.`;
}

// Shapes one backend forecast into the same contract ForecastCentreCard already renders
// (`available`, `horizon`, plus the four Founder-facing fields), so the screen's rendering
// logic needs no restructuring -- only its data source changes.
function forecastCardFromRecord(forecast) {
  if (!forecast) {
    return null;
  }
  const payload = parseEvidencePayload(forecast);
  const supporting = payload.supporting_evidence || [];
  const contradictory = payload.contradictory_evidence || [];
  const risks = payload.key_risks || [];
  const stale = stalenessNote(forecast);

  const whatIExpect = [
    `${directionLabel(forecast.direction)} over roughly the next ${forecast.horizon_days} day${forecast.horizon_days === 1 ? '' : 's'}.`,
    stale,
  ].filter(Boolean).join(' ');

  const why = [
    forecast.reasoning,
    supporting.length ? `Supporting this: ${supporting.join('; ')}.` : null,
  ].filter(Boolean).join(' ');

  const whatCouldChange = [
    forecast.invalidation ? `This view would be wrong if: ${forecast.invalidation}` : null,
    contradictory.length ? `Arguing against it: ${contradictory.join('; ')}.` : null,
    risks.length ? `Key risks: ${risks.join('; ')}.` : null,
  ].filter(Boolean).join(' ');

  return {
    available: true,
    symbol: forecast.symbol,
    horizon: `${forecast.symbol} — next ${forecast.horizon_days} days`,
    horizonKey: `forecast-${forecast.forecast_id}`,
    direction: String(forecast.direction || '').toLowerCase(),
    confidence: confidenceLabel(forecast.confidence),
    confidenceValue: Number(forecast.confidence),
    whatIExpect,
    why: why || 'No reasoning was recorded for this forecast.',
    whatCouldChange: whatCouldChange || 'No invalidation conditions were recorded for this forecast.',
    createdAt: forecast.created_at,
  };
}

// The honest empty state. Deliberately explains WHY there is nothing to show and what
// would change that, rather than rendering a blank card or -- worse -- falling back to a
// fabricated number.
const NO_FORECAST_CARD = Object.freeze({
  available: false,
  horizon: 'Market forecast',
  horizonKey: 'forecast-unavailable',
  reason:
    'I have not produced a market forecast yet. These are generated from real price history and technical analysis on a regular schedule, so one should appear shortly after enough price history has been gathered for the assets I follow.',
});

function marketForecastCards(response) {
  const forecasts = response?.forecasts || [];
  if (!forecasts.length) {
    return [NO_FORECAST_CARD];
  }
  // One card per symbol, newest first. The backend already returns newest-first, so the
  // first record seen for a symbol is its current view.
  const seen = new Set();
  const cards = [];
  forecasts.forEach((forecast) => {
    const symbol = String(forecast?.symbol || '').toUpperCase();
    if (!symbol || seen.has(symbol)) {
      return;
    }
    seen.add(symbol);
    const card = forecastCardFromRecord(forecast);
    if (card) {
      cards.push(card);
    }
  });
  return cards.length ? cards : [NO_FORECAST_CARD];
}


// 2026-08-24, Founder-directed: the Executive Briefing carried 19 separate coin forecasts,
// each a wall of technical jargon (trend_score, momentum_score, ATR_pct, "higher_bias price
// structure"), and most concluded "Unclear" with Low confidence. That was roughly 80% of the
// screen telling the Founder nothing. This is the one line that replaces it; the full cards
// stay available behind a tap for when he actually wants them.
//
// Only counts a directional call the model is at least Medium confident about. An "Upward,
// Low confidence" call is not something to act on, and presenting it as one would be exactly
// the false precision the rest of this file avoids.
function forecastHeadline(cards) {
  const usable = (cards || []).filter((card) => card && card.available);
  if (!usable.length) {
    return 'I have no price forecasts yet.';
  }
  const confident = usable.filter((card) => card.confidence === 'High' || card.confidence === 'Medium');
  const up = confident.filter((card) => card.direction === 'up').length;
  const down = confident.filter((card) => card.direction === 'down').length;
  const unclear = usable.length - up - down;
  if (!up && !down) {
    return `Of ${usable.length} assets I follow, none has a clear enough direction to act on.`;
  }
  const parts = [];
  if (up) {
    parts.push(`${up} looking up`);
  }
  if (down) {
    parts.push(`${down} looking down`);
  }
  return `Of ${usable.length} assets I follow: ${parts.join(', ')}, ${unclear} unclear.`;
}

module.exports = {
  forecastHeadline,
  NO_FORECAST_CARD,
  confidenceLabel,
  directionLabel,
  forecastCardFromRecord,
  marketForecastCards,
  stalenessNote,
};
