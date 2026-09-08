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
const { ActivityIndicator, Text, TextInput, TouchableOpacity, View } = require('react-native');

const { styles } = require('../styles');
const { Section, Button } = require('../components/shared');
const { withDayStamps, newestExchangesFirst } = require('../lib/chatBubbles');
const { normalizeChatText } = require('../lib/chat');
const { formatPence } = require('../lib/cost');
const { useVoiceCapture } = require('../lib/useVoiceCapture');
const { useSpeaker, canSpeak } = require('../lib/useSpeaker');
const {
  progressLine, pollOutcome, POLL_MS, POLL_TIMEOUT_MS,
} = require('../lib/standupTurn');
const { micButtonLabel, micButtonAccessibilityLabel } = require('../lib/voiceQuestion');

const MODES = [
  { key: 'both', label: 'Standup', hint: 'Both, talking to each other' },
  { key: 'trader', label: 'Trader', hint: 'Just the trading AI' },
  { key: 'claude', label: 'Claude', hint: 'Just Claude' },
];

// Who said it, in the Founder's own words for them. "Trader" rather than "ChatGPT" because the
// label names the ROLE in the room -- he calls it both, and the role is the part that stays
// true if the model behind it ever changes.
const SPEAKER_LABEL = { founder: 'You', trader: 'Trader', claude: 'Claude' };

// Starting a turn is a small request: the server spawns the work and answers immediately with
// an id. Only the START has a timeout now -- the turn itself is watched by polling, so no
// amount of thinking can time out a conversation.
//
// 2026-09-08, Founder-reported: "after 2 messages or less you provide a message saying 'the
// rest of that exchange did not get through'". The app used to hold one request open for the
// whole turn and give up at two minutes; his own logs showed Claude's turns running 1m 31s,
// 1m 57s and 4m 06s, because it goes away and checks things before answering.
const START_TIMEOUT_MS = 20000;

// How many polls in a row may fail before the turn is called lost. A dropped poll on a phone is
// ordinary; five in a row is a network that has gone, and continuing to wait would be a lie.
const MAX_POLL_FAILURES = 5;

// A hard stop on how far one question can run, independent of the server's own budget. Belt
// and braces: if the server ever kept naming a next speaker, the app would still hand the
// floor back rather than looping.
const MAX_TURNS_PER_QUESTION = 5;

// 2026-09-07, Founder-reported: "there was the circular animation on the send button that just
// kept going, and I never got anything back." A spinner says something is happening; it does
// not say WHAT, or for how long, so a slow answer is indistinguishable from a hang.
//
// The wording moved to lib/standupTurn.progressLine on 2026-09-08, once the turn was watched
// rather than waited on. It can now say what is actually happening -- "Claude is reading the
// code - lookup 6 of 12" -- which is the difference between a bounded wait and a mystery.

// One colour each. 2026-09-07, Founder-directed: "each of us needs a different chat bubble
// colour so that it's easy to understand who is asking the questions and who is answering."
// The label stays as well as the colour -- colour alone fails a colour-blind reader, and a
// label alone was what made the wall of grey hard to read in the first place.
const BUBBLE = {
  founder: { row: 'standupMine', text: 'standupMineText', speaker: 'standupSpeaker' },
  trader: { row: 'standupTrader', text: 'standupTraderText', speaker: 'standupTraderSpeaker' },
  claude: { row: 'standupClaude', text: 'standupClaudeText', speaker: 'standupClaudeSpeaker' },
};

function bubbleFor(speaker) {
  // An unknown speaker falls back to the neutral "theirs" styling rather than crashing on a
  // missing style, which is what would happen if a new participant were ever added.
  return BUBBLE[speaker] || { row: 'standupTheirs', text: 'standupTheirsText', speaker: 'standupSpeaker' };
}

