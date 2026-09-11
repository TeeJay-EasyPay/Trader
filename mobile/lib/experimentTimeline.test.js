const test = require('node:test'), assert = require('node:assert/strict');
const { experimentTimeline } = require('./experimentTimeline');
const start = '2026-09-11T01:27:00Z';
const fixture = () => ({ created_at: start, status: 'shadow_running', spec: {
  evaluation_days: 60, simulator: 'daily-bar-paired-v1' }, report: { observations: 0 }, state: {} });
test('timeline uses frozen duration, not a newly moving deadline', () => {
  const a = experimentTimeline(fixture(), Date.parse(start) + 86400000);
  const b = experimentTimeline(fixture(), Date.parse(start) + 2 * 86400000);
  assert.equal(a.planned, '60 days 0 hours');
  assert.equal(a.elapsed, '1 day 0 hours');
  assert.equal(a.target, b.target);
  assert.ok(a.remaining.includes('59 days'));
  assert.ok(a.stage.includes('Waiting for new'));
  assert.ok(a.verdict.startsWith('Pending'));
});
test('unresolved due date is not reported as a completed successful test', () => {
  const data = fixture(); data.report.observations = 8;
  const r = experimentTimeline(data, Date.parse(start) + 61 * 86400000);
  assert.ok(r.stage.startsWith('Evaluation due'));
  assert.ok(r.remaining.includes('does not mean enough evidence'));
  assert.ok(r.graceEnd);
});
test('waiting for bars and tracking positions are distinct stages', () => {
  const data = fixture();
  data.opportunities = [{ arms: { baseline: { status: 'awaiting_bar' } } }];
  assert.ok(experimentTimeline(data).stage.includes('market bars'));
  data.state.baseline = { positions: { MSFT: {} } };
  assert.ok(experimentTimeline(data).stage.includes('open simulated'));
});
test('completed and suspended cases do not keep claiming to run', () => {
  const data = fixture(); data.status = 'insufficient_evidence';
  data.report = { finished: true, verdict: 'insufficient_evidence' };
  data.events = [{ action: 'evaluation_finished', created_at: '2026-09-12T01:27:00Z' }];
  const r = experimentTimeline(data, Date.parse(start) + 90 * 86400000);
  assert.equal(r.elapsed, '1 day 0 hours');
  assert.equal(r.verdict, 'insufficient evidence');
  assert.ok(r.remaining.includes('no longer running'));
  data.status = 'suspended';
  assert.ok(experimentTimeline(data).stage.startsWith('Paused'));
});
test('legacy or missing date fields stay unknown', () => {
  const r = experimentTimeline({ created_at: 'bad', status: 'shadow_running' });
  assert.equal(r.start, 'Not recorded');
  assert.equal(r.planned, 'Not recorded');
  assert.equal(r.elapsed, 'Not recorded');
  assert.equal(r.graceEnd, null);
});
