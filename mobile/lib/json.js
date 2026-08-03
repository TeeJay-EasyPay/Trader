// Generic JSON parsing/formatting used across trade detail, learning lab, and elsewhere.
// Extracted from App.js as part of AT-ED-011 Phase 2 (mobile modularisation).

'use strict';

function parseMaybeJson(value) {
  if (!value) {
    return null;
  }
  if (typeof value === 'object') {
    return value;
  }
  try {
    return JSON.parse(String(value));
  } catch (error) {
    return null;
  }
}

function formatJsonText(value) {
  const parsed = parseMaybeJson(value);
  if (!parsed) {
    return typeof value === 'string' ? value : null;
  }
  return JSON.stringify(parsed, null, 2);
}

module.exports = {
  parseMaybeJson,
  formatJsonText,
};
