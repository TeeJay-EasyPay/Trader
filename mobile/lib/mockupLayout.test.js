const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const babel = require('@babel/core');
const { createRequire } = require('node:module');
const React = require('react');

function load(relative, extra = {}) {
  const file = require.resolve(relative), local = createRequire(file), module = { exports: {} };
  const hooks = { ...React, useState: x => [x, () => {}] };
  vm.runInNewContext(babel.transformFileSync(file, { presets: [require.resolve('babel-preset-expo')] }).code, {
    module, exports: module.exports, require: name => {
      if (name === 'react') return hooks;
      if (name === 'react-native') return { View: 'View', Text: 'Text', TouchableOpacity: 'TouchableOpacity', ActivityIndicator: 'ActivityIndicator', StyleSheet: { create: x => x } };
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

test('sun and cloud are decorative native shapes with no image URI', () => {
  const { GreetingIllustration } = load('../components/GreetingIllustration');
  const tree = GreetingIllustration();
  assert.equal(tree.props.importantForAccessibility, 'no-hide-descendants');
  assert.equal(nodes(tree).filter(x => x.type === 'View').length, 6);
  assert.ok(!JSON.stringify(tree).includes('uri'));
});

test('new conversation colours remain readable and distinctly identify all speakers', () => {
  const { styles } = load('../styles');
  assert.equal(styles.standupMine.backgroundColor, '#E7F2FF');
  assert.equal(styles.standupTrader.backgroundColor, '#FFFFFF');
  assert.equal(styles.standupClaude.backgroundColor, '#F5F1FF');
  assert.equal(styles.standupMineText.color, '#16324F');
  assert.equal(styles.composerInput.minHeight, 48);
  assert.equal(styles.accountMetricGrid.flexWrap, 'wrap');
});
