'use strict';

// 2026-09-03, Founder-directed: my question on the right, the AI's answer on the left, no "You"
// label, different colours. These tests pin the rules that make that readable rather than just
// colourful.

const assert = require('node:assert/strict');
const { test } = require('node:test');
const {
  isFounder, bubbleAlignment, bubbleColours, bubbleOpacity,
  bubbleStyle, normalizeTurn, mergeTurns,
} = require('./chatBubbles');

test('my messages sit on the right and the AI on the left', () => {
  assert.equal(bubbleAlignment('founder'), 'flex-end');
  assert.equal(bubbleAlignment('assistant'), 'flex-start');
});

test('an unrecognised role is never shown as mine', () => {
  // A message of unknown origin appearing in the Founder's colour on his own side would be a
  // lie about who said it. Defaulting to the AI side is the safe direction.
  assert.equal(isFounder('system'), false);
  assert.equal(isFounder(null), false);
  assert.equal(bubbleAlignment(undefined), 'flex-start');
});

test('"user" is treated as mine, because the server and the app name it differently', () => {
  assert.equal(isFounder('user'), true);
  assert.equal(isFounder('founder'), true);
});

test('the two speakers never share a colour', () => {
  const mine = bubbleColours('founder');
  const theirs = bubbleColours('assistant');
  assert.notEqual(mine.background, theirs.background);
  assert.notEqual(mine.text, theirs.text);
});

test('neither bubble borrows the colours that mean money in this app', () => {
  // Red and green mean loss and profit on every other screen. A neutral sentence rendered in
  // either would read as a result.
  for (const role of ['founder', 'assistant']) {
    const { background } = bubbleColours(role);
    assert.ok(!/^#(ff0000|00ff00|d0021b|2ecc71)/i.test(background), `${role} uses a P&L colour`);
  }
});

test('a pending turn is dimmed so it does not look like a finished answer', () => {
  // The spoken "let me check that" arrives before any real answer. Without this it is
  // indistinguishable from the reply itself.
  assert.ok(bubbleOpacity({ pending: true }) < 1);
  assert.equal(bubbleOpacity({ pending: false }), 1);
  assert.equal(bubbleOpacity(null), 1);
});

test('the squared corner is on the speaker side', () => {
  assert.equal(bubbleStyle({ role: 'founder' }).borderBottomRightRadius, 4);
  assert.equal(bubbleStyle({ role: 'assistant' }).borderBottomLeftRadius, 4);
});

test('a bubble never spans the full width, so the side it sits on stays visible', () => {
  assert.equal(bubbleStyle({ role: 'founder' }).maxWidth, '85%');
});

test('empty turns are dropped rather than rendered as blank bubbles', () => {
  assert.equal(normalizeTurn({ role: 'founder', text: '   ' }), null);
  assert.equal(normalizeTurn(null), null);
});

test('stored history and this session merge without showing anything twice', () => {
  // The server does not know about optimistic turns; the session does not know about
  // yesterday. Both are needed and the overlap has to go.
  const stored = [
    { turn_id: 1, role: 'founder', text: 'am I up today' },
    { turn_id: 2, role: 'assistant', text: 'Kraken is up 5.67 today.' },
  ];
  const live = [
    { role: 'founder', text: 'am I up today' },
    { role: 'assistant', text: 'Kraken is up 5.67 today.' },
    { role: 'founder', text: 'and crypto?' },
  ];
  const merged = mergeTurns(stored, live);
  assert.equal(merged.length, 3);
  assert.equal(merged[2].text, 'and crypto?');
});

test('history comes first so the conversation reads in order', () => {
  const merged = mergeTurns(
    [{ turn_id: 1, role: 'founder', text: 'older' }],
    [{ role: 'founder', text: 'newer' }],
  );
  assert.deepEqual(merged.map((t) => t.text), ['older', 'newer']);
});

test('every turn gets a stable key so the list does not re-render wrongly', () => {
  const merged = mergeTurns([{ turn_id: 7, role: 'assistant', text: 'hello' }], []);
  assert.equal(merged[0].key, 't7');
  const live = mergeTurns([], [{ role: 'founder', text: 'hello' }]);
  assert.ok(live[0].key.length > 0);
});

test('the server role name survives normalisation', () => {
  assert.equal(normalizeTurn({ role: 'founder', text: 'x' }).role, 'founder');
  assert.equal(normalizeTurn({ role: 'assistant', text: 'x' }).role, 'assistant');
  assert.equal(normalizeTurn({ role: 'user', text: 'x' }).role, 'founder');
});
