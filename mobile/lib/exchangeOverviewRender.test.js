const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const babel = require('@babel/core');
const { createRequire } = require('node:module');
const file = require.resolve('../components/ExchangeOverview');
const localRequire = createRequire(file);
const React = { createElement: (type, props, ...children) => ({ type, props, children }) };
const loaded = { exports: {} };
vm.runInNewContext(babel.transformFileSync(file, { presets: [require.resolve('babel-preset-expo')] }).code, {
  module: loaded,
  require: name => {
    if (name === 'react') return React;
    if (name === 'react-native') return { Text: 'Text', View: 'View' };
    if (name === '../styles') return { styles: {} };
    if (name === './shared') return { Section: 'Section', CollapsibleSection: 'CollapsibleSection', Metric: 'Metric' };
    return localRequire(name);
  },
});
test('four exchange cards retain separate names, currency, modes and unavailable values', () => {
  const brokers = ['kraken','alpaca','third','fourth'].map((broker,i)=>({broker,label:`Venue ${i}`,currency:['GBP','USD','USD','EUR'][i],account_mode:i?'paper':'live',portfolio_value:i?100:null}));
  const tree = loaded.exports.ExchangeOverview({brokers,detailed:true});
  const content = JSON.stringify(tree);
  for(let i=0;i<4;i++) assert.match(content,new RegExp(`Venue ${i}`));
  for(const text of ['GBP','USD','EUR','Unavailable','live','paper']) assert.ok(content.includes(text));
  assert.equal((tree.children || tree.props.children)[2].length,4);
});
test('missing evidence renders an explicit empty state',()=>{
  assert.match(JSON.stringify(loaded.exports.ExchangeOverview({})),/Account evidence has not loaded/);
});
