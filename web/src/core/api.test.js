import test from 'node:test';
import assert from 'node:assert/strict';
import { apiFetch, adminWsUrl, loginWithToken, ticketedWsUrl } from './api.js';

test('auth wrapper uses cookies, rejects cross-origin requests, and signals expiry', async () => {
  const oldWindow = globalThis.window;
  const oldFetch = globalThis.fetch;
  const events = [];
  const calls = [];
  globalThis.window = {
    location: { origin: 'https://dash.test', host: 'dash.test', protocol: 'https:' },
    dispatchEvent: event => events.push(event.type),
  };
  globalThis.fetch = async (...args) => {
    calls.push(args);
    return new Response('{}', { status: 401 });
  };
  try {
    await apiFetch('/api/knowledge/documents');
    assert.equal(calls[0][1].credentials, 'same-origin');
    assert.equal(calls[0][1].redirect, 'error');
    assert.deepEqual(events, ['dori-auth-required']);
    await assert.rejects(apiFetch('https://evil.test/api'), /dashboard origin/);
    assert.equal(calls.length, 1);
    await assert.rejects(loginWithToken('test-token'));
    assert.equal(new Headers(calls[1][1].headers).get('Authorization'), 'Bearer test-token');
    assert.equal(calls[1][1].method, 'POST');
    await assert.rejects(loginWithToken('emergency', 'access'));
    assert.equal(new Headers(calls[2][1].headers).get('Access'), 'emergency');
    assert.equal(adminWsUrl(), 'wss://dash.test/ws/admin');
    await assert.rejects(ticketedWsUrl('wss://evil.test/ws/admin'), /WebSocket/);
    await assert.rejects(ticketedWsUrl('wss://dash.test:9090'), /WebSocket/);
    assert.equal(calls.length, 3);
    globalThis.fetch = async () => Response.json({ ticket: 'one-use' });
    assert.equal(await ticketedWsUrl(adminWsUrl()), 'wss://dash.test/ws/admin?ticket=one-use');
  } finally {
    globalThis.window = oldWindow;
    globalThis.fetch = oldFetch;
  }
});
