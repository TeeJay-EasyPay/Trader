'use strict';

// The three-way standup: the Founder, the trading AI, and Claude.
//
// 2026-09-07, Founder-directed:
//   "a morning stand up call daily to talk about what chatgpt needs, and gaps or items that
//    need fixing. real time troubleshooting of issues through dialogue"
//   "the conversation should basically be free flowing.... there may be times I explore a topic
//    with Claude while chatgpt listens after which it also joins in if asked"
//   "there needs to be a separate button or way of triggering the conversation with both
//    chatgpt and Claude and then also ending it"
//   "maybe have a way of just chatting with chatgpt or Claude separately as well"
//
// Deliberately its OWN screen and its own endpoint rather than a mode bolted onto Ask. Ask
// carries the voice-action detector, and on 2026-09-06 a question phrased "Daily check-in. Do
// you have everything you need..." matched it and started a real trading cycle. A standup must
// never be able to place a trade by being phrased unluckily.

const React = require('react');
const { useCallback, useEffect, useMemo, useRef, useState } = React;
const { ActivityIndicator, ScrollView, Text, TextInput, TouchableOpacity, View } = require('react-native');

const { styles } = require('../styles');
const { Section, Button } = require('../components/shared');
const { withDayStamps, newestExchangesFirst } = require('../lib/chatBubbles');
const { normalizeChatText } = require('../lib/chat');

const MODES = [
  { key: 'both', label: 'Standup', hint: 'Both, talking to each other' },
  { key: 'trader', label: 'Trader', hint: 'Just the trading AI' },
  { key: 'claude', label: 'Claude', hint: 'Just Claude' },
];

// Who said it, in the Founder's own words for them. "Trader" rather than "ChatGPT" because the
// label names the ROLE in the room -- he calls it both, and the role is the part that stays
// true if the model behind it ever changes.
const SPEAKER_LABEL = { founder: 'You', trader: 'Trader', claude: 'Claude' };

