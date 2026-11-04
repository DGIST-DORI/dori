import test from 'node:test';
import assert from 'node:assert/strict';
import { world, screen, fitMap, zoomAt, poseFromFields, selectionPose, sceneKey } from './geometry.js';

const near = (a, b) => assert.ok(Math.abs(a - b) < 1e-9, `${a} != ${b}`);
test('world and screen coordinates round trip with inverted screen Y', () => {
  const size = { w: 800, h: 400 }, view = { x: -3, y: 5, scale: 20 };
  assert.deepEqual(screen([-3, 6], view, size), [400, 180]);
  const point = [-9.25, 12.5];
  world(screen(point, view, size), view, size).forEach((v, i) => near(v, point[i]));
});
test('fit respects map resolution and rotated origin', () => {
  const map = { origin: [10, -2, Math.PI / 2], width: 100, height: 40, resolution: .1 };
  const view = fitMap(map, { w: 800, h: 400 });
  near(view.x, 8); near(view.y, 3); near(view.scale, 400 / 11);
});
test('zoom is anchored to cursor and bounded', () => {
  const view = { x: 1, y: 2, scale: 50 }, size = { w: 400, h: 300 }, cursor = [30, 90];
  for (const delta of [-100000, 100000, 100]) {
    const next = zoomAt(cursor, delta, view, size);
    assert.ok(next.scale >= 2 && next.scale <= 600);
    world(cursor, next, size).forEach((v, i) => near(v, world(cursor, view, size)[i]));
  }
});
test('pose input preserves zero, rejects empty/nonfinite, and converts degrees', () => {
  assert.deepEqual(poseFromFields(['0', '-2', '90']), [0, -2, Math.PI / 2]);
  for (const fields of [['', '1', '0'], ['0', ' ', '0'], ['0', '1', 'Infinity'], ['no', '1', '0']]) {
    assert.equal(poseFromFields(fields), null);
  }
  assert.deepEqual(selectionPose([1, 2], [1, 4]), [1, 2, Math.PI / 2]);
});
test('server/frame/map geometry resets selection but occupancy updates do not', () => {
  const state = { instance_id: 'one', frame: 'map', map: { version: 1, origin: [0, 0, 0], width: 10, height: 10, resolution: .1 } };
  assert.equal(sceneKey(state), sceneKey({ ...state, map: { ...state.map, version: 2 } }));
  for (const next of [{ ...state, instance_id: 'two' }, { ...state, frame: 'odom' }, { ...state, map: { ...state.map, origin: [1, 0, 0] } }]) {
    assert.notEqual(sceneKey(state), sceneKey(next));
  }
});
