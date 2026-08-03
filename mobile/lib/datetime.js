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

module.exports = {
  dateMs,
  formatDateTime,
  formatPercent,
};
