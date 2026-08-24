// How Ask AI Trader calls the backend.
//
// This lives in lib/ rather than inline in screens/Ask.js for one reason: the value that
// matters here is easy to change in a way that has no effect, and a screen full of JSX
// cannot be unit tested. 2026-08-24 is the worked example -- Ask.js built its own
// AbortController with a raised timeout, but api/client.js applies its OWN timer and sets
// `signal: controller.signal` AFTER spreading the caller's options, so the caller's signal
// was discarded and the effective timeout stayed at the 25s dashboard default. The screen
// looked fixed, shipped, and still timed out on the Founder's phone.
//
// The only thing the shared client honours is an explicit `timeoutMs` in its options, so
// that is what Ask must pass, and that is what askRequestOptions() exists to guarantee.

'use strict';

// The dashboard default in api/client.js. Duplicated deliberately: the test below asserts
// Ask asks for MORE than this, and importing api/client.js here would drag Expo config
// loading into a plain node test run.
const DASHBOARD_REFRESH_TIMEOUT_MS = 25000;

// Render's proxy hangs up at a hard 60s and returns nothing at all. The backend works to
// a 50s budget and always returns something inside it -- a real OpenAI answer when there
// is time, the stored evidence summary when there is not. So Ask should wait for that,
// and still give up before the proxy makes the wait pointless.
const RENDER_PROXY_LIMIT_MS = 60000;
const ASK_BACKEND_BUDGET_MS = 50000;
const ASK_REQUEST_TIMEOUT_MS = 55000;

function askRequestOptions(question) {
  return {
    method: 'POST',
    body: JSON.stringify({ question }),
    // Must be passed explicitly. Without it the shared client silently applies the 25s
    // dashboard default, which is shorter than the backend's own budget.
    timeoutMs: ASK_REQUEST_TIMEOUT_MS,
  };
}

const TIMEOUT_MARKERS = ['aborterror', 'abort', 'timed out', 'timeout', 'network request failed'];

function askErrorMessage(error) {
  // 2026-08-24: this test was case-sensitive and only looked for 'AbortError'/'aborted'.
  // React Native reports an aborted fetch as "Aborted" (and sometimes "Network request
  // failed"), so a genuine timeout fell through to the generic branch and told the
  // Founder "something went wrong reaching AI Trader" -- pointing at the network when
  // the truth was that the backend was still working. Wrong diagnosis, wrong next step.
  const message = String((error && error.message) || error || '').toLowerCase();
  if (TIMEOUT_MARKERS.some((marker) => message.includes(marker))) {
    return 'AI Trader took too long to answer that one. It is still gathering evidence in the background - try again in a moment, or ask a shorter question.';
  }
  return 'I could not answer that yet - something went wrong reaching AI Trader. Please try again in a moment.';
}

module.exports = {
  ASK_REQUEST_TIMEOUT_MS,
  ASK_BACKEND_BUDGET_MS,
  DASHBOARD_REFRESH_TIMEOUT_MS,
  RENDER_PROXY_LIMIT_MS,
  askRequestOptions,
  askErrorMessage,
};
