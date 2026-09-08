'use strict';

// Watching a standup turn that is being worked on somewhere else.
//
// 2026-09-08, Founder-reported:
//
//   "after 2 messages or less you provide a message saying 'the rest of that exchange did not
//    get through.....' what does that mean and does it mean the conversation has ended?"
//
// It meant the app gave up waiting. His own server logs that morning:
//
//   09:16:24 -> 09:17:55   8 lookups   1m 31s   got through
//   09:22:17 -> 09:24:14  13 lookups   1m 57s   the app gave up at two minutes
//   09:25:55 -> 09:30:01  ~19 calls    4m 06s   nobody was listening any more
//
// Claude goes away and checks things while it answers -- searches the code, reads a file,
// queries the database -- and each check is another round trip. So the app no longer holds one
// request open for the whole turn. It starts the turn, then asks how it is going every couple
// of seconds until there is an answer.
//
// This file is the pure half: what to say while waiting, and when to stop waiting. Pure so the
// wording can be tested without a phone, because the wording IS the feature here --
//
//   "A spinner says something is happening; it does not say WHAT, or for how long."
//
// -- and getting it wrong is what made him stop a turn that was working.

// How often to ask. Two seconds is often enough to feel live, rare enough that a four-minute
// turn is 120 small requests rather than a flood.
const POLL_MS = 2000;

// Each poll is tiny -- it reads memory on the server and touches no database -- so it has no
// business taking long. A short timeout here means a dropped poll is retried quickly instead
// of stalling the whole conversation behind one hung request.
const POLL_TIMEOUT_MS = 15000;

// The end of the app's patience, and it is deliberately far beyond any turn seen so far. The
// longest real one was 4m 06s; ten minutes means the only things that hit this are a server
// that has died or a phone that has lost the network -- not an AI that is simply thinking.
const MAX_TURN_MS = 600000;

/** "1m 20s", "45s". Plain, and never "80s", which reads as a stopwatch rather than a wait. */
function clockText(seconds) {
  const total = Math.max(0, Math.round(seconds || 0));
  if (total < 60) return `${total}s`;
  const minutes = Math.floor(total / 60);
  return `${minutes}m ${String(total % 60).padStart(2, '0')}s`;
}

// What each lookup actually is, said the way he would say it. The tool names are ours, not his.
const TOOL_WORDS = {
  search_source: 'searching the code',
  read_source_file: 'reading the code',
  query_database: 'checking the database',
};

const SPEAKER_WORDS = { trader: 'Trader', claude: 'Claude' };

/**
 * One line saying who is working, on what, and for how long.
 *
 * @param progress  what the server last reported: { speaker, stage, lookups, max_lookups,
 *                  last_tool }. Any of it may be missing -- a turn reports nothing until its
 *                  first update lands, and the line still has to say something true.
 * @param elapsedSeconds  how long this turn has been going.
 */
function progressLine(progress, elapsedSeconds) {
  const state = progress || {};
  const who = SPEAKER_WORDS[state.speaker] || 'They';
  const clock = clockText(elapsedSeconds);
  const subject = who === 'They' ? 'Working' : `${who} is`;

  if (state.stage === 'looking') {
    const doing = TOOL_WORDS[state.last_tool] || 'checking something';
    const lookups = Number(state.lookups || 0) + 1;
    const cap = Number(state.max_lookups || 0);
    // The count matters as much as the verb: it says the waiting is bounded, which "thinking..."
    // never did. Twelve is the cap, so "lookup 9 of 12" also says it is nearly done.
    const counted = cap > 0 ? `  -  lookup ${Math.min(lookups, cap)} of ${cap}` : '';
    return `${subject === 'Working' ? 'Working' : `${who} is ${doing}`}${counted}  ·  ${clock}`;
  }
  if (state.stage === 'summarising') {
    return `${who} is writing the answer  ·  ${clock}`;
  }
  if (state.stage === 'thinking' && Number(state.lookups || 0) > 0) {
    // Between lookups. Saying how many have already happened stops the line going backwards
    // from "lookup 6 of 12" to a bare "thinking", which reads as progress being lost.
    const cap = Number(state.max_lookups || 0);
    const counted = cap > 0 ? `  -  ${state.lookups} of ${cap} lookups done` : '';
    return `${who} is thinking${counted}  ·  ${clock}`;
  }
  return `${subject === 'Working' ? 'Working' : `${who} is thinking`}  ·  ${clock}`;
}

/**
 * What the app should do with a poll result.
 *
 * Separated from the polling itself because the decisions are where the mistakes live: a turn
 * the server has forgotten must not be waited on forever, and a turn still running must not be
 * mistaken for a finished one with no reply.
 */
function pollOutcome(state, elapsedMs) {
  const payload = state || {};
  if (payload.status === 'done') return { action: 'finished', result: payload.result || {} };
  if (payload.status === 'failed') {
    return { action: 'failed', message: 'That turn stopped before it finished. The conversation is still open.' };
  }
  if (payload.status === 'unknown') {
    // The server restarted, or the turn aged out. Either way it is not coming, and saying so is
    // better than a wait that never ends.
    return { action: 'failed', message: 'That answer was lost when the server restarted. Ask again and it will pick up where you left off.' };
  }
  if (Number(elapsedMs || 0) > MAX_TURN_MS) {
    return { action: 'failed', message: 'That has been going for ten minutes with nothing back. The conversation is still open.' };
  }
  return { action: 'wait' };
}

module.exports = {
  progressLine,
  pollOutcome,
  clockText,
  POLL_MS,
  POLL_TIMEOUT_MS,
  MAX_TURN_MS,
  TOOL_WORDS,
};