function StandupScreen({ request }) {
  const [mode, setMode] = useState('both');
  const [running, setRunning] = useState(false);
  const [turns, setTurns] = useState([]);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [statusLine, setStatusLine] = useState('Not started');
  const [spentTotal, setSpentTotal] = useState(0);
  const mountedRef = useRef(true);
  useEffect(() => () => { mountedRef.current = false; }, []);

  // What was already said, loaded on open. 2026-09-07: without this the card was empty until
  // you asked something new, which is the complaint the Founder made about Ask on 2026-08-31 --
  // "the ask trader card only shows the last conversations once a question is asked". The
  // transcript was being stored the whole time; nothing read it back.
  useEffect(() => {
    let cancelled = false;
    request('/standup/history?conversation_id=standup&limit=40')
      .then((payload) => {
        if (cancelled || !mountedRef.current) return;
        const stored = (payload && payload.turns) || [];
        setTurns(stored.map((turn) => ({
          speaker: turn.speaker,
          text: normalizeChatText(turn.text),
          createdAt: turn.created_at,
        })));
      })
      // A history that will not load is not worth an error message: the conversation still
      // works, and the turns from this session will appear as normal.
      .catch(() => {});
    return () => { cancelled = true; };
  }, [request]);

  // 2026-09-07, Founder-reported: he opened the standup, spoke, and nothing happened -- there
  // was no microphone on this screen at all. Speaking is how he uses this app; a conversation
  // screen he cannot talk to is not a conversation screen.
  //
  // sendRef exists because the hook is declared before `send`. Reading it through a ref keeps
  // the hook's identity stable, so a new callback on every render cannot restart the recorder
  // mid-sentence.
  const sendRef = useRef(null);
  // Stamps each question so replies to an abandoned one can be recognised and dropped.
  const exchangeRef = useRef(0);
  // True while a SPOKEN conversation is running, so the microphone reopens by itself once the
  // room has finished talking. 2026-09-08, Founder-reported: "the conversation tends to just
  // stop after your message above. so it doesn't feel like a free flowing conversation."
  // Cleared the moment anything makes carrying on wrong -- typing, ending, or a failed turn.
  const handsFreeRef = useRef(false);
  // What was left unsaid when a turn was lost, so the exchange can be picked up rather than
  // abandoned. Holds the request body for whoever was due to speak next.
  const [resumable, setResumable] = useState(null);

  const voice = useVoiceCapture({
    request,
    onTranscript: (text) => {
      handsFreeRef.current = true;
      if (sendRef.current) sendRef.current(text, { spoken: true });
    },
    onProblem: (message) => {
      // A voice failure ends the hands-free run. Reopening the microphone after something went
      // wrong would talk over him while he is still working out what happened.
      handsFreeRef.current = false;
      setTurns((prev) => [...prev, {
        speaker: 'claude', text: normalizeChatText(message), createdAt: new Date().toISOString(),
      }]);
    },
    onStatus: setStatusLine,
  });

  // The other half of speaking, missing since this screen was built. Ask reads its answers out
  // loud and reopens the microphone; Standup had a microphone and no voice coming back.
  const speaker = useSpeaker({
    request,
    onFinished: () => {
      // The room has finished talking, so it is his turn -- without reaching for the phone.
      if (!mountedRef.current || !handsFreeRef.current) return;
      voice.start();
    },
  });

  const start = useCallback(() => {
    setRunning(true);
    setSpentTotal(0);
    setStatusLine(mode === 'both' ? 'Standup open - both are listening' : 'Open');
  }, [mode]);

  // Ending is explicit and clears the floor. The transcript stays on the server, so ending a
  // conversation loses nothing except the screenful -- see /standup's conversation_id.
  const end = useCallback(() => {
    setRunning(false);
    // Abandon anything still in flight. Without this, replies to the question he gave up on
    // arrive later and read as the AIs talking unprompted -- exactly what he reported.
    exchangeRef.current += 1;
    handsFreeRef.current = false;
    setBusy(false);
    setResumable(null);
    // Ending must stop BOTH halves. A microphone left live on a closed conversation is the
    // failure this screen can least afford; a reply still being read aloud is the same fault
    // wearing the other hat.
    voice.cancel();
    speaker.stop();
    setStatusLine('Ended');
  }, [speaker, voice]);

  const send = useCallback(async (text, { spoken = false, resume = null } = {}) => {
    const said = String(text || '').trim();
    if (busy) return;
    if (!resume && !said) return;
    // Typing ends a spoken conversation. He has moved to the keyboard, so the microphone
    // opening after the next reply would be a surprise rather than a convenience.
    if (!resume && !spoken) handsFreeRef.current = false;
    setDraft('');
    setResumable(null);
    setBusy(true);
    // Every reply from here belongs to THIS question. 2026-09-07, Founder-reported: a slow
    // standup answer arrived after he had given up, switched to Trader and asked something
    // else -- so two AIs appeared to start "talking amongst themselves" unbidden. The stamp is
    // checked before anything is rendered, so a late reply from an abandoned question is
    // discarded rather than dropped into a conversation that has moved on.
    const ticket = (exchangeRef.current += 1);
    const stale = () => !mountedRef.current || exchangeRef.current !== ticket;
    const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

    // Shown immediately. A question that vanishes into a spinner reads as the app ignoring
    // him -- the same complaint that put the live transcript into Ask on 2026-08-31.
    if (!resume) {
      setTurns((prev) => [...prev, { speaker: 'founder', text: said, createdAt: new Date().toISOString() }]);
    }

    // One speaker's turn, started on the server and then watched.
    //
    // The turn is NOT held open as a single request. 2026-09-08: Claude searches the code and
    // queries the database while it answers, which took 1m 31s, 1m 57s and 4m 06s on the three
    // turns in his logs that morning, against an app that gave up at two minutes. So the app
    // starts the turn, gets an id back straight away, and asks how it is going every couple of
    // seconds -- which also lets it say WHO is working and HOW FAR IN rather than spinning
    // silently at him.
    const runTurn = async (turnBody) => {
      const started = await request('/standup', {
        method: 'POST',
        body: JSON.stringify({ ...turnBody, background: true }),
        timeoutMs: START_TIMEOUT_MS,
      });
      // A server that predates this change answers the question outright instead of handing
      // back an id. Taking that at face value keeps the app working against either one.
      if (!started || !started.turn_id) return started || {};

      const beganAt = Date.now();
      let failures = 0;
      for (;;) {
        await pause(POLL_MS);
        if (stale()) return null;
        let state = null;
        try {
          state = await request('/standup/turn?turn_id=' + encodeURIComponent(started.turn_id), {
            timeoutMs: POLL_TIMEOUT_MS,
          });
          failures = 0;
        } catch (error) {
          // One dropped poll on a phone is ordinary. Several in a row is a network that has
          // gone, and pretending otherwise leaves him watching a line that never moves.
          failures += 1;
          if (failures >= MAX_POLL_FAILURES) throw error;
          continue;
        }
        if (stale()) return null;

        const outcome = pollOutcome(state, Date.now() - beganAt);
        if (outcome.action === 'finished') return outcome.result;
        if (outcome.action === 'failed') throw new Error(outcome.message);
        setStatusLine(progressLine(
          (state && state.progress) || {},
          (state && state.elapsed_seconds) || (Date.now() - beganAt) / 1000,
        ));
      }
    };

    let body = resume || { message: said, mode, conversation_id: 'standup', max_replies: 1 };
    let spent = 0;
    let replies = 0;

    try {
      for (let step = 0; step < MAX_TURNS_PER_QUESTION; step += 1) {
        setStatusLine(progressLine({ speaker: body.continue_as || (mode === 'claude' ? 'claude' : null) }, 0));
        const payload = await runTurn(body);
        if (stale() || payload === null) return;

        const produced = (payload && payload.turns) || [];
        spent += Number((payload && payload.cost_usd) || 0);
        replies += produced.length;
        setTurns((prev) => [
          ...prev,
          ...produced.map((turn) => ({
            speaker: turn.speaker,
            text: normalizeChatText(turn.text),
            toolCalls: (turn.tool_calls || []).length,
            createdAt: new Date().toISOString(),
          })),
        ]);
        // Queued as each reply lands rather than joined into one block: the spoken version is
        // capped at 700 characters, so joining the Trader and Claude would read out the first
        // and silently swallow the second.
        if (handsFreeRef.current) {
          produced.forEach((turn) => speaker.speak(turn.text));
        }
        if (spent) setSpentTotal((prev) => prev + Number((payload && payload.cost_usd) || 0));

        const next = payload && payload.next_speaker;
        if (!next || !produced.length) break;
        // Carry the exchange forward. Nothing new is said; the next participant answers what
        // is already in the transcript.
        body = {
          continue_as: next,
          mode,
          conversation_id: 'standup',
          max_replies: 1,
          // Both counters go back untouched. exchange_used is how many peer replies have
          // happened; opening_left is whether this turn still belongs to the opening question
          // or is already one AI answering the other. Without the second the peer counter
          // never advances and the exchange never ends.
          exchange_used: Number((payload && payload.exchange_used) || 0),
          opening_left: Number((payload && payload.opening_left) || 0),
        };
      }
      if (stale()) return;
      setStatusLine(
        replies
          ? `${replies} repl${replies === 1 ? 'y' : 'ies'} - your turn`
            + (spent ? `  ·  ${formatPence(spent)}` : '')
          : 'No reply came back'
      );
      // Nothing will be read aloud on this device, so the floor has to come back some other
      // way -- otherwise a spoken conversation stops dead on a phone that cannot play audio.
      if (handsFreeRef.current && replies && !canSpeak()) voice.start();
    } catch (error) {
      if (stale()) return;
      // The exchange is paused, not abandoned: whoever was due to speak is remembered so he can
      // pick it up with one tap instead of asking the whole question again.
      if (body && body.continue_as) setResumable(body);
      handsFreeRef.current = false;
      setTurns((prev) => [...prev, {
        speaker: 'claude',
        text: normalizeChatText(String((error && error.message) || '')
          || 'That did not get through. The conversation is still open - try again.'),
        createdAt: new Date().toISOString(),
      }]);
      setStatusLine('Stopped - your turn');
    } finally {
      if (mountedRef.current && exchangeRef.current === ticket) setBusy(false);
    }
  }, [busy, mode, request, speaker, voice]);

  useEffect(() => { sendRef.current = send; }, [send]);

  // Changing who you are talking to abandons the previous question. 2026-09-07: he asked in
  // Standup mode, gave up, switched to Trader and asked again -- and the first question's
  // replies arrived into the new conversation, so both AIs appeared to answer a question he
  // had not asked them. Switching mode is him saying "not that, this".
  useEffect(() => {
    exchangeRef.current += 1;
    setBusy(false);
    setResumable(null);
    // A reply still being read aloud belongs to the conversation he has just left, and the
    // microphone must not reopen into the new one on the back of it.
    handsFreeRef.current = false;
    speaker.stop();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode]);

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
          speak and whoever was last talking continues. Ask out loud and the replies are read
          back to you, with the microphone reopening when they finish.
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
        {/* 2026-09-08: a turn that fails used to end the exchange, because the app forgot whose
            turn was next. Now it remembers, so picking it up is one tap rather than asking the
            whole question again. */}
        {resumable && !busy ? (
          <TouchableOpacity
            style={styles.standupResume}
            onPress={() => send('', { resume: resumable })}
            accessibilityRole="button"
            accessibilityLabel={`Let ${SPEAKER_LABEL[resumable.continue_as] || 'them'} carry on`}
          >
            <Text style={styles.standupResumeText}>
              Carry on - {SPEAKER_LABEL[resumable.continue_as] || 'they'} had not answered yet
            </Text>
          </TouchableOpacity>
        ) : null}
        {spentTotal ? (
          <Text style={styles.smallText}>
            This conversation so far: {formatPence(spentTotal)}
          </Text>
        ) : null}

        {running ? (
          <View style={styles.standupComposer}>
            <TextInput
              style={styles.multilineInput}
              value={draft}
              onChangeText={setDraft}
              placeholder="Tap the microphone and speak, or type here"
              multiline
              editable={!busy}
            />

            {/* 2026-09-07, Founder-reported: "I clicked start conversation. Nothing gets picked
                up, and there's no icon that's animated that shows me that it's listening."
                There was no microphone on this screen at all. Speaking is how he uses this app.

                Recording turns the button red and the status line becomes a ticking counter --
                the count is the proof it is hearing him, which is the specific thing whose
                absence he reported. */}
            <View style={styles.standupActions}>
              <TouchableOpacity
                style={[styles.standupMic, voice.isRecording && styles.standupMicRecording]}
                onPress={() => (voice.isRecording ? voice.stop() : voice.start())}
                disabled={busy || voice.isBusy}
                accessibilityRole="button"
                accessibilityLabel={micButtonAccessibilityLabel(voice.voiceState)}
              >
                <Text style={styles.standupMicText}>{micButtonLabel(voice.voiceState)}</Text>
              </TouchableOpacity>

              {/* 2026-09-07, Founder-directed: "there should be an x button if I want to cancel
                  the transcription or my voice in case I get it wrong."

                  Shown while recording AND while transcribing, because both are moments where
                  he can already tell it has gone wrong and the only alternative is to let it
                  finish and then delete the result. Cancelling discards the audio and abandons
                  any transcription already in flight, so the words never arrive at all. */}
              {voice.isRecording || voice.isBusy ? (
                <TouchableOpacity
                  style={styles.standupCancel}
                  onPress={() => voice.cancel()}
                  accessibilityRole="button"
                  accessibilityLabel="Cancel what I just said"
                >
                  <Text style={styles.standupCancelText}>✕</Text>
                </TouchableOpacity>
              ) : null}

              <TouchableOpacity
                style={[styles.standupSend, (busy || !draft.trim()) && styles.standupSendBusy]}
                onPress={() => send(draft)}
                disabled={busy || !draft.trim()}
              >
                {busy ? <ActivityIndicator color="#ffffff" /> : <Text style={styles.standupSendText}>Send</Text>}
              </TouchableOpacity>
            </View>

            {/* Send is disabled with an empty box, which on its own looks identical to a broken
                button -- he pressed it, nothing happened, and he had no way to tell which. */}
            {!draft.trim() && !voice.isRecording && !busy ? (
              <Text style={styles.smallText}>
                Tap the microphone and just talk - it sends when you stop. Or type instead.
              </Text>
            ) : null}
          </View>
        ) : null}

      </Section>

      {/* 2026-09-07, Founder-directed: "it doesn't show your conversation in a scrollable
          section like in the executive briefing."

          It was crammed into the controls card inside a fixed 460px nested ScrollView, which
          on a tall screen sat mostly below the fold -- so the conversation was there but
          effectively unreachable. The briefing has no nested scrolling anywhere: it is a run
          of titled Section cards that flow into the app's own page scroll. This now does the
          same, which is both what he asked for and less machinery.

          Ask keeps its nested scroll deliberately (he asked for it on 2026-09-04), and the
          difference is real: there the composer must stay put while you page through history.
          Here the newest exchange is already at the top, so the answer to what you just said
          needs no scrolling at all. */}
      {turns.length ? (
        <Section title="Conversation">
          {rendered.map((item, index) =>
            item.type === 'stamp' ? (
              <View key={item.key} style={styles.chatDayStampRow}>
                <Text style={styles.chatDayStamp}>{item.label}</Text>
              </View>
            ) : (
              <View key={item.key || `x-${index}`} style={styles.chatExchange}>
                {item.exchange.map((turn, position) => {
                  const bubble = bubbleFor(turn.speaker);
                  return (
                    <View key={`${turn.key || position}`} style={styles[bubble.row]}>
                      {/* Colour says who at a glance; the label confirms it. Two AI replies
                          one after the other were unreadable when they shared a colour. */}
                      {turn.speaker !== 'founder' ? (
                        <Text style={styles[bubble.speaker]}>
                          {SPEAKER_LABEL[turn.speaker] || 'AI'}
                          {turn.toolCalls ? `  ·  checked ${turn.toolCalls} thing${turn.toolCalls === 1 ? '' : 's'}` : ''}
                        </Text>
                      ) : null}
                      <Text style={styles[bubble.text]} selectable>
                        {turn.text}
                      </Text>
                    </View>
                  );
                })}
              </View>
            )
          )}
        </Section>
      ) : null}
    </View>
  );
}

module.exports = { StandupScreen, MODES, SPEAKER_LABEL, BUBBLE, bubbleFor };
