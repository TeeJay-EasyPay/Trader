// AT-ED-014 Section 9: Forecast Accountability - tracking forecast vs. actual outcome over time.
// Kept dependency-free (no React/RN imports), matching every other lib/*.js convention - see
// forecastAccountability.test.js.
//
// This backend has no persisted forecast-history table - AT-ED-014 is the pass that introduces
// forecasting at all (see lib/forecasting.js), so there is nothing yet to compare a forecast
// against a later, realized outcome. Per the directive's own instruction ("scaffold the
// architecture rather than fabricating results"), this module defines the real shape a forecast
// record and an accuracy summary will take, and computes real statistics whenever a caller does
// have a `records` array to pass in (e.g. once a future pass adds persistence) - but with no
// records, it always reports the honest, literal truth: no track record exists yet.

'use strict';

// The shape every future forecast-history record should take once persistence exists. Exported
// so a future backend/local-storage integration has one authoritative shape to write to, rather
// than each caller inventing its own field names.
const FORECAST_RECORD_SHAPE = Object.freeze([
  'forecast', 'expectedOutcome', 'actualOutcome', 'confidenceGiven', 'createdAt', 'resolvedAt',
]);

function isResolved(record) {
  return record && record.actualOutcome !== null && record.actualOutcome !== undefined;
}

// A resolved record counts as accurate only when the caller has already determined and set
// `correct: true/false` on it (comparing expected vs. actual is a domain judgement this module
// does not make up a rule for) - a record without that field is treated as not yet judged, never
// silently assumed correct.
function forecastAccountability(records) {
  const list = records || [];
  if (!list.length) {
    return {
      available: false,
      reason: 'AI Trader has not yet recorded a forecast to compare against an outcome. Accountability tracking begins with the next forecast this pass introduces.',
      trackRecord: [],
      accuracy: null,
      confidenceGiven: null,
      confidenceEarned: null,
    };
  }
  const resolved = list.filter(isResolved);
  const judged = resolved.filter((record) => typeof record.correct === 'boolean');
  const accuracy = judged.length ? judged.filter((record) => record.correct).length / judged.length : null;
  const confidenceValues = list
    .map((record) => Number(record.confidenceGiven))
    .filter((value) => Number.isFinite(value));
  const confidenceGiven = confidenceValues.length
    ? confidenceValues.reduce((sum, value) => sum + value, 0) / confidenceValues.length
    : null;
  return {
    available: true,
    reason: null,
    trackRecord: list,
    accuracy,
    confidenceGiven,
    // "Confidence earned" is only meaningful once forecasts are judged - never inferred from
    // confidenceGiven alone, since a confident forecast that turned out wrong must lower it, not
    // just restate the original confidence back.
    confidenceEarned: accuracy,
  };
}

module.exports = {
  FORECAST_RECORD_SHAPE,
  isResolved,
  forecastAccountability,
};