function StandupScreen({ request }) {
  const [mode, setMode] = useState('both');
  const [running, setRunning] = useState(false);
  const [turns, setTurns] = useState([]);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [statusLine, setStatusLine] = useState('Not started');
  const mountedRef = useRef(true);
  useEffect(() => () => { mountedRef.current = false; }, []);

  const start = useCallback(() => {
    setRunning(true);
    setTurns([]);
    setStatusLine(mode === 'both' ? 'Standup open - both are listening' : 'Open');
  }, [mode]);

  // Ending is explicit and clears the floor. The transcript stays on the server, so ending a
  // conversation loses nothing except the screenful -- see /standup's conversation_id.
  const end = useCallback(() => {
    setRunning(false);
    setBusy(false);
    setStatusLine('Ended');
  }, []);

  const send = useCallback(async (text) => {
    const said = String(text || '').trim();
    if (!said || busy) return;
    setDraft('');
    setBusy(true);
    setStatusLine('Thinking...');
    // Shown immediately. A question that vanishes into a spinner reads as the app ignoring
    // him -- the same complaint that put the live transcript into Ask on 2026-08-31.
    setTurns((prev) => [...prev, { speaker: 'founder', text: said, createdAt: new Date().toISOString() }]);
    try {
      const payload = await request('/standup', {
        method: 'POST',
        body: JSON.stringify({ message: said, mode, conversation_id: 'standup' }),
        timeoutMs: 240000,
      });
      if (!mountedRef.current) return;
      const produced = (payload && payload.turns) || [];
      setTurns((prev) => [
        ...prev,
        ...produced.map((turn) => ({
          speaker: turn.speaker,
          text: normalizeChatText(turn.text),
          toolCalls: (turn.tool_calls || []).length,
          createdAt: new Date().toISOString(),
        })),
      ]);
      setStatusLine(
        produced.length
          ? `${produced.length} repl${produced.length === 1 ? 'y' : 'ies'} - your turn`
          : 'No reply came back'
      );
    } catch (error) {
      if (!mountedRef.current) return;
      setTurns((prev) => [...prev, {
        speaker: 'claude',
        text: 'That did not get through. The conversation is still open - try again.',
        createdAt: new Date().toISOString(),
      }]);
      setStatusLine('Failed');
    } finally {
      if (mountedRef.current) setBusy(false);
    }
  }, [busy, mode, request]);

  // Newest exchange first, matching Ask -- the Founder asked for that on 2026-09-04 so the
  // reply to what he just said needs no scrolling to find.
  const rendered = useMemo(
    () => withDayStamps(newestExchangesFirst(turns.map((turn) => ({ ...turn, role: turn.speaker === 'founder' ? 'founder' : 'assistant' })))),
    [turns]
  );

  return (
    <View>
      <Section title="Standup">
        <Text style={styles.bodyText}>
          You chair it. Name someone to direct a question - "Claude, why is that slow?" - or just
          speak and whoever was last talking continues.
        </Text>

        <View style={styles.standupModeRow}>
          {MODES.map((item) => (
            <TouchableOpacity
              key={item.key}
              style={[styles.standupMode, mode === item.key && styles.standupModeActive]}
              onPress={() => setMode(item.key)}
              disabled={running}
            >
              <Text style={[styles.standupModeText, mode === item.key && styles.standupModeTextActive]}>
                {item.label}
              </Text>
            </TouchableOpacity>
          ))}
        </View>
        <Text style={styles.smallText}>{(MODES.find((m) => m.key === mode) || {}).hint}</Text>

        {running ? (
          <TouchableOpacity style={styles.standupEnd} onPress={end}>
            <Text style={styles.standupEndText}>End conversation</Text>
          </TouchableOpacity>
        ) : (
          <TouchableOpacity style={styles.standupStart} onPress={start}>
            <Text style={styles.standupStartText}>Start conversation</Text>
          </TouchableOpacity>
        )}

        <Text style={styles.smallText}>{statusLine}</Text>

        {running ? (
          <View style={styles.standupComposer}>
            <TextInput
              style={styles.multilineInput}
              value={draft}
              onChangeText={setDraft}
              placeholder="Say something, or name who you are asking"
              multiline
              editable={!busy}
            />
            <TouchableOpacity
              style={[styles.standupSend, busy && styles.standupSendBusy]}
              onPress={() => send(draft)}
              disabled={busy || !draft.trim()}
            >
              {busy ? <ActivityIndicator color="#ffffff" /> : <Text style={styles.standupSendText}>Send</Text>}
            </TouchableOpacity>
          </View>
        ) : null}

        {turns.length ? (
          <ScrollView style={styles.standupTranscript} nestedScrollEnabled keyboardShouldPersistTaps="handled">
            {rendered.map((item, index) =>
              item.type === 'stamp' ? (
                <View key={item.key} style={styles.chatDayStampRow}>
                  <Text style={styles.chatDayStamp}>{item.label}</Text>
                </View>
              ) : (
                <View key={item.key || `x-${index}`} style={styles.chatExchange}>
                  {item.exchange.map((turn, position) => (
                    <View
                      key={`${turn.key || position}`}
                      style={turn.speaker === 'founder' ? styles.standupMine : styles.standupTheirs}
                    >
                      {/* The label is load-bearing in a three-way conversation: two AI replies in
                          the same colour, one after the other, are unreadable without knowing
                          who is speaking. */}
                      {turn.speaker !== 'founder' ? (
                        <Text style={styles.standupSpeaker}>
                          {SPEAKER_LABEL[turn.speaker] || 'AI'}
                          {turn.toolCalls ? `  ·  checked ${turn.toolCalls} thing${turn.toolCalls === 1 ? '' : 's'}` : ''}
                        </Text>
                      ) : null}
                      <Text style={turn.speaker === 'founder' ? styles.standupMineText : styles.standupTheirsText} selectable>
                        {turn.text}
                      </Text>
                    </View>
                  ))}
                </View>
              )
            )}
          </ScrollView>
        ) : null}
      </Section>
    </View>
  );
}

module.exports = { StandupScreen, MODES, SPEAKER_LABEL };
