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

// 2026-08-25 Founder-reported: the briefing said "Today: 0 worked / 1 didn't" while the
// Portfolio card on the same refresh said "Completed Trades Today: 0". Neither number was
// wrong -- they answer different questions while wearing the same word. These buckets are
// ROLLING windows (see summarize_trade_outcomes: last 24h / 7d / 30d, deliberately rolling so
// the card is not near-empty just after a calendar month turns over), whereas the Portfolio
// card counts the calendar day since midnight. At 2pm the rolling window still contains
// yesterday afternoon, so the two legitimately disagree.
//
// Labelling them honestly is the fix, not forcing them to match: a founder who reads "Last 24
// hours" and "Completed today" can hold both in his head at once, where "Today" and "Today"
// showing different numbers just means the app cannot be trusted.
const PERIOD_LABELS = [
  ['day', 'Last 24 hours'],
  ['week', 'Last 7 days'],
  ['month', 'Last 30 days'],
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

function feesText(scorecard) {
  const fees = scorecard && scorecard.fees;
  if (!fees || !fees.available) return null;
  return typeof fees.plain_english === 'string' && fees.plain_english.trim()
    ? fees.plain_english.trim()
    : null;
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
    fees: feesText(scorecard),
  };
}

module.exports = {
  NO_SCORECARD_MESSAGE,
  NO_SCORECARD_ROWS,
  countText,
  feesText,
  lessonsText,
  netText,
  pendingText,
  scorecardRows,
  tradeScorecardCard,
  winRateText,
};
