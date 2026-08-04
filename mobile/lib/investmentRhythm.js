// AT-ED-014 Section 4: the Investment Rhythm - AI Trader's organisational heartbeat. Kept
// dependency-free (no React/RN imports), matching every other lib/*.js convention - see
// investmentRhythm.test.js.
//
// The six stage names and times below are AI Trader's PUBLISHED DAILY SCHEDULE (a description of
// how the organisation operates, not a live evidence claim) - "Current Stage"/"Next Stage" are
// derived purely by comparing the clock to that published schedule, never by guessing whether a
// stage actually ran. Separately, and never confused with the schedule position, each stage also
// carries its own evidence-backed completion status: Research and the Founder Brief have real
// timestamps in this backend (last_equity_research/last_crypto_research completed_at, and the
// founder brief's own created_at); Learning, Strategy Committee, and Risk Committee do not exist
// as separately-timestamped stages in current evidence - governance runs per-recommendation, not
// as a scheduled daily batch - so those three are always honestly reported as "not tracked",
// never marked complete. This is the module's literal implementation of "never fabricate
// completion".

'use strict';

const RHYTHM_STAGES = Object.freeze([
  { key: 'research', name: 'Research Complete', scheduledTime: '05:00' },
  { key: 'learning', name: 'Learning Complete', scheduledTime: '05:30' },
  { key: 'strategy_committee', name: 'Strategy Committee', scheduledTime: '06:00' },
  { key: 'risk_committee', name: 'Risk Committee', scheduledTime: '06:15' },
  { key: 'cio_review', name: 'Chief Investment Officer Review', scheduledTime: '06:30' },
  { key: 'founder_brief', name: 'Founder Morning Brief Available', scheduledTime: '07:00' },
]);

const NOT_TRACKED_REASON = 'Not separately timestamped in current evidence - governance runs per-recommendation, not as a scheduled daily batch.';

function toMinutes(time) {
  const [hours, minutes] = time.split(':').map(Number);
  return hours * 60 + minutes;
}

function stageStatus(key, { lastEquityResearchCompletedAt, lastCryptoResearchCompletedAt, founderBriefCreatedAt }) {
  if (key === 'research') {
    const completedAt = [lastEquityResearchCompletedAt, lastCryptoResearchCompletedAt]
      .filter(Boolean)
      .sort((a, b) => new Date(b).getTime() - new Date(a).getTime())[0] || null;
    return completedAt
      ? { status: 'completed', completedAt, note: 'Confirmed by the latest equity/crypto research evidence.' }
      : { status: 'pending', completedAt: null, note: 'No research completion evidence recorded yet today.' };
  }
  if (key === 'cio_review' || key === 'founder_brief') {
    return founderBriefCreatedAt
      ? { status: 'completed', completedAt: founderBriefCreatedAt, note: 'Confirmed by the latest generated Founder brief.' }
      : { status: 'pending', completedAt: null, note: 'No Founder brief has been generated yet today.' };
  }
  return { status: 'not_tracked', completedAt: null, note: NOT_TRACKED_REASON };
}

function buildInvestmentRhythm({ lastEquityResearchCompletedAt, lastCryptoResearchCompletedAt, founderBriefCreatedAt, now = new Date() } = {}) {
  const stages = RHYTHM_STAGES.map((stage) => ({
    ...stage,
    ...stageStatus(stage.key, { lastEquityResearchCompletedAt, lastCryptoResearchCompletedAt, founderBriefCreatedAt }),
  }));
  // UTC, not local time - the schedule is defined in one fixed reference frame so this never
  // drifts depending on which timezone the phone or server happens to be running in.
  const nowMinutes = now.getUTCHours() * 60 + now.getUTCMinutes();
  let scheduledCurrent = null;
  let scheduledNext = null;
  stages.forEach((stage) => {
    if (toMinutes(stage.scheduledTime) <= nowMinutes) {
      scheduledCurrent = stage;
    } else if (!scheduledNext) {
      scheduledNext = stage;
    }
  });
  return { stages, scheduledCurrent, scheduledNext };
}

module.exports = {
  RHYTHM_STAGES,
  buildInvestmentRhythm,
};
