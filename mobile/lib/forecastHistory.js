// AT-ED-016 Part 3: Forecast Accountability, now with real persistence. Kept dependency-free
// (no React/RN, no AsyncStorage import - that I/O lives in hooks/useForecastHistory.js, mirroring
// how lib/founderEvidenceCache.js stays pure while its AsyncStorage calls live in
// hooks/useFounderEvidence.js) - see forecastHistory.test.js.
//
// Produces records in exactly the shape lib/forecastAccountability.js's FORECAST_RECORD_SHAPE
// already defined (AT-ED-014) - that module was scaffolded specifically for this moment
// ("once persistence exists"); this pass is what finally gives it real records to summarise,
// rather than duplicating its accuracy-calculation logic here.
//
// Honesty boundary (see Executive_Briefing_Evolution_Design_Review.md, Part 3): this is local,
// on-device persistence, not a backend table - "compare forecast to actual outcome" means
// comparing against the portfolio value this device next observes live on or after the
// forecast's target date, not a continuously-sampled time series (none is collected). A forecast
// is graded on DIRECTIONAL accuracy only (did it correctly call up/down/flat) - exact-value
// accuracy is not a meaningful bar for a linear extrapolation model, and grading it that way
// would make every real forecast "wrong" by some tiny margin, which is not what "accuracy" means
// here.

'use strict';

const { HORIZONS } = require('./forecastEngine');

const HORIZON_DAYS_BY_KEY = HORIZONS.reduce((map, horizon) => ({ ...map, [horizon.key]: horizon.days }), {});

// Roughly once per day, matching the morning-briefing cadence - without this, a screen that
// auto-refreshes every couple of minutes (see AT-ED-010's AUTO_REFRESH_INTERVAL_MS) would store a
// near-duplicate forecast record on every refresh, drowning the real accountability signal in
// noise rather than producing a meaningful daily track record.
const MIN_RECORD_INTERVAL_MS = 20 * 60 * 60 * 1000;

function shouldRecordNewForecast(records, horizonKey, now = new Date()) {
  const recent = (records || []).find(
    (record) => record.horizonKey === horizonKey && now.getTime() - new Date(record.createdAt).getTime() < MIN_RECORD_INTERVAL_MS
  );
  return !recent;
}

// Only a horizon lib/forecastEngine.js's projectHorizon() marked `available: true` is ever
// turned into a stored promise - an unavailable forecast is not a forecast, so there is nothing
// to hold AI Trader accountable for.
function buildForecastRecord({ horizon, horizonDays, portfolioValueAtCreation, createdAt = new Date().toISOString() }) {
  if (!horizon || !horizon.available || !Number.isFinite(horizonDays)) {
    return null;
  }
  const created = new Date(createdAt);
  if (Number.isNaN(created.getTime())) {
    return null;
  }
  const targetDate = new Date(created.getTime() + horizonDays * 86400000).toISOString();
  return {
    id: `${horizon.horizonKey}-${created.getTime()}`,
    horizonKey: horizon.horizonKey,
    forecast: `${horizon.horizon} portfolio value`,
    createdAt,
    targetDate,
    expectedOutcome: horizon.expectedValue,
    bullExpectedValue: horizon.bullCase ? horizon.bullCase.expectedValue : null,
    bearExpectedValue: horizon.bearCase ? horizon.bearCase.expectedValue : null,
    // The real historical win rate this forecast was built from (lib/forecastEngine.js's
    // `probability`), not a Low/Medium/High label mapped to an arbitrary number.
    confidenceGiven: horizon.probability,
    portfolioValueAtCreation,
    actualOutcome: null,
    resolvedAt: null,
    forecastError: null,
    correct: null,
  };
}

function isDueForResolution(record, now = new Date()) {
  return Boolean(record) && !record.resolvedAt && new Date(record.targetDate).getTime() <= now.getTime();
}

// null (not `false`) when there is no meaningful direction to grade - e.g. the forecast expected
// no change, or either value is missing. A record with a null verdict is never counted as
// correct or incorrect by lib/forecastAccountability.js (it only counts records with a real
// boolean `correct`).
function judgeDirection(fromValue, toValue) {
  if (!Number.isFinite(fromValue) || !Number.isFinite(toValue) || fromValue === toValue) {
    return null;
  }
  return toValue > fromValue ? 'up' : 'down';
}

function resolveRecord(record, actualPortfolioValue, now = new Date()) {
  if (!record) {
    return record;
  }
  const expectedDirection = judgeDirection(record.portfolioValueAtCreation, record.expectedOutcome);
  const actualDirection = judgeDirection(record.portfolioValueAtCreation, actualPortfolioValue);
  const correct = expectedDirection && actualDirection ? expectedDirection === actualDirection : null;
  const forecastError = Number.isFinite(actualPortfolioValue) && Number.isFinite(record.expectedOutcome)
    ? actualPortfolioValue - record.expectedOutcome
    : null;
  return {
    ...record,
    actualOutcome: actualPortfolioValue,
    resolvedAt: now.toISOString(),
    forecastError,
    correct,
  };
}

// Resolves every record that is due and not yet resolved against the one real observation this
// device has right now (the current portfolio value) - unresolved, not-yet-due records are
// returned unchanged.
function resolveDueRecords(records, actualPortfolioValue, now = new Date()) {
  return (records || []).map((record) => (isDueForResolution(record, now) ? resolveRecord(record, actualPortfolioValue, now) : record));
}

// One call to turn "here are today's five horizon forecasts" into "here are the new records
// worth storing" - skips any horizon that isn't `available`, and any horizon that already has a
// recent (within MIN_RECORD_INTERVAL_MS) unresolved record, so a screen can safely call this on
// every refresh without spamming duplicate promises.
function buildNewRecordsForHorizons({ horizons, portfolioValueAtCreation, existingRecords, now = new Date(), createdAt }) {
  return (horizons || [])
    .filter((horizon) => horizon.available && shouldRecordNewForecast(existingRecords, horizon.horizonKey, now))
    .map((horizon) => buildForecastRecord({
      horizon,
      horizonDays: HORIZON_DAYS_BY_KEY[horizon.horizonKey],
      portfolioValueAtCreation,
      createdAt: createdAt || now.toISOString(),
    }))
    .filter(Boolean);
}

module.exports = {
  HORIZON_DAYS_BY_KEY,
  MIN_RECORD_INTERVAL_MS,
  shouldRecordNewForecast,
  buildForecastRecord,
  buildNewRecordsForHorizons,
  isDueForResolution,
  judgeDirection,
  resolveRecord,
  resolveDueRecords,
};
