'use strict';

const assert = require('assert');
const {
  ASK_REQUEST_TIMEOUT_MS,
  ASK_BACKEND_BUDGET_MS,
  DASHBOARD_REFRESH_TIMEOUT_MS,
  RENDER_PROXY_LIMIT_MS,
  askRequestOptions,
  askErrorMessage,
} = require('./askRequest');

let passed = 0;
function test(name, fn) {
  fn();
  console.log(`ok - ${name}`);
  passed += 1;
}

test('Ask asks for an explicit timeout, because the shared client ignores everything else', () => {
  // 2026-08-24: Ask.js raised its own AbortController to 55s, but api/client.js applies
  // its own timer and overrides the caller's signal, so the effective timeout stayed at
  // the 25s dashboard default and the Founder kept seeing "the request timed out" for
  // answers the backend had already produced. `timeoutMs` is the only lever that works.
  const options = askRequestOptions('How do you think XRP will do?');
  assert.strictEqual(options.timeoutMs, ASK_REQUEST_TIMEOUT_MS);
  assert.strictEqual(options.method, 'POST');
  // 2026-09-03: `spoken` travels with the question so the stored transcript records how it was
  // asked. It defaults to false, so a typed question is unchanged from the app's point of view.
  assert.deepStrictEqual(JSON.parse(options.body), { question: 'How do you think XRP will do?', spoken: false });
  assert.deepStrictEqual(JSON.parse(askRequestOptions('spoken one', true).body), { question: 'spoken one', spoken: true });
});

test('Ask waits longer than a dashboard refresh', () => {
  // Ask gathers evidence and calls OpenAI; it is not the 1-2s poll the default is tuned for.
  assert.ok(
    ASK_REQUEST_TIMEOUT_MS > DASHBOARD_REFRESH_TIMEOUT_MS,
    `Ask timeout ${ASK_REQUEST_TIMEOUT_MS}ms must exceed the ${DASHBOARD_REFRESH_TIMEOUT_MS}ms dashboard default`
  );
});

test('Ask waits long enough for the backend to spend its whole budget', () => {
  // Measured in production: a real answer took 23.5s. The backend guarantees a response
  // by its 50s budget, so hanging up earlier throws away answers that are on their way.
  assert.ok(
    ASK_REQUEST_TIMEOUT_MS > ASK_BACKEND_BUDGET_MS,
    `Ask timeout ${ASK_REQUEST_TIMEOUT_MS}ms must outlast the backend's ${ASK_BACKEND_BUDGET_MS}ms budget`
  );
});

test('Ask gives up before Render kills the connection anyway', () => {
  // Past the proxy limit nothing can arrive, so waiting longer only delays the error.
  assert.ok(
    ASK_REQUEST_TIMEOUT_MS < RENDER_PROXY_LIMIT_MS,
    `Ask timeout ${ASK_REQUEST_TIMEOUT_MS}ms must stay under Render's ${RENDER_PROXY_LIMIT_MS}ms proxy limit`
  );
});

test('a timeout is reported as a timeout whatever case the platform used', () => {
  // React Native reports an aborted fetch as "Aborted", not "aborted" or "AbortError".
  // The old check was case-sensitive, so a real timeout was described to the Founder as
  // "something went wrong reaching AI Trader" -- blaming the network for a backend that
  // was still working, which points at the wrong fix.
  for (const raw of [
    new Error('Aborted'),
    new Error('AbortError: The user aborted a request.'),
    new Error('aborted'),
    new Error('Network request failed'),
    new Error('Request timed out'),
  ]) {
    assert.ok(
      askErrorMessage(raw).includes('took too long'),
      `${raw.message} should be reported as a timeout, got: ${askErrorMessage(raw)}`
    );
  }
});

test('a genuine failure is not dressed up as a timeout', () => {
  const message = askErrorMessage(new Error('Backend returned non-JSON data from /ask-ai-trader (500).'));
  assert.ok(message.includes('something went wrong'), message);
  assert.ok(!message.includes('took too long'), message);
});

test('a missing or empty error still produces a founder-safe message', () => {
  for (const raw of [null, undefined, '', {}]) {
    const message = askErrorMessage(raw);
    assert.ok(message.length > 0);
    assert.ok(!message.includes('undefined'), message);
  }
});

console.log(`\n${passed} passed`);
