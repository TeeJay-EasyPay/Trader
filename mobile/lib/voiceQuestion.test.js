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

test('the button shows an icon rather than a word', () => {
  // 2026-09-03, Founder-directed: "can the button have a microphone icon on it instead of the
  // word speak". The words move to the accessibility label, so nothing is lost for a screen
  // reader -- which is the part a glyph would otherwise break.
  const { MIC_GLYPH, STOP_GLYPH, micButtonAccessibilityLabel, thinkingFrame } = require('./voiceQuestion');
  assert.strictEqual(micButtonLabel('idle'), MIC_GLYPH);
  assert.strictEqual(micButtonLabel('recording'), STOP_GLYPH);
  assert.ok(micButtonAccessibilityLabel('idle').toLowerCase().includes('spoken question'));
  assert.ok(micButtonAccessibilityLabel('recording').toLowerCase().includes('stop'));
});

test('the working state animates instead of sitting still', () => {
  // "while it is checking the speak button should show an animated icon." A still glyph cannot
  // tell "thinking" from "frozen", which is the same complaint that produced the recording
  // indicator in August.
  const { thinkingFrame, THINKING_FRAMES } = require('./voiceQuestion');
  const frames = [0, 1, 2].map(thinkingFrame);
  assert.strictEqual(new Set(frames).size, THINKING_FRAMES.length, 'every frame must differ');
  assert.strictEqual(thinkingFrame(3), thinkingFrame(0), 'and then cycle');
  assert.strictEqual(thinkingFrame(NaN), thinkingFrame(0), 'a bad tick must not blank the button');
});

test('every state keeps the button the same width so it cannot jump under a thumb', () => {
  const { MIC_GLYPH, STOP_GLYPH } = require('./voiceQuestion');
  for (const label of [MIC_GLYPH, STOP_GLYPH, micButtonLabel('transcribing')]) {
    assert.ok(label.length > 0 && label.length <= 3, JSON.stringify(label));
  }
});

test('the status line is always a real sentence', () => {
  for (const state of ['idle', 'requesting', 'recording', 'transcribing', 'nonsense']) {
    assert.ok(voiceStatusText(state).length > 0);
  }
});

console.log(`\n${passed} passed`);

test('recording shows a live, moving indicator (2026-08-25)', () => {
  // Founder-reported: "when I click on speak there is no icon moving or showing my voice is
  // being recorded, like in other apps." The only feedback was a status word further up the
  // card. Without movement there is no way to tell "recording" from "frozen", so the natural
  // response is to press again and lose the question.
  const { recordingIndicator } = require('./voiceQuestion');
  const first = recordingIndicator(0);
  const second = recordingIndicator(1);
  assert.notStrictEqual(first, second, 'the indicator must visibly change each second');
  assert.ok(first.includes('Recording'), first);
  assert.ok(second.includes('1s'), second);
});

test('the indicator warns as the limit approaches', () => {
  const { recordingIndicator } = require('./voiceQuestion');
  assert.ok(recordingIndicator(55).includes('stopping in 5s'), recordingIndicator(55));
  assert.ok(recordingIndicator(10).includes('press Stop'), recordingIndicator(10));
});
