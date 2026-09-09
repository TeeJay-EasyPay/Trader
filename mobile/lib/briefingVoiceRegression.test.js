'use strict';
const assert = require('node:assert/strict');
const { test } = require('node:test');
const fs = require('node:fs');
const vm = require('node:vm');
const { buildOperationalSupport } = require('./founderActions');
const { buildOpportunityCards } = require('./principalOpportunities');
const { spokenChunks, speechRequestOptions } = require('./spokenReply');

test('operational support ignores investment recommendations and resolved incidents', () => {
  assert.deepEqual(buildOperationalSupport({ recommendations: [{ ticker: 'DOT' }] }), []);
  assert.deepEqual(buildOperationalSupport({ connectionReadiness: { ready: true, checks: [
    { component: 'Kraken', ready: true },
  ] }, incidents: [{ resolved_at: 'today' }, { status: 'resolved' }] }), []);
  const check = { component: 'Background Worker', ready: false, detail: 'Heartbeat missing' };
  const actions = buildOperationalSupport({ connectionReadiness: { checks: [check, check,
    { component: 'Supabase', ready: false, detail: 'Access unavailable' },
  ] } });
  assert.equal(actions.length, 2);
  assert.equal(actions[0].recommendation, 'Heartbeat missing');
  assert.match(actions[0].ifNothing, /not a request to approve a trade/);
});

test('duplicate assets use highest-confidence eligible record, not rejected or expired ones', () => {
  const cards = buildOpportunityCards({ distinctAssets: true, recommendations: [
    { symbol: 'DOT', broker: 'Kraken', committee_result: 'Reject', confidence: 1 },
    { symbol: 'DOT', broker: 'Kraken', freshness_status: 'Expired', confidence: 1 },
    { symbol: 'DOT', broker: 'Kraken', confidence: 0.5, reason_for_recommendation: 'older' },
    { symbol: 'dot', broker: 'kraken', confidence: 0.8, reason_for_recommendation: 'selected' },
  ] });
  assert.equal(cards.length, 1);
  assert.equal(cards[0].whyILikeIt, 'selected');
});

test('Standup speech clips preserve every word and fit existing speech requests', () => {
  const text = 'A complete sentence with meaningful detail. '.repeat(90).trim();
  const chunks = spokenChunks(text);
  assert.ok(chunks.length > 1);
  assert.equal(chunks.join(' '), text);
  for (const chunk of chunks) {
    assert.ok(chunk.length <= 700);
    assert.equal(JSON.parse(speechRequestOptions(chunk).body).text, chunk);
  }
  assert.equal(spokenChunks('x'.repeat(1600)).join(''), 'x'.repeat(1600));
  assert.deepEqual(spokenChunks('   '), []);
});

// Run the actual hook with native playback stubbed: no device, TTS bill or database.
function speakerHarness(request, nativeAudio = true) {
  const effects = [];
  const sounds = [];
  let drained = 0;
  const React = { useRef: (current) => ({ current }), useCallback: (fn) => fn,
    useEffect: (fn) => { effects.push(fn); } };
  const Audio = { setAudioModeAsync: async () => {}, Sound: { createAsync: async () => {
    const sound = { unloadAsync: async () => {}, setOnPlaybackStatusUpdate: (fn) => { sound.status = fn; } };
    sounds.push(sound);
    return { sound };
  } } };
  const module = { exports: {} };
  vm.runInNewContext(fs.readFileSync(require.resolve('./useSpeaker'), 'utf8'), {
    module, require: (name) => {
      if (name === 'react') return React;
      if (name === 'expo-modules-core') return { requireOptionalNativeModule: () => nativeAudio };
      if (name === 'expo-av') return { Audio };
      return require(name);
    },
  });
  const hook = module.exports.useSpeaker({ request, onFinished: () => { drained += 1; } });
  effects.forEach((effect) => effect());
  return { hook, sounds, drained: () => drained };
}
const flush = () => new Promise((resolve) => setImmediate(resolve));

test('missing native audio drains without making a speech request', () => {
  const h = speakerHarness(() => { throw new Error('must not request audio'); }, false);
  h.hook.speak('visible reply');
  assert.equal(h.hook.isIdle(), true);
  assert.equal(h.drained(), 1);
});

test('speech queue drains only after all clips, tolerates playback errors once', async () => {
  const h = speakerHarness(async () => ({ audio_base64: 'stub' }));
  h.hook.speak('First reply');
  h.hook.speak('Second reply');
  await flush();
  assert.equal(h.hook.isIdle(), false);
  h.sounds[0].status({ didJustFinish: true });
  h.sounds[0].status({ didJustFinish: true });
  await flush();
  assert.equal(h.sounds.length, 2);
  assert.equal(h.drained(), 0);
  h.sounds[1].status({ error: 'playback failed' });
  assert.equal(h.drained(), 1);
  assert.equal(h.hook.isIdle(), true);
});

test('a cancelled speech request cannot release the floor during newer speech', async () => {
  let finishOld;
  let count = 0;
  const h = speakerHarness(() => ++count === 1
    ? new Promise((resolve) => { finishOld = resolve; })
    : Promise.resolve({ audio_base64: 'new' }));
  h.hook.speak('old');
  h.hook.stop();
  h.hook.speak('new');
  await flush();
  finishOld({ audio_base64: 'old' });
  await flush();
  assert.equal(h.hook.isIdle(), false);
  assert.equal(h.sounds.length, 1);
  assert.equal(h.drained(), 0);
  h.sounds[0].status({ didJustFinish: true });
  assert.equal(h.drained(), 1);
});
