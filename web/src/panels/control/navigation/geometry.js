export const defaultView = () => ({ x: 0, y: 0, scale: 55 });

export function world(point, view, size) {
  return [view.x + (point[0] - size.w / 2) / view.scale,
    view.y - (point[1] - size.h / 2) / view.scale];
}

export function screen(point, view, size) {
  return [size.w / 2 + (point[0] - view.x) * view.scale,
    size.h / 2 - (point[1] - view.y) * view.scale];
}

export function fitMap(map, size) {
  const [x, y, angle] = map.origin;
  const w = map.width * map.resolution, h = map.height * map.resolution;
  const c = Math.cos(angle), s = Math.sin(angle);
  return { x: x + c * w / 2 - s * h / 2, y: y + s * w / 2 + c * h / 2,
    scale: Math.max(2, Math.min(size.w / (Math.abs(w * c) + Math.abs(h * s) + 1),
      size.h / (Math.abs(w * s) + Math.abs(h * c) + 1))) };
}

export function zoomAt(point, delta, view, size) {
  const before = world(point, view, size);
  const next = { ...view, scale: Math.max(2, Math.min(600, view.scale * Math.exp(-delta * .001))) };
  const after = world(point, next, size);
  return { ...next, x: next.x + before[0] - after[0], y: next.y + before[1] - after[1] };
}

export function poseFromFields(fields) {
  if (fields.some(value => String(value).trim() === '')) return null;
  const [x, y, degrees] = fields.map(Number);
  return [x, y, degrees].every(Number.isFinite) ? [x, y, degrees * Math.PI / 180] : null;
}

export function selectionPose(start, end) {
  return [...start, Math.atan2(end[1] - start[1], end[0] - start[0])];
}

// A new server or coordinate system invalidates pending selections and map imagery.
export function sceneKey(state) {
  return JSON.stringify([state?.instance_id, state?.frame, state?.map?.origin,
    state?.map?.width, state?.map?.height, state?.map?.resolution]);
}
