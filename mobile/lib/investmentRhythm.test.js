// Plain Node assert-based tests for investmentRhythm.js - run with `node lib/investmentRhythm.test.js`.

'use strict';

const assert = require('assert');
const { RHYTHM_STAGES, buildInvestmentRhythm } = require('./investmentRhythm');

let passed = 0;
function test(name, fn) {
  try {
    fn();
    passed += 1;
    console.log(`ok - ${name}`);
  } catch (err) {
    console.error(`FAIL - ${name}`);
    console.error(err);
    process.exitCode = 1;
  }
}

test('RHYTHM_STAGES: exactly the six published stages, in schedule order', () => {
  assert.deepStrictEqual(
    RHYTHM_STAGES.map((stage) => stage.name),
    ['Research Complete', 'Learning Complete', 'Strategy Committee', 'Risk Committee', 'Chief Investment Officer Review', 'Founder Morning Brief Available']
  );
});

test('buildInvestmentRhythm: research is marked completed only with real research-completion evidence', () => {
  const result = buildInvestmentRhythm({
    lastEquityResearchCompletedAt: '2026-08-05T05:00:00Z',
    now: new Date('2026-08-05T08:00:00Z'),
  });
  const research = result.stages.find((stage) => stage.key === 'research');
  assert.strictEqual(research.status, 'completed');
  assert.strictEqual(research.completedAt, '2026-08-05T05:00:00Z');
});

test('buildInvestmentRhythm: research with no evidence is pending, never fabricated as completed', () => {
  const result = buildInvestmentRhythm({ now: new Date('2026-08-05T08:00:00Z') });
  const research = result.stages.find((stage) => stage.key === 'research');
  assert.strictEqual(research.status, 'pending');
  assert.strictEqual(research.completedAt, null);
});

test('buildInvestmentRhythm: Learning/Strategy Committee/Risk Committee are always not_tracked - no batch evidence exists for them', () => {
  const result = buildInvestmentRhythm({
    lastEquityResearchCompletedAt: '2026-08-05T05:00:00Z',
    founderBriefCreatedAt: '2026-08-05T07:00:00Z',
    now: new Date('2026-08-05T08:00:00Z'),
  });
  ['learning', 'strategy_committee', 'risk_committee'].forEach((key) => {
    const stage = result.stages.find((item) => item.key === key);
    assert.strictEqual(stage.status, 'not_tracked');
    assert.ok(stage.note.length > 0);
  });
});

test('buildInvestmentRhythm: CIO Review and Founder Brief are completed only when a real brief was generated', () => {
  const withBrief = buildInvestmentRhythm({ founderBriefCreatedAt: '2026-08-05T07:00:00Z', now: new Date('2026-08-05T08:00:00Z') });
  const withoutBrief = buildInvestmentRhythm({ now: new Date('2026-08-05T08:00:00Z') });
  assert.strictEqual(withBrief.stages.find((s) => s.key === 'cio_review').status, 'completed');
  assert.strictEqual(withoutBrief.stages.find((s) => s.key === 'cio_review').status, 'pending');
});

test('buildInvestmentRhythm: scheduledCurrent/scheduledNext follow the published schedule against the clock, not evidence', () => {
  const result = buildInvestmentRhythm({ now: new Date('2026-08-05T06:20:00Z') });
  assert.strictEqual(result.scheduledCurrent.key, 'risk_committee');
  assert.strictEqual(result.scheduledNext.key, 'cio_review');
});

test('buildInvestmentRhythm: before the first scheduled stage, scheduledCurrent is null, never fabricated', () => {
  const result = buildInvestmentRhythm({ now: new Date('2026-08-05T04:00:00Z') });
  assert.strictEqual(result.scheduledCurrent, null);
  assert.strictEqual(result.scheduledNext.key, 'research');
});

console.log(`\n${passed} passed`);
if (process.exitCode) {
  console.error('Some investmentRhythm tests failed.');
}
