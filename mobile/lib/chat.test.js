// Plain Node assert-based tests for chat.js - run with `node mobile/lib/chat.test.js`.

'use strict';

const assert = require('assert');
const { withTimeout, normalizeChatText, chatMessageText, chatTurnsNewestFirst } = require('./chat');

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

async function run() {
  await (async () => {
    try {
      const result = await withTimeout(Promise.resolve('done'), 1000);
      assert.strictEqual(result, 'done');
      passed += 1;
      console.log('ok - withTimeout: resolves with the promise value when it wins the race');
    } catch (err) {
      console.error('FAIL - withTimeout: resolves with the promise value when it wins the race');
      console.error(err);
      process.exitCode = 1;
    }
  })();

  await (async () => {
    try {
      const neverResolves = new Promise(() => {});
      await assert.rejects(() => withTimeout(neverResolves, 10), /timed out/);
      passed += 1;
      console.log('ok - withTimeout: rejects with a timeout error when the promise never resolves');
    } catch (err) {
      console.error('FAIL - withTimeout: rejects with a timeout error when the promise never resolves');
      console.error(err);
      process.exitCode = 1;
    }
  })();

  test('normalizeChatText: null/undefined returns an empty string', () => {
    assert.strictEqual(normalizeChatText(null), '');
    assert.strictEqual(normalizeChatText(undefined), '');
  });

  test('normalizeChatText: a non-string value is stringified', () => {
    assert.strictEqual(normalizeChatText({ a: 1 }), JSON.stringify({ a: 1 }, null, 2));
  });

  test('normalizeChatText: collapses runs of 4+ blank lines to at most 2', () => {
    assert.strictEqual(normalizeChatText('a\n\n\n\n\nb'), 'a\n\n\nb');
  });

  test('chatMessageText: empty text falls back to a explanatory message', () => {
    assert.strictEqual(
      chatMessageText(''),
      'No message text was returned. Try asking again, or check Render logs for the /ask-ai-trader response.'
    );
  });

  test('chatMessageText: real text is normalised and returned', () => {
    assert.strictEqual(chatMessageText('hello'), 'hello');
  });

  test('chatTurnsNewestFirst: groups consecutive messages into turns starting at each user message, newest first', () => {
    const messages = [
      { role: 'assistant', text: 'welcome' },
      { role: 'user', text: 'q1' },
      { role: 'assistant', text: 'a1' },
      { role: 'user', text: 'q2' },
      { role: 'assistant', text: 'a2' },
    ];
    const turns = chatTurnsNewestFirst(messages);
    assert.strictEqual(turns.length, 3);
    assert.deepStrictEqual(turns[0].map((m) => m.text), ['q2', 'a2']);
    assert.deepStrictEqual(turns[1].map((m) => m.text), ['q1', 'a1']);
    assert.deepStrictEqual(turns[2].map((m) => m.text), ['welcome']);
  });

  test('chatTurnsNewestFirst: empty input returns no turns', () => {
    assert.deepStrictEqual(chatTurnsNewestFirst([]), []);
  });

  console.log(`\n${passed} passed`);
}

run();
