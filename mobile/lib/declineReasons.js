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

const NO_DECLINES_MESSAGE = 'No refusals appear in the returned evidence sample.';

const NOT_LOADED_MESSAGE = 'Recent decisions have not loaded yet.';

function brokerLabel(value) {
  if (!value || value === 'unknown') return 'Exchange unknown';
  return ({ kraken: 'Kraken', alpaca: 'Alpaca' })[value] || value;
}

function confidenceNote(confidence) {
  if (confidence === null || confidence === undefined || confidence === '') return null;
  const value = Number(confidence);
  if (!Number.isFinite(value)) return null;
  return `${Math.round(value * 100)}% confident`;
}

function declineRow(record) {
  if (!record || !record.symbol || !record.why) return null;
  return {
    key: `${record.broker || 'unknown'}-${record.symbol}-${record.created_at || ''}`,
    broker: brokerLabel(record.broker),
    created_at: record.created_at,
    symbol: record.symbol,
    outcome: record.outcome || 'Declined',
    why: record.why,
    // `why` is already the concern when one exists; `assessment` is the fuller view.
    assessment: record.assessment || null,
    confidence: confidenceNote(record.confidence),
  };
}

function declineRows(payload) {
  if (!payload || !Array.isArray(payload.declines)) return [];
  return payload.declines.map(declineRow).filter(Boolean);
}

// 2026-09-01, Founder-questioned: "I wonder whether the View Ahead card and Trades I turned
// down cards are giving me up to date information."
//
// The View Ahead was current. This card had been empty for days -- correctly by its own
// design, since it shows the AI reviewer's JUDGEMENT calls and nothing had reached the
// reviewer. But a card headed "Trades I Turned Down" showing nothing, on a day the app turned
// down hundreds of ideas on mechanical rules, reads as broken rather than as precise.
//
// Both categories are now shown. Empty describes only the returned evidence sample.
function mechanicalRows(payload) {
  const summary = payload && Array.isArray(payload.mechanical_summary)
    ? payload.mechanical_summary
    : [];
  return summary
    .filter((item) => item && item.count)
    .map((item) => {
      const examples = Array.isArray(item.examples) && item.examples.length
        ? ` (${item.examples.join(', ')})`
        : '';
      return {
        key: `mechanical-${item.broker || 'unknown'}-${item.reason}`,
        broker: brokerLabel(item.broker),
        symbol: `${item.count} decision check${item.count === 1 ? '' : 's'}`,
        outcome: 'blocked by rules',
        why: `${item.explanation}${examples}.`,
        assessment: '',
        confidence: '',
      };
    });
}

function declineReasonsCard(payload) {
  const rows = declineRows(payload);
  const mechanical = mechanicalRows(payload);
  return {
    loaded: Boolean(payload),
    rows: [...rows, ...mechanical],
    mechanical: !rows.length && mechanical.length > 0,
    emptyMessage: payload?.available === false ? 'Decision evidence is unavailable.' : payload ? NO_DECLINES_MESSAGE : NOT_LOADED_MESSAGE,
  };
}

module.exports = {
  mechanicalRows,
  NO_DECLINES_MESSAGE,
  NOT_LOADED_MESSAGE,
  confidenceNote,
  declineReasonsCard,
  declineRow,
  declineRows,
};
