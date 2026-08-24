'use strict';

const assert = require('assert');
const {
  ASK_REQUEST_TIMEOUT_MS,
  ASK_BACKEND_BUDGET_MS,
  DASHBOARD_REFRESH_TIMEOUT_MS,
  RENDER_PROXY_LIMIT_MS,
  askRequestOptions,
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
  assert.deepStrictEqual(JSON.parse(options.body), { question: 'How do you think XRP will do?' });
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

console.log(`\n${passed} passed`);
