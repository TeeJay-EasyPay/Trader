// Pure helpers for the Learning screen's Ask AI Trader chat: request-timeout racing, message
// text normalisation, and grouping chat history into newest-first user/assistant turns.
// Extracted from App.js as part of AT-ED-011 Phase 2 (mobile modularisation).

'use strict';

function withTimeout(promise, timeoutMs) {
  let timeoutId;
  const timeoutPromise = new Promise((_, reject) => {
    timeoutId = setTimeout(() => reject(new Error(`Request timed out after ${Math.round(timeoutMs / 1000)} seconds.`)), timeoutMs);
  });
  return Promise.race([promise, timeoutPromise]).finally(() => clearTimeout(timeoutId));
}

function normalizeChatText(value) {
  if (value === null || value === undefined) {
    return '';
  }
  const text = typeof value === 'string' ? value : JSON.stringify(value, null, 2);
  return text
    .replace(/\r\n/g, '\n')
    .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g, '')
    .replace(/\n{4,}/g, '\n\n\n')
    .trim();
}

function chatMessageText(value) {
  const text = normalizeChatText(value);
  return text || 'No message text was returned. Try asking again, or check Render logs for the /ask-ai-trader response.';
}

function chatTurnsNewestFirst(messages) {
  const turns = [];
  let current = [];
  (messages || []).forEach((message) => {
    if (message.role === 'user' && current.length) {
      turns.push(current);
      current = [];
    }
    current.push(message);
  });
  if (current.length) {
    turns.push(current);
  }
  return turns.reverse();
}


module.exports = {
  withTimeout,
  normalizeChatText,
  chatMessageText,
  chatTurnsNewestFirst,
};
