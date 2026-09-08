'use strict';

// Speak, be heard, see it written down. The microphone half of a spoken conversation.
//
// 2026-09-07, Founder-reported, and the report is the reason this file exists:
//
//   "I clicked start conversation. Nothing gets picked up, and there's no icon that's animated
//    that shows me that it's listening... I clicked send. Nothing happened."
//
// The Standup screen had no microphone at all. It was built text-only and that was never said
// out loud, so he reasonably expected the microphone he uses everywhere else in the app, tapped
// a screen with nothing listening on it, and had no way to tell whether he was unheard or the
// thing was broken.
//
// Extracted rather than copied. Ask has this flow already, but Ask is mounted on the Executive
// Briefing, and voice work has taken that screen down once before (2026-08-25, "Cannot find
// native module 'ExponentAV'"). So the shared piece is proven on the new screen first and Ask
// is left alone until it is. Duplication for a while is cheaper than breaking his main screen
// a second time.
//
// The pure decisions still live in voiceQuestion.js. This holds only the parts that need React
// state and the native recorder.

const React = require('react');
const { useCallback, useEffect, useRef, useState } = React;

const {
  recordingIndicator,
  resolveTranscription,
  voiceErrorMessage,
  voiceStatusText,
  MAX_RECORDING_SECONDS,
} = require('./voiceQuestion');
const { initialPauseState, nextPauseState, listeningLabel } = require('./speechPause');

// How often the recorder reports its sound level. Fast enough that a two-second pause is
// noticed promptly, slow enough not to wake the JavaScript thread five times a second.
const PAUSE_POLL_MS = 250;

// Loaded on demand, never at module load. An installed app whose binary predates expo-av has no
// such native code, and Expo's lookup throws out through the module registry rather than as an
// ordinary exception a caller can catch -- so the only safe approach is never to reach the
// require unless the native side is actually registered. requireOptionalNativeModule answers
// exactly that question and returns null instead of throwing.
function loadAudioModules() {
  try {
    const { requireOptionalNativeModule } = require('expo-modules-core');
    if (!requireOptionalNativeModule || !requireOptionalNativeModule('ExponentAV')) {
      return null;
    }
    return { Audio: require('expo-av').Audio, FileSystem: require('expo-file-system') };
  } catch (error) {
    return null;
  }
}

/**
 * The microphone, as a hook.
 *
 * @param request       the app's authenticated fetch
 * @param onTranscript  called with what was heard; speaking IS submitting
 * @param onProblem     called with a plain sentence when voice cannot be used
 * @param onStatus      called with the line to display, including the ticking counter
 */
