'use strict';

// 2026-09-04, Founder-reported: the status said "Answered using gpt-4.1" while the answer was
// a canned readout of table values. The backend had returned status "openai_failed" with a 429.
// The screen printed the CONFIGURED model rather than the one that answered, so a failure was
// displayed as a success -- and the real problem, that the model never ran, stayed hidden.

const assert = require('node:assert/strict');
const { test } = require('node:test');
const { askStatusLine, isModelAnswer, isRateLimited } = require('./askStatus');

test('a real answer names the model that produced it', () => {
  assert.equal(askStatusLine({ status: 'answered', model: 'gpt-4.1' }), 'Answered using gpt-4.1.');
});

test('a rate-limited fallback never claims a model answered', () => {
  // The exact case the Founder caught.
  const line = askStatusLine({
    status: 'openai_failed',
    model: 'gpt-4.1',
    note: 'OpenAI explanation failed... Reason: HTTP Error 429: Too Many Requests',
  });
  assert.ok(!line.includes('gpt-4.1'), line);
  assert.ok(line.includes('stored evidence'), line);
  assert.ok(line.includes('rate-limited'), line);
});

test('the rate-limit case tells him what to do about it', () => {
  // 429 is the one failure he can act on himself, and it is the one that was hidden.
  const line = askStatusLine({ status: 'openai_failed', model: 'gpt-4.1', note: 'HTTP Error 429' });
  assert.ok(/wait a minute/i.test(line), line);
});

test('a non-rate-limit failure does not blame the rate limit', () => {
  const line = askStatusLine({ status: 'openai_failed', model: 'gpt-4.1', note: 'connection reset' });
  assert.ok(line.includes('could not be reached'), line);
  assert.ok(!/rate-limited/i.test(line), line);
});

test('running out of time says so, and says to ask again', () => {
  const line = askStatusLine({ status: 'evidence_only', model: 'gpt-4.1' });
  assert.ok(line.includes('time available'), line);
  assert.ok(/ask again/i.test(line), line);
});

test('a deployment with no model configured says that plainly', () => {
  const line = askStatusLine({ status: 'openai_not_configured', model: null });
  assert.ok(line.includes('no AI model is configured'), line);
});

test('an unknown status is never reported as a model answer', () => {
  // Safer than assuming success for a status this file has not been taught yet -- assuming
  // success is exactly the bug being fixed.
  const line = askStatusLine({ status: 'something_new', model: 'gpt-4.1' });
  assert.ok(!line.includes('gpt-4.1'), line);
});

test('a missing model on a real answer still reads as answered', () => {
  assert.equal(askStatusLine({ status: 'answered' }), 'Answered.');
});

test('isModelAnswer is true only when a model really produced the words', () => {
  assert.equal(isModelAnswer({ status: 'answered' }), true);
  assert.equal(isModelAnswer({ status: 'openai_failed' }), false);
  assert.equal(isModelAnswer({ status: 'evidence_only' }), false);
  assert.equal(isModelAnswer({}), false);
});

test('rate limiting is recognised however the note words it', () => {
  assert.equal(isRateLimited({ note: 'HTTP Error 429: Too Many Requests' }), true);
  assert.equal(isRateLimited({ note: 'rate limit reached for gpt-4.1' }), true);
  assert.equal(isRateLimited({ note: 'Too Many Requests' }), true);
  assert.equal(isRateLimited({ note: 'timed out' }), false);
  assert.equal(isRateLimited({}), false);
});
