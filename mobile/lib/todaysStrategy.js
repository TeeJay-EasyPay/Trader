// AT-ED-018 (Founder request, 2026-08-14): "like real traders the app should have a trading
// strategy for each day early in the morning which it then executes for the day whether that
// means having good trades available or not taking trades because the market conditions are not
// right." Sourced from production_evidence.py's daily_plan key (src/ai_trader/daily_plan.py),
// generated once each morning by the premarket-equity job and reconciled live against the day's
// actual trades on every read. Alpaca-only so far -- crypto research already runs continuously,
// with no single "morning" to decide against.
//
// Dependency-free (no React/RN imports), matching every other lib/*.js convention - see
// todaysStrategy.test.js.

'use strict';

function scopeNote(source) {
  const broker = String(source.broker || '').toLowerCase();
  if (broker && broker !== 'alpaca') return null;
  return 'This is the shares plan only. Crypto is researched continuously through the day and is not covered here.';
}

function describeDailyPlan(plan) {
  const source = plan || {};
  if (source.status === 'generated') {
    return {
      status: 'generated',
      // 2026-08-21: the label said a flat "Standing aside today" while crypto was actively
      // trading, so the Founder reasonably read it as "the app did nothing". The plan is
      // Alpaca-only and honest about that -- it just never said which market it covered.
      // Naming the market makes the same true statement stop being misleading.
      decisionLabel: source.decision === 'seek_trades' ? 'Seeking share trades today' : 'Standing aside on shares today',
      decisionTone: source.decision === 'seek_trades' ? 'good' : 'neutral',
      reasoning: source.reasoning || null,
      outcomeText: source.outcome_plain_english || null,
      scope: scopeNote(source),
    };
  }
  return {
    status: 'not_yet_generated',
    plainEnglish: source.plain_english || "Today's plan has not been generated yet -- it is decided each morning before market open.",
  };
}

module.exports = { describeDailyPlan };
