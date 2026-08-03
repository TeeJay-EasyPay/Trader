// Plain Node assert-based tests for market.js - run with `node mobile/lib/market.test.js`.

'use strict';

const assert = require('assert');
const {
  describeDecision,
  marketsOpenText,
  latestLearningText,
  companiesForThemeList,
  findRecommendationForCompany,
} = require('./market');

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

test('describeDecision: null returns null', () => {
  assert.strictEqual(describeDecision(null), null);
});

test('describeDecision: includes the rejection reason when present', () => {
  assert.strictEqual(
    describeDecision({ symbol: 'AAPL', decision: 'rejected', rejection_reason: 'low confidence' }),
    'AAPL rejected: low confidence'
  );
});

test('marketsOpenText: no decision returns Not available', () => {
  assert.strictEqual(marketsOpenText({}), 'Not available');
});

test('marketsOpenText: reflects open/closed with the exchange name', () => {
  assert.strictEqual(
    marketsOpenText({ last_orchestrator_decision: { market_open: true, exchange: 'NASDAQ' } }),
    'NASDAQ open'
  );
  assert.strictEqual(
    marketsOpenText({ last_orchestrator_decision: { market_open: false, exchange: 'NASDAQ' } }),
    'NASDAQ closed'
  );
});

test('latestLearningText: prefers the benchmark observation, appending the decision when both exist', () => {
  const status = { last_orchestrator_decision: { symbol: 'AAPL', decision: 'no_trade' } };
  const benchmark = { items: [{ ai_interpretation: 'Market flat today.' }] };
  assert.strictEqual(
    latestLearningText(status, benchmark),
    'Market flat today.\nLast orchestrator decision: AAPL no_trade'
  );
});

test('latestLearningText: falls back to just the decision when there is no benchmark observation', () => {
  const status = { last_orchestrator_decision: { symbol: 'AAPL', decision: 'no_trade' } };
  assert.strictEqual(latestLearningText(status, null), 'AAPL no_trade');
});

test('companiesForThemeList: matches by sector or company name substring, capped at 8', () => {
  const theme = { theme: 'AI', summary: 'artificial intelligence boom', key_drivers: '' };
  const companies = Array.from({ length: 10 }, (_, i) => ({ sector: 'AI', company_name: `Company ${i}` }));
  const matches = companiesForThemeList(theme, companies);
  assert.strictEqual(matches.length, 8);
});

test('companiesForThemeList: no companies returns an empty list', () => {
  assert.deepStrictEqual(companiesForThemeList({ theme: 'AI' }, []), []);
});

test('findRecommendationForCompany: matches by ticker, case-insensitively', () => {
  const recs = [{ ticker: 'aapl', proposal_id: 1 }];
  assert.strictEqual(findRecommendationForCompany({ ticker: 'AAPL' }, recs).proposal_id, 1);
});

test('findRecommendationForCompany: no match returns null, not an error', () => {
  assert.strictEqual(findRecommendationForCompany({ ticker: 'MSFT' }, []), null);
});

console.log(`\n${passed} passed`);
