const test = require('node:test'), assert = require('node:assert/strict');
const fs = require('node:fs'), vm = require('node:vm');
const babel = require('@babel/core');
function load(states = []) {
  const file = require.resolve('../screens/Experiments'), local = require('node:module').createRequire(file);
  let index = 0;
  const module = { exports: {} };
  vm.runInNewContext(babel.transformFileSync(file, { presets: [require.resolve('babel-preset-expo')] }).code, {
    module, exports: module.exports, require: name => name === 'react-native'
      ? { View: 'View', Text: 'Text', TouchableOpacity: 'Button', TextInput: 'Input', ActivityIndicator: 'Spinner', StyleSheet: { create: v => v } }
      : name === 'react' ? { ...local(name), useState: v => [index < states.length ? states[index++] : v, () => {}], useEffect: () => {} }
      : local(name),
  });
  return module.exports;
}

test('learning measurement distinguishes missing evidence from proven improvement', () => {
  const compact = JSON.stringify(load().LearningProgress({}));
  assert.ok(compact.includes('We haven’t confirmed an improvement yet.'));
  assert.ok(!compact.includes('Historical screening'));
  const ui = load([true]);
  const empty = JSON.stringify(ui.LearningProgress({}));
  assert.ok(empty.includes('No improvement claim yet'));
  assert.ok(empty.includes('Missing history is not a pass'));
  const rendered = JSON.stringify(load([true]).LearningProgress({measurement:{periods:{weekly:{status:'available',comparisons:[{
    id:'test',broker:'kraken',currency:'GBP',new_resolved_pairs:2,delta_change:-3,status:'not_established'}]}}},
    historical:{status:'completed',day:'today',trials:[{status:'data_required',reason:'Missing historical bars'}]}}));
  assert.ok(rendered.includes('£-3.00'));
  assert.ok(rendered.includes('not established'));
  assert.ok(rendered.includes('Missing historical bars'));
});
test('experiment UI has an honest empty state without fake performance', () => {
  const ui = load([{ items: [], policy: { enabled: false } }, '', false, null, false]);
  const rendered = JSON.stringify(ui.ExperimentsCard({ request: () => assert.fail('render sent a request') }));
  assert.ok(rendered.includes('No tests are running.'));
  assert.ok(rendered.includes('Live activation is disabled'));
});
test('recommendation detail separates library approval from live trading', () => {
  const data = { id: 'x', status: 'recommended', version: 'a'.repeat(64), created_at: 'today',
    spec: { hypothesis: 'A testable idea', threshold: 2.5, costs_status: 'estimated', evidence_ids: [1] }, report: {}, events: [] };
  const ui = load([data, '', false, null, '100']);
  const rendered = JSON.stringify(ui.ExperimentDetail({ request: () => assert.fail('render wrote data'), id: 'x' }));
  assert.ok(rendered.includes('Approve for strategy library'));
  assert.ok(!rendered.includes('Enable live'));
  assert.ok(rendered.includes('Targets are not expected returns'));
});
test('all entry points use the shared experiment UI and exact-version decisions', () => {
  const screen = fs.readFileSync(require.resolve('../screens/Experiments'), 'utf8');
  const app = fs.readFileSync(require.resolve('../App'), 'utf8');
  const learning = fs.readFileSync(require.resolve('../screens/Learning'), 'utf8');
  assert.ok(app.includes('ExperimentPrompt'));
  assert.ok(app.includes('ExperimentsCard request={apiRequest} notifications'));
  assert.ok(learning.includes('<ExperimentsCard request={request}'));
  for (const value of ['version: data.version', 'revision: data.revision', 'confirmed: true', 'idempotency_key:', '/experiments/decision']) assert.ok(screen.includes(value));
  assert.ok(!screen.includes('/database-maintenance'));
  assert.ok(!screen.includes('setInterval'));
});

test('journey explains time and evidence separately', () => {
  const ui = load();
  const rendered = JSON.stringify(ui.TestingJourney({ data: { status: 'shadow_running',
    created_at: '2026-09-11T01:27:00Z', spec: { evaluation_days: 60, simulator: 'daily-bar-paired-v1' }, report: {} } }));
  for (const phrase of ['Planned observation period', 'Next weekly review', 'device timezone', 'not a promise of improved trading', '15 extra calendar days']) {
    assert.ok(rendered.includes(phrase), phrase);
  }
});
