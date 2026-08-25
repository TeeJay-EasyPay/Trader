'use strict';

const assert = require('assert');
const { micButtonLabel, resolveTranscription, voiceErrorMessage, voiceStatusText } = require('./voiceQuestion');

let passed = 0;
function test(name, fn) { fn(); console.log(`ok - ${name}`); passed += 1; }

test('a good recording returns the words to ask with', () => {
  const result = resolveTranscription({ status: 'transcribed', text: '  How is XRP doing?  ' });
  assert.strictEqual(result.ok, true);
  assert.strictEqual(result.text, 'How is XRP doing?');
});

test('silence is explained, never asked as an empty question', () => {
  // An empty question sent to Ask reads as the system ignoring the Founder.
  const result = resolveTranscription({ status: 'transcribed', text: '   ' });
  assert.strictEqual(result.ok, false);
  assert.ok(result.message.includes('could not hear'), result.message);
});

test('every failure tells the Founder he can type instead', () => {
  // Voice is a convenience on top of Ask. It must never become a way to lose a question.
  for (const status of ['failed', 'invalid_audio', 'too_large', 'not_configured', 'no_audio']) {
    const result = resolveTranscription({ status });
    assert.strictEqual(result.ok, false);
    assert.ok(/type/i.test(result.message), `${status}: ${result.message}`);
  }
});

test("the backend's own explanation is preferred when it has one", () => {
  const result = resolveTranscription({ status: 'too_large', message: 'That recording is too long. Ask a shorter question, or type it instead.' });
  assert.ok(result.message.includes('too long'), result.message);
});

test('an app without the microphone module says so instead of breaking', () => {
  // runtimeVersion is "appVersion", so one OTA update reaches the build that has the native
  // audio module and the build that does not. The older one must degrade to a sentence.
  const message = voiceErrorMessage('unsupported');
  assert.ok(message.includes('newest version'), message);
  assert.ok(/type/i.test(message), message);
});

test('a permission refusal points at the phone settings, not at an error', () => {
  const message = voiceErrorMessage('permission_denied');
  assert.ok(message.includes('microphone access'), message);
  assert.ok(message.includes('settings'), message);
});

test('the button says what pressing it will do', () => {
  assert.strictEqual(micButtonLabel('idle'), 'Speak');
  assert.strictEqual(micButtonLabel('recording'), 'Stop');
  assert.strictEqual(micButtonLabel('transcribing'), 'Working...');
});

test('the status line is always a real sentence', () => {
  for (const state of ['idle', 'requesting', 'recording', 'transcribing', 'nonsense']) {
    assert.ok(voiceStatusText(state).length > 0);
  }
});

console.log(`\n${passed} passed`);
