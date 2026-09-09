const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const babel = require('@babel/core');
const { createRequire } = require('node:module');
const React = require('react');

function load(relative, extra = {}) {
  const file = require.resolve(relative), local = createRequire(file), module = { exports: {} };
  const hooks = { ...React, useState: x => [x, () => {}], useRef: x => ({ current: x }), useMemo: fn => fn(), useEffect: () => {}, useCallback: fn => fn };
  vm.runInNewContext(babel.transformFileSync(file, { presets: [require.resolve('babel-preset-expo')] }).code, {
    module, exports: module.exports, require: name => {
      if (name === 'react') return hooks;
      if (name === 'react-native') return { TextInput: 'TextInput', Image: 'Image', View: 'View', Text: 'Text', TouchableOpacity: 'TouchableOpacity', ActivityIndicator: 'ActivityIndicator', StyleSheet: { create: x => x, absoluteFillObject: { position: 'absolute', top: 0, bottom: 0, left: 0, right: 0 } } };
      if (name.endsWith('.png')) return 'bundled-greeting-image';
      if (Object.hasOwn(extra, name)) return extra[name];
      return local(name);
    },
  });
  return module.exports;
}
function nodes(tree) {
  if (!tree || typeof tree !== 'object') return [];
  if (Array.isArray(tree)) return tree.flatMap(nodes);
  return [tree, ...nodes(tree.props?.children)];
}
const shared = { Section: 'Section', CollapsibleSection: 'CollapsibleSection', Metric: 'Metric', Button: 'Button' };

test('account overview renders four labelled tiles, preserves zero/missing values and modes', () => {
  const { ExchangeOverview } = load('../components/ExchangeOverview', { '../styles': { styles: {} }, './shared': shared });
  const tree = ExchangeOverview({ detailed: true, brokers: [{ broker: 'alpaca', account_mode: 'paper', portfolio_value: 100, todays_pnl: 0, cash_available: null, estimated_in_positions: 100 }] });
  assert.equal(tree.props.bare, true);
  const text = JSON.stringify(tree);
  for (const label of ['Account value', 'Account change today', 'Cash', 'In investments', 'paper', 'Includes manual holdings']) assert.ok(text.includes(label));
  assert.ok(text.includes('0.00'));
  assert.ok(!text.includes('NaN'));
});

test('cycle stack retains exact scopes and disables every start action when busy', () => {
  const { styles } = load('../styles');
  const { RunCycleScreen } = load('../screens/RunCycle', {
    '../styles': { styles }, '../components/shared/Section': { Section: 'Section' },
    '../components/shared/Button': { Button: 'Button' }, '../components/shared/StatusPill': { StatusPill: 'StatusPill' },
  });
  const scopes = [];
  const base = { steps: [], cycle: null, lastChecked: null, start: scope => scopes.push(scope) };
  const tree = RunCycleScreen({ cycleRun: base });
  const buttons = nodes(tree).filter(x => x.type === 'Button');
  buttons.forEach(x => x.props.onPress());
  assert.deepEqual(scopes, ['all', 'kraken', 'alpaca']);
  assert.ok(nodes(tree).some(x => x.props?.style === styles.cycleButtonStack));
  assert.ok(JSON.stringify(tree).includes('real orders'));
  assert.ok(nodes(RunCycleScreen({ cycleRun: { ...base, busy: true } })).filter(x => x.type === 'Button').every(x => x.props.disabled));
});

test('failed cycle detail stays visible while completed detail is initially collapsed', () => {
  const { RunCycleScreen } = load('../screens/RunCycle', { '../styles': { styles: {} }, '../components/shared/Section': { Section: 'Section' }, '../components/shared/Button': { Button: 'Button' }, '../components/shared/StatusPill': { StatusPill: 'StatusPill' } });
  const tree = RunCycleScreen({ cycleRun: { cycle: { cycle_id: 'test' }, steps: [{ seq: 1, label: 'First', status: 'completed', summary: 'HIDDEN_SUCCESS_DETAIL' }, { seq: 2, label: 'Second', status: 'failed', summary: 'VISIBLE_FAILURE_DETAIL' }], start: () => {} } });
  assert.ok(JSON.stringify(tree).includes('VISIBLE_FAILURE_DETAIL'));
  assert.ok(!JSON.stringify(tree).includes('HIDDEN_SUCCESS_DETAIL'));
});

