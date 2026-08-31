'use strict';

// 2026-08-31, Founder-directed: "can it have a speaking function as well so that when I speak
// to it it responds back to me with text and speech", and when asked when it should speak:
// "I want it to be like a chatgpt conversation. And like option 1 above 'only when you asked
// by voice'".
//
// So: speaking is a property of the TURN, not a setting. Ask by voice and it answers out
// loud; type and it stays quiet. No toggle to forget, no surprise noise when the app is
// opened somewhere quiet, and no extra control on a screen the Founder has twice asked to
// keep simple.
//
// This file holds only the decisions, so they can be tested with plain node. The audio
// playback itself lives in screens/Ask.js, which cannot be unit tested.

// Speech is generated server-side (expo-av is already in the shipped binary and can play
// audio; expo-speech would be a new native module and a manual reinstall). The request is a
// second round trip after the answer, so it needs its own budget: long enough for a few
// seconds of audio to be produced and returned, short enough that a hanging speech request
// never delays the text the Founder can already read.
const SPEECH_TIMEOUT_MS = 30000;

// Read aloud, a wall of text is worse than a short answer plus the screen. The full answer is
// always displayed; only the spoken version is trimmed.
const MAX_SPOKEN_CHARACTERS = 700;

/**
 * Whether this reply should be spoken.
 *
 * The rule is deliberately narrow: only a question the Founder ASKED BY VOICE gets a spoken
 * answer. An error message is never spoken -- hearing a failure read out is worse than
 * seeing it, and it would speak over him while he is still working out what went wrong.
 */
function shouldSpeak({ askedByVoice, ok, answer }) {
  if (!askedByVoice || !ok) return false;
  return Boolean(String(answer || '').trim());
}

/**
 * The text to speak: the answer, trimmed at a sentence boundary where possible.
 *
 * Trimming mid-word sounds broken. Trimming at a full stop sounds like a summary, which is
 * what a spoken answer should be when the detail is already on screen.
 */
function spokenText(answer) {
  const text = String(answer || '').replace(/\s+/g, ' ').trim();
  if (!text) return '';
  if (text.length <= MAX_SPOKEN_CHARACTERS) return text;
  const cut = text.slice(0, MAX_SPOKEN_CHARACTERS);
  const lastStop = Math.max(cut.lastIndexOf('. '), cut.lastIndexOf('! '), cut.lastIndexOf('? '));
  if (lastStop > MAX_SPOKEN_CHARACTERS * 0.5) {
    return cut.slice(0, lastStop + 1);
  }
  return `${cut.slice(0, cut.lastIndexOf(' '))}...`;
}

/** Request options for the speech endpoint. */
function speechRequestOptions(text) {
  return {
    method: 'POST',
    body: JSON.stringify({ text: spokenText(text) }),
    // Must be explicit: api/client.js applies its own 25s default to anything that does not
    // pass timeoutMs, which is the same trap askRequest.js documents.
    timeoutMs: SPEECH_TIMEOUT_MS,
  };
}

/**
 * The playable data URI from a speech response, or null if there is nothing to play.
 *
 * Returns null rather than throwing on every failure shape. A missing spoken reply must
 * degrade to "you can still read it", never to an error on top of a perfectly good answer.
 */
function playableAudioUri(payload) {
  if (!payload || typeof payload !== 'object') return null;
  const audio = payload.audio_base64;
  if (typeof audio !== 'string' || !audio.trim()) return null;
  const contentType = payload.content_type || 'audio/mpeg';
  return `data:${contentType};base64,${audio}`;
}


// 2026-08-31, Founder-reported: "if it needs time to do something, it should be able to
// respond and say, let me check that or just give me a second or let me take a look. And
// that way, at least I know that it's doing something."
//
// The answer itself cannot always be fast -- it reads real broker and market evidence -- so
// the fix is not to pretend otherwise but to STOP THE SILENCE. The acknowledgement is shown
// and spoken within a second of the question landing, so the wait becomes a pause in a
// conversation rather than an app that might be broken.
//
// Varied rather than fixed, because hearing the identical sentence every time is how a
// person stops believing anything is happening. Chosen by question length so a quick "am I
// up today" does not get "this might take a moment".
const QUICK_ACKS = [
  'Let me check that.',
  'One moment.',
  'Let me take a look.',
];

const SLOWER_ACKS = [
  'Let me look that up, give me a second.',
  'Good question, let me check the numbers.',
  'Let me pull that together for you.',
];

/**
 * What to say the instant a question arrives, before the real answer exists.
 *
 * `seed` makes the choice deterministic for tests while still varying in use -- callers pass
 * something that changes per question, such as its length or a timestamp.
 */
function acknowledgement(question, seed) {
  const text = String(question || '').trim();
  if (!text) return '';
  const pool = text.length > 45 ? SLOWER_ACKS : QUICK_ACKS;
  const index = Math.abs(Number.isFinite(seed) ? seed : text.length) % pool.length;
  return pool[index];
}

module.exports = {
  acknowledgement,
  shouldSpeak,
  spokenText,
  speechRequestOptions,
  playableAudioUri,
  SPEECH_TIMEOUT_MS,
  MAX_SPOKEN_CHARACTERS,
};
