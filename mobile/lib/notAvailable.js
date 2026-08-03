function notAvailable(value) {
  if (value === null || value === undefined || value === '') {
    return 'Not available - source data has not been recorded yet.';
  }
  return String(value);
}

function explainMissing(field, reason) {
  return `Not available - ${field} is unavailable because ${reason}.`;
}

module.exports = {
  notAvailable,
  explainMissing,
};
