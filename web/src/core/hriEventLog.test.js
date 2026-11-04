import test from 'node:test';
import assert from 'node:assert/strict';
import { describeHriEvent, readManagerState } from './hriEventLog.js';

test('repeated BT snapshots never evict conversation events just because time passes', () => {
  const snapshots = {}, messages = [];
  for (let i = 0; i < 1000; i++) {
    for (const [source, payload] of Object.entries({
      manager_state: { state: 'IDLE', state_elapsed_sec: i / 10, timestamp: i },
      status: { state: 'IDLE', user_visible: false, mic_attached: true, access_blocked: false, tracking_required: false },
    })) {
      const event = describeHriEvent(source, snapshots[source], payload);
      snapshots[source] = event.snapshot;
      if (event.message) messages.push(event.message);
    }
  }
  assert.equal(messages.length, 2); // One initial state and one initial condition snapshot.
  assert.match(messages[0], /state="IDLE"/);
  assert.match(messages[1], /access_blocked=false/);
});

test('every fast state transition is retained, and mirrored status.state is ignored', () => {
  let previous;
  const messages = [];
  for (const state of ['IDLE', 'LISTENING', 'RESPONDING', 'IDLE']) {
    const event = describeHriEvent('manager_state', previous, { state });
    previous = event.snapshot;
    messages.push(event.message);
    assert.equal(describeHriEvent('status', {}, { state }).message, null);
  }
  assert.deepEqual(messages, [
    'manager_state: state="IDLE"', 'manager_state: IDLE → LISTENING',
    'manager_state: LISTENING → RESPONDING', 'manager_state: RESPONDING → IDLE',
  ]);
});

test('conditions, targets and location changes remain visible with old and new values', () => {
  for (const key of ['user_visible', 'mic_attached', 'access_blocked', 'tracking_required']) {
    const event = describeHriEvent('status', { [key]: false }, { [key]: true, state: 'IDLE' });
    assert.equal(event.message, `status: ${key}: false → true`);
    assert.equal(describeHriEvent('status', event.snapshot, { [key]: true }).message, null);
    assert.equal(describeHriEvent('status', event.snapshot, { [key]: false }).message, `status: ${key}: true → false`);
  }
  const previous = { state: 'GUIDING', target_id: 1, location_context: 'E1' };
  const event = describeHriEvent('manager_state', previous, { ...previous, target_id: 2, location_context: 'E7' });
  assert.equal(event.message, 'manager_state: target_id: 1 → 2, location_context: "E1" → "E7"');
  assert.match(describeHriEvent('manager_state', event.snapshot, { state: 'GUIDING' }).message, /target_id: 2 → \(unset\)/);
});

test('a fresh connection records its baseline and invalid manager states cannot create a false IDLE transition', () => {
  assert.equal(describeHriEvent('manager_state', undefined, { state: 'IDLE' }).message, 'manager_state: state="IDLE"');
  assert.deepEqual(readManagerState('LISTENING'), { state: 'LISTENING', state_elapsed_sec: 0 });
  assert.equal(readManagerState({ state: 'IDLE', state_elapsed_sec: 'invalid' }).state_elapsed_sec, 0);
  for (const payload of [null, {}, { state: 1 }, '']) assert.throws(() => readManagerState(payload));
});

test('emotion timestamps and expression scores do not create duplicate EXPR events', () => {
  const snapshots = {}, messages = [];
  for (let i = 0; i < 1000; i++) {
    for (const [source, payload] of Object.entries({
      emotion: { emotion: 'CALM', source: 'ros', timestamp: i, hri_state: 'IDLE' },
      expression: { expression: 'HAPPY', confidence: i / 1000, timestamp: i },
    })) {
      const event = describeHriEvent(source, snapshots[source], payload);
      snapshots[source] = event.snapshot;
      if (event.message) messages.push(event.message);
    }
  }
  assert.equal(messages.length, 2);
  assert.equal(describeHriEvent('expression', snapshots.expression, { expression: 'NEUTRAL' }).message,
    'expression: HAPPY → NEUTRAL');
  const override = describeHriEvent('emotion', snapshots.emotion, { emotion: 'HAPPY', source: 'override' });
  assert.match(override.message, /CALM → HAPPY/);
  assert.match(override.message, /"ros" → "override"/);
  assert.equal(describeHriEvent('emotion', override.snapshot, { emotion: 'HAPPY', source: 'override' }).message, null);
  assert.match(describeHriEvent('emotion', override.snapshot, { emotion: 'HAPPY', source: 'ros' }).message,
    /"override" → "ros"/);
});
