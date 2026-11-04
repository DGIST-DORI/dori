import test from 'node:test';
import assert from 'node:assert/strict';
import { apiFetch, adminWsUrl, getAuthSession, loginWithToken, ticketedWsUrl } from './api.js';

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
    await assert.rejects(loginWithToken('test-token'), { code: 'auth.error.token' });
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

test('session check accepts Access identity and distinguishes server setup from login expiry', async () => {
  const oldWindow = globalThis.window;
  const oldFetch = globalThis.fetch;
  globalThis.window = { location: { origin: 'https://dash.test' }, dispatchEvent() {} };
  try {
    const identity = { user_id: 'viewer@example.org', roles: ['viewer'], auth_type: 'cf_access' };
    globalThis.fetch = async (_url, options) => {
      assert.equal(options.cache, 'no-store');
      assert.equal(options.credentials, 'same-origin');
      return Response.json(identity);
    };
    assert.deepEqual(await getAuthSession(), identity);
    globalThis.fetch = async () => Response.json({ detail: 'Authentication required' }, { status: 401 });
    assert.equal(await getAuthSession(), null);
    globalThis.fetch = async () => new Response('Expired Access session', { status: 401 });
    assert.equal(await getAuthSession(), null);
    globalThis.fetch = async () => Response.json({ detail: 'Cloudflare Access not configured' }, { status: 503 });
    await assert.rejects(getAuthSession(), { code: 'auth.error.configuration' });
    globalThis.fetch = async () => Response.json({ detail: 'CF Access token invalid' }, { status: 401 });
    await assert.rejects(getAuthSession(), { code: 'auth.error.access' });
    globalThis.fetch = async () => Response.json({ detail: 'Forbidden' }, { status: 403 });
    await assert.rejects(getAuthSession(), { code: 'auth.error.permission' });
    globalThis.fetch = async () => new Response('Unavailable', { status: 502 });
    await assert.rejects(getAuthSession(), { code: 'auth.error.session' });
    globalThis.fetch = async () => { throw new TypeError('Failed to fetch'); };
    await assert.rejects(getAuthSession(), { code: 'auth.error.connection' });
  } finally {
    globalThis.window = oldWindow;
    globalThis.fetch = oldFetch;
  }
});