function useVoiceCapture({ request, onTranscript, onProblem, onStatus }) {
  const [voiceState, setVoiceState] = useState('idle');
  const [recordingSeconds, setRecordingSeconds] = useState(0);
  const recordingRef = useRef(null);
  const audioRef = useRef(null);
  const tickRef = useRef(null);
  const mountedRef = useRef(true);
  // Stamps each recording so a transcription the Founder cancelled cannot deliver its words
  // afterwards. 2026-09-07: "there should be an x button if I want to cancel the transcription
  // or my voice in case I get it wrong" -- cancelling has to mean it never arrives, not that
  // it arrives slightly later.
  const ticketRef = useRef(0);
  const pauseRef = useRef(initialPauseState());
  // The status callback is created before stop() exists and outlives every render, so it calls
  // through a ref rather than closing over a particular version of it.
  const stopRef = useRef(() => {});

  const say = useCallback((line) => { if (onStatus) onStatus(line); }, [onStatus]);
  const problem = useCallback((line) => { if (onProblem) onProblem(line); }, [onProblem]);

  // Leaving the screen must stop the recorder. A microphone still running on a screen nobody is
  // looking at would be the worst failure this file could have.
  useEffect(() => () => {
    mountedRef.current = false;
    if (tickRef.current) clearInterval(tickRef.current);
    const recording = recordingRef.current;
    recordingRef.current = null;
    if (recording) {
      try { recording.stopAndUnloadAsync(); } catch (error) { /* already gone */ }
    }
  }, []);

  const clearTick = useCallback(() => {
    if (tickRef.current) {
      clearInterval(tickRef.current);
      tickRef.current = null;
    }
    setRecordingSeconds(0);
  }, []);

  const stop = useCallback(async () => {
    clearTick();
    const recording = recordingRef.current;
    recordingRef.current = null;
    if (!recording) {
      setVoiceState('idle');
      return;
    }
    // This transcription belongs to this recording. If he cancels while it is in flight the
    // stamp moves on, and the words that eventually come back are discarded instead of being
    // dropped into the conversation he just cancelled out of.
    const ticket = (ticketRef.current += 1);
    const abandoned = () => !mountedRef.current || ticketRef.current !== ticket;

    setVoiceState('transcribing');
    // 2026-09-07, Founder-reported: "the transcribing... went on for quite a while, so much so
    // that we just stopped it." A static "Transcribing..." cannot be told apart from a hang, so
    // it counts. Upload plus speech-to-text on a long recording genuinely takes a while; the
    // counter is the difference between waiting and giving up.
    say(voiceStatusText('transcribing'));
    const transcribeStart = Date.now();
    tickRef.current = setInterval(() => {
      const seconds = Math.round((Date.now() - transcribeStart) / 1000);
      say(`${voiceStatusText('transcribing')}  ${seconds}s`);
    }, 1000);
    try {
      await recording.stopAndUnloadAsync();
      const uri = recording.getURI();
      const { FileSystem } = audioRef.current || {};
      const audio = await FileSystem.readAsStringAsync(uri, {
        encoding: FileSystem.EncodingType.Base64,
      });
      const payload = await request('/transcribe-question', {
        method: 'POST',
        body: JSON.stringify({ audio_base64: audio, filename: 'question.m4a' }),
        timeoutMs: 60000,
      });
      const result = resolveTranscription(payload);
      if (abandoned()) return;
      if (result.ok) {
        setVoiceState('idle');
        // Handed straight on. He asked to "press it and just ask the app something verbally and
        // submit it", so speaking is the submission -- and the words appear the moment they
        // exist, before any thinking starts, because staring at a screen with no evidence of
        // having been heard is the complaint this file answers.
        if (onTranscript) onTranscript(result.text);
        return;
      }
      problem(result.message);
      say('Could not make that out.');
    } catch (error) {
      if (abandoned()) return;
      problem(voiceErrorMessage('failed'));
      say('Voice failed.');
    } finally {
      clearTick();
      if (mountedRef.current && ticketRef.current === ticket) setVoiceState('idle');
    }
  }, [clearTick, onTranscript, problem, request, say]);

  useEffect(() => { stopRef.current = stop; }, [stop]);

  const start = useCallback(async () => {
    let native = null;
    try {
      native = loadAudioModules();
    } catch (error) {
      native = null;
    }
    if (!native) {
      problem(voiceErrorMessage('unsupported'));
      say('Voice needs a newer app version.');
      setVoiceState('idle');
      return;
    }
    audioRef.current = native;
    const { Audio } = native;
    setVoiceState('requesting');
    say(voiceStatusText('requesting'));
    try {
      const permission = await Audio.requestPermissionsAsync();
      if (!permission.granted) {
        problem(voiceErrorMessage('permission_denied'));
        say('Microphone not available.');
        setVoiceState('idle');
        return;
      }
      await Audio.setAudioModeAsync({ allowsRecordingIOS: true, playsInSilentModeIOS: true });

      // 2026-09-07, Founder-directed: "I don't want to click on a send button each time. I want
      // the app to detect a long pause and then just respond." Metering is what makes that
      // possible -- it reports the sound level as he speaks, and speechPause.js decides from
      // that when a pause is a full stop rather than a breath.
      //
      // If the hardware ignores isMeteringEnabled the readings come back empty, the detector
      // never fires, and the Stop button behaves exactly as it does today. An addition, never a
      // replacement.
      pauseRef.current = initialPauseState();
      let lastReadingAt = Date.now();
      const created = await Audio.Recording.createAsync(
        { ...Audio.RecordingOptionsPresets.HIGH_QUALITY, isMeteringEnabled: true },
        (status) => {
          if (!status || !status.isRecording || !mountedRef.current) return;
          const now = Date.now();
          const sinceLastMs = now - lastReadingAt;
          lastReadingAt = now;
          pauseRef.current = nextPauseState(pauseRef.current, {
            metering: status.metering, sinceLastMs,
          });
          say(listeningLabel(pauseRef.current, (status.durationMillis || 0) / 1000));
          if (pauseRef.current.shouldSubmit) {
            // He has finished. Sending is the whole point -- reaching for the screen at the end
            // of every sentence is the friction he asked to be rid of.
            stopRef.current();
          }
        },
        PAUSE_POLL_MS,
      );
      const recording = created.recording;
      if (!mountedRef.current) {
        try { await recording.stopAndUnloadAsync(); } catch (error) { /* left already */ }
        return;
      }
      recordingRef.current = recording;
      setVoiceState('recording');
      // The ticking count IS the proof that it is listening, and its absence is exactly what
      // was reported. See recordingIndicator.
      setRecordingSeconds(0);
      say(recordingIndicator(0));
      tickRef.current = setInterval(() => {
        setRecordingSeconds((seconds) => {
          const next = seconds + 1;
          say(recordingIndicator(next));
          return next;
        });
      }, 1000);
      // A phone left recording in a pocket must not upload something huge, so this stops itself
      // rather than relying on anyone remembering to press stop.
      setTimeout(() => {
        if (recordingRef.current === recording) stop();
      }, MAX_RECORDING_SECONDS * 1000);
    } catch (error) {
      problem(voiceErrorMessage('failed'));
      say('Voice failed.');
      setVoiceState('idle');
    }
  }, [problem, say, stop]);

  // Throw away what was captured without sending it. Used when a tap means "stop talking to me"
  // rather than "submit this" -- sending would upload the silence recorded while he reached for
  // the phone.
  const cancel = useCallback(async () => {
    // Moving the stamp is what makes cancelling real: any transcription already in flight will
    // find itself abandoned when it returns, and say nothing.
    ticketRef.current += 1;
    clearTick();
    pauseRef.current = initialPauseState();
    const recording = recordingRef.current;
    recordingRef.current = null;
    setVoiceState('idle');
    say('Cancelled.');
    if (!recording) return;
    try {
      await recording.stopAndUnloadAsync();
    } catch (error) {
      // Already stopped. Nothing is sent either way.
    }
  }, [clearTick]);

  return {
    voiceState,
    recordingSeconds,
    isRecording: voiceState === 'recording',
    isBusy: voiceState === 'transcribing' || voiceState === 'requesting',
    start,
    stop,
    cancel,
    audioRef,
  };
}

module.exports = { useVoiceCapture, loadAudioModules };
