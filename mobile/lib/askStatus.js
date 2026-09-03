// What the Ask Status line should say, given what the backend actually did.
//
// 2026-09-04, Founder-reported: "It still says when it responds that it's using chat GPT four
// point one" -- while the answer was plainly a canned readout of table values.
//
// He was right to be suspicious. The backend had returned:
//
//     status: "openai_failed"
//     note:   "OpenAI explanation failed... Reason: HTTP Error 429: Too Many Requests"
//
// and the screen printed "Answered using gpt-4.1" anyway, because it showed whichever model was
// CONFIGURED rather than whichever produced the answer. So a failure was displayed as a
// success, and the real problem -- the model never ran -- was hidden behind a label that said
// it had. That is the same defect as Ask inventing a week of stopped research from an empty
// section: the app stating something it had not checked.
//
// The rule here is narrow and worth keeping: only claim a model answered when a model answered.

'use strict';

// The backend's own vocabulary. Anything else is treated as "we do not know", which is safer
// than assuming success for a status this file has not been taught yet.
const REAL_ANSWER = 'answered';
const FELL_BACK = ['openai_failed', 'evidence_only', 'openai_not_configured'];

function askStatusLine(result) {
  const status = String(result?.status || '').toLowerCase();
  const model = String(result?.model || '').trim();

  if (status === REAL_ANSWER && model) return `Answered using ${model}.`;
  if (status === REAL_ANSWER) return 'Answered.';

  if (status === 'openai_not_configured') {
    return 'Answered from stored evidence - no AI model is configured for this deployment.';
  }
  if (status === 'evidence_only') {
    return 'Answered from stored evidence - gathering it used up the time available. Ask again for a fuller answer.';
  }
  if (status === 'openai_failed') {
    // The specific cause matters to the Founder here, because the two have completely
    // different fixes: waiting a minute versus checking the account.
    return isRateLimited(result)
      ? 'Answered from stored evidence - the AI model was rate-limited. Wait a minute and ask again.'
      : 'Answered from stored evidence - the AI model could not be reached.';
  }
  if (!status) return 'Answered.';
  return 'Answered from stored evidence.';
}

// 429 is the one failure the Founder can act on himself, and it is the one that was hidden.
function isRateLimited(result) {
  const note = String(result?.note || '').toLowerCase();
  return note.includes('429') || note.includes('too many requests') || note.includes('rate limit');
}

// True only when a model genuinely produced the words on screen. Used to decide whether the
// answer is worth speaking aloud: reading a table dump out loud is worse than saying nothing.
function isModelAnswer(result) {
  return String(result?.status || '').toLowerCase() === REAL_ANSWER;
}

module.exports = { askStatusLine, isModelAnswer, isRateLimited, REAL_ANSWER, FELL_BACK };
