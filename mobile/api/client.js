// Single shared API client for every backend call the mobile app makes. Extracted from
// App.js as part of AT-ED-011 (mobile modularisation) - response contracts are unchanged,
// this only consolidates duplicated fetch/timeout/auth-header handling into one place.

'use strict';

const API_BASE = process.env.EXPO_PUBLIC_AI_TRADER_API_URL || 'https://trader-no0f.onrender.com';
const API_TOKEN = process.env.EXPO_PUBLIC_AI_TRADER_API_TOKEN || '';
const API_TOKEN_MASK = API_TOKEN ? `${API_TOKEN.slice(0, 6)}...${API_TOKEN.slice(-6)}` : 'missing';

const PRIMARY_REFRESH_TIMEOUT_MS = 18000;
const SECONDARY_REFRESH_TIMEOUT_MS = 8000;
const COMMAND_TIMEOUT_MS = 45000;

function bodyPreview(text) {
  const trimmed = String(text || '').replace(/\s+/g, ' ').trim();
  if (!trimmed) {
    return 'The response body was empty.';
  }
  return `Response started with: ${trimmed.slice(0, 80)}`;
}

function shortApiBase() {
  return API_BASE.replace(/^https?:\/\//, '');
}

function absoluteApiUrl(path) {
  if (!path) {
    return API_BASE;
  }
  if (String(path).startsWith('http')) {
    return path;
  }
  return `${API_BASE}${String(path).startsWith('/') ? '' : '/'}${path}`;
}

// The one fetch implementation every screen and hook goes through: adds the bearer token,
// enforces a timeout via AbortController, and normalises non-JSON/non-OK responses into a
// single Error shape so callers never need their own parsing/timeout logic.
async function apiRequest(path, options = {}) {
  const { timeoutMs = PRIMARY_REFRESH_TIMEOUT_MS, ...fetchOptions } = options || {};
  const headers = {
    'Content-Type': 'application/json',
    ...(API_TOKEN ? { Authorization: `Bearer ${API_TOKEN}` } : {}),
  };
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${API_BASE}${path}`, {
      headers,
      ...fetchOptions,
      signal: controller.signal,
    });
    const text = await response.text();
    let json = {};
    if (text) {
      try {
        json = JSON.parse(text);
      } catch (error) {
        throw new Error(
          `Backend returned non-JSON data from ${path} (${response.status}). ${bodyPreview(text)}`
        );
      }
    }
    if (!response.ok) {
      if (response.status === 401) {
        throw new Error(
          `${json.message || json.error || 'unauthorized'}. Mobile command token is ${
            API_TOKEN ? `loaded (${API_TOKEN_MASK})` : 'missing'
          }. It must exactly match AI_TRADER_API_TOKEN in Render.`
        );
      }
      throw new Error(json.message || json.error || `Request failed: ${response.status}`);
    }
    return json;
  } catch (error) {
    if (error?.name === 'AbortError') {
      throw new Error(`Request timed out after ${Math.round(timeoutMs / 1000)}s: ${path}`);
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

module.exports = {
  API_BASE,
  API_TOKEN,
  API_TOKEN_MASK,
  PRIMARY_REFRESH_TIMEOUT_MS,
  SECONDARY_REFRESH_TIMEOUT_MS,
  COMMAND_TIMEOUT_MS,
  bodyPreview,
  shortApiBase,
  absoluteApiUrl,
  apiRequest,
};
