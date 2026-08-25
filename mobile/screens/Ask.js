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

const { micButtonLabel, recordingIndicator, resolveTranscription, voiceErrorMessage, voiceStatusText, MAX_RECORDING_SECONDS } = require('../lib/voiceQuestion');


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
        // Sent straight through: the Founder asked to "press it and just ask the app
        // something verbally and submit it", so speaking IS the submission.
        await ask(result.text);
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

  const toggleVoice = () => (voiceState === 'recording' ? stopRecording() : startRecording());
  const ask = async (text) => {
    const finalQuestion = String(text || question || '').trim();
    if (!finalQuestion || askLoading) {
      return;
    }
    setQuestion('');
    setMessages((prev) => [...prev, { role: 'user', text: normalizeChatText(finalQuestion) }]);
    setAskLoading(true);
    setAskStatus('Thinking...');
    // The timeout has to travel as `timeoutMs` in the request options -- api/client.js
    // applies its own AbortController and overrides any signal passed in, so a local
    // controller here would be silently ignored (it was, until 2026-08-24). See
    // lib/askRequest.js for the full reasoning and the tests that pin it.
    const options = askRequestOptions(finalQuestion);
    try {
      const result = await withTimeout(
        request('/ask-ai-trader', options),
        options.timeoutMs + 2000
      );
      const answerText = normalizeChatText(result.answer);
      const note = result.note ? `\n\n${normalizeChatText(result.note)}` : '';
      setMessages((prev) => [...prev, { role: 'assistant', text: normalizeChatText(`${answerText}${note}`) }]);
      setAskStatus(`Answered using ${result.model || 'local evidence'}.`);
    } catch (error) {
      // AT-ED-013 Section 12: never surface a raw exception/stack-trace string to the
      // Founder - only the timeout case gets a specific explanation (it has a genuine,
      // actionable business meaning: the backend is slow to wake up); anything else is
      // reported honestly but in plain English, with no exception text attached.
      setMessages((prev) => [...prev, { role: 'assistant', text: normalizeChatText(askErrorMessage(error)) }]);
      setAskStatus('Ask failed or timed out.');
    } finally {
      setAskLoading(false);
    }
  };
  const suggestions = [
    'Am I up or down today, and why?',
    'What open positions do I have?',
    'Which recent trades made or lost money?',
    'What has AI Trader learned today?',
    'Is AI Trader getting better at trading?',
  ];
  return (
    <View>
      <Section title="Ask AI Trader">
        <Text style={styles.bodyText}>
          Ask for a plain-English explanation of AI Trader data. This chat is read-only and cannot place trades, approve trades, enable auto trading, or change guardrails.
        </Text>
        <Metric label="Ask Status" value={askStatus} />
        <View style={styles.buttonGrid}>
          {suggestions.map((item) => (
            <Button key={item} label={item} tone="neutral" onPress={() => ask(item)} disabled={askLoading} />
          ))}
        </View>
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
            label={micButtonLabel(voiceState)}
            tone={voiceState === 'recording' ? 'warn' : 'neutral'}
            onPress={toggleVoice}
            disabled={askLoading || voiceState === 'transcribing' || voiceState === 'requesting'}
          />
        </View>
      </Section>
      <Section title="Conversation">
        {messages.length ? (
          chatTurnsNewestFirst(messages).map((turn, turnIndex) => (
            <View key={`turn-${turnIndex}`} style={styles.chatTurn}>
              {turn.map((item, messageIndex) => (
                <View key={`${item.role}-${turnIndex}-${messageIndex}`} style={[styles.chatBubble, item.role === 'user' ? styles.chatUser : styles.chatAssistant]}>
                  <Text style={styles.metricLabel}>{item.role === 'user' ? 'You' : 'AI Trader'}</Text>
                  <Text style={styles.bodyText} selectable>{chatMessageText(item.text)}</Text>
                </View>
              ))}
            </View>
          ))
        ) : (
          <Text style={styles.bodyText}>Ask me about balances, open positions, trades, reports, recommendations, or what AI Trader learned.</Text>
        )}
      </Section>
    </View>
  );
}

module.exports = { AskAiTrader };
