// Founder-requested 2026-08-20: a small Executive Briefing card showing how many trades
// each day, week and month were successful and how many were not, with a short AI summary
// of the lessons learned.
//
// The reshaping rules here exist because of specific things that have gone wrong on this
// screen before:
//   - `null` (not yet loaded) must never render as "0 successful". Number(null) === 0 is
//     finite, and that exact trap already produced a card asserting "Low confidence" when
//     the truth was "unknown" (see marketForecast.js's confidenceLabel).
//   - Trades that closed but have no reconciled profit or loss are shown separately as
//     "awaiting reconciliation", never folded into the win or loss counts.
//   - The lessons line is kept short. The briefing already suffers from long generated
//     text burying the short high-value sections.

const PERIOD_LABELS = [
  ['day', 'Today'],
  ['week', 'This week'],
  ['month', 'This month'],
];

const NO_SCORECARD_ROWS = [];

const NO_SCORECARD_MESSAGE = 'Trade results have not loaded yet.';

function isFiniteNumber(value) {
  if (value === null || value === undefined || value === '') return false;
  return Number.isFinite(Number(value));
}

function countText(bucket) {
  if (!bucket) return null;
  const successful = isFiniteNumber(bucket.successful) ? Number(bucket.successful) : null;
  const unsuccessful = isFiniteNumber(bucket.unsuccessful) ? Number(bucket.unsuccessful) : null;
  if (successful === null || unsuccessful === null) return null;
  if (successful === 0 && unsuccessful === 0) return 'No completed trades';
  return `${successful} worked / ${unsuccessful} didn't`;
}

function winRateText(bucket) {
  if (!bucket || !isFiniteNumber(bucket.win_rate)) return null;
  return `${Math.round(Number(bucket.win_rate) * 100)}% win rate`;
}

function pendingText(bucket) {
  if (!bucket || !isFiniteNumber(bucket.unknown)) return null;
  const unknown = Number(bucket.unknown);
  if (unknown <= 0) return null;
  return `${unknown} awaiting reconciliation`;
}

function netText(bucket) {
  if (!bucket || !isFiniteNumber(bucket.net_pnl)) return null;
  const net = Number(bucket.net_pnl);
  if (net === 0) return null;
  const sign = net > 0 ? '+' : '-';
  return `${sign}£${Math.abs(net).toFixed(2)}`;
}

function scorecardRows(scorecard) {
  if (!scorecard) return NO_SCORECARD_ROWS;
  return PERIOD_LABELS.map(([key, label]) => {
    const bucket = scorecard[key];
    return {
      key,
      label,
      counts: countText(bucket) || 'No completed trades',
      winRate: winRateText(bucket),
      pending: pendingText(bucket),
      net: netText(bucket),
    };
  });
}

function lessonsText(scorecard) {
  if (!scorecard) return NO_SCORECARD_MESSAGE;
  const lessons = typeof scorecard.lessons === 'string' ? scorecard.lessons.trim() : '';
  if (!lessons) return 'No lessons recorded yet.';
  return lessons;
}

function tradeScorecardCard(scorecard) {
  return {
    loaded: Boolean(scorecard),
    rows: scorecardRows(scorecard),
    lessons: lessonsText(scorecard),
  };
}

module.exports = {
  NO_SCORECARD_MESSAGE,
  NO_SCORECARD_ROWS,
  countText,
  lessonsText,
  netText,
  pendingText,
  scorecardRows,
  tradeScorecardCard,
  winRateText,
};
