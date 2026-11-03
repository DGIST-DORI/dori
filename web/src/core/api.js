/** Same-origin credentials only. Secrets are exchanged for an HttpOnly cookie. */
export async function apiFetch(path, options = {}) {
  const url = new URL(path, window.location.origin);
  if (url.origin !== window.location.origin) {
    throw new Error('API requests must use the dashboard origin');
  }
  const response = await fetch(url, {
    ...options, credentials: 'same-origin', redirect: 'error',
    headers: { ...Object.fromEntries(new Headers(options.headers)), 'X-Requested-With': 'XMLHttpRequest' },
  });
  if (response.status === 401) {
    window.dispatchEvent(new Event('dori-auth-required'));
  }
  return response;
}

export async function loginWithToken(token, kind = 'jwt') {
  const headers = kind === 'access'
    ? { Access: token.trim() }
    : { Authorization: `Bearer ${token.trim()}` };
  const response = await apiFetch('/api/auth/session', { method: 'POST', headers });
  if (!response.ok) throw new Error('로그인에 실패했습니다. 토큰과 권한을 확인하세요.');
  return response.json();
}

export async function logout() {
  const response = await apiFetch('/api/auth/session', { method: 'DELETE' });
  if (!response.ok) throw new Error('로그아웃 요청에 실패했습니다.');
  window.dispatchEvent(new Event('dori-auth-required'));
  const data = await response.json();
  if (data.logout_url === '/cdn-cgi/access/logout') window.location.assign(data.logout_url);
}

export function adminWsUrl(location = window.location) {
  return `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/admin`;
}

export async function ticketedWsUrl(url) {
  const parsed = new URL(url);
  if (parsed.href !== adminWsUrl()) {
    throw new Error('WebSocket은 현재 대시보드의 /ws/admin 주소를 사용해야 합니다.');
  }
  const response = await apiFetch('/api/auth/ws-ticket', { method: 'POST' });
  if (!response.ok) throw new Error('ROS 연결에는 관리자 로그인이 필요합니다.');
  const { ticket } = await response.json();
  parsed.searchParams.set('ticket', ticket);
  return parsed.href;
}
