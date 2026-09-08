'use strict';

// Deciding when someone has finished speaking.
//
// 2026-09-07, Founder-directed:
//
//   "I also don't want to click on a send button each time. I want the app to detect a long
//    pause and then just respond rather than clicking on the select button."
//
// He is right that a button is friction. He speaks to this app; asking him to reach for the
// screen at the end of every sentence makes it a form with a microphone attached rather than a
// conversation.
//
// Pure on purpose. The microphone, the timers and the native recorder all live in
// useVoiceCapture; what belongs here is only the JUDGEMENT -- has he stopped talking, or is he
// thinking mid-sentence? That decision is worth testing without a device, because getting it
// wrong is worse than the button: cutting him off mid-thought loses what he was saying, and
// never firing leaves him talking into a recorder that has stopped listening for the end.
//
// THREE RULES, each earning its place:
//
//   * Silence only counts AFTER speech. A phone on a desk in a quiet room is silent from the
//     first millisecond; without this it would submit an empty recording instantly, every time.
//   * The pause has to be long enough to be a full stop rather than a breath. Two seconds is
//     the gap people leave when they have finished, not the one mid-sentence.
//   * If the device reports no sound level at all, this never fires. Some hardware does not
//     meter, and silently refusing to submit would be far worse than the button he already
//     has -- so the button stays, and this is only ever an addition to it.

// Sound level is reported in dBFS: 0 is the loudest the microphone can register and -160 is
// digital silence. Speech in a normal room sits around -30 to -10; room tone and breathing sit
// below -45. -45 keeps quiet speech on the right side of the line, because cutting someone off
// for talking softly is the failure that would actually annoy him.
const SILENCE_DB = -45;

// How long the quiet has to last to count as "finished". Long enough to survive the gap between
// sentences, short enough that he is not left waiting for the app to notice.
const PAUSE_MS = 2000;

// He has to have actually said something. A door closing is a spike, not a sentence.
const MIN_SPEECH_MS = 300;

function initialPauseState() {
  return { heardSpeechMs: 0, silentMs: 0, metered: false, shouldSubmit: false };
}

/**
 * Fold one status reading into the decision.
 *
 * @param state     the previous state, from initialPauseState()
 * @param reading   { metering, sinceLastMs } -- sound level in dBFS and the gap since the last
 *                  reading. metering may be null or undefined on hardware that does not meter.
 * @param options   overrides for the three thresholds, for tests and for tuning.
 */
function nextPauseState(state, reading, options = {}) {
  const silenceDb = options.silenceDb === undefined ? SILENCE_DB : options.silenceDb;
  const pauseMs = options.pauseMs === undefined ? PAUSE_MS : options.pauseMs;
  const minSpeechMs = options.minSpeechMs === undefined ? MIN_SPEECH_MS : options.minSpeechMs;

  const previous = state || initialPauseState();
  const level = reading ? reading.metering : null;
  const step = Math.max(0, Number((reading && reading.sinceLastMs) || 0));

  // No metering at all: stay silent about it and never fire. The Stop button is still there,
  // and a device that cannot hear levels must not end up unable to submit.
  if (level === null || level === undefined || Number.isNaN(Number(level))) {
    return { ...previous, shouldSubmit: false };
  }

  const loud = Number(level) > silenceDb;
  const heardSpeechMs = loud ? previous.heardSpeechMs + step : previous.heardSpeechMs;
  const silentMs = loud ? 0 : previous.silentMs + step;

  return {
    metered: true,
    heardSpeechMs,
    silentMs,
    // Both halves are required: enough speech to be a sentence, then enough quiet to be its
    // end. Either alone is a false positive waiting to happen.
    shouldSubmit: heardSpeechMs >= minSpeechMs && silentMs >= pauseMs,
  };
}

/** What to show while listening, so the pause rule is visible rather than mysterious. */
function listeningLabel(state, elapsedSeconds) {
  const seconds = Math.max(0, Math.round(elapsedSeconds || 0));
  const current = state || initialPauseState();
  if (!current.metered) {
    return `Listening  ${seconds}s  -  tap to send`;
  }
  if (current.heardSpeechMs <= 0) {
    return `Listening  ${seconds}s  -  go ahead`;
  }
  if (current.silentMs >= 600) {
    return `Listening  ${seconds}s  -  sending when you stop`;
  }
  return `Listening  ${seconds}s`;
}

module.exports = {
  initialPauseState,
  nextPauseState,
  listeningLabel,
  SILENCE_DB,
  PAUSE_MS,
  MIN_SPEECH_MS,
};
