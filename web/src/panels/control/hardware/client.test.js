import test from 'node:test';
import assert from 'node:assert/strict';
import { createHardwareClient, driveReady, hardwareClientId } from './client.js';

const flush = async () => { for (let i = 0; i < 40; i++) await Promise.resolve(); };

test('plain HTTP LAN origins can create a valid client identity without randomUUID', () => {
  const id = hardwareClientId({ getRandomValues: array => array.fill(4294967295) });
  assert.match(id, /^[a-zA-Z0-9_-]{1,64}$/);
});

function harness() {
  let time = 1000, id = 0, handler;
  const timers = new Map(), calls = [], updates = [];
  let state = { can_control: true, live_enabled: true, supervisor_available: true,
    mode: 0, action_state: 0, control_epoch: 'a'.repeat(32) };
  const client = createHardwareClient(value => updates.push(value), {
    clientId: 'test', now: () => time,
    schedule: (fn, delay) => { const key = ++id; timers.set(key, { fn, at: time + delay }); return key; },
    cancel: key => timers.delete(key),
    request: async (path, options) => {
      const call = { path, ...options, payload: options.body ? JSON.parse(options.body) : null };
      calls.push(call);
      const response = handler?.(call);
      return response || Response.json(path.endsWith('/state') ? state : { executed: state.live_enabled });
    },
  });
  return { client, calls, updates, timers, latest: () => updates.at(-1),
    commands: () => calls.filter(c => c.payload).map(c => c.payload.action),
    state: patch => { state = { ...state, ...patch }; }, handler: value => { handler = value; },
    async advance(ms) {
      const target = time + ms;
      while (true) {
        const due = [...timers.entries()].filter(([, v]) => v.at <= target).sort((a, b) => a[1].at - b[1].at)[0];
        if (!due) break;
        time = due[1].at; timers.delete(due[0]); due[1].fn(); await flush();
      }
      time = target; await flush();
    },
  };
}

test('mount and reconnection only observe; viewers cannot issue commands', async () => {
  const h = harness(); h.state({ can_control: false }); h.client.start(); await flush();
  h.client.hold({ linear_x: .1 }); await h.client.command('resume'); await h.client.stop(true);
  assert.deepEqual(h.commands(), []);
  h.state({ can_control: true }); await h.advance(250);
  assert.deepEqual(h.commands(), []); h.client.dispose();
});

test('hold refreshes bounded inputs with client/epoch; release stops and never resumes', async () => {
  const h = harness(); h.client.start(); await flush();
  h.client.hold({ linear_x: .1, angular_z: 0 }); await flush(); await h.advance(300);
  assert.ok(h.commands().filter(a => a === 'move').length >= 2);
  const move = h.calls.find(c => c.payload?.action === 'move').payload;
  assert.deepEqual(move.params, { linear_x: .1, angular_z: 0, client_id: 'test', control_epoch: 'a'.repeat(32) });
  await h.client.stop(); const count = h.commands().length;
  await h.advance(1000); assert.equal(h.commands().length, count);
  assert.equal(h.commands().at(-1), 'stop'); assert.equal(h.latest().holding, false);
  h.client.dispose();
});

test('release immediately stops, then stops again after an in-flight move settles', async () => {
  const h = harness(); h.client.start(); await flush(); let resolve;
  h.handler(c => c.payload?.action === 'move' ? new Promise(r => { resolve = r; }) : null);
  h.client.hold({ linear_x: .1 }); await flush(); await h.advance(300);
  assert.equal(h.commands().filter(a => a === 'move').length, 1);
  await h.client.stop(); assert.deepEqual(h.commands(), ['move', 'stop']);
  resolve(Response.json({ executed: true })); await flush();
  assert.deepEqual(h.commands(), ['move', 'stop', 'stop']);
  await h.advance(1000); assert.equal(h.commands().length, 3); h.client.dispose();
});

test('stalled status stops a held drive; recovery does not replay it', async () => {
  const h = harness(); h.client.start(); await flush();
  h.client.hold({ linear_x: .1 }); await flush();
  h.handler(c => c.path.endsWith('/state') ? new Promise(() => {}) : null);
  await h.advance(1200);
  assert.equal(h.latest().online, false); assert.equal(h.latest().holding, false);
  assert.equal(h.commands().at(-1), 'stop'); h.client.dispose();
});

test('unsafe state, conflicting inputs and another owner prohibit driving', async () => {
  const h = harness(); h.client.start(); await flush();
  for (const patch of [{ mode: 1 }, { action_state: 4 }, { stop_latched: true },
    { manual_input_conflict: true }, { supervisor_available: false }, { move_owner: 'other' }]) {
    assert.equal(driveReady({ ...h.latest().state, ...patch }, 'test'), false);
  }
  h.client.hold({ linear_x: .1 }); await flush();
  h.state({ action_state: 2 }); await h.advance(250);
  assert.equal(h.commands().at(-1), 'stop'); h.client.dispose();
});

