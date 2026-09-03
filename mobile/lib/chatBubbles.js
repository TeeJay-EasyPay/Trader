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

module.exports = {
  isFounder,
  bubbleAlignment,
  bubbleColours,
  bubbleOpacity,
  bubbleStyle,
  bubbleTextStyle,
  normalizeTurn,
  mergeTurns,
};
