/** Same-origin credentials only. Secrets are exchanged for an HttpOnly cookie. */
class AuthError extends Error {
  constructor(code, message) {
    super(message);
    this.name = 'AuthError';
    this.code = code;
  }
}

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
  if (!response.ok) throw new AuthError('auth.error.token', 'Sign-in failed. Check your token and permissions.');
  return response.json();
}

export async function getAuthSession() {
  let response;
  try {
    response = await apiFetch('/api/auth/session', { cache: 'no-store' });
  } catch {
    throw new AuthError('auth.error.connection', 'Unable to connect. Check your connection and sign in again.');
  }
  const data = await response.json().catch(() => ({}));
  if (response.ok) return data;
  if (data.detail === 'Cloudflare Access not configured') {
    throw new AuthError('auth.error.configuration', 'Access sign-in is not configured. Contact an administrator.');
  }
  if (data.detail === 'CF Access token invalid') {
    throw new AuthError('auth.error.access', 'Unable to verify your Access session. Sign in again or contact an administrator.');
  }
  if (response.status === 401) return null;
  if (response.status === 403) throw new AuthError('auth.error.permission', 'This account does not have access to the dashboard.');
  throw new AuthError('auth.error.session', 'Unable to check your sign-in status. Please try again shortly.');
}

export async function logout() {
  const response = await apiFetch('/api/auth/session', { method: 'DELETE' });
  if (!response.ok) throw new AuthError('auth.error.logout', 'Sign-out failed. Please try again.');
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
