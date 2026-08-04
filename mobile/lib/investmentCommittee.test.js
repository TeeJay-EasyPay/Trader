// Plain Node assert-based tests for investmentCommittee.js - run with `node lib/investmentCommittee.test.js`.
// AT-ED-016: extended from 7 to 9 departments (adds Forecast Engine, Broker Monitoring,
// Portfolio Intelligence; drops the standalone "Chief Investment Officer" entry) - see
// Executive_Briefing_Evolution_Design_Review.md for why this is an intentional evolution, not a
// regression.

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

test('buildInvestmentCommittee: returns exactly the nine departments, in the directive-specified order', () => {
  const result = buildInvestmentCommittee({});
  assert.deepStrictEqual(
    result.map((item) => item.name),
    ['Market Intelligence', 'Research', 'Learning', 'Forecast Engine', 'Risk Committee', 'Strategy Committee', 'Execution', 'Broker Monitoring', 'Portfolio Intelligence']
  );
});

test('buildInvestmentCommittee: no evidence anywhere is honest for every department, never fabricated', () => {
  const result = buildInvestmentCommittee({});
  result.forEach((item) => {
    assert.strictEqual(item.hasEvidence, false);
    assert.ok(item.conclusion.length > 0);
  });
});

test('buildInvestmentCommittee: Research reflects real research evidence when present, without leaking a raw broker id (AT-ED-016.1)', () => {
  const result = buildInvestmentCommittee({
    operationsHealth: { last_research_run: { broker: 'alpaca', assets_analysed: 12 } },
  });
  const research = result.find((item) => item.name === 'Research');
  assert.strictEqual(research.hasEvidence, true);
  assert.ok(research.conclusion.includes('12'));
  assert.ok(!research.conclusion.includes('alpaca'));
});

test('buildInvestmentCommittee: Risk Committee reflects real readiness evidence, both ready and not-ready', () => {
  const ready = buildInvestmentCommittee({ connectionReadiness: { trade_ready: true } });
  const notReady = buildInvestmentCommittee({ connectionReadiness: { trade_ready: false, note: 'Broker not connected.' } });
  assert.strictEqual(ready.find((item) => item.name === 'Risk Committee').conclusion, 'Portfolio remains within acceptable limits.');
  assert.strictEqual(notReady.find((item) => item.name === 'Risk Committee').conclusion, 'Broker not connected.');
});

test('buildInvestmentCommittee: Forecast Engine reflects real tradeStatistics() availability (AT-ED-016.1: one clean sentence, not a stat dump - the full reason still lives in the Forecast Centre section)', () => {
  const available = buildInvestmentCommittee({ forecastStats: { available: true, sampleSize: 10, winRate: 0.6 } });
  const unavailable = buildInvestmentCommittee({ forecastStats: { available: false, reason: 'Only 2 closed trades exist.' } });
  const forecastDept = available.find((item) => item.name === 'Forecast Engine');
  assert.strictEqual(forecastDept.hasEvidence, true);
  assert.strictEqual(forecastDept.conclusion, 'Producing live forecasts from real trade history.');
  assert.strictEqual(unavailable.find((item) => item.name === 'Forecast Engine').conclusion, 'Not enough trade history yet to produce a forecast.');
});

test('buildInvestmentCommittee: Broker Monitoring counts real connected brokers out of the total', () => {
  const result = buildInvestmentCommittee({
    brokerPanels: [{ connection_status: 'connected' }, { connection_status: 'disconnected' }],
  });
  const broker = result.find((item) => item.name === 'Broker Monitoring');
  assert.strictEqual(broker.hasEvidence, true);
  assert.ok(broker.conclusion.includes('1 of 2'));
});

test('buildInvestmentCommittee: Portfolio Intelligence uses the real plain_english field', () => {
  const result = buildInvestmentCommittee({ portfolioIntelligence: { plain_english: 'Up 2% today.' } });
  assert.strictEqual(result.find((item) => item.name === 'Portfolio Intelligence').conclusion, 'Up 2% today.');
});

console.log(`\n${passed} passed`);
if (process.exitCode) {
  console.error('Some investmentCommittee tests failed.');
}
