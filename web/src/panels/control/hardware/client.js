import { apiFetch } from '../../../core/api.js';

// randomUUID is unavailable on plain HTTP LAN origins; getRandomValues is supported.
export const hardwareClientId = (source = crypto) => source.randomUUID?.()
  || `browser-${Array.from(source.getRandomValues(new Uint32Array(4))).join('-')}`;

export function driveReady(state, clientId) {
  return !!state?.can_control && (state.executor === 'dry-run' || (state.live_enabled &&
    state.supervisor_available && state.mode === 0 && [0, 1].includes(state.action_state)
    && !state.stop_latched && !state.manual_input_conflict
    && (!state.move_owner || state.move_owner === clientId)
  ));
}

/** One in-flight motion request; release also stops after a late response. */
export function createHardwareClient(onChange, {
  request = apiFetch, schedule = setTimeout, cancel = clearTimeout, now = Date.now,
  clientId = hardwareClientId(),
} = {}) {
  let snapshot = { state: null, online: false, holding: false, busy: false, error: '', notice: '', clientId };
  let disposed = false, started = false, pollTimer, staleTimer, holdTimer;
  let hold = null, pendingMove = false, lastMove = 0;
  let controlRevision = 0, pendingCommands = 0;
  const emit = patch => { snapshot = { ...snapshot, ...patch }; if (!disposed) onChange(snapshot); };

  async function json(path, options = {}) {
    const controller = new AbortController();
    const timeout = schedule(() => controller.abort(), 1500);
    try {
      const response = await request(path, { ...options, cache: 'no-store', signal: controller.signal });
      const body = await response.json();
      if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : `요청 실패 (${response.status})`);
      return body;
    } finally { cancel(timeout); }
  }
  async function send(action, params = {}, keepalive = false) {
    params = { ...params, client_id: clientId };
    if (action !== 'stop' && params.control_epoch === undefined && snapshot.state?.control_epoch) {
      params = { ...params, control_epoch: snapshot.state.control_epoch };
    }
    return json('/api/control/actions', { method: 'POST', keepalive,
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action, params }) });
  }
  async function stop(force = false) {
    const active = !!hold;
    hold = null; cancel(holdTimer);
    emit({ holding: false });
    if ((!active && !force) || !snapshot.state?.can_control) return;
    const revision = ++controlRevision;
    try {
      const result = await send('stop', {}, true);
      if (revision === controlRevision) emit({ notice: result.executed ? '정지 명령 전달됨 · 다시 움직이려면 정지를 해제하세요.' : '모의 제어 · 정지 명령 검증 완료', error: '' });
    } catch (error) { emit({ error: `정지 확인 실패: ${error.message}` }); }
  }
  async function pulse(current) {
    if (hold !== current || disposed || pendingMove) return;
    if (!snapshot.online || !driveReady(snapshot.state, clientId)
        || current.control_epoch !== snapshot.state.control_epoch || (lastMove && now() - lastMove > 350)) {
      void stop(); return;
    }
    pendingMove = true; lastMove = now();
    try {
      const result = await send('move', current);
      if (hold !== current || disposed) {
        // A released press must not survive an HTTP response that arrives late.
        await stop(true);
      } else {
        emit({ notice: result.executed ? '수동 주행 명령 전달 중' : '모의 제어 · 주행 명령 검증 중', error: '' });
      }
    } catch (error) {
      await stop();
      emit({ error: `주행 중단: ${error.message}` });
    } finally {
      pendingMove = false;
      if (hold === current && !disposed) holdTimer = schedule(() => void pulse(current), 120);
    }
  }
  async function poll() {
    const revision = controlRevision;
    try {
      const state = await json('/api/control/state');
      if (disposed || revision !== controlRevision) return;
      emit({ state, online: true, ...(snapshot.error.startsWith('하드웨어 연결:') ? { error: '' } : {}) });
      if (hold && (!driveReady(state, clientId) || hold.control_epoch !== state.control_epoch)) void stop();
      cancel(staleTimer);
      staleTimer = schedule(() => { emit({ online: false }); void stop(); }, 1200);
    } catch (error) {
      if (!disposed) { emit({ online: false, error: `하드웨어 연결: ${error.message}` }); void stop(); }
    } finally { if (!disposed) pollTimer = schedule(poll, 250); }
  }
  return {
    start() { if (!started) { started = true; void poll(); } },
    hold(params) {
      if (disposed || hold || pendingMove || snapshot.busy || !snapshot.online || !driveReady(snapshot.state, clientId)) return;
      hold = { ...params, control_epoch: snapshot.state.control_epoch }; lastMove = 0;
      emit({ holding: true }); void pulse(hold);
    },
    stop,
    async command(action, params = {}) {
      if (action === 'stop') return stop(true);
      const disabling = action === 'set_live_control' && params.enabled === false;
      if (disposed || !snapshot.state?.can_control) return;
      if (!disabling && (hold || pendingMove || snapshot.busy || !snapshot.online)) return;
      if (disabling) { hold = null; cancel(holdTimer); emit({ holding: false }); }
      const revision = ++controlRevision;
      pendingCommands++;
      emit({ busy: true, error: '' });
      try {
        const result = await send(action, params);
        if (revision !== controlRevision) return;
        if (result.control_state) {
          controlRevision++;
          emit({ state: { ...snapshot.state, ...result.control_state } });
        }
        emit({ notice: action === 'set_live_control'
          ? result.control_state?.live_enabled ? '실제 제어 켜짐 · 정지를 해제한 뒤 조작하세요.' : '실제 제어 꺼짐 · 모의 제어로 전환했습니다.'
          : result.executed ? '명령 전달됨 · 아래 로봇 상태에서 결과를 확인하세요.' : '모의 제어 · 명령 검증 완료 (로봇은 움직이지 않습니다)' });
      } catch (error) { emit({ error: error.message }); }
      finally { pendingCommands--; emit({ busy: pendingCommands > 0 }); }
    },
    dispose() {
      disposed = true;
      cancel(pollTimer); cancel(staleTimer); cancel(holdTimer);
      // Leave the bounded in-flight move intact so its completion sends another stop.
      void stop();
    },
  };
}
