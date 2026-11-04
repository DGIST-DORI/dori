// State, expression and emotion topics repeat snapshots. Log semantic changes.
// manager_state owns state transitions; status repeats state and owns conditions.
const EVENT_FIELDS = {
  manager_state: ['state', 'target_id', 'location_context'],
  status: ['user_visible', 'mic_attached', 'access_blocked', 'tracking_required'],
  expression: ['expression'],
  emotion: ['emotion', 'source'],
};

export function readManagerState(payload) {
  const value = typeof payload === 'string' ? { state: payload } : payload;
  if (!value || typeof value.state !== 'string' || !value.state.trim()) {
    throw new Error('manager_state requires a non-empty state');
  }
  return {
    ...value,
    state: value.state.trim(),
    state_elapsed_sec: Number.isFinite(value.state_elapsed_sec) ? value.state_elapsed_sec : 0,
  };
}

const formatValue = value => value === undefined ? '(unset)' : JSON.stringify(value);

export function describeHriEvent(source, previous, payload) {
  const fields = EVENT_FIELDS[source];
  const snapshot = Object.fromEntries(fields
    .filter(key => Object.hasOwn(payload, key))
    .map(key => [key, payload[key]]));
  const changed = fields.filter(key => formatValue(previous?.[key]) !== formatValue(snapshot[key]));
  if (!changed.length) return { snapshot, message: null };

  const parts = changed.map(key => {
    if (key === source) return previous ? `${previous[key]} → ${snapshot[key]}` : snapshot[key];
    if (!previous) return `${key}=${formatValue(snapshot[key])}`;
    if (key === 'state') return `${previous.state} → ${snapshot.state}`;
    return `${key}: ${formatValue(previous[key])} → ${formatValue(snapshot[key])}`;
  });
  return { snapshot, message: `${source}: ${parts.join(', ')}` };
}
