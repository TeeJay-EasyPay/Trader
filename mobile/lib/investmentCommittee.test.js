// Plain Node assert-based tests for investmentCommittee.js - run with `node lib/investmentCommittee.test.js`.

'use strict';

const assert = require('assert');
const { buildInvestmentCommittee } = require('./investmentCommittee');

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

test('buildInvestmentCommittee: returns exactly the seven departments, in pipeline order', () => {
  const result = buildInvestmentCommittee({});
  assert.deepStrictEqual(
    result.map((item) => item.name),
    ['Research', 'Learning', 'Market Intelligence', 'Strategy', 'Risk', 'Execution', 'Chief Investment Officer']
  );
});

test('buildInvestmentCommittee: no evidence anywhere is honest for every department, never fabricated', () => {
  const result = buildInvestmentCommittee({});
  result.forEach((item) => {
    assert.strictEqual(item.hasEvidence, false);
    assert.ok(item.conclusion.length > 0);
  });
});

test('buildInvestmentCommittee: Research reflects real research evidence when present', () => {
  const result = buildInvestmentCommittee({
    operationsHealth: { last_research_run: { broker: 'alpaca', assets_analysed: 12 } },
  });
  const research = result.find((item) => item.name === 'Research');
  assert.strictEqual(research.hasEvidence, true);
  assert.ok(research.conclusion.includes('alpaca'));
  assert.ok(research.conclusion.includes('12'));
});

test('buildInvestmentCommittee: Risk reflects real readiness evidence, both ready and not-ready', () => {
  const ready = buildInvestmentCommittee({ connectionReadiness: { trade_ready: true } });
  const notReady = buildInvestmentCommittee({ connectionReadiness: { trade_ready: false, note: 'Broker not connected.' } });
  assert.ok(ready.find((item) => item.name === 'Risk').conclusion.includes('currently pass'));
  assert.strictEqual(notReady.find((item) => item.name === 'Risk').conclusion, 'Broker not connected.');
});

test('buildInvestmentCommittee: Chief Investment Officer uses the real executive headline', () => {
  const result = buildInvestmentCommittee({ executiveHeadline: 'Portfolio is stable.' });
  assert.strictEqual(result.find((item) => item.name === 'Chief Investment Officer').conclusion, 'Portfolio is stable.');
});

console.log(`\n${passed} passed`);
if (process.exitCode) {
  console.error('Some investmentCommittee tests failed.');
}
