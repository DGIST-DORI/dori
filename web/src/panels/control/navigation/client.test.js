import test from 'node:test';
import assert from 'node:assert/strict';
import { createNavigationClient, canControl, readResponse } from './client.js';

const flush = async () => { for (let i = 0; i < 30; i++) await Promise.resolve(); };
function harness(roles = ['control']) {
  let time = 0, nextId = 0;
  const timers = new Map(), calls = [], updates = [];
  let state = { server_age: 0, instance_id: 'one', csrf: 'csrf-1', control_owner: null };
  let handler;
  const client = createNavigationClient(value => updates.push(value), {
    now: () => time, clientId: 'test-client',
    schedule: (fn, delay) => { const id = ++nextId; timers.set(id, { fn, at: time + delay }); return id; },
    cancel: id => timers.delete(id),
    fetcher: async (path, options) => {
      calls.push({ path, ...options });
      if (handler) { const response = handler(path, options); if (response) return response; }
      return Response.json(path === '/api/auth/session' ? { roles }
        : path.endsWith('/session') ? { csrf: state.csrf }
          : path.endsWith('/state') ? state : { ok: true });
    },
  });
  return { client, calls, updates, timers, setState: value => { state = value; },
    setHandler: value => { handler = value; }, latest: () => updates.at(-1),
    async advance(ms) {
      const target = time + ms;
      while (true) {
        const due = [...timers.entries()].filter(([, value]) => value.at <= target).sort((a, b) => a[1].at - b[1].at)[0];
        if (!due) break;
        time = due[1].at; timers.delete(due[0]); due[1].fn(); await flush();
      }
      time = target; await flush();
    },
  };
}

test('role mapping matches backend; viewer never sends a command', async () => {
  for (const role of ['admin', 'control', 'deploy']) assert.equal(canControl([role]), true);
  assert.equal(canControl(['viewer']), false);
  const h = harness(['viewer']); h.client.start(); await flush();
  assert.equal(h.latest().online, true);
  await assert.rejects(h.client.command('enable'), /권한/);
  assert.equal(h.calls.some(call => call.method === 'POST'), false);
  h.client.dispose();
});
test('commands keep CSRF/client contract and server restart refreshes CSRF', async () => {
  const h = harness(); h.client.start(); await flush();
  await h.client.command('goal', { x: 0, y: 2, yaw: Math.PI / 2 });
  const first = h.calls.at(-1);
  assert.equal(first.headers['X-Dori-Control'], 'csrf-1');
  assert.deepEqual(JSON.parse(first.body), { action: 'goal', client: 'test-client', x: 0, y: 2, yaw: Math.PI / 2 });
  h.setState({ server_age: 0, instance_id: 'two', csrf: 'csrf-2' }); await h.advance(200);
  await h.client.command('stop');
  assert.equal(h.calls.at(-1).headers['X-Dori-Control'], 'csrf-2');
  h.client.dispose();
});
test('stale timer disables control while a state request is stalled; cleanup aborts it', async () => {
  const h = harness(); h.client.start(); await flush();
  h.setHandler(path => path.endsWith('/state') ? new Promise(() => {}) : null);
  await h.advance(1500);
  assert.equal(h.latest().online, false);
  await assert.rejects(h.client.command('goal'), /최신/);
  const stateCalls = h.calls.filter(call => call.path.endsWith('/state'));
  assert.equal(stateCalls.length, 2);
  assert.equal(stateCalls[1].signal.aborted, false);
  h.client.dispose();
  assert.equal(stateCalls[1].signal.aborted, true);
  const count = h.calls.length; await h.advance(5000); assert.equal(h.calls.length, count);
});
test('heartbeat only for own lease; stop suppresses further heartbeats', async () => {
  const h = harness();
  h.setState({ server_age: 0, csrf: 'csrf', control_owner: 'other-client' });
  h.client.start(); await flush();
  assert.equal(h.calls.some(call => call.method === 'POST'), false);
  h.setState({ server_age: 0, csrf: 'csrf', control_owner: 'test-client' });
  await h.advance(200);
  assert.equal(JSON.parse(h.calls.at(-1).body).action, 'heartbeat');
  await h.client.command('stop');
  const count = h.calls.filter(call => call.method === 'POST').length;
  await h.advance(600);
  assert.equal(h.calls.filter(call => call.method === 'POST').length, count);
  h.client.dispose();
});
test('ROS state age and upstream errors mark offline; recovery does not replay commands', async () => {
  const h = harness(); h.client.start(); await flush();
  h.setState({ server_age: 3, csrf: 'old' }); await h.advance(200);
  assert.equal(h.latest().online, false);
  h.setHandler(path => path.endsWith('/state') ? new Response('', { status: 503 }) : null);
  await h.advance(200); assert.match(h.latest().error, /웹 뷰어/);
  h.setHandler(null); h.setState({ server_age: 0, csrf: 'new' }); await h.advance(200);
  assert.equal(h.latest().online, true);
  assert.equal(h.calls.some(call => call.method === 'POST'), false);
  h.client.dispose();
});
test('HTTP errors surface auth, permissions and backend command rejection', async () => {
  for (const [status, message] of [[401, /로그인/], [403, /권한/], [503, /웹 뷰어/]]) {
    await assert.rejects(readResponse(Response.json({}, { status })), message);
  }
  await assert.rejects(readResponse(Response.json({ error: '다른 브라우저가 주행을 제어 중입니다' }, { status: 400 })), /다른 브라우저/);
});
test('dispose prevents late state and new mount does not acquire prior lease', async () => {
  const h = harness(); h.client.start(); await flush(); h.client.dispose();
  const updates = h.updates.length;
  await h.advance(3000); assert.equal(h.updates.length, updates);
  await assert.rejects(h.client.command('enable'));
  const next = harness(); next.setState({ server_age: 0, csrf: 'csrf', control_owner: 'previous-client' });
  next.client.start(); await flush();
  assert.equal(next.calls.some(call => call.method === 'POST'), false);
  next.client.dispose();
});

test('late enable response after stop cannot restart heartbeat', async () => {
  const h = harness(); h.client.start(); await flush();
  let finishEnable;
  h.setHandler((path, options) => path.endsWith('/command') && JSON.parse(options.body).action === 'enable'
    ? new Promise(resolve => { finishEnable = resolve; }) : null);
  const enabling = h.client.command('enable'); await flush();
  await h.client.command('stop');
  finishEnable(Response.json({ ok: true })); await enabling;
  h.setState({ server_age: 0, csrf: 'csrf', control_owner: 'test-client' });
  await h.advance(600);
  assert.equal(h.calls.filter(call => call.body && JSON.parse(call.body).action === 'heartbeat').length, 0);
  h.client.dispose();
});
