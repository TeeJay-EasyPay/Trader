// 2026-08-25, Founder-directed: "can we have a microphone button... so I don't have to type
// stuff, I can just press it and just ask the app something verbally and submit it."
//
// The recording itself has to happen on the device; the words do not. The phone records and
// sends bytes, and the backend (/transcribe-question) turns them into text using the same
// OpenAI account the rest of the app already uses. That keeps one native dependency instead of
// two, one permission prompt instead of two, and identical behaviour on Android and iOS.
//
// The states below exist because a microphone has more ways to go wrong than a text box, and
// every one of them has to leave the Founder able to type the question instead. Voice is a
// convenience on top of Ask; it must never become a way to lose a question.

'use strict';

const VOICE_STATES = {
  idle: 'Ready',
  requesting: 'Asking for microphone access...',
  recording: 'Listening - press again to stop',
  transcribing: 'Working out what you said...',
};

// Long enough for a real question, short enough that a phone left recording in a pocket cannot
// upload something huge or expensive.
const MAX_RECORDING_SECONDS = 60;

function voiceStatusText(state) {
  return VOICE_STATES[state] || VOICE_STATES.idle;
}

function micButtonLabel(state) {
  if (state === 'recording') return 'Stop';
  if (state === 'transcribing') return 'Working...';
  return 'Speak';
}

// A microphone failure has to say what the Founder can do next, not what went wrong inside.
function voiceErrorMessage(kind) {
  switch (kind) {
    case 'permission_denied':
      return 'AI Trader needs microphone access to take a spoken question. You can enable it in your phone settings, or type the question instead.';
    case 'not_configured':
      return 'Voice questions are not switched on for this deployment yet. Type the question instead.';
    case 'too_large':
      return 'That recording is too long. Ask a shorter question, or type it instead.';
    case 'empty':
      return 'I could not hear a question in that recording. Try again, or type it instead.';
    default:
      return 'I could not record that. Try again, or type the question instead.';
  }
}

// The backend answers with a status and a message rather than raising, so this decides what the
// screen does with it: use the words, or explain and leave the text box ready.
function resolveTranscription(payload) {
  const status = String(payload?.status || '');
  const text = String(payload?.text || '').trim();
  if (status === 'transcribed' && text) {
    return { ok: true, text };
  }
  if (status === 'transcribed' && !text) {
    return { ok: false, text: '', message: voiceErrorMessage('empty') };
  }
  return {
    ok: false,
    text: '',
    // The backend's own message is preferred when it has one: it knows whether the key is
    // missing, the file was unreadable, or the recording was simply too long.
    message: String(payload?.message || '') || voiceErrorMessage(status),
  };
}

module.exports = {
  VOICE_STATES,
  MAX_RECORDING_SECONDS,
  voiceStatusText,
  micButtonLabel,
  voiceErrorMessage,
  resolveTranscription,
};
