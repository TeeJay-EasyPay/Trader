const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const babel = require('@babel/core');
const { createRequire } = require('node:module');
const file = require.resolve('../screens/ExecutiveBriefing');
const localRequire = createRequire(file);
const loaded = { exports: {} };
vm.runInNewContext(babel.transformFileSync(file, { presets: [require.resolve('babel-preset-expo')] }).code, {
  module: loaded,
  require: name => {
    if (name === 'react-native') return { Text: 'Text', View: 'View' };
    if (name === '../styles') return { styles: {} };
    if (name === '../components/shared') return { Section: 'Section', CollapsibleSection: 'CollapsibleSection', StatusPill: 'StatusPill', Button: 'Button' };
    if (name === '../components/ExchangeOverview') return { ExchangeOverview: 'ExchangeOverview' };
    if (name === '../components/GreetingIllustration') return { GreetingIllustration: 'GreetingIllustration' };
    if (name === '../hooks/useForecastHistory') return { useForecastHistory: () => ({}) };
    return localRequire(name);
  },
});
const stamp = '2026-09-09T11:30:00Z';
test('refusal card renders before and after its asynchronous timestamped payload arrives', () => {
  assert.doesNotThrow(() => loaded.exports.DeclineReasonsCard({ declineReasons: null }));
  const tree = loaded.exports.DeclineReasonsCard({ declineReasons: {
    available: true, fetched_at: stamp, refresh_failed: true,
    sample: { events_examined: 2, oldest: stamp, newest: stamp },
    declines: [{ broker: 'kraken', symbol: 'DOT', why: 'Risk too high.', created_at: stamp }],
  } });
  assert.match(JSON.stringify(tree), /Last loaded/);
  assert.match(JSON.stringify(tree), /Risk too high/);
});
test('scorecard renders after its asynchronous loaded timestamp arrives', () => {
  const tree = loaded.exports.TradeScorecardCard({ tradeScorecard: { fetched_at: stamp, refresh_failed: true } });
  assert.match(JSON.stringify(tree), /last loaded/);
});
