function dateMs(value) {
  if (typeof value === 'number' || (typeof value === 'string' && /^\d+(\.\d+)?$/.test(value.trim()))) {
    const number = Number(value);
    if (Number.isFinite(number) && number > 1000000000) {
      return number > 1000000000000 ? number : number * 1000;
    }
  }
  const ms = Date.parse(value || '');
  return Number.isFinite(ms) ? ms : 0;
}

function formatDateTime(value) {
  if (!value) {
    return null;
  }
  const epochMs = dateMs(value);
  const date = epochMs ? new Date(epochMs) : new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString(undefined, {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

// A compact "21 Aug, 07:49" form for narrow table columns (Trade History) where the full
// formatDateTime() output ("21 Aug 2026, 07:49") does not fit alongside four other columns on a
// phone screen. Drops the year (every row on this screen is recent enough that the year is
// implied) rather than the day or time, since a trader's first two questions are "when, today
// or a prior day" and "what time", not "what year".
function formatShortDateTime(value) {
  if (!value) {
    return null;
  }
  const epochMs = dateMs(value);
  const date = epochMs ? new Date(epochMs) : new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  const datePart = date.toLocaleString(undefined, { day: '2-digit', month: 'short' });
  const timePart = date.toLocaleString(undefined, { hour: '2-digit', minute: '2-digit' });
  return `${datePart}, ${timePart}`;
}

function formatPercent(value) {
  if (value === null || value === undefined || value === '') {
    return null;
  }
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return value;
  }
  const percent = number <= 1 ? number * 100 : number;
  return `${percent.toFixed(0)}%`;
}

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

// AT-ED-017 (Founder request, 2026-08-05): "a line which is realised gains so far this month" -
// UTC calendar-month prefix ("YYYY-MM"), matching todayIso()'s UTC calendar-day convention so
// "today" and "this month" figures never disagree about which timezone boundary is in use.
function currentMonthPrefix() {
  return new Date().toISOString().slice(0, 7);
}

module.exports = {
  dateMs,
  formatDateTime,
  formatShortDateTime,
  formatPercent,
  todayIso,
  currentMonthPrefix,
};
