import { apiFetch } from '../../../core/api.js';

export const STALE_MS = 1500;
export const canControl = roles => roles?.some(role => ['admin', 'control', 'deploy'].includes(role)) || false;

// getRandomValues also works on HTTP LAN development origins without randomUUID.
const newClientId = () => crypto.randomUUID?.()
  || `browser-${Array.from(crypto.getRandomValues(new Uint32Array(4))).join('-')}`;

export async function readResponse(response) {
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const messages = { 401: '로그인이 만료되었습니다.', 403: '제어 권한이 없거나 세션이 변경되었습니다.',
      503: '내비게이션 서비스에 연결할 수 없습니다. 웹 뷰어 실행 상태를 확인하세요.' };
    throw new Error(messages[response.status] || body.error || body.detail || `요청 실패 (${response.status})`);
  }
  return response.json();
}

/** One lifetime per mounted panel. No commands are replayed after reconnect. */
export function createNavigationClient(onChange, { fetcher = apiFetch, now = Date.now,
  schedule = setTimeout, cancel = clearTimeout, clientId = newClientId() } = {}) {
  let disposed = false, started = false, pollTimer, staleTimer, heartbeat = false;
  let csrf = '', authAt = -Infinity, lastUpdate = 0, suppressHeartbeat = false;
  let stopRevision = 0;
  let snapshot = { state: null, online: false, canControl: false, error: '', clientId };
  const requests = new Set();
  function emit(update) {
    if (!disposed) { snapshot = { ...snapshot, ...update }; onChange(snapshot); }
  }
  async function request(path, options = {}, timeout = 2000) {
    if (disposed) throw new Error('패널이 닫혔습니다.');
    const controller = new AbortController();
    requests.add(controller);
    const timer = schedule(() => controller.abort(), timeout);
    try { return await fetcher(path, { ...options, signal: controller.signal }); }
    finally { cancel(timer); requests.delete(controller); }
  }
  async function command(action, extra = {}) {
    if (disposed || !snapshot.canControl) throw new Error('제어 권한이 필요합니다.');
    if (!csrf) throw new Error('내비게이션 연결을 기다리세요.');
    if (action !== 'stop' && (!snapshot.online || now() - lastUpdate >= STALE_MS)) {
      throw new Error('최신 상태를 기다리세요.');
    }
    if (action === 'stop') { suppressHeartbeat = true; stopRevision++; }
    const revision = stopRevision;
    const result = await readResponse(await request('/navigation/api/command', {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Dori-Control': csrf },
      body: JSON.stringify({ ...extra, action, client: clientId }),
    }, 3000));
    // A late enable response must not resume heartbeats after an explicit stop.
    if (action === 'enable' && revision === stopRevision) suppressHeartbeat = false;
    return result;
  }
  async function poll() {
    try {
      if (now() - authAt >= 60000) {
        emit({ canControl: false });
        const auth = await readResponse(await request('/api/auth/session'));
        emit({ canControl: canControl(auth.roles) });
        authAt = now();
      }
      if (!csrf) csrf = (await readResponse(await request('/navigation/api/session'))).csrf;
      const state = await readResponse(await request('/navigation/api/state'));
      if (disposed) return;
      if (state.server_age > 2) throw new Error('ROS 상태 갱신이 중단되었습니다.');
      csrf = state.csrf || csrf;
      lastUpdate = now();
      emit({ state, online: true, error: '' });
      cancel(staleTimer);
      staleTimer = schedule(() => emit({ online: false, error: '상태 수신 지연 — 연결을 확인하세요.' }), STALE_MS);
      if (state.control_owner === clientId && snapshot.canControl && !suppressHeartbeat && !heartbeat) {
        heartbeat = true;
        // Independent of polling, but at most one heartbeat request is in flight.
        command('heartbeat').catch(error => emit({ error: error.message })).finally(() => { heartbeat = false; });
      }
    } catch (error) {
      emit({ online: false, error: error.message });
    } finally {
      if (!disposed) pollTimer = schedule(poll, 200);
    }
  }
  return {
    command,
    start() { if (!started && !disposed) { started = true; void poll(); } },
    dispose() {
      disposed = true;
      cancel(pollTimer); cancel(staleTimer);
      for (const controller of requests) controller.abort();
      requests.clear();
    },
  };
}