test('server rejection stops driving and surfaces the reason', async () => {
  const h = harness(); h.client.start(); await flush();
  h.handler(c => c.payload?.action === 'move' ? Response.json({ detail: 'Supervisor unavailable' }, { status: 503 }) : null);
  h.client.hold({ linear_x: .1 }); await flush();
  assert.deepEqual(h.commands(), ['move', 'stop']);
  assert.match(h.latest().error, /Supervisor unavailable/); h.client.dispose();
});

test('unmount stops active motion and cancels future polls and refreshes', async () => {
  const h = harness(); h.client.start(); await flush();
  h.client.hold({ linear_x: .1 }); await flush(); h.client.dispose(); await flush();
  const count = h.calls.length; await h.advance(5000);
  assert.equal(h.calls.length, count); assert.equal(h.commands().at(-1), 'stop');
  assert.equal(h.timers.size, 0);
});

test('dry-run feedback never claims that hardware moved', async () => {
  const h = harness(); h.state({ executor: 'dry-run', live_enabled: false, supervisor_available: false });
  h.client.start(); await flush(); await h.client.command('transform', { pose: 'B' });
  assert.match(h.latest().notice, /모의 제어/); assert.match(h.latest().notice, /움직이지 않습니다/);
  h.client.dispose();
});

test('switching uses the authenticated command route and immediately reflects shared state', async () => {
  const h = harness(); h.state({ executor: 'dry-run', live_enabled: false });
  h.client.start(); await flush();
  h.handler(c => c.payload?.action === 'set_live_control' ? Response.json({
    executed: true, control_state: { executor: 'bridge', live_enabled: true, stop_latched: true,
      action_state: 4, control_epoch: 'b'.repeat(32) },
  }) : null);
  await h.client.command('set_live_control', { enabled: true });
  assert.deepEqual(h.calls.at(-1).payload, { action: 'set_live_control', params: {
    enabled: true, client_id: 'test', control_epoch: 'a'.repeat(32),
  } });
  assert.equal(h.latest().state.live_enabled, true);
  assert.equal(driveReady(h.latest().state, 'test'), false);
  assert.match(h.latest().notice, /정지를 해제/); h.client.dispose();
});

test('a held simulated input cannot become real motion when another dashboard enables control', async () => {
  const h = harness(); h.state({ executor: 'dry-run', live_enabled: false });
  h.client.start(); await flush(); h.client.hold({ linear_x: .1 }); await flush();
  h.state({ executor: 'bridge', live_enabled: true, control_epoch: 'b'.repeat(32) });
  await h.advance(300);
  assert.equal(h.latest().holding, false);
  assert.equal(h.commands().at(-1), 'stop');
  assert.ok(h.calls.filter(c => c.payload?.action === 'move').every(c => c.payload.params.control_epoch === 'a'.repeat(32)));
  h.client.dispose();
});

test('disable is available during a held request and after status disconnects', async () => {
  const h = harness(); h.client.start(); await flush();
  let resolve;
  h.handler(c => c.payload?.action === 'move' ? new Promise(r => { resolve = r; }) : null);
  h.client.hold({ linear_x: .1 }); await flush();
  await h.client.command('set_live_control', { enabled: false });
  assert.ok(h.commands().includes('set_live_control'));
  assert.equal(h.latest().holding, false);
  resolve(Response.json({ executed: true })); await flush();
  h.handler(c => c.path.endsWith('/state') ? Response.json({ detail: 'offline' }, { status: 503 }) : null);
  await h.advance(300); assert.equal(h.latest().online, false);
  await h.client.command('set_live_control', { enabled: false });
  assert.equal(h.commands().at(-1), 'set_live_control'); h.client.dispose();
});

test('a delayed enable response cannot overwrite a later disable response', async () => {
  const h = harness(); h.state({ executor: 'dry-run', live_enabled: false });
  h.client.start(); await flush(); let resolve;
  h.handler(c => c.payload?.action === 'set_live_control' ? c.payload.params.enabled
    ? new Promise(r => { resolve = r; })
    : Response.json({ control_state: { live_enabled: false, executor: 'dry-run', control_epoch: 'c'.repeat(32) } }) : null);
  const enable = h.client.command('set_live_control', { enabled: true }); await flush();
  await h.client.command('set_live_control', { enabled: false });
  resolve(Response.json({ control_state: { live_enabled: true, executor: 'bridge', control_epoch: 'b'.repeat(32) } }));
  await enable;
  assert.equal(h.latest().state.live_enabled, false);
  assert.equal(h.latest().state.control_epoch, 'c'.repeat(32));
  assert.equal(h.latest().busy, false); h.client.dispose();
});
