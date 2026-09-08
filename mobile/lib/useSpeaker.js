'use strict';

// Reading replies out loud, and handing the floor back when the last one finishes.
//
// 2026-09-08, Founder-reported:
//
//   "by the way the app does not speak and the conversation tends to just stop after your
//    message above. so it doesn't feel like a free flowing conversation."
//
// He was right, and it was an omission rather than a fault. Ask has spoken answers and reopens
// the microphone once the voice stops; Standup got a microphone on 2026-09-07 and none of the
// half that answers back. That is two days running that a screen shipped with a missing half
// nobody announced.
//
// Pulled out as a hook rather than copied so the next conversational screen inherits both
// halves at once. Ask is deliberately left alone for now: it works, and rewriting a working
// voice path to share code with a new one is how you break the working path.
//
// A QUEUE, not a single utterance, because a standup produces more than one reply to a
// question -- the Trader answers and then Claude does. Joining them into one block would hit
// the 700-character spoken cap and silently swallow the second speaker; queueing reads them in
// turn and only hands the floor back when the room has finished.
//
// EVERYTHING HERE IS BEST-EFFORT. The replies are already on screen in writing, so a failure to
// speak must end in silence, never in an error message sitting on top of a good answer.

const React = require('react');
const { useCallback, useEffect, useRef } = React;

const { speechRequestOptions, playableAudioUri, spokenText } = require('./spokenReply');

// Loaded on demand, never at module load. An installed app whose binary predates expo-av has no
// such native code, and Expo's lookup throws out through the module registry rather than as an
// ordinary exception a caller can catch -- so the only safe approach is never to reach the
// require unless the native side is actually registered.
function loadAudio() {
  try {
    const { requireOptionalNativeModule } = require('expo-modules-core');
    if (!requireOptionalNativeModule || !requireOptionalNativeModule('ExponentAV')) {
      return null;
    }
    return require('expo-av').Audio;
  } catch (error) {
    return null;
  }
}

/** Whether this binary can play audio at all. Callers use it to decide what to promise. */
function canSpeak() {
  return loadAudio() !== null;
}

/**
 * The voice, as a hook.
 *
 * @param request     the app's authenticated fetch
 * @param onFinished  called once the queue has drained and nothing was interrupted. This is
 *                    where the microphone reopens: the conversation only flows if the floor
 *                    comes back to him without him reaching for the phone.
 */
function useSpeaker({ request, onFinished }) {
  const soundRef = useRef(null);
  const queueRef = useRef([]);
  const playingRef = useRef(false);
  const mountedRef = useRef(true);
  // Stamps the current run of speech. Interrupting has to mean the finished-callback from what
  // he cut off cannot fire later and open the microphone underneath him.
  const ticketRef = useRef(0);
  const finishedRef = useRef(onFinished);
  useEffect(() => { finishedRef.current = onFinished; }, [onFinished]);
  // playNext calls itself once a clip ends, so it is reached through a ref rather than closing
  // over a particular version of itself.
  const nextRef = useRef(() => {});

  const unload = useCallback(() => {
    const sound = soundRef.current;
    soundRef.current = null;
    if (sound) { try { sound.unloadAsync(); } catch (error) { /* gone already */ } }
  }, []);

  const stop = useCallback(() => {
    ticketRef.current += 1;
    queueRef.current = [];
    playingRef.current = false;
    unload();
  }, [unload]);

  // Leaving the screen must stop the voice. A reply still being read aloud on a screen he has
  // left is the same class of failure as a microphone left running on a closed conversation.
  useEffect(() => () => {
    mountedRef.current = false;
    ticketRef.current += 1;
    queueRef.current = [];
    const sound = soundRef.current;
    soundRef.current = null;
    if (sound) { try { sound.unloadAsync(); } catch (error) { /* gone already */ } }
  }, []);

  const playNext = useCallback(async () => {
    if (playingRef.current) return;
    const said = queueRef.current.shift();
    if (said === undefined) {
      // The room has finished. His turn.
      if (mountedRef.current && finishedRef.current) finishedRef.current();
      return;
    }
    playingRef.current = true;
    const ticket = ticketRef.current;
    const abandoned = () => !mountedRef.current || ticketRef.current !== ticket;
    // Whatever happens to this clip -- played, failed, or nothing to play -- the queue must
    // keep moving. A swallowed failure that stops the queue would leave the floor with nobody.
    const carryOn = () => {
      playingRef.current = false;
      if (!abandoned()) nextRef.current();
    };

    try {
      const Audio = loadAudio();
      if (!Audio) { carryOn(); return; }
      const payload = await request('/speak', speechRequestOptions(said));
      const uri = playableAudioUri(payload);
      if (abandoned()) { playingRef.current = false; return; }
      if (!uri) { carryOn(); return; }
      // Through the speaker rather than the earpiece, and still working when the phone is on
      // silent -- he asked out loud and expects to hear the answer.
      await Audio.setAudioModeAsync({ allowsRecordingIOS: false, playsInSilentModeIOS: true });
      if (abandoned()) { playingRef.current = false; return; }
      const created = await Audio.Sound.createAsync({ uri }, { shouldPlay: true });
      if (abandoned()) {
        try { await created.sound.unloadAsync(); } catch (error) { /* gone already */ }
        playingRef.current = false;
        return;
      }
      soundRef.current = created.sound;
      created.sound.setOnPlaybackStatusUpdate((status) => {
        if (!status || !status.didJustFinish) return;
        if (abandoned()) return;
        unload();
        carryOn();
      });
    } catch (error) {
      carryOn();
    }
  }, [request, unload]);
  useEffect(() => { nextRef.current = playNext; }, [playNext]);

  /** Add a reply to the queue. Starts playing if nothing is. */
  const speak = useCallback((text) => {
    const said = spokenText(text);
    if (!said) return;
    queueRef.current.push(said);
    playNext();
  }, [playNext]);

  return { speak, stop, canSpeak };
}

module.exports = { useSpeaker, canSpeak, loadAudio };
