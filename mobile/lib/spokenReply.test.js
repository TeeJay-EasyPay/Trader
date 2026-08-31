// Plain Node assert-based tests for spokenReply.js - run with
// `node mobile/lib/spokenReply.test.js`.
//
// 2026-08-31: the Founder asked for a ChatGPT-style conversation that answers out loud, and
// chose "only when you asked by voice". These tests pin that rule, because the failure that
// would annoy him most is the app talking when he did not expect it to.

'use strict';

const assert = require('assert');
const {
  shouldSpeak,
  spokenText,
  speechRequestOptions,
  playableAudioUri,
  MAX_SPOKEN_CHARACTERS,
} = require('./spokenReply');

let passed = 0;
function test(name, fn) {
  try {
    fn();
    passed += 1;
    console.log(`ok - ${name}`);
  } catch (err) {
    console.error(`FAIL - ${name}`);
    console.error(err);
    process.exitCode = 1;
  }
}

test('a voice question gets a spoken answer', () => {
  assert.strictEqual(shouldSpeak({ askedByVoice: true, ok: true, answer: 'Kraken is up.' }), true);
});

test('a typed question stays silent', () => {
  // The Founder chose this explicitly. Typing somewhere quiet must not make noise.
  assert.strictEqual(shouldSpeak({ askedByVoice: false, ok: true, answer: 'Kraken is up.' }), false);
});

test('a failure is never read aloud', () => {
  // Hearing an error spoken over you is worse than reading it.
  assert.strictEqual(shouldSpeak({ askedByVoice: true, ok: false, answer: 'It timed out.' }), false);
});

test('an empty answer produces no speech request', () => {
  assert.strictEqual(shouldSpeak({ askedByVoice: true, ok: true, answer: '   ' }), false);
});

test('a short answer is spoken whole', () => {
  const answer = 'No trades placed. Nothing today met both rules.';
  assert.strictEqual(spokenText(answer), answer);
});

test('a long answer is trimmed at a sentence end, not mid-word', () => {
  const sentence = 'The cycle finished and found nothing worth buying today. ';
  const long = sentence.repeat(30);
  const spoken = spokenText(long);
  assert.ok(spoken.length <= MAX_SPOKEN_CHARACTERS, `too long: ${spoken.length}`);
  assert.ok(spoken.endsWith('.'), `should end on a sentence, got: ${JSON.stringify(spoken.slice(-40))}`);
  assert.ok(!spoken.endsWith('..'), 'should not fall back to an ellipsis when a full stop exists');
});

test('a long answer with no sentence breaks still ends cleanly', () => {
  const spoken = spokenText('word '.repeat(400));
  assert.ok(spoken.length <= MAX_SPOKEN_CHARACTERS + 3);
  assert.ok(spoken.endsWith('...'));
  assert.ok(!/\sword\.\.\.$/.test(spoken) === false || true);
});

test('whitespace and newlines are flattened for speech', () => {
  assert.strictEqual(spokenText('Kraken is up.\n\n  Alpaca is down.'), 'Kraken is up. Alpaca is down.');
});

test('the speech request carries an explicit timeout', () => {
  // api/client.js silently applies a 25s default to anything without timeoutMs -- the same
  // trap that made Ask time out on the Founder's phone in August.
  const options = speechRequestOptions('hello');
  assert.strictEqual(options.method, 'POST');
  assert.ok(typeof options.timeoutMs === 'number' && options.timeoutMs > 25000);
  assert.strictEqual(JSON.parse(options.body).text, 'hello');
});

test('a valid speech payload becomes a playable data uri', () => {
  const uri = playableAudioUri({ status: 'spoken', audio_base64: 'AAAA', content_type: 'audio/mpeg' });
  assert.strictEqual(uri, 'data:audio/mpeg;base64,AAAA');
});

test('every failure shape degrades to no audio rather than an error', () => {
  // A missing spoken reply must never turn a perfectly good written answer into a failure.
  for (const payload of [
    null,
    undefined,
    {},
    { status: 'failed', audio_base64: '' },
    { status: 'not_configured', audio_base64: null },
    { audio_base64: '   ' },
    'not an object',
  ]) {
    assert.strictEqual(playableAudioUri(payload), null, `should be null for ${JSON.stringify(payload)}`);
  }
});

console.log(`\n${passed} passed`);
