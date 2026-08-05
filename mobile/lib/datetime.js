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
  formatPercent,
  todayIso,
  currentMonthPrefix,
};
