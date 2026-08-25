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

// 2026-08-25 Founder-reported: "when I click on speak there is no icon moving or showing my
// voice is being recorded, like in other apps." He was right -- the only feedback was a status
// word changing further up the card, which is easy to miss and says nothing about whether the
// microphone is actually picking anything up. Without it there is no way to tell "recording"
// from "frozen", so the natural thing to do is press again and lose the question.
//
// A live elapsed count is the honest version of a moving waveform: it is real information
// (the recording is running, and this is how long it has), it needs no animation library, and
// it doubles as a warning as the 60-second limit approaches.
function recordingIndicator(elapsedSeconds, maxSeconds = MAX_RECORDING_SECONDS) {
  const elapsed = Math.max(0, Math.floor(Number(elapsedSeconds) || 0));
  const remaining = Math.max(0, maxSeconds - elapsed);
  // A pulsing dot built from text, so the movement the Founder asked for needs no extra
  // dependency: the filled circle alternates each second.
  const pulse = elapsed % 2 === 0 ? '●' : '○';
  if (remaining <= 10) {
    return `${pulse} Recording ${elapsed}s - stopping in ${remaining}s`;
  }
  return `${pulse} Recording ${elapsed}s - press Stop when finished`;
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
    case 'unsupported':
      // The installed app predates the microphone. runtimeVersion is "appVersion", so one
      // over-the-air update reaches builds with and without the native audio module; the
      // older one must say so plainly rather than appear broken.
      return 'Speaking needs the newest version of AI Trader. Type your question here for now, and use voice once the new app is installed.';
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
  recordingIndicator,
  micButtonLabel,
  voiceErrorMessage,
  resolveTranscription,
};
