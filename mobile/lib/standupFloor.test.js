'use strict';
const assert = require('node:assert/strict');
const { test } = require('node:test');
const vm = require('node:vm');
const babel = require('@babel/core');
const { createRequire } = require('node:module');
const screenPath = require.resolve('../screens/Standup');
const localRequire = createRequire(screenPath);
const source = babel.transformFileSync(screenPath, {
  presets: [require.resolve('babel-preset-expo')],
}).code;
const flush = () => new Promise((resolve) => setImmediate(resolve));

// Exercise the real component's event handlers; all networking/audio is fake.
function harness() {
  let cursor = 0;
  const slots = [];
  let effects = [];
  let capture;
  let speakerOptions;
  let listenCount = 0;
  let idle = true;
  const calls = [];
  const React = {
    createElement: (type, props, ...children) => ({ type, props: props || {}, children }),
    useRef: (value) => {
      const i = cursor++;
      if (!slots[i]) slots[i] = { current: value };
      return slots[i];
    },
    useState: (value) => {
      const i = cursor++;
      if (!(i in slots)) slots[i] = value;
      return [slots[i], (next) => { slots[i] = typeof next === 'function' ? next(slots[i]) : next; }];
    },
    useCallback: (fn) => fn,
    useMemo: (fn) => fn(),
    useEffect: (fn, deps) => {
      const i = cursor++;
      if (!slots[i] || deps.some((d, j) => d !== slots[i][j])) effects.push(fn);
      slots[i] = deps;
    },
  };
  const voice = { start: () => { listenCount += 1; }, cancel: () => {}, stop: () => {} };
  const speaker = { speak: () => { idle = false; }, stop: () => { idle = true; }, isIdle: () => idle };
  const request = (path, options) => {
    if (path.includes('/history')) return Promise.resolve({ turns: [] });
    return new Promise((resolve, reject) => calls.push({ body: JSON.parse(options.body), resolve, reject }));
  };
  const module = { exports: {} };
  vm.runInNewContext(source, { module, require: (name) => {
    if (name === 'react') return React;
    if (name === 'react-native') return Object.fromEntries(['ActivityIndicator', 'Text', 'TextInput', 'TouchableOpacity', 'View'].map((n) => [n, n]));
    if (name === '../styles') return { styles: {} };
    if (name === '../components/shared') return { Section: 'Section', Button: 'Button' };
    if (name === '../lib/useVoiceCapture') return { useVoiceCapture: (opts) => { capture = opts; return voice; } };
    if (name === '../lib/useSpeaker') return { useSpeaker: (opts) => { speakerOptions = opts; return speaker; } };
    return localRequire(name);
  }, setTimeout, Date });
  function render() {
    cursor = 0;
    effects = [];
    const tree = module.exports.StandupScreen({ request });
    effects.forEach((fn) => fn());
    return tree;
  }
  function find(node, predicate) {
    if (!node || typeof node !== 'object') return null;
    if (predicate(node)) return node;
    const children = node.children || node.props?.children || [];
    for (const child of (Array.isArray(node) ? node : Array.isArray(children) ? children : [children])) {
      const found = find(child, predicate);
      if (found) return found;
    }
    return null;
  }
  render();
  return { calls, render, find, transcript: (text) => capture.onTranscript(text),
    finishSpeech: () => { idle = true; speakerOptions.onFinished(); },
    listens: () => listenCount };
}

test('mic waits for the final model reply, even when earlier speech finishes first', async () => {
  const h = harness();
  h.transcript('morning');
  assert.equal(h.calls[0].body.exchange_budget, 4);
  h.calls[0].resolve({ turns: [{ speaker: 'trader', text: 'First' }], next_speaker: 'claude', exchange_used: 0, opening_left: 1 });
  await flush();
  assert.equal(h.calls.length, 2);
  assert.equal(h.calls[1].body.exchange_budget, 4);
  h.finishSpeech();
  assert.equal(h.listens(), 0);
  h.calls[1].resolve({ turns: [{ speaker: 'claude', text: 'Last' }] });
  await flush();
  assert.equal(h.listens(), 0);
  h.finishSpeech();
  assert.equal(h.listens(), 1);
});

test('speech arriving during a model turn waits, then becomes a new question, not a peer loop', async () => {
  const h = harness();
  h.transcript('first question');
  h.transcript('Hey Claude my next question');
  assert.equal(h.calls.length, 1);
  h.calls[0].resolve({ turns: [{ speaker: 'trader', text: 'reply' }], next_speaker: 'claude' });
  await flush();
  assert.equal(h.calls.length, 2);
  assert.equal(h.calls[1].body.message, 'Hey Claude my next question');
  assert.equal(h.calls[1].body.continue_as, undefined);
});

test('failed current reply preserves pending words without automatically resending', async () => {
  const h = harness();
  h.transcript('first question');
  h.transcript('words to preserve');
  h.calls[0].reject(new Error('offline'));
  await flush();
  assert.equal(h.calls.length, 1);
  const tree = h.render();
  const status = h.find(tree, (node) => JSON.stringify(node.props?.children || node.children || '').includes('Your words are saved'));
  assert.ok(status);
  assert.equal(h.listens(), 0);
});

test('ending the conversation abandons queued speech and late model continuations', async () => {
  const h = harness();
  const start = h.find(h.render(), (node) => node.props?.onPress && JSON.stringify(node.props.children || node.children).includes('Start conversation'));
  start.props.onPress();
  h.transcript('first question');
  h.transcript('queued question');
  const end = h.find(h.render(), (node) => node.props?.onPress && JSON.stringify(node.props.children || node.children).includes('End conversation'));
  end.props.onPress();
  h.calls[0].resolve({ turns: [{ speaker: 'trader', text: 'late reply' }], next_speaker: 'claude' });
  await flush();
  assert.equal(h.calls.length, 1);
  h.finishSpeech();
  assert.equal(h.listens(), 0);
});

test('even a server that always requests another speaker cannot exceed ten turns', async () => {
  const h = harness();
  h.transcript('discuss this');
  for (let i = 0; i < 10; i += 1) {
    assert.equal(h.calls.length, i + 1);
    h.calls[i].resolve({ turns: [{ speaker: 'trader', text: 'reply' }], next_speaker: 'claude' });
    await flush();
  }
  assert.equal(h.calls.length, 10);
  h.finishSpeech();
  assert.equal(h.listens(), 1);
});
