// Founder-requested 2026-08-20: "AIs decline reasoning should be available but in a short
// easy to understand answers."
//
// The reviewer vetoes real trades that already cleared every mechanical gate, but its
// reasoning was readable nowhere. This reshapes /decline-reasons for the briefing card.
//
// Kept deliberately terse. The backend already trims to a couple of sentences and strips
// markdown; this layer only decides what is worth showing and never fabricates a value for
// a missing field.

'use strict';

const NO_DECLINES_MESSAGE = 'I have not turned down any trades on judgement recently.';

const NOT_LOADED_MESSAGE = 'Recent decisions have not loaded yet.';

function confidenceNote(confidence) {
  if (confidence === null || confidence === undefined || confidence === '') return null;
  const value = Number(confidence);
  if (!Number.isFinite(value)) return null;
  return `${Math.round(value * 100)}% confident`;
}

function declineRow(record) {
  if (!record || !record.symbol || !record.why) return null;
  return {
    key: `${record.symbol}-${record.created_at || ''}`,
    symbol: record.symbol,
    outcome: record.outcome || 'Declined',
    why: record.why,
    concern: record.main_concern || null,
    confidence: confidenceNote(record.confidence),
  };
}

function declineRows(payload) {
  if (!payload || !Array.isArray(payload.declines)) return [];
  return payload.declines.map(declineRow).filter(Boolean);
}

function declineReasonsCard(payload) {
  const rows = declineRows(payload);
  return {
    loaded: Boolean(payload),
    rows,
    emptyMessage: payload ? NO_DECLINES_MESSAGE : NOT_LOADED_MESSAGE,
  };
}

module.exports = {
  NO_DECLINES_MESSAGE,
  NOT_LOADED_MESSAGE,
  confidenceNote,
  declineReasonsCard,
  declineRow,
  declineRows,
};
