const test = require('node:test');
const assert = require('node:assert/strict');
const { cycleElapsedLabel } = require('./cycleProgress');

test('elapsed uses existing polling time, and freezes at completion', () => {
  const cycle = { started_at: '2026-09-08T21:01:43Z' };
  const checked = new Date('2026-09-08T21:31:46Z');
  assert.equal(cycleElapsedLabel(cycle, checked), '30 min elapsed');
  cycle.completed_at = '2026-09-08T21:21:43Z';
  assert.equal(cycleElapsedLabel(cycle, checked), '20 min elapsed');
  assert.equal(cycleElapsedLabel(null, checked), null);
  assert.equal(cycleElapsedLabel({ started_at: 'bad' }, checked), null);
  assert.equal(cycleElapsedLabel({ started_at: '2026-09-08T21:40:00Z' }, checked), '0 min elapsed');
});

test('progress polling is slower without adding another endpoint', () => {
  const fs = require('node:fs');
  const source = fs.readFileSync(require('node:path').join(__dirname, '../hooks/useCycleRun.js'), 'utf8');
  assert.match(source, /const POLL_MS = 10000;/);
});
