// Ask AI Trader: the founder's own screen as of the 2026-08-24 simplification.
//
// It used to sit at the bottom of Learning, below a wall of strategy-lab evidence the
// Founder had to scroll past to reach it. Learning's own numbers duplicated the Trade
// Scorecard on the Executive Briefing, so the screen was cut and the one genuinely unique
// line (the latest lesson) moved onto the Scorecard. What remains here is the part that was
// actually used: asking a plain-English question and getting a plain-English answer.

'use strict';

const React = require('react');
const { useState } = React;
const { Text, TextInput, View } = require('react-native');
const { styles } = require('../styles');
const { Section, Metric, Button } = require('../components/shared');
const { withTimeout, normalizeChatText, chatMessageText, chatTurnsNewestFirst } = require('../lib/chat');
const { askRequestOptions, askErrorMessage } = require('../lib/askRequest');
// 2026-08-25: expo-av and expo-file-system are NATIVE modules, and this app's
// runtimeVersion policy is "appVersion" -- so the build WITHOUT them and the build WITH
// them share runtime 1.0.3, and one over-the-air update is delivered to both. Requiring
// them at module load would therefore run this import inside an installed app whose binary
// has no such native code, and this component is now mounted on the Executive Briefing, so
// a throw here would take down the Founder's main screen rather than just the microphone.
//
// Loaded on demand instead, inside the press handler. An older app simply reports that voice
// needs the newer version; everything else on the screen, including typing a question, is
// untouched. A convenience must never be able to break the screen it sits on.
function loadAudioModules() {
  // 2026-08-25, second attempt. The first wrapped require('expo-av') in try/catch, which was
  // NOT enough -- verified by pressing the button on a real emulator running the older build:
  //
  //   com.facebook.react.common.JavascriptException:
  //     Error: Cannot find native module 'ExponentAV'
  //       requireNativeModule ... loadAudioModules ... startRecording ... toggleVoice
  //
  // The app went to the home screen. Expo's native-module lookup throws out through the
  // module registry rather than as an ordinary exception the caller can catch, so the only
  // safe approach is never to reach the require unless the native side is actually
  // registered. requireOptionalNativeModule answers exactly that question and returns null
  // instead of throwing.
  //
  // This matters more than a missing microphone: Ask is mounted on the Executive Briefing, so
  // this crash took out the Founder's main screen. A convenience must never be able to break
  // the screen it sits on -- and I should have proven that on a device before saying it was
  // safe, rather than reasoning that it must be.
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

const { micButtonLabel, micButtonAccessibilityLabel, thinkingFrame, recordingIndicator, resolveTranscription, voiceErrorMessage, voiceStatusText, MAX_RECORDING_SECONDS } = require('../lib/voiceQuestion');
const { acknowledgement, shouldSpeak, speechRequestOptions, playableAudioUri } = require('../lib/spokenReply');
const { mergeTurns, bubbleStyle, bubbleTextStyle } = require('../lib/chatBubbles');
const { askStatusLine, isModelAnswer } = require('../lib/askStatus');


function AskAiTrader({ messages, setMessages, request }) {
  const [question, setQuestion] = useState('');
  const [askLoading, setAskLoading] = useState(false);
  const [askStatus, setAskStatus] = useState('Ready');
  // 2026-08-25, Founder-directed microphone. The decisions about what each state means and what
  // to say when it fails live in lib/voiceQuestion.js, where they are tested; this holds only
  // the recorder itself, which cannot be.
  const [voiceState, setVoiceState] = useState('idle');
  const recordingRef = React.useRef(null);
  const audioRef = React.useRef(null);
  const [recordingSeconds, setRecordingSeconds] = useState(0);
  const tickRef = React.useRef(null);
  // 2026-09-03, Founder-directed: "can all the discussions be stored... that way I can scroll
  // back to previous discussions if I want to." Loaded once when the card mounts and merged
  // with anything said since -- see lib/chatBubbles.mergeTurns for why both are needed.
  const [storedTurns, setStoredTurns] = useState([]);
  // Drives the animated dots on the button while the app is working. A counter rather than an
  // animation library: thinkingFrame turns it into a glyph, and that stays testable.
  const [thinkTick, setThinkTick] = useState(0);
  const thinkRef = React.useRef(null);

  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const payload = await request('/ask-history');
        if (!cancelled && payload && Array.isArray(payload.turns)) setStoredTurns(payload.turns);
      } catch (error) {
        // History is a convenience. Failing to load it must never stop a question being asked,
        // so this stays silent rather than showing an error for something nobody requested.
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // The button animates whenever the app is busy, whichever way the question arrived.
  React.useEffect(() => {
    const busy = askLoading || voiceState === 'transcribing';
    if (busy && !thinkRef.current) {
      thinkRef.current = setInterval(() => setThinkTick((n) => n + 1), 400);
    } else if (!busy && thinkRef.current) {
      clearInterval(thinkRef.current);
      thinkRef.current = null;
      setThinkTick(0);
    }
    return () => {
      if (thinkRef.current && !(askLoading || voiceState === 'transcribing')) {
        clearInterval(thinkRef.current);
        thinkRef.current = null;
      }
    };
  }, [askLoading, voiceState]);

  const stopRecording = async () => {
    if (tickRef.current) {
      clearInterval(tickRef.current);
      tickRef.current = null;
    }
    setRecordingSeconds(0);
    const recording = recordingRef.current;
    recordingRef.current = null;
    if (!recording) {
      setVoiceState('idle');
      return;
    }
    setVoiceState('transcribing');
    setAskStatus(voiceStatusText('transcribing'));
    try {
      await recording.stopAndUnloadAsync();
      const uri = recording.getURI();
      const { FileSystem } = audioRef.current || {};
      const audio = await FileSystem.readAsStringAsync(uri, { encoding: FileSystem.EncodingType.Base64 });
      const payload = await request('/transcribe-question', {
        method: 'POST',
        body: JSON.stringify({ audio_base64: audio, filename: 'question.m4a' }),
        timeoutMs: 60000,
      });
      const result = resolveTranscription(payload);
      if (result.ok) {
        setVoiceState('idle');
        setAskStatus('Ready');
        // 2026-08-31, Founder-reported: "when I speak to it and it's transcribing or
        // figuring out what I'm saying, it should be writing it down. So at least I can see
        // what it thinks I'm saying." The words went up only once the ANSWER arrived, so a
        // slow answer meant staring at a screen with no evidence he had been heard at all.
        // Shown here, the moment the transcript exists and before any thinking starts.
        setMessages((prev) => [...prev, { role: 'user', text: normalizeChatText(result.text) }]);
        // Sent straight through: the Founder asked to "press it and just ask the app
        // something verbally and submit it", so speaking IS the submission.
        await ask(result.text, { spoken: true, alreadyShown: true });
        return;
      }
      setMessages((prev) => [...prev, { role: 'assistant', text: normalizeChatText(result.message) }]);
      setAskStatus('Voice question failed.');
    } catch (error) {
      setMessages((prev) => [...prev, { role: 'assistant', text: normalizeChatText(voiceErrorMessage('failed')) }]);
      setAskStatus('Voice question failed.');
    } finally {
      setVoiceState('idle');
    }
  };

  const startRecording = async () => {
    let native = null;
    try {
      native = loadAudioModules();
    } catch (error) {
      native = null;
    }
    if (!native) {
      setMessages((prev) => [...prev, { role: 'assistant', text: normalizeChatText(voiceErrorMessage('unsupported')) }]);
      setAskStatus('Voice not available in this app version.');
      setVoiceState('idle');
      return;
    }
    const { Audio } = native;
    audioRef.current = native;
    setVoiceState('requesting');
    setAskStatus(voiceStatusText('requesting'));
    try {
      const permission = await Audio.requestPermissionsAsync();
      if (!permission.granted) {
        setMessages((prev) => [...prev, { role: 'assistant', text: normalizeChatText(voiceErrorMessage('permission_denied')) }]);
        setAskStatus('Microphone not available.');
        setVoiceState('idle');
        return;
      }
      await Audio.setAudioModeAsync({ allowsRecordingIOS: true, playsInSilentModeIOS: true });
      const { recording } = await Audio.Recording.createAsync(Audio.RecordingOptionsPresets.HIGH_QUALITY);
      recordingRef.current = recording;
      setVoiceState('recording');
      // The ticking count IS the feedback -- see recordingIndicator. Cleared in
      // stopRecording so it can never keep counting after the recorder has gone.
      setRecordingSeconds(0);
      setAskStatus(recordingIndicator(0));
      tickRef.current = setInterval(() => {
        setRecordingSeconds((seconds) => {
          const next = seconds + 1;
          setAskStatus(recordingIndicator(next));
          return next;
        });
      }, 1000);
      // A phone left recording in a pocket must not upload something huge, so this stops
      // itself rather than relying on the Founder remembering to press stop.
      setTimeout(() => { if (recordingRef.current === recording) stopRecording(); }, MAX_RECORDING_SECONDS * 1000);
    } catch (error) {
      setMessages((prev) => [...prev, { role: 'assistant', text: normalizeChatText(voiceErrorMessage('failed')) }]);
      setAskStatus('Voice question failed.');
      setVoiceState('idle');
    }
  };

  // Interrupting the reply by pressing the mic is how a real conversation works.
  const toggleVoice = () => (voiceState === 'recording' ? stopRecording() : (stopSpeaking(), startRecording()));
  // Holds the currently playing spoken reply so a new answer can stop the previous one --
  // otherwise a quick second question talks over the first, which is the opposite of a
  // conversation.
  const spokenRef = React.useRef(null);

  const stopSpeaking = async () => {
    const sound = spokenRef.current;
    spokenRef.current = null;
    if (!sound) return;
    try {
      await sound.unloadAsync();
    } catch (error) {
      // Already finished or unloaded. Nothing to recover from.
    }
  };

  const speakAnswer = async (answerText) => {
    // Best-effort by design: the written answer is already on screen, so a failure here
    // must never surface as an error. Silence is an acceptable outcome; a red message on
    // top of a good answer is not.
    try {
      const payload = await request('/speak', speechRequestOptions(answerText));
      const uri = playableAudioUri(payload);
      if (!uri) return;
      const { Audio } = audioRef.current || {};
      if (!Audio) return;
      await stopSpeaking();
      // Play through the speaker rather than the earpiece, and keep working when the phone
      // is on silent -- the Founder asked a question out loud and expects to hear back.
      await Audio.setAudioModeAsync({ allowsRecordingIOS: false, playsInSilentModeIOS: true });
      const { sound } = await Audio.Sound.createAsync({ uri }, { shouldPlay: true });
      spokenRef.current = sound;
      sound.setOnPlaybackStatusUpdate((status) => {
        if (status && status.didJustFinish) stopSpeaking();
      });
    } catch (error) {
      // Deliberately silent -- see above.
    }
  };

  const ask = async (text, { spoken = false, alreadyShown = false } = {}) => {
    const finalQuestion = String(text || question || '').trim();
    if (!finalQuestion || askLoading) {
      return;
    }
    setQuestion('');
    if (!alreadyShown) {
      setMessages((prev) => [...prev, { role: 'user', text: normalizeChatText(finalQuestion) }]);
    }
    setAskLoading(true);
    setAskStatus('Thinking...');
    // Break the silence immediately. The answer reads real broker and market evidence and
    // cannot always be quick, so rather than pretend otherwise the app says it is working --
    // shown at once, and spoken too when the question was spoken.
    const ack = acknowledgement(finalQuestion, finalQuestion.length);
    if (ack) {
      setMessages((prev) => [...prev, { role: 'assistant', text: ack, pending: true }]);
      if (spoken) speakAnswer(ack);
    }
    // The timeout has to travel as `timeoutMs` in the request options -- api/client.js
    // applies its own AbortController and overrides any signal passed in, so a local
    // controller here would be silently ignored (it was, until 2026-08-24). See
    // lib/askRequest.js for the full reasoning and the tests that pin it.
    const options = askRequestOptions(finalQuestion, spoken);
    try {
      const result = await withTimeout(
        request('/ask-ai-trader', options),
        options.timeoutMs + 2000
      );
      const answerText = normalizeChatText(result.answer);
      const note = result.note ? `\n\n${normalizeChatText(result.note)}` : '';
      setMessages((prev) => [
        ...prev.filter((m) => !m.pending),
        { role: 'assistant', text: normalizeChatText(`${answerText}${note}`) },
      ]);
      // 2026-09-04: only claim a model answered when a model answered. See lib/askStatus.
      setAskStatus(askStatusLine(result));
      // Reading a canned table dump aloud is worse than saying nothing, so a fallback
      // answer is shown but not spoken.
      if (isModelAnswer(result) && shouldSpeak({ askedByVoice: spoken, ok: true, answer: answerText })) {
        speakAnswer(answerText);
      }
    } catch (error) {
      // AT-ED-013 Section 12: never surface a raw exception/stack-trace string to the
      // Founder - only the timeout case gets a specific explanation (it has a genuine,
      // actionable business meaning: the backend is slow to wake up); anything else is
      // reported honestly but in plain English, with no exception text attached.
      setMessages((prev) => [
        ...prev.filter((m) => !m.pending),
        { role: 'assistant', text: normalizeChatText(askErrorMessage(error)) },
      ]);
      setAskStatus('Ask failed or timed out.');
    } finally {
      setAskLoading(false);
    }
  };
  return (
    <View>
      <Section title="Ask AI Trader">
        <Text style={styles.bodyText}>
          Ask anything AI Trader knows - type it, or tap the microphone and speak. Spoken questions get spoken answers, and the conversation is kept so you can scroll back. I can run a cycle, re-check what we hold, or refresh prices if you ask. I cannot place or approve a trade, change a threshold, or turn trading on or off.
        </Text>
        <Metric label="Ask Status" value={askStatus} />
        {/* 2026-09-01, Founder-directed: "can we remove the 5 buttons that are questions. I
            don't really use them and it adds clutter." Five full-width buttons sat between
            the description and the input box, pushing the thing he actually uses off the
            first screen. */}
        <TextInput
          style={[styles.input, styles.multilineInput]}
          multiline
          placeholder="Ask AI Trader a question..."
          value={question}
          onChangeText={setQuestion}
        />
        <View style={styles.buttonGrid}>
          <Button label={askLoading ? 'Thinking...' : 'Ask'} onPress={() => ask()} disabled={askLoading || !question.trim()} />
          <Button
            icon
            label={askLoading || voiceState === 'transcribing' ? thinkingFrame(thinkTick) : micButtonLabel(voiceState)}
            accessibilityLabel={micButtonAccessibilityLabel(askLoading ? 'thinking' : voiceState)}
            tone={voiceState === 'recording' ? 'warn' : 'neutral'}
            onPress={toggleVoice}
            disabled={askLoading || voiceState === 'transcribing' || voiceState === 'requesting'}
          />
        </View>
        {/* 2026-09-01, Founder-directed: "can we just remove it and let the app provide its
            answers in the same ask AI trader card that the question is typed. it's just
            cleaner that way."
            
            The answers now sit directly under the input that produced them, inside one card,
            rather than in a second card further down the screen. Newest turn first, so the
            reply to the question just asked is the thing immediately below the buttons and
            needs no scrolling to find. */}
        {messages.length ? (
          <View style={styles.askConversation}>
            {/* 2026-09-03, Founder-directed: "my request once transcribed shouldn't have to
                have 'You' above it... it should just be on the right of the box and then when
                the AI replies the reply should be on the left."
                The label is gone because position and colour already say who spoke -- it was a
                caption explaining something the eye had understood. See lib/chatBubbles. */}
            {mergeTurns(storedTurns, messages).map((turn) => (
              <View key={turn.key} style={bubbleStyle(turn)}>
                <Text style={bubbleTextStyle(turn)} selectable>{chatMessageText(turn.text)}</Text>
              </View>
            ))}
          </View>
        ) : null}
      </Section>
    </View>
  );
}

module.exports = { AskAiTrader };
