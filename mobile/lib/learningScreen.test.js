const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const { learningRequest, shiftedDate, resultText, humanStatus } = require('./learningScreen');
const { priceText } = require('./learningScreen');
test('compact prices preserve small values and never turn missing data into zero', () => {
  assert.equal(priceText(0.01346040756), '0.0134604');
  assert.equal(priceText(0.000000001234567), '1.23457e-9');
  assert.equal(priceText(0), '0');
  assert.equal(priceText(null), 'Unknown');
  assert.equal(priceText(NaN), 'Unknown');
  const source = fs.readFileSync(require.resolve('../screens/Learning'), 'utf8');
  assert.ok(source.includes("flexWrap: 'nowrap'"));
  assert.ok(!source.includes('paddingRight: 112'));
  assert.ok(source.includes('Exact recorded prices'));
});

test('calendar navigation handles leap years and month ends', () => {
  assert.equal(shiftedDate('2024-03-31', 'monthly', -1), '2024-02-01');
  assert.equal(shiftedDate('2024-03-01', 'daily', -1), '2024-02-29');
  assert.equal(shiftedDate('2026-01-01', 'weekly', -1), '2025-12-25');
});
test('unknown results are not zero, currencies and losses remain separate', () => {
  assert.equal(resultText(null, 'kraken'), 'Unknown');
  assert.equal(resultText(0, 'kraken'), '£0.00');
  assert.equal(resultText(-2, 'alpaca'), '−US$2.00');
  assert.equal(humanStatus('pending'), 'Still tracking');
  assert.equal(humanStatus('unsettleable'), 'Outcome uncertain');
});
test('repeated evidence reads coalesce and reuse a compact cached response', async () => {
  let calls = 0;
  const request = async () => { calls++; return { rows: [] }; };
  await Promise.all([learningRequest(request, '/test-cache'), learningRequest(request, '/test-cache')]);
  await learningRequest(request, '/test-cache');
  assert.equal(calls, 1);
});
test('failed reads are retryable and never cached as success', async () => {
  let calls = 0;
  const request = async () => { if (++calls === 1) throw Error('Unavailable'); return { rows: [] }; };
  await assert.rejects(learningRequest(request, '/test-retry'));
  await learningRequest(request, '/test-retry');
  assert.equal(calls, 2);
});
test('Learning uses read-only evidence, bundled art and real pending states', () => {
  const source = fs.readFileSync(require.resolve('../screens/Learning'), 'utf8');
  for (const text of ['daily', 'weekly', 'monthly', 'LearningCloud', 'waveA', 'waveB', 'pointerEvents="none"',
    '/learning-summary?', '/learning-details?', 'No paired rule experiment recorded', 'Before unreconciled fees',
    'Back to Learning', 'Unavailable', 'setBroker', 'data.has_more']) assert.ok(source.includes(text), text);
  assert.ok(!source.includes('/daily-learning-update'));
  assert.ok(!source.includes('setInterval'));
  const babel = require('@babel/core');
  assert.ok(babel.transformFileSync(require.resolve('../screens/Learning'), { presets: [require.resolve('babel-preset-expo')] }).code);
});

test('overview renders missing sources safely and wires all seven evidence pages', () => {
  const babel = require('@babel/core'), vm = require('node:vm');
  const file = require.resolve('../screens/Learning'), local = require('node:module').createRequire(file);
  const module = { exports: {} };
  vm.runInNewContext(babel.transformFileSync(file, { presets: [require.resolve('babel-preset-expo')] }).code, {
    module, exports: module.exports, require: name => name === 'react-native'
      ? { View: 'View', Text: 'Text', TouchableOpacity: 'Button', StyleSheet: { create: x => x }, Platform: { OS: 'android' } }
      : name === 'react' ? { ...local(name), useState: value => [value, () => {}] }
      : name === '../components/LearningCloud' ? { LearningCloud: 'CloudArtwork' } : local(name),
  });
  const opened = [];
  const tree = module.exports.LearningOverview({ period: 'daily', anchor: '2026-09-09', today: '2026-09-09', onOpen: x => opened.push(x),
    data: { period: { kind: 'daily', start: '2026-09-09', end: '2026-09-10', in_progress: true },
      proposals: [], unavailable: ['completed trades', 'shadow tracking', 'rejection events', 'lesson proposals'],
      reviews: [], rejections: [], shadows: [], outcomes: [], assessment: { explanation: 'Insufficient evidence' }, caveats: [] } });
  function walk(n) { if (!n) return []; if (Array.isArray(n)) return n.flatMap(walk); if (typeof n !== 'object') return [];
    return [n, ...walk(n.props?.children)]; }
  for (const n of walk(tree)) if (['Read trade reviews →', 'View proposed lessons →', 'View tracked opportunities →',
    'View rejected decisions →', 'Review completed trades →', 'Strategy ideas', 'Test results'].includes(n.props?.label)) n.props.onPress();
  assert.deepEqual(opened.sort(), ['decisions', 'proposals', 'rejected', 'reviews', 'strategies', 'tests', 'trades']);
  assert.ok(JSON.stringify(tree).includes('Rejection counts unavailable'));
  assert.ok(JSON.stringify(tree).includes('Completed-trade evidence could not be loaded.'));
  const chart = module.exports.LearningComparisonChart({ period: { kind: 'daily', start: '2026-09-09', end: '2026-09-10' } });
  const rendered = JSON.stringify(chart);
  for (const text of ['Awaiting comparison results', 'Proposed rule', 'Unchanged rule', 'scale pending', '2026-09-09']) assert.ok(rendered.includes(text));
  assert.equal(walk(chart).filter(n => Array.isArray(n.props?.style) && n.props.style[1]?.top).length, 4);
  assert.ok(!rendered.includes('104'), 'no illustrative performance numbers');
});
