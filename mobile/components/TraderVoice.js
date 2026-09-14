'use strict';
const React = require('react');
const { useEffect, useRef, useState } = React;
const { View, Text, TouchableOpacity, AppState, Platform, NativeModules, Linking } = require('react-native');
const { styles } = require('../styles');

function TraderVoice({ request, disabled, onActive, refreshKey }) {
  const active = useRef(null);
  const generation = useRef(0);
  const mounted = useRef(true);
  const [status, setStatus] = useState('Ready for a short conversation');
  const [live, setLive] = useState(false);
  const [muted, setMuted] = useState(false);
  const [transcript, setTranscript] = useState([]);
  const [usage, setUsage] = useState(null);
  const [modelUsage, setModelUsage] = useState(null);
  async function refreshUsage() {
    try {
      const result = await request('/model-usage');
      if (mounted.current) setModelUsage(result);
    } catch (_) { if (mounted.current) setModelUsage(null); }
    try {
      const result = await request('/trader-voice/budget');
      if (mounted.current) setUsage(result);
    } catch (_) { if (mounted.current) setUsage(null); }
  }
  useEffect(() => { refreshUsage(); }, [refreshKey, live]);
  useEffect(() => {
    if (!live) return undefined;
    const timer = setInterval(refreshUsage, 15000);
    return () => clearInterval(timer);
  }, [live]);
  function show(value) { if (mounted.current) setStatus(value); }
  async function stop(reason = 'Conversation ended') {
    generation.current += 1;
    const s = active.current;
    active.current = null;
    if (s) {
      clearTimeout(s.timer);
      if (s.stream) s.stream.getTracks().forEach(t => t.stop());
      if (s.channel) s.channel.close();
      if (s.peer) s.peer.close();
      if (s.audio) { s.audio.srcObject = null; s.audio.remove(); }
      if (s.id) {
        try { await request('/trader-voice/end', { method:'POST', body:JSON.stringify({ session_id:s.id }) }); }
        catch (_) { reason += ' · Server time limit remains in place.'; }
      }
    }
    if (mounted.current) { setLive(false); setMuted(false); show(reason); onActive(false); }
  }
  useEffect(() => {
    mounted.current = true;
    const sub = AppState.addEventListener('change', state => { if (state !== 'active') stop('Voice stopped while app is in background'); });
    return () => { mounted.current = false; stop(); onActive(false); sub.remove(); };
  }, []);
  async function start() {
    if (active.current || disabled) return;
    const ticket = ++generation.current;
    const s = {};
    active.current = s;
    setLive(true); onActive(true); show('Connecting securely…');
    try {
      let rtc;
      if (Platform.OS === 'web') {
        rtc = { RTCPeerConnection:globalThis.RTCPeerConnection, mediaDevices:navigator.mediaDevices };
      } else {
        if (!NativeModules.WebRTCModule) throw new Error('Install the new Android build to use live voice. Recorded messages and text still work.');
        rtc = require('react-native-webrtc');
      }
      s.peer = new rtc.RTCPeerConnection({ iceServers:[] });
      s.peer.ontrack = event => {
        if (Platform.OS === 'web') {
          s.audio = document.createElement('audio'); s.audio.autoplay = true;
          s.audio.srcObject = event.streams[0]; document.body.appendChild(s.audio);
          s.audio.play().catch(() => show('Tap the audio control if playback was blocked'));
        }
      };
      s.peer.onconnectionstatechange = () => {
        if (['failed','disconnected','closed'].includes(s.peer.connectionState) && active.current === s) stop('Voice connection ended');
      };
      s.stream = await rtc.mediaDevices.getUserMedia({ audio:true, video:false });
      if (ticket !== generation.current) { s.stream.getTracks().forEach(t => t.stop()); return; }
      s.stream.getTracks().forEach(track => s.peer.addTrack(track, s.stream));
      s.channel = s.peer.createDataChannel('oai-events');
      s.channel.onopen = () => show('Listening · you can interrupt Trader');
      s.channel.onmessage = event => {
        if (ticket !== generation.current) return;
        try {
          const data = JSON.parse(event.data);
          if (data.type === 'input_audio_buffer.speech_started') show('Listening');
          if (data.type === 'response.created') show('Trader is responding');
          if (data.type === 'response.done') show('Listening');
          if (['conversation.item.input_audio_transcription.completed','response.output_audio_transcript.done'].includes(data.type)) {
            setTranscript(prev => [...prev.slice(-19), { role:data.type.startsWith('conversation')?'You':'Trader', text:data.transcript || '' }]);
          }
        } catch (_) { /* Ignore non-JSON transport messages. */ }
      };
      const offer = await s.peer.createOffer();
      await s.peer.setLocalDescription(offer);
      const result = await request('/trader-voice/start', { method:'POST', timeoutMs:60000,
        body:JSON.stringify({ mode:'trader', confirmed:true, sdp:offer.sdp }) });
      s.id = result.session_id;
      if (ticket !== generation.current) {
        await request('/trader-voice/end', { method:'POST', body:JSON.stringify({session_id:s.id}) }); return;
      }
      setUsage(result.budget);
      await s.peer.setRemoteDescription({ type:'answer', sdp:result.sdp });
      s.timer = setTimeout(() => stop('Five-minute voice check-in ended; continue in text or start another.'), result.max_seconds*1000);
    } catch (error) { if (ticket === generation.current) await stop(error.message || 'Could not connect. Text remains available.'); }
  }
  function toggleMute() {
    const value = !muted;
    active.current?.stream?.getAudioTracks().forEach(t => { t.enabled = !value; });
    setMuted(value); show(value ? 'Microphone muted' : 'Listening');
  }
  return <View style={{ padding:12, marginVertical:10, borderWidth:1, borderColor:'#BCD4CB', borderRadius:12 }}>
    <Text style={styles.smallText}>Live conversation with Trader · AI-generated voice</Text>
    <Text accessibilityLiveRegion="polite" style={styles.smallText}>{status}</Text>
    <Text style={styles.smallText}>Ask: What do you need? Why these results? What will you test next?</Text>
    <Text style={styles.smallText}>Voice allowance: $10/month. {usage ? '$'+usage.spent_usd.toFixed(2)+' conservatively accounted.' : 'Checked before connecting.'} Text chat has its own model costs.</Text>
    <Text style={styles.smallText}>OpenAI prepaid balance: not available in this app. The voice allowance is not your credit balance.</Text>
    {modelUsage ? <Text style={styles.smallText}>Tracked today (UTC): {modelUsage.calls} model calls · {modelUsage.input_tokens} input / {modelUsage.output_tokens} output tokens. {modelUsage.scope} {modelUsage.unknown_usage ? modelUsage.unknown_usage+' calls have missing usage.' : ''}</Text> : <Text style={styles.smallText}>Model usage unavailable — not assumed to be zero.</Text>}
    <TouchableOpacity accessibilityRole="link" onPress={() => Linking.openURL('https://platform.openai.com/settings/organization/billing/overview').catch(() => show('Open the OpenAI billing dashboard in your browser.'))}><Text style={styles.smallText}>View actual credit balance in OpenAI billing ↗</Text></TouchableOpacity>
    <TouchableOpacity accessibilityRole="button" onPress={refreshUsage}><Text style={styles.smallText}>Refresh usage</Text></TouchableOpacity>
    <TouchableOpacity accessibilityRole="button" disabled={disabled && !live} style={styles.standupStart} onPress={live ? () => stop() : start}>
      <Text style={styles.standupStartText}>{live ? 'End voice conversation' : 'Start voice conversation'}</Text>
    </TouchableOpacity>
    {live && <TouchableOpacity accessibilityRole="button" style={styles.standupMode} onPress={toggleMute}><Text>{muted?'Unmute microphone':'Mute microphone'}</Text></TouchableOpacity>}
    {transcript.map((t,i) => <Text key={i} style={styles.smallText}>{t.role}: {t.text}</Text>)}
  </View>;
}
module.exports = { TraderVoice };
