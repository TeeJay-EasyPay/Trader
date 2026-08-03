// Plain Node assert-based tests for api/client.js - run with `node mobile/api/client.test.js`.
// apiRequest is tested by temporarily stubbing the global fetch (Node 22 provides fetch/
// AbortController natively, so no polyfill is required).

'use strict';

const assert = require('assert');
const { bodyPreview, shortApiBase, absoluteApiUrl, apiRequest, API_BASE } = require('./client');

let passed = 0;
function test(name, fn) {
  return fn()
    .then(() => {
      passed += 1;
      console.log(`ok - ${name}`);
    })
    .catch((err) => {
      console.error(`FAIL - ${name}`);
      console.error(err);
      process.exitCode = 1;
    });
}

async function withStubbedFetch(impl, fn) {
  const original = global.fetch;
  global.fetch = impl;
  try {
    await fn();
  } finally {
    global.fetch = original;
  }
}

function jsonResponse(status, body) {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: async () => JSON.stringify(body),
  };
}

async function main() {
  await test('bodyPreview: empty body reads as explicitly empty, not a blank string', async () => {
    assert.strictEqual(bodyPreview(''), 'The response body was empty.');
  });

  await test('bodyPreview: truncates a long body to a preview', async () => {
    const result = bodyPreview('x'.repeat(200));
    assert.ok(result.startsWith('Response started with:'));
    assert.ok(result.length < 200);
  });

  await test('shortApiBase: strips the protocol from the configured API base', async () => {
    assert.strictEqual(shortApiBase(), API_BASE.replace(/^https?:\/\//, ''));
  });

  await test('absoluteApiUrl: a relative path is joined onto the API base', async () => {
    assert.strictEqual(absoluteApiUrl('/reports/1.pdf'), `${API_BASE}/reports/1.pdf`);
  });

  await test('absoluteApiUrl: an already-absolute URL is returned unchanged', async () => {
    assert.strictEqual(absoluteApiUrl('https://example.com/x'), 'https://example.com/x');
  });

  await test('absoluteApiUrl: no path returns the bare API base', async () => {
    assert.strictEqual(absoluteApiUrl(null), API_BASE);
  });

  await test('apiRequest: a successful call returns the parsed JSON body', async () => {
    await withStubbedFetch(async () => jsonResponse(200, { ok: true }), async () => {
      const result = await apiRequest('/status');
      assert.deepStrictEqual(result, { ok: true });
    });
  });

  await test('apiRequest: a 401 response names the masked token in the error message', async () => {
    await withStubbedFetch(async () => jsonResponse(401, { message: 'unauthorized' }), async () => {
      await assert.rejects(() => apiRequest('/status'), /Mobile command token is/);
    });
  });

  await test('apiRequest: a non-JSON body raises a descriptive error instead of throwing a raw parse error', async () => {
    await withStubbedFetch(async () => ({
      ok: true,
      status: 200,
      text: async () => 'not json at all',
    }), async () => {
      await assert.rejects(() => apiRequest('/status'), /Backend returned non-JSON data/);
    });
  });

  await test('apiRequest: an aborted request due to timeout raises a timeout-specific error', async () => {
    await withStubbedFetch(async (url, init) => new Promise((_, reject) => {
      init.signal.addEventListener('abort', () => {
        const error = new Error('aborted');
        error.name = 'AbortError';
        reject(error);
      });
    }), async () => {
      await assert.rejects(() => apiRequest('/slow', { timeoutMs: 10 }), /Request timed out after/);
    });
  });

  console.log(`\n${passed} passed`);
}

main();