test('greeting is a bundled absolute background, not a sibling icon or remote URI', () => {
  const { GreetingIllustration } = load('../components/GreetingIllustration');
  const tree = GreetingIllustration();
  assert.equal(tree.props.importantForAccessibility, 'no-hide-descendants');
  assert.equal(tree.type, 'Image');
  assert.equal(tree.props.source, 'bundled-greeting-image');
  assert.equal(tree.props.style.position, 'absolute');
  assert.ok(!JSON.stringify(tree).includes('uri'));
});

test('new conversation colours remain readable and distinctly identify all speakers', () => {
  const { styles } = load('../styles');
  assert.equal(styles.standupMine.backgroundColor, '#E7F2FF');
  assert.equal(styles.standupTrader.backgroundColor, '#FFFFFF');
  assert.equal(styles.standupClaude.backgroundColor, '#F5F1FF');
  assert.equal(styles.standupMineText.color, '#16324F');
  assert.equal(styles.composerInput.minHeight, 92);
  assert.equal(styles.composerInput.width, '100%');
  assert.equal(styles.accountMetricGrid.flexWrap, 'wrap');
});

test('portfolio chart cards retain fee warnings, unavailable states and real latest value', () => {
  const { BrokerTrends, ValueChart, OutcomeChart } = load('../components/PortfolioTrends', { '../styles': { styles: {} }, './shared': shared, '../api/client': { apiRequest: () => { throw Error('Rendering must not request data'); } } });
  const broker = { broker: 'alpaca', currency: 'USD', account_mode: 'paper', value_status: 'ok', outcome_status: 'ok', values: [{ date: '2026-09-09', value: 123 }], outcomes: [] };
  const text = JSON.stringify(BrokerTrends({ broker, days: 30, weekly: false, asOf: '2026-09-09' }));
  assert.ok(text.includes('paper'));
  assert.ok(text.includes('123.00'));
  assert.ok(text.includes('fees not fully reconciled'));
  assert.ok(text.includes('counts, not money'));
  assert.ok(JSON.stringify(BrokerTrends({ broker: { ...broker, value_status: 'failed' }, days: 30, asOf: '2026-09-09' })).includes('Unavailable'));
  assert.ok(JSON.stringify(ValueChart({ rows: [], currency: 'GBP', colour: '#8064DC' })).includes('Missing values are not zero'));
  const chart = OutcomeChart({ bins: [{ date: '2026-09-09', wins: 2, losses: 1, breakeven: 0, unknown: 0 }], currency: 'USD' });
  assert.ok(JSON.stringify(chart).includes('2 won, 1 lost'));
});

test('Standup exposes microphone and full-width editable composer before Start', () => {
  const { styles } = load('../styles');
  let recordings = 0;
  const { StandupScreen } = load('../screens/Standup', {
    '../styles': { styles }, '../components/shared': shared,
    '../lib/useVoiceCapture': { useVoiceCapture: () => ({ voiceState: 'idle', start: () => recordings++, cancel: () => {} }) },
    '../lib/useSpeaker': { useSpeaker: () => ({ stop: () => {}, isIdle: () => true }) },
  });
  const tree = StandupScreen({ request: () => { throw Error('No requests during initial render'); } });
  const elements = nodes(tree);
  const input = elements.find(n => n.type === 'TextInput');
  assert.ok(input);
  assert.equal(input.props.editable, true);
  assert.equal(input.props.style.width, '100%');
  const mic = elements.find(n => Array.isArray(n.props?.style) && n.props.style[0] === styles.standupMic);
  assert.ok(mic && !mic.props.disabled);
  mic.props.onPress();
  assert.equal(recordings, 1);
  assert.ok(elements.find(n => n.props?.style === styles.standupStart));
});
