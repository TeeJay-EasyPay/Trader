// How a conversation turn is laid out and coloured.
//
// 2026-09-03, Founder-directed: "my request once transcribed shouldn't have to have 'You' above
// it to show it is text from me. it should just be on the right of the box and then when the AI
// replies the reply should be on the left. maybe the text colours can be different for me and
// for AI."
//
// He is describing every messaging app he uses, and he is right that the label was redundant:
// position and colour already say who spoke, so "You" was a caption explaining something the
// eye had already understood.
//
// Kept in lib/ rather than inline in the screen for the usual reason -- a screen full of JSX
// cannot be unit tested, and the rules below (who is on which side, what stays readable in
// both themes, what a pending turn looks like) are exactly the things that break quietly.

'use strict';

// Mine on the right, AI on the left. Anything unrecognised is treated as the AI's, because an
// unattributed message showing up in the Founder's own colour on his own side would be a lie
// about who said it.
function isFounder(role) {
  return String(role || '').toLowerCase() === 'founder' || String(role || '').toLowerCase() === 'user';
}

function bubbleAlignment(role) {
  return isFounder(role) ? 'flex-end' : 'flex-start';
}

// Two palettes rather than one, so it is obvious at a glance who is speaking without reading a
// word. Deliberately NOT red or green: those mean loss and profit everywhere else in this app,
// and borrowing them here would make a neutral sentence look like a result.
function bubbleColours(role) {
  return isFounder(role)
    ? { background: '#2f6fed', text: '#ffffff', meta: '#d7e4ff' }
    : { background: '#eef1f6', text: '#16233a', meta: '#5b6b86' };
}

// A turn the app has added optimistically -- the spoken acknowledgement, or the question shown
// the instant it is transcribed -- is dimmed until it is real. Without this the "let me check
// that" line is indistinguishable from a finished answer.
function bubbleOpacity(turn) {
  return turn && turn.pending ? 0.72 : 1;
}

function bubbleStyle(turn) {
  const role = turn && turn.role;
  const colours = bubbleColours(role);
  return {
    alignSelf: bubbleAlignment(role),
    backgroundColor: colours.background,
    opacity: bubbleOpacity(turn),
    maxWidth: '85%',
    borderRadius: 16,
    // One squared corner on the speaker's side: the visual tail that says which end it came
    // from, without drawing an actual tail.
    borderBottomRightRadius: isFounder(role) ? 4 : 16,
    borderBottomLeftRadius: isFounder(role) ? 16 : 4,
    paddingVertical: 10,
    paddingHorizontal: 14,
    marginBottom: 8,
  };
}

function bubbleTextStyle(turn) {
  return { color: bubbleColours(turn && turn.role).text, fontSize: 15, lineHeight: 21 };
}

// Turns arrive from two places: this session's own state, and /ask-history when the card
// opens. They must render identically, so both are normalised to one shape here rather than
// each caller inventing its own.
function normalizeTurn(raw) {
  if (!raw) return null;
  const role = isFounder(raw.role) ? 'founder' : 'assistant';
  const text = String(raw.text || '').trim();
  if (!text) return null;
  return {
    role,
    text,
    pending: Boolean(raw.pending),
    spoken: Boolean(raw.spoken),
    createdAt: raw.created_at || raw.createdAt || null,
    key: String(raw.turn_id != null ? `t${raw.turn_id}` : `${role}-${text.slice(0, 24)}-${raw.createdAt || ''}`),
  };
}

// History from the server plus anything said since, without showing the same turn twice.
// The server does not know about optimistic turns, and the session does not know about
// yesterday, so both are needed and the overlap has to be removed.
function mergeTurns(stored, live) {
  const out = [];
  const seen = new Set();
  for (const raw of [...(stored || []), ...(live || [])]) {
    const turn = normalizeTurn(raw);
    if (!turn) continue;
    const fingerprint = `${turn.role}:${turn.text}`;
    if (seen.has(fingerprint)) continue;
    seen.add(fingerprint);
    out.push(turn);
  }
  return out;
}

// 2026-09-04, Founder-directed: "the newest should be at the top... that way every time I ask a
// question I don't have to scroll all the way down to see the answer. And then if I want to ask
// a follow-up question, scroll all the way back up to ask a question."
//
// The EXCHANGES are reversed, not the individual turns. Within one exchange the question must
// still sit above its answer, or the reply appears before the thing it replies to and the whole
// card becomes unreadable. So: newest exchange first, and question-then-answer inside each.
function newestExchangesFirst(turns) {
  const exchanges = [];
  for (const turn of turns || []) {
    // A founder turn starts a new exchange; anything else belongs to the one in progress.
    if (turn.role === 'founder' || exchanges.length === 0) {
      exchanges.push([turn]);
    } else {
      exchanges[exchanges.length - 1].push(turn);
    }
  }
  return exchanges.reverse();
}

// 2026-09-06, Founder-directed: "there should be some sort of time indication in the chat. so
// I can see what conversation happened when. it could just be a simple date stamp that sits in
// the chat window when scrolling. something like in WhatsApp."
//
// Relative words for the two days a person actually thinks in, and a real date beyond that.
// "Today" and "Yesterday" are what makes a stamp readable at a glance; "4 September" is what
// makes it useful a week later.
function dayStampFor(createdAt, now) {
  if (!createdAt) return null;
  const when = new Date(createdAt);
  if (Number.isNaN(when.getTime())) return null;
  const today = now ? new Date(now) : new Date();
  const startOf = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const dayDiff = Math.round((startOf(today) - startOf(when)) / 86400000);
  if (dayDiff <= 0) return 'Today';
  if (dayDiff === 1) return 'Yesterday';
  const sameYear = when.getFullYear() === today.getFullYear();
  return when.toLocaleDateString(undefined, {
    day: 'numeric',
    month: 'long',
    ...(sameYear ? {} : { year: 'numeric' }),
  });
}

// Exchanges arrive newest-first, so reading DOWN the list walks backwards in time. A stamp is
// emitted whenever the day changes from the exchange above it, which puts each day's label
// directly above that day's newest exchange -- the same place WhatsApp puts it, just read in
// the other direction.
//
// An exchange with no usable timestamp gets no stamp rather than a guessed one: a wrong date
// on a conversation is worse than none, because it is the thing the Founder would rely on to
// tell two similar answers apart.
function withDayStamps(exchanges, now) {
  const out = [];
  let previous = null;
  for (const exchange of exchanges || []) {
    const stamped = (exchange || []).find((turn) => turn && turn.createdAt);
    const label = stamped ? dayStampFor(stamped.createdAt, now) : null;
    if (label && label !== previous) {
      out.push({ type: 'stamp', label, key: `stamp-${label}` });
      previous = label;
    }
    out.push({ type: 'exchange', exchange, key: (exchange[0] && exchange[0].key) || `exchange-${out.length}` });
  }
  return out;
}

module.exports = {
  dayStampFor,
  withDayStamps,
  newestExchangesFirst,
  isFounder,
  bubbleAlignment,
  bubbleColours,
  bubbleOpacity,
  bubbleStyle,
  bubbleTextStyle,
  normalizeTurn,
  mergeTurns,
};
