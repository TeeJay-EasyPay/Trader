'use strict';
const DAY = 86400000;
function timestamp(value) {
  if (!value) return null;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}
function dateLabel(value) {
  const time = timestamp(value);
  return time === null ? 'Not recorded' : new Date(time).toLocaleString(undefined, {
    day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}
function duration(ms) {
  const hours = Math.floor(Math.max(0, ms) / 3600000);
  const days = Math.floor(hours / 24), rest = hours % 24;
  return hours < 1 ? 'Less than 1 hour' : `${days} ${days === 1 ? 'day' : 'days'} ${rest} ${rest === 1 ? 'hour' : 'hours'}`;
}
function experimentTimeline(data, now = Date.now()) {
  const spec = data.spec || {}, report = data.report || {}, state = data.state || {};
  const start = timestamp(data.created_at);
  const days = Number(spec.evaluation_days);
  const target = timestamp(report.evaluate_after) ??
    (start !== null && Number.isFinite(days) && days > 0 ? start + days * DAY : null);
  const ended = data.status !== 'shadow_running';
  const reviewed = (data.events || []).find(event => event.action === 'evaluation_finished');
  const end = timestamp(reviewed?.created_at);
  const observations = report.observations ?? null;
  const open = Object.keys(state.baseline?.positions || report.baseline?.positions || {}).length +
    Object.keys(state.candidate?.positions || report.candidate?.positions || {}).length;
  const awaiting = (data.opportunities || []).some(o => Object.values(o.arms || {}).some(a => a.status === 'awaiting_bar'));
  let stage = 'Collecting opportunities and recording simulated decisions';
  if (observations === 0 || (!observations && !(data.opportunities || []).length)) stage = 'Waiting for new assessed opportunities';
  if (awaiting) stage = 'Waiting for market bars to simulate entries';
  if (open) stage = 'Tracking open simulated positions';
  if (!ended && target !== null && now >= target) stage = 'Evaluation due — awaiting review or unresolved outcomes';
  if (ended) stage = data.status === 'suspended' ? 'Paused — no further simulation processing' :
    data.status === 'insufficient_evidence' ? 'Test ended — insufficient evidence' :
    data.status === 'rejected' ? 'Test rejected' : 'Review / approval stage';
  return {
    stage, start: dateLabel(data.created_at),
    target: target === null ? 'Open the report for the planned date' : dateLabel(new Date(target).toISOString()),
    planned: start !== null && target !== null ? duration(target - start) : 'Not recorded',
    elapsed: start === null ? 'Not recorded' : duration((end ?? now) - start),
    elapsedLabel: end === null ? 'Calendar time since start' : 'Time from start to recorded review',
    remaining: target === null ? 'Not recorded' : ended ? 'Test is no longer running' : now >= target ?
      'Target date reached; this does not mean enough evidence exists' : duration(target - now) + ' until target review',
    graceEnd: target !== null && spec.simulator === 'daily-bar-paired-v1' ? dateLabel(new Date(target + 15 * DAY).toISOString()) : null,
    verdict: report.finished ? String(report.verdict || 'Not recorded').replace(/_/g, ' ') : 'Pending — interim figures are not a final result',
  };
}
module.exports = { experimentTimeline, dateLabel };
